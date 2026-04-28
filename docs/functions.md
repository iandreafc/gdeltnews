---
layout: default
title: Function reference
nav_order: 2
---

# Function reference

This page documents the functions shipped in `src/gdeltnews/` (and the most important helpers they rely on). It focuses on behavior, inputs, outputs, and notable edge cases.

## Top-level package exports (`gdeltnews`)

### `download(start, end, *, outdir="gdeltdata", overwrite=False, decompress=True, timeout=30, show_progress=True) -> DownloadStats`

Download GDELT Web NGrams minute files for an inclusive time range.

- **Inputs**
  - `start`, `end`: either `datetime` or a timestamp string. Supported string formats include:
    - `YYYY-MM-DDTHH:MM:SS` (optionally with trailing `Z`)
    - `YYYY-MM-DD HH:MM:SS`
    - `YYYYMMDDHHMMSS`
  - `outdir`: destination directory for downloaded files
  - `overwrite`: redownload even if the `.gz` already exists locally
  - `decompress`: if `True`, also write the decompressed `.json` files
  - `timeout`: HTTP timeout in seconds
  - `show_progress`: show a progress bar across minute slots

- **Behavior**
  - Iterates **minute-by-minute** from `start` to `end` (inclusive), attempting to fetch `<YYYYMMDDHHMMSS>.webngrams.json.gz` from the GDELT Web NGrams base URL.
  - If a minute file does not exist (non-200 response), it is skipped.


### `reconstruct(input_dir="gdeltdata", output_dir="gdeltpreprocessed", *, language=None, url_filters=None, processes=None, delete_gz=False, delete_empty_csv=True, show_progress=True) -> None`

Bulk reconstruction runner for a folder of GDELT `*.webngrams.json.gz` files.

- **Inputs**
  - `input_dir`: directory containing the `.gz` files
  - `output_dir`: directory where per-input CSVs are written
  - `language`: optional language code filter (e.g. `"it"`). `None` keeps all languages
  - `url_filters`: optional iterable of URL substrings to keep (any match keeps a URL)
  - `processes`: number of worker processes used per input file (`None` uses all cores)
  - `delete_gz`: delete original `.gz` after processing
  - `delete_empty_csv`: delete CSVs that contain only the header row
  - `show_progress`: show a progress bar across files

- **Outputs**
  - Writes one CSV per input file to `output_dir` with delimiter `|` and header:
    - `Text|Date|URL|Source`

- **Behavior**
  - Streams each `.json.gz` input directly; it does not create, require, or delete decompressed `.json` files.

### `filtermerge(input_dir, output_file, *, query=None, keep_temp=False, verbose=True) -> None`

Filter, merge, and deduplicate reconstructed CSVs.

- **Inputs**
  - `input_dir`: directory of CSV files (as produced by `reconstruct`)
  - `output_file`: destination CSV path
  - `query`: Boolean query string using `AND`, `OR`, `NOT` plus parentheses. Use double quotes for phrases, e.g. `"julia roberts"`.
  - `keep_temp`: keep the intermediate `output_file + ".tmp"` file
  - `verbose`: print progress messages

- **Behavior**
  - Performs **case-insensitive substring matching** over the `Text` column.
  - Deduplicates by `URL`, keeping the row with the **longest** `Text`.

---

## Module: `gdeltnews.wordmatch`

### `transform_dict(original_dict: dict[str, list[dict]]) -> dict[str, list[Entry]]`

Convert raw per-URL entry dictionaries into simplified “sentence fragment” entries.

- Builds `sentence` from `pre`, `ngram`, `post`.
- Normalizes some early-position artifacts (e.g. keeps substring after `" / "` when `pos < 20`).

### `reconstruct_sentence(fragments: list[str], positions: list[int] | None = None) -> str`

Reconstruct a longer text by merging overlapping fragments (word overlap).

- Greedy overlap merge (max overlap first).
- If `positions` are given, enforces a constraint that prevents obviously wrong reorderings:
  - only appends fragments whose position is not earlier than the current max position
  - only prepends fragments whose position is not later than the current min position

### `remove_overlap(text: str) -> str`

Conservative cleanup that removes simple duplicated prefix/suffix overlaps in the final reconstructed text.

### `load_and_filter_data(input_file: str, language_filter="en"|None, url_filter=None) -> (articles: dict, url_order: list[str])`

Read a `*.webngrams.json` or `*.webngrams.json.gz` file line-by-line and:

- optionally filter by language (`language_filter=None` keeps all)
- optionally filter by URL substring(s) — empty/whitespace-only filters are dropped, so passing `[""]` no longer matches every URL
- transform each kept record into a sentence-level entry inline (one pass over the file)
- group entries by URL
- return:
  - the per-URL entries dict
  - the URL order as first encountered in the file (kept for backward compatibility; `process_file_multiprocessing` no longer relies on it)

### `determine_source_label(url: str, url_filters: list[str] | None = None) -> str`

Derive a `Source` label from URL filters:

- exactly one filter matches: returns that filter string
- multiple filters match: returns `"Multiple URL matched"`
- no filters or no matches: returns `""`

### `process_article((url, entries), url_filters=None) -> dict[str, str]`

Reconstruct one article (intended for multiprocessing).

- sorts entries by `pos` (without mutating the caller's list)
- merges fragments with `reconstruct_sentence`
- runs `remove_overlap` and basic output cleanup
- returns a dict with `url`, `text`, `date`, `source`

`url_filters` accepts either a `list[str]` (back-compat — casefolded per call) or a list of pre-casefolded `(original, casefolded)` tuples. `process_file_multiprocessing` passes the tuple form so the casefold work happens once per file rather than once per article.

If reconstruction raises, the exception is caught inside `process_article` so a single bad article cannot kill the multiprocessing worker. The returned dict gains an extra `"error"` key with a short `"ExceptionType: message"` string; `url` and `source` are still populated so the driver can log which article failed.

### `process_file_multiprocessing(input_file, output_file, language_filter="en"|None, url_filter=None, num_processes=None, pool=None, show_progress=True) -> None`

Core driver for reconstructing one JSON or JSON.GZ file into a CSV.

- Uses a multiprocessing pool with `imap_unordered`.
- **Streams results to disk** as workers finish — the output rows therefore appear in worker-completion order, not in original URL order. This keeps memory flat regardless of input size (no in-memory buffer of all reconstructed articles).
- Always writes a CSV header even when no articles are found.
- Per-article reconstruction failures are logged to stdout (or via `tqdm.write` when the progress bar is active) and the failing article is written with empty `Text` but a populated `URL`/`Source`, so it is still traceable in the output CSV.
- New optional kwargs:
  - `pool`: an existing `multiprocessing.Pool` to reuse. When this driver is called once per input file (as it is from `reconstruct`), passing one pool across all calls avoids the per-file pool-startup cost (significant on Windows where Pool startup re-imports the module).
  - `show_progress`: set to `False` to silence the per-file tqdm bar (useful when an outer caller has its own progress bar).
