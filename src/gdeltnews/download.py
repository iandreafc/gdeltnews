"""Download GDELT Web NGrams 3.0 JSON.GZ files for a time range.

This module exposes a single public entrypoint, :func:`download`, that takes
normal Python parameters (no CLI).

Example:

    from download import download

    download(
        "2025-03-15T00:00:00",
        "2025-03-15T00:10:00",
        outdir="gdeltdata",
        decompress=True,
    )
"""

from __future__ import annotations
import datetime as dt
import gzip
import os
from dataclasses import dataclass
from typing import Iterable, Optional, Union

import requests
from tqdm import tqdm


GDELT_BASE_URL = "http://data.gdeltproject.org/gdeltv3/webngrams"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

TimestampLike = Union[str, dt.datetime]


@dataclass(frozen=True)
class DownloadStats:
    """Simple download summary returned by :func:`download`."""
    requested_minutes: int
    downloaded_gz: int
    decompressed_json: int


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

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


def _coerce_timestamp(value: TimestampLike) -> dt.datetime:
    """Accept either a datetime or a timestamp string."""
    if isinstance(value, dt.datetime):
        return value
    return parse_timestamp(str(value))


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


# ---------------------------------------------------------------------------
# Download and decompression
# ---------------------------------------------------------------------------

def download_gdelt_file(
    ts: dt.datetime,
    dest_dir: str,
    *,
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _download_range(
    start: TimestampLike,
    end: TimestampLike,
    *,
    outdir: str = "gdeltdata",
    overwrite: bool = False,
    decompress: bool = True,
    timeout: int = 30,
    show_progress: bool = True,
) -> DownloadStats:
    """Download GDELT Web NGrams files for the given time range.

    Args:
        start: start timestamp (datetime or supported string format).
        end: end timestamp (datetime or supported string format).
        outdir: destination directory.
        overwrite: redownload even if .gz exists.
        decompress: if True, also write decompressed .json files.
        timeout: HTTP request timeout seconds.
        show_progress: whether to show a tqdm progress bar.

    Returns:
        DownloadStats with requested slot count and successful counts.
    """
    start_dt = _coerce_timestamp(start)
    end_dt = _coerce_timestamp(end)

    minutes = list(iter_minutes(start_dt, end_dt))
    total = len(minutes)
    print(f"Time range from {start_dt} to {end_dt} covers {total} minute slots.")
    print(f"Target directory for downloads: {outdir}")

    os.makedirs(outdir, exist_ok=True)

    downloaded = 0
    decompressed = 0

    iterator = minutes
    if show_progress:
        iterator = tqdm(minutes, desc="Downloading", unit="file")

    for ts in iterator:
        gz_path = download_gdelt_file(
            ts,
            outdir,
            overwrite=overwrite,
            timeout=timeout,
            quiet=True,
        )
        if gz_path is None:
            continue
        downloaded += 1

        if decompress:
            try:
                decompress_gzip(gz_path)
                decompressed += 1
            except Exception as exc:
                print(f"Decompression failed for {gz_path}: {exc}")

    print(f"Downloaded {downloaded} .gz files into {outdir}.")
    if decompress:
        print(f"Decompressed {decompressed} files to .json in {outdir}.")

    return DownloadStats(
        requested_minutes=total,
        downloaded_gz=downloaded,
        decompressed_json=decompressed,
    )


def download(
    start: TimestampLike,
    end: TimestampLike,
    *,
    outdir: str = "gdeltdata",
    overwrite: bool = False,
    decompress: bool = True,
    timeout: int = 30,
    show_progress: bool = True,
) -> DownloadStats:
    """Download GDELT Web NGrams files for the given time range.

    This is the primary API for this module.
    """
    return _download_range(
        start,
        end,
        outdir=outdir,
        overwrite=overwrite,
        decompress=decompress,
        timeout=timeout,
        show_progress=show_progress,
    )


# Alias kept for convenience for existing imports (non-CLI).
__all__ = ["DownloadStats", "download", "parse_timestamp"]
