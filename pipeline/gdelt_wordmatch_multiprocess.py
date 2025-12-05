#!/usr/bin/env python3
"""Core logic for reconstructing articles from GDELT Web NGrams files.

Given a decompressed .webngrams.json file, this module:

1. Loads entries grouped by URL.
2. Applies optional language and URL filters.
3. Builds sentence fragments from pre/ngram/post.
4. Reconstructs full article text by merging overlapping fragments.
5. Writes a CSV with columns: Text|Date|URL.

Used by step2_reconstruct_gdelt.py via process_file_multiprocessing.
"""

import csv
import json
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple, Union

import multiprocessing as mp
from tqdm import tqdm


Entry = Dict[str, Union[str, int]]


# ---------------------------------------------------------------------------
# Transform raw entries into sentence fragments
# ---------------------------------------------------------------------------

def transform_dict(original_dict: Dict[str, List[Dict]]) -> Dict[str, List[Entry]]:
    """Transform raw GDELT entries into simplified sentence fragments.

    Builds a 'sentence' field from pre/ngram/post and normalizes a few
    known artifacts. Positions are stored as integers under the 'pos' key.
    """
    transformed: Dict[str, List[Entry]] = {}

    for url, entries in original_dict.items():
        new_entries: List[Entry] = []
        for entry in entries:
            pre = entry.get("pre", "").strip()
            ngram = entry.get("ngram", "").strip()
            post = entry.get("post", "").strip()

            # Basic sentence reconstruction from the ngram context
            sentence = " ".join(x for x in [pre, ngram, post] if x).strip()

            # Remove early slash artifacts in the first positions
            try:
                pos_val = int(entry.get("pos", 0))
            except (TypeError, ValueError):
                pos_val = 0

            if pos_val < 20 and " / " in sentence:
                # Keep the substring after the first slash sequence
                sentence = sentence.split(" / ", 1)[-1].strip()

            new_entry: Entry = {
                "sentence": sentence,
                "pos": pos_val,
                "date": entry.get("date", ""),
                "lang": entry.get("lang", ""),
                "type": entry.get("type", ""),
            }
            new_entries.append(new_entry)

        transformed[url] = new_entries

    return transformed


# ---------------------------------------------------------------------------
# Overlap-based reconstruction
# ---------------------------------------------------------------------------

def reconstruct_sentence(
    fragments: List[str],
    positions: Optional[List[int]] = None
) -> str:
    """Reconstruct a sentence from overlapping fragments, respecting positions.

    - Starts from the fragment with the smallest position (assuming the caller
      already sorted by pos).
    - Greedily merges fragments by maximum word overlap.
    - When positions are provided, it only:
        * appends fragments with pos >= current max pos
        * prepends fragments with pos <= current min pos

    This avoids moving later fragments before the true beginning of the article.
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
    pos_list: Optional[List[int]] = positions[:] if positions is not None else None

    # Start from the first fragment (caller sorted by pos)
    used = {0}
    result_words = words_list[0][:]

    if pos_list is not None:
        min_pos = max_pos = pos_list[0]
    else:
        min_pos = max_pos = None  # type: ignore[assignment]

    while len(used) < n:
        best_fragment = -1
        best_overlap = 0
        best_is_prefix = False  # True = prepend, False = append

        for idx, words in enumerate(words_list):
            if idx in used:
                continue

            max_k = min(len(result_words), len(words))
            if max_k == 0:
                continue

            # Decide if we are allowed to append/prepend this fragment
            can_append = True
            can_prepend = True
            if pos_list is not None:
                p = pos_list[idx]
                # Append only if this fragment is not earlier than what we already have
                can_append = p >= max_pos
                # Prepend only if this fragment is not later than what we already have
                can_prepend = p <= min_pos

            # Try appending: result ... fragment
            if can_append:
                for k in range(max_k, 0, -1):
                    if result_words[-k:] == words[:k]:
                        if k > best_overlap:
                            best_fragment = idx
                            best_overlap = k
                            best_is_prefix = False
                        break

            # Try prepending: fragment ... result
            if can_prepend:
                for k in range(max_k, 0, -1):
                    if result_words[:k] == words[-k:]:
                        if k > best_overlap:
                            best_fragment = idx
                            best_overlap = k
                            best_is_prefix = True
                        break

        if best_fragment == -1:
            # No overlapping fragments that respect positional constraints
            break

        fragment_words = words_list[best_fragment]

        if best_is_prefix:
            if best_overlap > 0:
                # fragment[:-overlap] + result
                result_words = fragment_words[:-best_overlap] + result_words
            else:
                # No overlap but still allowed to prepend (rare case)
                result_words = fragment_words + result_words
        else:
            if best_overlap > 0:
                # result + fragment[overlap:]
                result_words.extend(fragment_words[best_overlap:])
            else:
                # No overlap but allowed to append
                result_words.extend(fragment_words)

        used.add(best_fragment)

        if pos_list is not None:
            p = pos_list[best_fragment]
            min_pos = min(min_pos, p)
            max_pos = max(max_pos, p)

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

def load_and_filter_data(
    input_file: str,
    language_filter: Optional[str] = "en",
    url_filter: Optional[Union[str, Iterable[str]]] = None,
) -> Tuple[Dict[str, List[Entry]], List[str]]:
    """Load data from file and filter by language and URL.

    Returns:
        transformed_data: dict mapping URL -> list of entries with sentences.
        url_order: list of URLs in first-seen order.
    """
    articles: Dict[str, List[Dict]] = defaultdict(list)
    url_order: List[str] = []

    # Normalize URL filters so url_filter can be:
    # - None: no filtering on URL
    # - a single string
    # - an iterable of strings: any substring is enough to keep the URL
    if url_filter is None:
        url_filters: Optional[List[str]] = None
    elif isinstance(url_filter, (list, tuple, set)):
        url_filters = [str(f) for f in url_filter]
    else:
        url_filters = [str(url_filter)]

    with open(input_file, "r", encoding="utf-8") as file:
        for line in file:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Language filter:
            # - if language_filter is None, keep all languages
            # - otherwise, keep only entries with matching lang
            if language_filter is not None and entry.get("lang") != language_filter:
                continue

            url = entry.get("url", "")
            if not url:
                continue

            # URL filters: if present, at least one substring must match
            if url_filters is not None and not any(f in url for f in url_filters):
                continue

            if url not in articles:
                url_order.append(url)
            articles[url].append(entry)

    transformed_data = transform_dict(articles)
    return transformed_data, url_order


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


def process_article(url_entries_tuple: Tuple[str, List[Entry]]) -> Dict[str, str]:
    """Process a single article; designed to be run in parallel."""
    url, entries = url_entries_tuple

    if not entries:
        return {"url": url, "text": "", "date": ""}

    # Sort entries by position
    entries.sort(key=lambda x: int(x.get("pos", 0)))

    sentences = [entry["sentence"] for entry in entries]
    positions = [int(entry["pos"]) for entry in entries]

    text = reconstruct_sentence(sentences, positions)
    text = remove_overlap(text)
    text = _clean_text(text)

    # Derive a date string (YYYY-MM-DD) from the first entry if possible
    raw_date = str(entries[0].get("date", "")) or ""
    date_only = raw_date[:10] if len(raw_date) >= 10 else ""

    return {"url": url, "text": text, "date": date_only}


# ---------------------------------------------------------------------------
# File-level multiprocessing driver
# ---------------------------------------------------------------------------

def process_file_multiprocessing(
    input_file: str,
    output_file: str,
    language_filter: Optional[str] = "en",
    url_filter: Optional[Union[str, Iterable[str]]] = None,
    num_processes: Optional[int] = None,
) -> None:
    """Load a GDELT JSON file, reconstruct articles, and write a CSV.

    Args:
        input_file: path to the .json file.
        output_file: path to the output CSV file (Text|Date|URL).
        language_filter: language code to keep (None = no language filter).
        url_filter: URL substring or iterable of substrings to keep.
        num_processes: number of worker processes (None = CPU count).
    """
    print(f"Loading and filtering data from {input_file}...")
    articles, url_order = load_and_filter_data(
        input_file, language_filter=language_filter, url_filter=url_filter
    )

    if not articles:
        print("No articles found after filtering.")
        # Still create a CSV with just a header; step 2 may delete it later if empty.
        with open(output_file, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
            writer.writerow(["Text", "Date", "URL"])
        return

    url_index = {url: idx for idx, url in enumerate(url_order)}
    work_items = list(articles.items())

    if num_processes is None or num_processes <= 0:
        num_processes = mp.cpu_count()

    print(f"Reconstructing {len(work_items)} articles using {num_processes} processes...")
    results: List[Dict[str, str]] = []

    with mp.Pool(processes=num_processes) as pool:
        for res in tqdm(
            pool.imap_unordered(process_article, work_items, chunksize=10),
            total=len(work_items),
            desc="Reconstructing articles",
        ):
            results.append(res)

    # Preserve original URL order in output
    results_sorted = sorted(results, key=lambda x: url_index.get(x["url"], float("inf")))

    # Write output CSV
    with open(output_file, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
        writer.writerow(["Text", "Date", "URL"])
        for art in results_sorted:
            writer.writerow([art.get("text", ""), art.get("date", ""), art.get("url", "")])

    print(f"Wrote {len(results_sorted)} articles to {output_file}")
