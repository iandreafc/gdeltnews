"""
gdeltnews: download + reconstruct + filter GDELT Web NGrams 3.0 content.

High-level public API:
- download() for fetching Web NGrams minute files
- reconstruct() for reconstructing articles into per-file CSVs
- filtermerge() for filtering + deduplicating reconstructed CSVs
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .download import DownloadStats, download, parse_timestamp
from .filtermerge import build_query_expr, filtermerge
from .reconstruct import reconstruct
from .wordmatch import reconstruct_webngrams_file

try:
    __version__ = version("gdeltnews")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    "DownloadStats",
    "download",
    "parse_timestamp",
    "reconstruct",
    "filtermerge",
    "build_query_expr",
    "reconstruct_webngrams_file",
]
