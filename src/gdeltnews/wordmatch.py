#!/usr/bin/env python3
"""Core logic for reconstructing articles from GDELT Web NGrams files.

Given a *.webngrams.json or *.webngrams.json.gz file, this module:

1. Loads entries grouped by URL.
2. Applies optional language and URL filters.
3. Builds sentence fragments from pre/ngram/post.
4. Reconstructs full article text by merging overlapping fragments.
5. Writes a CSV with columns: Text|Date|URL|Source.

This module is called by `reconstruct.py`, but can also be imported directly.
"""

from __future__ import annotations

import csv
import json
import re
from bisect import bisect_left, bisect_right
from contextlib import contextmanager
from functools import partial
from collections import defaultdict
from typing import BinaryIO, Dict, Iterable, Iterator, List, Optional, Tuple, Union

# isal's igzip is a drop-in replacement for gzip that decompresses several
# times faster. It is an optional extra (`pip install gdeltnews[fast]`);
# without it everything behaves identically, just slower.
try:  # pragma: no cover - depends on an optional dependency
    from isal import igzip as gzip
except ImportError:  # pragma: no cover
    import gzip

import multiprocessing as mp
from tqdm import tqdm


Entry = Dict[str, Union[str, int]]


@contextmanager
def _open_webngrams_binary(input_file: str) -> Iterator[BinaryIO]:
    """Open either a decompressed JSON file or a gzipped JSON file in binary.

    Binary mode lets the loader run a cheap byte-substring pre-filter on each
    raw line and skip the UTF-8 decode + ``json.loads`` for the ~99.9% of
    lines that can't pass the language/URL filters anyway.
    """
    input_path = str(input_file)
    if input_path.lower().endswith(".gz"):
        with gzip.open(input_path, "rb") as file:
            yield file
    else:
        with open(input_path, "rb") as file:
            yield file


# ---------------------------------------------------------------------------
# Transform raw entries into sentence fragments
# ---------------------------------------------------------------------------

def _transform_entry(entry: Dict) -> Entry:
    """Build a single sentence-level Entry from a raw GDELT ngrams record."""
    pre = entry.get("pre", "").strip()
    ngram = entry.get("ngram", "").strip()
    post = entry.get("post", "").strip()

    sentence = " ".join(x for x in (pre, ngram, post) if x).strip()

    try:
        pos_val = int(entry.get("pos", 0))
    except (TypeError, ValueError):
        pos_val = 0

    if pos_val < 20 and " / " in sentence:
        sentence = sentence.split(" / ", 1)[-1].strip()

    return {
        "sentence": sentence,
        "pos": pos_val,
        "date": entry.get("date", ""),
        "lang": entry.get("lang", ""),
        "type": entry.get("type", ""),
    }


def transform_dict(original_dict: Dict[str, List[Dict]]) -> Dict[str, List[Entry]]:
    """Transform raw GDELT entries into simplified sentence fragments.

    Builds a 'sentence' field from pre/ngram/post and normalizes a few
    known artifacts. Positions are stored as integers under the 'pos' key.
    """
    return {
        url: [_transform_entry(e) for e in entries]
        for url, entries in original_dict.items()
    }


# ---------------------------------------------------------------------------
# Overlap-based reconstruction
# ---------------------------------------------------------------------------

def reconstruct_sentence(
    fragments: List[str],
    positions: Optional[List[int]] = None,
    keep_unmerged: bool = False,
) -> str:
    """Reconstruct a sentence from overlapping fragments, respecting positions.

    - Starts from the fragment with the smallest position (assuming the caller
      already sorted by pos).
    - Greedily merges fragments by maximum word overlap.
    - When positions are provided, it only:
        * appends fragments with pos >= current max pos
        * prepends fragments with pos <= current min pos

    This avoids moving later fragments before the true beginning of the article.

    Each round picks the fragment with the largest overlap; ties go to the
    lowest index, and within one fragment an append beats a prepend of equal
    length. The indexing below is only a faster way of finding that same
    winner: the reconstructed text is identical to what the original
    quadratic scan produced (see tests/test_reconstruct_equivalence.py).

    Args:
        fragments: sentence fragments to merge.
        positions: optional per-fragment position, same length as `fragments`.
        keep_unmerged: if True, fragments that never found an overlap are
            appended at the end (in position order) instead of being dropped.
            Default False, which is the historical behaviour.
    """
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]

    # Tokenize all fragments
    words_list = [frag.split() for frag in fragments]
    n = len(words_list)

    # Sanity check on positions
    if positions is not None and len(positions) != n:
        positions = None

    # Callers coming through `process_article` sort by pos, and for sorted
    # positions "appendable" is exactly an index suffix and "prependable"
    # exactly an index prefix -- two bisects then replace a per-fragment
    # comparison. The function is public, so unsorted input keeps the old path.
    sorted_positions = positions is not None and all(
        positions[i] <= positions[i + 1] for i in range(n - 1)
    )

    # Start from the first fragment (caller sorted by pos)
    result_words = words_list[0][:]

    # Indices still unused *and* still eligible, kept ascending so that the
    # lowest-index tie-break falls out of a plain forward scan.
    live = list(range(1, n))

    if positions is not None:
        min_pos = max_pos = positions[0]

    while live:
        best_fragment = -1
        best_overlap = 0
        best_is_prefix = False  # True = prepend, False = append

        result_len = len(result_words)

        # No remaining fragment can overlap by more than `cap`, so it doubles
        # as the early-exit bound for the scan below.
        longest = 0
        for i in live:
            length = len(words_list[i])
            if length > longest:
                longest = length
        cap = longest if longest < result_len else result_len
        if cap == 0:
            break

        # An append of length k requires result_words[-k] == words[0]; a
        # prepend of length k requires result_words[k - 1] == words[-1].
        # Indexing the tail/head windows by word turns the old descending scan
        # over every k into a single dict lookup per fragment -- usually a
        # miss, which rejects the fragment outright. Candidate lists are built
        # descending, so the first full match found is the longest one.
        tail_k: Dict[str, List[int]] = {}
        head_k: Dict[str, List[int]] = {}
        for k in range(cap, 0, -1):
            tail_k.setdefault(result_words[result_len - k], []).append(k)
            head_k.setdefault(result_words[k - 1], []).append(k)

        if sorted_positions:
            append_from = bisect_left(positions, max_pos)
            prepend_until = bisect_right(positions, min_pos)

        dead: Optional[List[int]] = None

        for idx in live:
            words = words_list[idx]
            length = len(words)
            max_k = result_len if result_len < length else length

            # Even a perfect overlap on this fragment couldn't beat the
            # best we've already seen -- skip the work entirely.
            if max_k <= best_overlap:
                continue

            # Decide if we are allowed to append/prepend this fragment
            can_append = True
            can_prepend = True
            if positions is not None:
                if sorted_positions:
                    can_append = idx >= append_from
                    can_prepend = idx < prepend_until
                else:
                    p = positions[idx]
                    # Append only if this fragment is not earlier than what we have
                    can_append = p >= max_pos
                    # Prepend only if this fragment is not later than what we have
                    can_prepend = p <= min_pos
                if not can_append and not can_prepend:
                    # min_pos only shrinks and max_pos only grows, so a
                    # fragment rejected once can never become eligible again.
                    if dead is None:
                        dead = []
                    dead.append(idx)
                    continue

            # Try appending: result ... fragment.
            if can_append:
                for k in tail_k.get(words[0], ()):
                    if k > max_k:
                        continue
                    if k <= best_overlap:
                        break
                    if result_words[-k:] == words[:k]:
                        best_fragment = idx
                        best_overlap = k
                        best_is_prefix = False
                        break

            # Try prepending: fragment ... result. If append just locked in a
            # perfect overlap, prepend can't beat it.
            if can_prepend and max_k > best_overlap:
                for k in head_k.get(words[-1], ()):
                    if k > max_k:
                        continue
                    if k <= best_overlap:
                        break
                    if result_words[:k] == words[-k:]:
                        best_fragment = idx
                        best_overlap = k
                        best_is_prefix = True
                        break

            if best_overlap >= cap:
                # Nothing left can beat this, and ties go to the lowest index,
                # which this ascending scan has already settled.
                break

        if best_fragment == -1:
            # No overlapping fragments that respect positional constraints
            break

        fragment_words = words_list[best_fragment]

        # best_overlap is always >= 1 here: a fragment is only ever selected
        # from inside a loop that requires an actual match.
        if best_is_prefix:
            result_words = fragment_words[:-best_overlap] + result_words
        else:
            result_words.extend(fragment_words[best_overlap:])

        if positions is not None:
            p = positions[best_fragment]
            if p < min_pos:
                min_pos = p
            if p > max_pos:
                max_pos = p

        if dead is None:
            live.remove(best_fragment)
        else:
            drop = set(dead)
            drop.add(best_fragment)
            live = [i for i in live if i not in drop]

    if keep_unmerged and live:
        # By default the loop above just drops whatever never overlapped,
        # which silently truncates the article. Opting in appends the
        # leftovers in position order instead, accepting some duplication.
        leftover = (
            sorted(live, key=lambda i: positions[i])
            if positions is not None
            else live
        )
        for idx in leftover:
            result_words.extend(words_list[idx])

    return " ".join(result_words)


def remove_overlap(text: str) -> str:
    """Remove simple prefix/suffix overlaps from the reconstructed text.

    If a non-trivial prefix of the text is identical to the suffix, drop
    the prefix. This is a conservative cleanup for some duplicate merges.
    """
    words = text.split()
    n = len(words)
    if n < 2:
        return text

    # Search for the longest overlap where prefix == suffix.
    for k in range(n // 2, 0, -1):
        if words[:k] == words[-k:]:
            return " ".join(words[k:])

    return text


# ---------------------------------------------------------------------------
# Load & filter raw data
# ---------------------------------------------------------------------------

def _normalize_url_filters(
    url_filter: Optional[Union[str, Iterable[str]]],
) -> Optional[List[str]]:
    """Normalize a url_filter argument into a list of non-empty strings, or None.

    Strips whitespace and drops empty entries so that ``[""]`` does not
    silently match every URL via ``"" in url``.
    """
    if url_filter is None:
        return None
    if isinstance(url_filter, (list, tuple, set)):
        cleaned = [s for s in (str(f).strip() for f in url_filter) if s]
    else:
        s = str(url_filter).strip()
        cleaned = [s] if s else []
    return cleaned or None


def load_and_filter_data(
    input_file: str,
    language_filter: Optional[str] = "en",
    url_filter: Optional[Union[str, Iterable[str]]] = None,
) -> Tuple[Dict[str, List[Entry]], List[str]]:
    """Load data from a .json or .json.gz file and filter by language and URL.

    Each kept record is transformed into a sentence-level Entry inline
    (no second full pass over the data).

    Returns:
        articles: dict mapping URL -> list of entries with sentences.
        url_order: list of URLs in first-seen order.
    """
    url_filters = _normalize_url_filters(url_filter)

    # Byte-level pre-filters run on the raw line before the expensive
    # json.loads. Each is a *necessary* condition for the corresponding real
    # check below, so a survivor is always re-checked and nothing that would
    # have passed can be dropped here:
    #   - lang value "xx" is JSON-encoded literally as `"xx"` (codes need no
    #     escaping), so `b'"xx"'` must appear in any line where lang == "xx".
    #   - an ASCII URL substring filter is, by definition, a substring of the
    #     URL, which is itself a substring of the raw line. Non-ASCII filters
    #     are exempt: GDELT may emit the URL with \uXXXX escapes, so the UTF-8
    #     bytes of the filter need not appear in the raw line even when the
    #     decoded URL does match. Those runs skip the URL pre-filter and rely
    #     on the post-parse check below.
    lang_token = (
        b'"' + language_filter.encode("utf-8") + b'"'
        if language_filter is not None
        else None
    )
    url_tokens = (
        [f.encode("utf-8") for f in url_filters]
        if url_filters and all(f.isascii() for f in url_filters)
        else None
    )

    articles: Dict[str, List[Entry]] = defaultdict(list)
    url_order: List[str] = []
    seen: set = set()

    with _open_webngrams_binary(input_file) as file:
        for raw in file:
            if lang_token is not None and lang_token not in raw:
                continue
            if url_tokens is not None and not any(t in raw for t in url_tokens):
                continue

            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if language_filter is not None and entry.get("lang") != language_filter:
                continue

            url = entry.get("url", "")
            if not url:
                continue

            if url_filters is not None and not any(f in url for f in url_filters):
                continue

            if url not in seen:
                seen.add(url)
                url_order.append(url)
            articles[url].append(_transform_entry(entry))

    return dict(articles), url_order


# ---------------------------------------------------------------------------
# Article-level processing
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Basic cleanup of reconstructed text for CSV output."""
    # Replace separators that conflict with the CSV format
    text = text.replace("|", " ").replace('"', " ")
    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text



def _source_from_pairs(
    url: str,
    pairs: Optional[List[Tuple[str, str]]],
) -> str:
    """Compute a source label from precomputed (original, casefolded) filter pairs."""
    if not pairs:
        return ""
    url_cf = url.casefold()
    matches = [orig for orig, cf in pairs if cf in url_cf]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "Multiple URL matched"
    return ""


def determine_source_label(url: str, url_filters: Optional[List[str]] = None) -> str:
    """Derive a source label from a URL and a list of URL substrings.

    Rules:
      - If exactly one filter matches, return that filter string.
      - If multiple filters match, return 'Multiple URL matched'.
      - If no filters are provided (None/empty), return ''.
      - If filters are provided but none match, return '' (should be rare if filtering was applied).
    """
    if not url_filters:
        return ""
    pairs = [(s, s.casefold()) for s in (str(f) for f in url_filters) if s]
    return _source_from_pairs(url, pairs)


def process_article(
    url_entries_tuple: Tuple[str, List[Entry]],
    url_filters: Optional[Union[List[str], List[Tuple[str, str]]]] = None,
    keep_unmerged: bool = False,
) -> Dict[str, str]:
    """Process a single article; designed to be run in parallel.

    ``url_filters`` may be either a list of substrings (casefolded per call,
    backwards compatible) or a list of pre-casefolded ``(original, casefolded)``
    pairs. Callers like ``process_file_multiprocessing`` pass the pair form so
    the casefold work happens once instead of per-article.

    Failures inside reconstruction are caught here so a single bad article
    can't kill the multiprocessing worker. On failure the returned dict has
    an extra ``"error"`` key with a short ``"ExceptionType: message"`` string;
    ``url`` and ``source`` are still populated so the caller can log which
    article failed.
    """
    url, entries = url_entries_tuple

    # Compute source label first — it's independent of entries and we want
    # it populated even if reconstruction itself fails.
    if url_filters and isinstance(url_filters[0], tuple):
        pairs = url_filters  # already pre-casefolded pairs
    elif url_filters:
        pairs = [(s, s.casefold()) for s in (str(f) for f in url_filters) if s]
    else:
        pairs = None
    source = _source_from_pairs(url, pairs)

    if not entries:
        return {"url": url, "text": "", "date": "", "source": source}

    try:
        # Sort by position without mutating the caller's list. ``pos`` is already
        # an int (set by _transform_entry), so no cast is needed here.
        sorted_entries = sorted(entries, key=lambda x: x["pos"])

        sentences = [e["sentence"] for e in sorted_entries]
        positions = [e["pos"] for e in sorted_entries]

        text = reconstruct_sentence(sentences, positions, keep_unmerged=keep_unmerged)
        text = remove_overlap(text)
        text = _clean_text(text)

        raw_date = str(sorted_entries[0].get("date", "")) or ""
        date_only = raw_date[:10] if len(raw_date) >= 10 else ""

        return {"url": url, "text": text, "date": date_only, "source": source}
    except Exception as exc:
        return {
            "url": url,
            "text": "",
            "date": "",
            "source": source,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# File-level multiprocessing driver
# ---------------------------------------------------------------------------

def process_file_multiprocessing(
    input_file: str,
    output_file: str,
    language_filter: Optional[str] = "en",
    url_filter: Optional[Union[str, Iterable[str]]] = None,
    num_processes: Optional[int] = None,
    pool: "Optional[mp.pool.Pool]" = None,
    show_progress: bool = True,
    keep_unmerged: bool = False,
) -> None:
    """Load a GDELT JSON or JSON.GZ file, reconstruct articles, and write a CSV.

    Args:
        input_file: path to a .json or .json.gz file.
        output_file: path to the output CSV file (Text|Date|URL|Source).
        language_filter: language code to keep (None = no language filter).
        url_filter: URL substring or iterable of substrings to keep.
        num_processes: number of worker processes (None = CPU count).
            Used both for sizing a pool when one is created and for tuning
            ``chunksize``. Ignored for sizing when ``pool`` is supplied.
        pool: an existing multiprocessing Pool to reuse. Useful when this
            function is called many times in a row (e.g. one call per file)
            since Pool startup is costly on Windows (spawn).
        show_progress: whether to display a tqdm progress bar.
        keep_unmerged: if True, fragments that never overlapped are appended
            to the article instead of being dropped. Default False.
    """
    print(f"Loading and filtering data from {input_file}...")
    articles, _url_order = load_and_filter_data(
        input_file, language_filter=language_filter, url_filter=url_filter
    )

    # Pre-build (original, casefolded) URL filter pairs once so each worker
    # call doesn't redo the casefold for every article.
    url_filters_list = _normalize_url_filters(url_filter)
    url_filter_pairs: Optional[List[Tuple[str, str]]] = (
        [(s, s.casefold()) for s in url_filters_list] if url_filters_list else None
    )

    if not articles:
        print("No articles found after filtering.")
        # Still create a CSV with just a header; the caller may delete it later if empty.
        with open(output_file, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
            writer.writerow(["Text", "Date", "URL", "Source"])
        return

    work_items = list(articles.items())

    owns_pool = pool is None
    if owns_pool:
        if num_processes is None or num_processes <= 0:
            num_processes = mp.cpu_count()
        active_pool = mp.Pool(processes=num_processes)
    else:
        active_pool = pool
        if num_processes is None or num_processes <= 0:
            num_processes = getattr(pool, "_processes", mp.cpu_count())

    chunksize = max(1, min(50, len(work_items) // (4 * num_processes)))

    print(f"Reconstructing {len(work_items)} articles using {num_processes} processes...")

    # Stream results straight to disk as workers finish. ``imap_unordered``
    # delivers rows in completion order, not URL order — that's an explicit
    # tradeoff to keep memory flat (we used to buffer every result in a list
    # so we could sort by original URL order before writing). ``text`` is
    # already cleaned in ``process_article``; date/url/source are cleaned
    # here so a stray ``|`` can't break the QUOTE_NONE format.
    written = 0
    errors = 0
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
            writer.writerow(["Text", "Date", "URL", "Source"])

            worker = partial(
                process_article,
                url_filters=url_filter_pairs,
                keep_unmerged=keep_unmerged,
            )
            result_iter = active_pool.imap_unordered(
                worker, work_items, chunksize=chunksize
            )
            if show_progress:
                result_iter = tqdm(
                    result_iter,
                    total=len(work_items),
                    desc="Reconstructing articles",
                )

            for art in result_iter:
                err = art.get("error")
                if err:
                    errors += 1
                    msg = f"  ! reconstruction failed for {art.get('url', '?')}: {err}"
                    if show_progress:
                        tqdm.write(msg)
                    else:
                        print(msg)
                writer.writerow([
                    art.get("text", ""),
                    _clean_text(art.get("date", "")),
                    _clean_text(art.get("url", "")),
                    _clean_text(art.get("source", "")),
                ])
                written += 1
    finally:
        if owns_pool:
            active_pool.close()
            active_pool.join()

    summary = f"Wrote {written} articles to {output_file}"
    if errors:
        summary += f" ({errors} failed during reconstruction)"
    print(summary)


# ---------------------------------------------------------------------------
# Convenience wrapper / public surface
# ---------------------------------------------------------------------------

__all__ = [
    "process_file_multiprocessing",
    "reconstruct_webngrams_file",
    "load_and_filter_data",
    "process_article",
    "reconstruct_sentence",
]


def reconstruct_webngrams_file(
    input_file: str,
    output_file: str,
    *,
    language: str | None = "en",
    url_filters: str | list[str] | tuple[str, ...] | set[str] | None = None,
    processes: int | None = None,
    keep_unmerged: bool = False,
) -> None:
    """Friendly wrapper around `process_file_multiprocessing`.

    Args:
        input_file: path to a *.webngrams.json or *.webngrams.json.gz file.
        output_file: path to the output CSV file.
        language: language code to keep (None = keep all).
        url_filters: URL substring or iterable of substrings to keep.
        processes: number of worker processes (None = CPU count).
        keep_unmerged: if True, fragments that never overlapped are appended
            to the article instead of being dropped. Default False.
    """
    process_file_multiprocessing(
        input_file=input_file,
        output_file=output_file,
        language_filter=language,
        url_filter=url_filters,
        num_processes=processes,
        keep_unmerged=keep_unmerged,
    )
