#!/usr/bin/env python3
"""Step 2: reconstruct articles from GDELT Web NGrams files.

For each GDELT .webngrams.json.gz file in a directory:

1. Decompress to .json.
2. Reconstruct articles using gdelt_wordmatch_multiprocess.process_file_multiprocessing.
3. Write one CSV per file into a target directory.
4. Remove the decompressed .json file.
5. Optionally, remove the original .gz file.
6. Delete empty CSVs (files with only a header row).
"""

import argparse
import csv
import gzip
import os
from pathlib import Path
from typing import List, Optional

from tqdm import tqdm

from gdelt_wordmatch_multiprocess import process_file_multiprocessing


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
    """Find all .webngrams.json.gz files in the given directory, sorted by name."""
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


def run_reconstruction(
    input_dir: str,
    output_dir: str,
    language: Optional[str] = None,
    url_filter: Optional[str] = None,
    processes: Optional[int] = None,
    delete_gz: bool = False,
) -> None:
    """Orchestrate step 2 over all .webngrams.json.gz files in input_dir."""
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)

    if not in_dir.exists() or not in_dir.is_dir():
        raise ValueError(f"Input directory does not exist or is not a directory: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    gz_files = find_gz_files(in_dir)
    total_files = len(gz_files)
    if total_files == 0:
        print(f"No .webngrams.json.gz files found in {in_dir}")
        return

    print(f"Found {total_files} .webngrams.json.gz files in {in_dir}")
    print(f"Output CSV files will be written to {out_dir}")

    # Parse URL filters: string can be a single substring or a comma-separated list
    url_filters: Optional[List[str]] = None
    if url_filter is not None:
        parts = [s.strip() for s in url_filter.split(",") if s.strip()]
        if parts:
            url_filters = parts

    for gz_path in tqdm(gz_files, desc="Step 2: processing files", unit="file"):
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
                url_filter=url_filters,
                num_processes=processes,
            )
        except Exception as exc:
            print(f"Error processing {json_path}: {exc}")
        finally:
            # 4) Remove the decompressed .json file
            try:
                if json_path.exists():
                    os.remove(json_path)
            except Exception as exc_rm:
                print(f"Could not remove temporary JSON file {json_path}: {exc_rm}")

        # 5) Remove empty CSVs (only header or no rows)
        if csv_path.exists() and not csv_has_data(csv_path):
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Step 2: decompress GDELT .webngrams.json.gz files, reconstruct "
            "articles with gdelt_wordmatch_multiprocess.py, and write CSV files."
        )
    )
    parser.add_argument(
        "--input-dir",
        default="gdeltdata",
        help='Directory containing .webngrams.json.gz files (default: "gdeltdata").',
    )
    parser.add_argument(
        "--output-dir",
        default="gdeltpreprocessed",
        help='Directory for output CSV files (default: "gdeltpreprocessed").',
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code for filtering inside reconstruction (if omitted, no language filter).",
    )
    parser.add_argument(
        "--url-filter",
        default=None,
        help=(
            "Optional substring or comma-separated list of substrings to filter URLs, "
            "for example: 'repubblica.it,corriere.it'."
        ),
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=None,
        help="Number of worker processes for reconstruction (default: all available cores).",
    )
    parser.add_argument(
        "--delete-gz",
        action="store_true",
        help="If set, remove the original .webngrams.json.gz files after processing.",
    )

    args = parser.parse_args()

    try:
        run_reconstruction(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            language=args.language,
            url_filter=args.url_filter,
            processes=args.processes,
            delete_gz=args.delete_gz,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
