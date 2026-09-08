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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm


GDELT_BASE_URL = "http://data.gdeltproject.org/gdeltv3/webngrams"

# GDELT serves one small file per minute, so wall time is dominated by
# per-request latency rather than bandwidth: fetching them concurrently over a
# single pooled connection set is far faster than one blocking GET at a time.
DEFAULT_WORKERS = 8
DEFAULT_RETRIES = 3

# 4xx means "this minute isn't published" and retrying is pointless -- except
# for these two, which say "ask again later" rather than "never".
_RETRYABLE_4XX = frozenset({408, 429})


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

TimestampLike = Union[str, dt.datetime]


@dataclass(frozen=True)
class DownloadStats:
    """Simple download summary returned by :func:`download`.

    ``missing`` and ``failed`` are deliberately separate: a missing minute is
    normal (GDELT simply has no file for it), whereas a failed one means the
    request kept erroring after all retries and leaves a real gap in the data.
    """
    requested_minutes: int
    downloaded_gz: int
    decompressed_json: int
    missing: int = 0
    failed: int = 0


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

def make_session(workers: int = DEFAULT_WORKERS) -> requests.Session:
    """Build a Session whose connection pool is large enough for `workers`.

    Without this every minute file paid for a fresh TCP handshake, which on a
    multi-hour range costs more than the transfers themselves.
    """
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_minute(
    ts: dt.datetime,
    dest_dir: str,
    *,
    overwrite: bool = False,
    timeout: int = 30,
    quiet: bool = False,
    session: Optional[requests.Session] = None,
    retries: int = DEFAULT_RETRIES,
) -> Tuple[Optional[str], str]:
    """Download one minute file. Returns (path_or_None, outcome).

    ``outcome`` is one of "ok", "cached", "missing" (404 - that minute simply
    isn't published) or "failed" (still erroring after `retries` attempts).

    :func:`download` is the normal entry point. This lower-level variant exists
    for callers that drive their own loop and need the per-minute outcome --
    the GUI uses it to advance its progress bar and still tell the user how
    many slots genuinely failed.
    """
    os.makedirs(dest_dir, exist_ok=True)

    fname = gdelt_filename_for_minute(ts)
    url = f"{GDELT_BASE_URL}/{fname}"
    gz_path = os.path.join(dest_dir, fname)

    if not overwrite and os.path.exists(gz_path):
        if not quiet:
            print(f"File already present, skipping download: {gz_path}")
        return gz_path, "cached"

    http = session if session is not None else requests
    # Download to a sidecar and rename on success. Writing straight to
    # gz_path meant an interrupted run left a truncated file that the
    # "already present" check above would happily accept on the next run.
    part_path = gz_path + ".part"
    last_error = ""

    for attempt in range(retries + 1):
        try:
            resp = http.get(url, stream=True, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
        else:
            with resp:
                if resp.status_code == 200:
                    try:
                        with open(part_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=1 << 20):
                                if chunk:
                                    f.write(chunk)
                        os.replace(part_path, gz_path)
                        return gz_path, "ok"
                    except (OSError, requests.RequestException) as exc:
                        last_error = str(exc)
                    finally:
                        if os.path.exists(part_path):
                            try:
                                os.remove(part_path)
                            except OSError:
                                pass
                elif resp.status_code == 404:
                    # Not an error: GDELT has no file for this minute.
                    if not quiet:
                        print(f"File not available (status 404): {url}")
                    return None, "missing"
                elif resp.status_code < 500 and resp.status_code not in _RETRYABLE_4XX:
                    if not quiet:
                        print(
                            f"File not available (status {resp.status_code}): {url}"
                        )
                    return None, "missing"
                else:
                    # 5xx, 408 or 429: worth another attempt.
                    last_error = f"HTTP {resp.status_code}"

        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))

    if not quiet:
        print(f"Giving up on {url} after {retries + 1} attempts: {last_error}")
    return None, "failed"


def download_gdelt_file(
    ts: dt.datetime,
    dest_dir: str,
    *,
    overwrite: bool = False,
    timeout: int = 30,
    quiet: bool = False,
    session: Optional[requests.Session] = None,
    retries: int = DEFAULT_RETRIES,
) -> Optional[str]:
    """Download a single GDELT Web NGrams file for a given minute.

    Returns the path to the downloaded .gz file, or None if the file
    does not exist on the server or the request kept failing.

    Args:
        session: reuse an existing Session (see :func:`make_session`) to avoid
            a fresh TCP handshake per file. Optional; a plain request is used
            when omitted.
        retries: extra attempts on network errors, 5xx, 408 and 429. Other
            4xx responses are never retried: a 404 just means GDELT has no
            file for that minute.
    """
    gz_path, _outcome = fetch_minute(
        ts,
        dest_dir,
        overwrite=overwrite,
        timeout=timeout,
        quiet=quiet,
        session=session,
        retries=retries,
    )
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
    workers: int = DEFAULT_WORKERS,
    retries: int = DEFAULT_RETRIES,
) -> DownloadStats:
    """Download GDELT Web NGrams files for the given time range.

    Args:
        start: start timestamp (datetime or supported string format).
        end: end timestamp (datetime or supported string format).
        outdir: destination directory.
        overwrite: redownload even if .gz exists.
        decompress: if True, also write decompressed .json files. Not needed
            for reconstruction, which reads the .gz files directly; leaving
            this off halves disk usage and I/O.
        timeout: HTTP request timeout seconds.
        show_progress: whether to show a tqdm progress bar.
        workers: concurrent downloads. This is I/O bound, so threads are
            enough. Pass 1 for the old strictly-serial behaviour.
        retries: extra attempts per file on network errors, 5xx, 408 and 429.

    Returns:
        DownloadStats with requested slot count and per-outcome counts.
    """
    start_dt = _coerce_timestamp(start)
    end_dt = _coerce_timestamp(end)

    minutes = list(iter_minutes(start_dt, end_dt))
    total = len(minutes)
    print(f"Time range from {start_dt} to {end_dt} covers {total} minute slots.")
    print(f"Target directory for downloads: {outdir}")

    os.makedirs(outdir, exist_ok=True)

    workers = max(1, min(int(workers), total or 1))
    downloaded = 0
    missing = 0
    failed = 0
    fetched: List[str] = []

    with make_session(workers) as session:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    fetch_minute,
                    ts,
                    outdir,
                    overwrite=overwrite,
                    timeout=timeout,
                    quiet=True,
                    session=session,
                    retries=retries,
                )
                for ts in minutes
            ]

            completed = as_completed(futures)
            if show_progress:
                completed = tqdm(
                    completed, total=total, desc="Downloading", unit="file"
                )

            for future in completed:
                gz_path, outcome = future.result()
                if outcome == "missing":
                    missing += 1
                elif outcome == "failed":
                    failed += 1
                else:
                    downloaded += 1
                    if gz_path is not None:
                        fetched.append(gz_path)

    decompressed = 0
    if decompress:
        iterator = fetched
        if show_progress:
            iterator = tqdm(fetched, desc="Decompressing", unit="file")
        for gz_path in iterator:
            try:
                decompress_gzip(gz_path)
                decompressed += 1
            except Exception as exc:
                print(f"Decompression failed for {gz_path}: {exc}")

    print(f"Downloaded {downloaded} .gz files into {outdir}.")
    if missing:
        print(f"{missing} minute slots have no file on the GDELT server.")
    if failed:
        print(
            f"WARNING: {failed} minute slots failed after {retries + 1} attempts "
            "and are missing from the output directory."
        )
    if decompress:
        print(f"Decompressed {decompressed} files to .json in {outdir}.")

    return DownloadStats(
        requested_minutes=total,
        downloaded_gz=downloaded,
        decompressed_json=decompressed,
        missing=missing,
        failed=failed,
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
    workers: int = DEFAULT_WORKERS,
    retries: int = DEFAULT_RETRIES,
) -> DownloadStats:
    """Download GDELT Web NGrams files for the given time range.

    This is the primary API for this module. Files are fetched concurrently
    over a shared connection pool; pass ``workers=1`` to restore the old
    strictly-serial behaviour.

    Note that ``reconstruct()`` reads the ``.json.gz`` files directly, so
    ``decompress=False`` saves both disk space and time.
    """
    return _download_range(
        start,
        end,
        outdir=outdir,
        overwrite=overwrite,
        decompress=decompress,
        timeout=timeout,
        show_progress=show_progress,
        workers=workers,
        retries=retries,
    )


# Alias kept for convenience for existing imports (non-CLI).
__all__ = [
    "DownloadStats",
    "download",
    "fetch_minute",
    "make_session",
    "parse_timestamp",
]
