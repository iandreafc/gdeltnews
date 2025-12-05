#!/usr/bin/env python3
"""
Step 1: download GDELT Web NGrams files for a time range.

Downloads GDELT Web NGrams 3.0 JSON.GZ files for a given UTC time range
and stores them under a local directory (default "gdeltdata").

By default, both the compressed (.json.gz) and decompressed (.json) versions
are created. If --no-decompress is used, only .json.gz files are written.
"""

import argparse
import datetime as dt
import gzip
import os
from typing import Iterable, Optional

import requests
from tqdm import tqdm


GDELT_BASE_URL = "http://data.gdeltproject.org/gdeltv3/webngrams"


def parse_timestamp(ts: str) -> dt.datetime:
    """Parse a timestamp string into a naive UTC datetime.

    Accepted formats:
      - 2025-03-16T00:01:00
      - 2025-03-16T00:01:00Z
      - 2025-03-16 00:01:00
      - 20250316000100
    """
    ts = ts.strip()
    if len(ts) == 14 and ts.isdigit():
        return dt.datetime.strptime(ts, "%Y%m%d%H%M%S")

    if ts.endswith("Z"):
        ts = ts[:-1]

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(ts, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unrecognized timestamp format: {ts}")


def iter_minutes(start: dt.datetime, end: dt.datetime) -> Iterable[dt.datetime]:
    """Yield every minute from start to end inclusive."""
    if end < start:
        raise ValueError("End time must be >= start time")

    current = start
    step = dt.timedelta(minutes=1)
    while current <= end:
        yield current
        current += step


def gdelt_filename_for_minute(ts: dt.datetime) -> str:
    """Return the GDELT Web NGrams filename for a given minute timestamp."""
    return ts.strftime("%Y%m%d%H%M%S") + ".webngrams.json.gz"


def download_gdelt_file(
    ts: dt.datetime,
    dest_dir: str,
    overwrite: bool = False,
    timeout: int = 30,
    quiet: bool = False,
) -> Optional[str]:
    """Download a single GDELT Web NGrams file for a given minute.

    Returns the path to the downloaded .gz file, or None if the file
    does not exist on the server or a request error occurs.
    """
    os.makedirs(dest_dir, exist_ok=True)

    fname = gdelt_filename_for_minute(ts)
    url = f"{GDELT_BASE_URL}/{fname}"
    gz_path = os.path.join(dest_dir, fname)

    if not overwrite and os.path.exists(gz_path):
        if not quiet:
            print(f"File already present, skipping download: {gz_path}")
        return gz_path

    try:
        resp = requests.get(url, stream=True, timeout=timeout)
    except requests.RequestException as exc:
        if not quiet:
            print(f"Request error for {url}: {exc}")
        return None

    if resp.status_code != 200:
        if not quiet:
            print(f"File not available (status {resp.status_code}): {url}")
        return None

    with open(gz_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)

    return gz_path


def decompress_gzip(path_gz: str) -> str:
    """Decompress a .gz file to a .json file in the same directory.

    Returns the path to the .json file. If the .json file already exists,
    it is returned as-is and no decompression is performed.
    """
    if not path_gz.endswith(".gz"):
        raise ValueError(f"Expected a .gz file, got: {path_gz}")

    path_json = path_gz[:-3]
    if os.path.exists(path_json):
        return path_json

    with gzip.open(path_gz, "rb") as f_in, open(path_json, "wb") as f_out:
        while True:
            chunk = f_in.read(1 << 20)
            if not chunk:
                break
            f_out.write(chunk)

    return path_json


def run_download(
    start_ts: str,
    end_ts: str,
    outdir: str,
    overwrite: bool = False,
    no_decompress: bool = False,
) -> None:
    """Download GDELT files for the given time range and optionally decompress."""
    start_dt = parse_timestamp(start_ts)
    end_dt = parse_timestamp(end_ts)

    minutes = list(iter_minutes(start_dt, end_dt))
    total = len(minutes)
    print(f"Time range from {start_dt} to {end_dt} covers {total} minute slots.")
    print(f"Target directory for downloads: {outdir}")

    os.makedirs(outdir, exist_ok=True)

    downloaded = 0
    decompressed = 0

    for ts in tqdm(minutes, desc="Downloading", unit="file"):
        gz_path = download_gdelt_file(ts, outdir, overwrite=overwrite, quiet=True)
        if gz_path is None:
            continue
        downloaded += 1

        if not no_decompress:
            try:
                decompress_gzip(gz_path)
                decompressed += 1
            except Exception as exc:
                print(f"Decompression failed for {gz_path}: {exc}")

    print(f"Downloaded {downloaded} .gz files into {outdir}.")
    if not no_decompress:
        print(f"Decompressed {decompressed} files to .json in {outdir}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download GDELT Web NGrams files for a time range into a directory "
            "and optionally decompress them to JSON."
        )
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start timestamp (UTC), for example 2025-03-15T00:00:00 or 20250315000000.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End timestamp (UTC), for example 2025-03-16T23:59:00 or 20250316235900.",
    )
    parser.add_argument(
        "--outdir",
        default="gdeltdata",
        help='Output directory for downloaded files (default: "gdeltdata").',
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redownload files even if the .gz file already exists.",
    )
    parser.add_argument(
        "--no-decompress",
        action="store_true",
        help="Skip decompression of .gz files to .json.",
    )

    args = parser.parse_args()

    try:
        run_download(
            start_ts=args.start,
            end_ts=args.end,
            outdir=args.outdir,
            overwrite=args.overwrite,
            no_decompress=args.no_decompress,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
