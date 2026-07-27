"""Filter and deduplicate reconstructed article CSVs.

Reads article CSV files produced by `reconstruct.py`, filters articles with a
Boolean query (AND / OR / NOT with parentheses), and writes a single CSV with:

- deduplicated URLs (keeping the longest text per URL)
- a `Source` label column when available

Query syntax:
- Operators: AND, OR, NOT (case-insensitive); every term needs an explicit operator
- Parentheses: (...) to group
- Terms: single words (e.g. fico) or quoted phrases ("giorgia meloni"). A term
  containing anything but letters/digits/underscore MUST be quoted, so write
  "centro-destra" and "fratelli d'italia", not centro-destra or d'italia.
Public entrypoint: :func:`filtermerge`.

Matching: case-insensitive whole-word search over the `Text` field.
"""

from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

try:
    import boolean  # type: ignore
except ImportError:  # pragma: no cover
    boolean = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Boolean query parsing & evaluation using boolean.py
# ---------------------------------------------------------------------------

_algebra = None


def _get_algebra():
    """Return a singleton BooleanAlgebra instance.

    We import boolean.py lazily so that importing this module doesn't terminate
    the whole program when the dependency is missing.
    """
    global _algebra
    if _algebra is None:
        if boolean is None:  # pragma: no cover
            raise ImportError(
                "The 'boolean.py' library is required. Install it with 'pip install boolean.py'."
            )
        _algebra = boolean.BooleanAlgebra()
    return _algebra


def _normalize_boolean_operators(query: str) -> str:
    """Replace AND/OR/NOT (any case) with boolean.py's 'and', 'or', 'not'."""
    q = re.sub(r"\bAND\b", " and ", query, flags=re.IGNORECASE)
    q = re.sub(r"\bOR\b", " or ", q, flags=re.IGNORECASE)
    q = re.sub(r"\bNOT\b", " not ", q, flags=re.IGNORECASE)
    # Collapse repeated whitespace
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_phrases(query: str) -> Tuple[str, Dict[str, str]]:
    """Replace quoted phrases with placeholder tokens.

    Example:
        '("giorgia meloni" AND fico)'

    becomes:
        '(PHRASE_0 AND fico)' with mapping {'PHRASE_0': 'giorgia meloni'}.
    """
    phrases: Dict[str, str] = {}

    def repl(match: re.Match) -> str:
        phrase = match.group(1)
        key = f"PHRASE_{len(phrases)}"
        phrases[key] = phrase
        return key

    # Double-quoted phrases only
    q = re.sub(r'"([^"]+)"', repl, query)
    return q, phrases


# boolean.py's tokenizer turns these words into TRUE/FALSE literals, so a bare
# term like `false` or `none` would silently make its branch constant instead of
# searching for the word. Hide them behind the same placeholder mechanism.
_RESERVED_TOKENS = ("true", "false", "none", "1", "0")


def _protect_reserved(query: str, phrases: Dict[str, str]) -> str:
    """Replace bare terms that boolean.py reads as TRUE/FALSE with placeholders.

    Runs after phrase extraction, and the boundary lookarounds keep it away from
    the digits inside the `PHRASE_<n>` placeholders themselves.
    """
    def repl(match: re.Match) -> str:
        key = f"PHRASE_{len(phrases)}"
        phrases[key] = match.group(0)
        return key

    pattern = r"(?<!\w)(?:%s)(?!\w)" % "|".join(_RESERVED_TOKENS)
    return re.sub(pattern, repl, query, flags=re.IGNORECASE)


def build_query_expr(query: Optional[str]):
    """Build and validate the parsed Boolean expression plus phrase mapping.

    Returns:
        (expr, phrases_dict) or (None, {}) if query is empty/None.
    """
    if query is None or not str(query).strip():
        return None, {}

    # 1) Extract phrases into placeholders
    q, phrases = _extract_phrases(query)

    # 2) Normalize boolean operators
    q = _normalize_boolean_operators(q)

    # 3) Shield terms boolean.py would read as TRUE/FALSE literals
    q = _protect_reserved(q, phrases)

    algebra = _get_algebra()

    try:
        expr = algebra.parse(q)
    except Exception as exc:
        raise ValueError(
            f"Invalid Boolean query: {exc}. Terms containing anything but "
            'letters/digits/underscore must be double-quoted (e.g. "centro-destra"), '
            "and every term needs an explicit AND / OR / NOT between them."
        ) from exc

    return expr, phrases


@lru_cache(maxsize=4096)
def _term_regex(term_cf: str) -> "re.Pattern[str]":
    """Whole-word matcher for an already-casefolded term.

    Plain substring matching made `butti` hit `debutti`, `buttiamo`, `farabutti`
    and surnames like `Gabutti`, so a term must land on word boundaries. The
    boundary is only asserted on a side that actually starts/ends with a word
    character, so terms like `c++` or `.net` still match.

    No re.IGNORECASE: the pattern is built from the casefolded term and searched
    against casefolded text, which makes the cheap `term in text` pre-check in
    `text_matches_query` an exact necessary condition for this regex.
    """
    pat = re.escape(term_cf)
    if term_cf[:1].isalnum() or term_cf[:1] == "_":
        pat = r"(?<!\w)" + pat
    if term_cf[-1:].isalnum() or term_cf[-1:] == "_":
        pat = pat + r"(?!\w)"
    return re.compile(pat)


def text_matches_query(text: str, expr: Any, phrases: Dict[str, str]) -> bool:
    """Evaluate expression on a given text (case-insensitive whole-word match)."""
    if expr is None:
        return True

    text_cf = text.casefold()

    algebra = _get_algebra()
    symbols = expr.get_symbols()
    subs: Dict[Any, Any] = {}

    for sym in symbols:
        name = sym.obj  # original symbol name
        if name in phrases:
            term = phrases[name].casefold()
        else:
            term = str(name).casefold()

        # Substring is a necessary condition for the whole-word match, so this
        # cheap check short-circuits the regex for the vast majority of texts.
        hit = bool(term) and term in text_cf and _term_regex(term).search(text_cf) is not None
        subs[sym] = algebra.TRUE if hit else algebra.FALSE

    try:
        value = expr.subs(subs).simplify()
    except Exception as exc:
        raise ValueError(f"Failed to evaluate query on text: {exc}") from exc

    return value == algebra.TRUE


# ---------------------------------------------------------------------------
# CSV filtering and deduplication
# ---------------------------------------------------------------------------

def iter_csv_files(input_dir: str) -> List[str]:
    """List CSV files in the given directory, sorted by name."""
    files: List[str] = []
    for name in os.listdir(input_dir):
        if name.lower().endswith(".csv"):
            files.append(os.path.join(input_dir, name))
    files.sort()
    return files


def filter_csvs_to_temp(
    input_dir: str,
    temp_output: str,
    expr,
    phrases: Dict[str, str],
) -> None:
    """Filter rows according to expr/phrases and write to a temporary CSV.

    Expected columns in the source CSVs:
        Text|Date|URL|Source  (Source may be empty)

    Column order can differ, as long as 'Text' and 'URL' exist.
    """
    csv_files = iter_csv_files(input_dir)
    if not csv_files:
        raise ValueError(f"No CSV files found in directory: {input_dir}")

    with open(temp_output, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
        writer.writerow(["Text", "Date", "URL", "Source"])

        for path in csv_files:
            with open(path, "r", encoding="utf-8") as in_f:
                reader = csv.reader(in_f, delimiter="|")
                try:
                    header = next(reader)
                except StopIteration:
                    continue

                col_index = {name: idx for idx, name in enumerate(header)}
                if "Text" not in col_index or "URL" not in col_index:
                    continue

                text_idx = col_index["Text"]
                date_idx = col_index.get("Date")
                url_idx = col_index["URL"]
                source_idx = col_index.get("Source")

                for row in reader:
                    if len(row) <= max(text_idx, url_idx):
                        continue
                    text = row[text_idx]
                    url = row[url_idx]
                    date = row[date_idx] if date_idx is not None and date_idx < len(row) else ""
                    source = row[source_idx] if source_idx is not None and source_idx < len(row) else ""

                    if not text_matches_query(text, expr, phrases):
                        continue

                    writer.writerow([text, date, url, source])


def deduplicate_by_url(temp_input: str, final_output: str) -> None:
    """Group rows by URL and keep only the row with the longest Text field."""
    if not os.path.exists(temp_input):
        raise ValueError(f"Temporary file not found: {temp_input}")

    best_rows: Dict[str, Dict[str, str]] = {}

    with open(temp_input, "r", encoding="utf-8") as in_f:
        reader = csv.reader(in_f, delimiter="|")
        header = next(reader, None) or ["Text", "Date", "URL", "Source"]

        col_index = {name: idx for idx, name in enumerate(header)}
        if "Text" not in col_index or "URL" not in col_index:
            raise ValueError("Temporary CSV does not contain expected 'Text' and 'URL' columns")

        text_idx = col_index["Text"]
        date_idx = col_index.get("Date")
        url_idx = col_index["URL"]
        source_idx = col_index.get("Source")

        for row in reader:
            if len(row) <= max(text_idx, url_idx):
                continue

            text = row[text_idx]
            url = row[url_idx]
            date = row[date_idx] if date_idx is not None and date_idx < len(row) else ""
            source = row[source_idx] if source_idx is not None and source_idx < len(row) else ""

            prev = best_rows.get(url)
            if prev is None or len(text) > len(prev["Text"]):
                best_rows[url] = {"Text": text, "Date": date, "URL": url, "Source": source}

    with open(final_output, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f, delimiter="|", quoting=csv.QUOTE_NONE)
        writer.writerow(["Text", "Date", "URL", "Source"])
        for row in best_rows.values():
            writer.writerow([row["Text"], row["Date"], row["URL"], row.get("Source", "")])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def filtermerge(
    input_dir: str,
    output_file: str,
    *,
    query: Optional[str] = None,
    keep_temp: bool = False,
    verbose: bool = True,
) -> None:
    """Filter CSVs in `input_dir` and write one deduplicated output CSV.

    Args:
        input_dir: directory containing per-file CSVs (e.g. from reconstruct.py).
        output_file: final output CSV path.
        query: boolean query string, or None for no filtering.
        keep_temp: keep the intermediate `.tmp` file if True.
        verbose: print progress messages if True.
    """
    expr, phrases = build_query_expr(query)
    temp_output = output_file + ".tmp"

    if verbose:
        print(f"Filtering CSV files in {input_dir} into temporary file {temp_output}.")
    filter_csvs_to_temp(input_dir, temp_output, expr, phrases)

    if verbose:
        print(f"Deduplicating by URL and writing final output to {output_file}.")
    deduplicate_by_url(temp_output, output_file)

    if not keep_temp and os.path.exists(temp_output):
        os.remove(temp_output)


__all__ = ["filtermerge", "build_query_expr"]
