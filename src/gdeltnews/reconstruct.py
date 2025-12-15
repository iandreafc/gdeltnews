"""Reconstruct articles from GDELT Web NGrams files in bulk.

For each GDELT *.webngrams.json.gz file in a directory:

1. Decompress to *.json (optional to keep).
2. Reconstruct articles using `wordmatch.process_file_multiprocessing`.
3. Write one CSV per input file into a target directory.
4. Optionally delete:
   - the temporary decompressed *.json
   - empty CSVs (header-only)
   - the original *.gz files

Public entrypoint: :func:`reconstruct`.

Example:

    from reconstruct import reconstruct

    reconstruct(
        input_dir="gdeltdata",
        output_dir="gdeltpreprocessed",
        language="it",
        url_filters=["repubblica.it", "corriere.it"],
        processes=8,
    )
"""

from __future__ import annotations

import csv
import gzip
import os
from pathlib import Path
from typing import Iterable, List, Optional

from tqdm import tqdm

# Support both "script in the same folder" and "package import" layouts.
try:  # pragma: no cover
    from .wordmatch import process_file_multiprocessing
except ImportError:  # pragma: no cover
    from wordmatch import process_file_multiprocessing


def decompress_gzip(path_gz: Path) -> Path:
    """Decompress a .gz file to a .json file in the same directory.

    If the .json file already exists, it is returned and decompression is
    skipped.
    """
    if not str(path_gz).endswith(".gz"):
        raise ValueError(f"Expected a .gz file, got: {path_gz}")

    path_json = Path(str(path_gz)[:-3])
    if path_json.exists():
        return path_json

    with gzip.open(path_gz, "rb") as f_in, open(path_json, "wb") as f_out:
        while True:
            chunk = f_in.read(1 << 20)
            if not chunk:
                break
            f_out.write(chunk)

    return path_json


def find_gz_files(input_dir: Path) -> List[Path]:
    """Find all *.webngrams.json.gz files in the given directory, sorted by name."""
    return sorted(input_dir.glob("*.webngrams.json.gz"))


def csv_has_data(csv_path: Path) -> bool:
    """Return True if the CSV file contains at least one data row beyond the header."""
    if not csv_path.exists():
        return False

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            header = next(reader, None)
            if header is None:
                return False
            for _ in reader:
                return True
            return False
    except OSError:
        return False


def reconstruct(
    input_dir: str = "gdeltdata",
    output_dir: str = "gdeltpreprocessed",
    *,
    language: Optional[str] = None,
    url_filters: Optional[Iterable[str]] = None,
    processes: Optional[int] = None,
    delete_gz: bool = False,
    delete_json: bool = True,
    delete_empty_csv: bool = True,
    show_progress: bool = True,
) -> None:
    """Orchestrate reconstruction over all *.webngrams.json.gz files in a directory.

    Args:
        input_dir: directory containing *.webngrams.json.gz files.
        output_dir: directory where per-file CSVs are written.
        language: optional language code (None = no language filter).
        url_filters: optional iterable of URL substrings to keep. Example:
            ["repubblica.it", "corriere.it"]
        processes: number of worker processes (None = all cores).
        delete_gz: if True, delete the original *.gz after processing.
        delete_json: if True, delete the temporary decompressed *.json.
        delete_empty_csv: if True, delete CSVs that only contain a header row.
        show_progress: whether to show a tqdm progress bar.
    """
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)

    if not in_dir.exists() or not in_dir.is_dir():
        raise ValueError(f"Input directory does not exist or is not a directory: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    gz_files = find_gz_files(in_dir)
    total_files = len(gz_files)
    if total_files == 0:
        print(f"No *.webngrams.json.gz files found in {in_dir}")
        return

    print(f"Found {total_files} *.webngrams.json.gz files in {in_dir}")
    print(f"Output CSV files will be written to {out_dir}")

    # Normalize URL filters into a list of strings (or None)
    url_filters_list: Optional[List[str]] = None
    if url_filters is not None:
        parts = [str(s).strip() for s in url_filters if str(s).strip()]
        url_filters_list = parts or None

    iterator = gz_files
    if show_progress:
        iterator = tqdm(gz_files, desc="Reconstructing", unit="file")

    for gz_path in iterator:
        print(f"\nProcessing {gz_path.name}")

        # 1) Decompress to .json
        try:
            json_path = decompress_gzip(gz_path)
        except Exception as exc:
            print(f"Decompression failed for {gz_path}: {exc}")
            continue

        # 2) Build output CSV path
        base_name = json_path.stem  # e.g. "20250316000100.webngrams"
        csv_name = f"{base_name}.articles.csv"
        csv_path = out_dir / csv_name

        # 3) Call reconstruction function
        try:
            process_file_multiprocessing(
                input_file=str(json_path),
                output_file=str(csv_path),
                language_filter=language,
                url_filter=url_filters_list,
                num_processes=processes,
            )
        except Exception as exc:
            print(f"Error processing {json_path}: {exc}")
        finally:
            # 4) Optionally remove the decompressed .json file
            if delete_json:
                try:
                    if json_path.exists():
                        os.remove(json_path)
                except Exception as exc_rm:
                    print(f"Could not remove temporary JSON file {json_path}: {exc_rm}")

        # 5) Optionally remove empty CSVs (only header or no rows)
        if delete_empty_csv and csv_path.exists() and not csv_has_data(csv_path):
            try:
                os.remove(csv_path)
                print(f"Removed empty CSV (no articles): {csv_path.name}")
            except Exception as exc_rm_csv:
                print(f"Could not remove empty CSV {csv_path}: {exc_rm_csv}")

        # 6) Optionally remove the original .gz file
        if delete_gz:
            try:
                if gz_path.exists():
                    os.remove(gz_path)
            except Exception as exc_rm_gz:
                print(f"Could not remove original GZ file {gz_path}: {exc_rm_gz}")


__all__ = ["reconstruct", "decompress_gzip", "find_gz_files"]
