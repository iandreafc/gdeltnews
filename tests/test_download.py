"""Self-check for the download layer against a local HTTP server.

Covers the behaviours that are easy to get wrong and impossible to notice in
production, because a lost minute file just looks like a quiet news minute:

  - a 404 (or any other plain 4xx) means "GDELT has no file for that minute"
    and must NOT be retried;
  - a 5xx, a 429, or a dropped connection MUST be retried, then reported as a
    failure rather than silently skipped;
  - an interrupted download must not leave a truncated .gz that the next run
    mistakes for a complete one;
  - concurrent downloads must fetch every minute exactly once.

No network access: it spins up http.server on localhost and points
GDELT_BASE_URL at it.

Run: python tests/test_download.py   (no framework needed)
"""

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# import_module, not `from gdeltnews import download`: __init__ re-exports the
# download() function under that name, which shadows the submodule.
from importlib import import_module

dl = import_module("gdeltnews.download")

PAYLOAD = b"x" * 4096

# filename -> list of behaviours, one per attempt: "ok", "cut" (truncated
# response) or any HTTP status code as a string, e.g. "404", "500", "429".
SCRIPT = {}
HITS = {}
_LOCK = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the default stderr spam
        pass

    def do_GET(self):
        name = self.path.rsplit("/", 1)[-1]
        with _LOCK:
            HITS[name] = HITS.get(name, 0) + 1
            attempt = HITS[name] - 1
            script = SCRIPT.get(name, ["ok"])
        behaviour = script[attempt] if attempt < len(script) else script[-1]

        if behaviour.isdigit():
            self.send_error(int(behaviour))
        elif behaviour == "cut":
            # Announce the full length, then hang up halfway through.
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD[: len(PAYLOAD) // 2])
            self.wfile.flush()
            self.close_connection = True
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)


def _reset():
    SCRIPT.clear()
    HITS.clear()


def _run_case(server_url, script, minutes=1, **kwargs):
    """Run download() over `minutes` slots with a per-file behaviour script."""
    _reset()
    start = "2025-11-25T10:00:00"
    end = "2025-11-25T10:%02d:00" % (minutes - 1)
    for i in range(minutes):
        # GDELT names files YYYYMMDDHHMMSS, so the minute offset lands in MM.
        SCRIPT["2025112510%02d00.webngrams.json.gz" % i] = list(script)

    with tempfile.TemporaryDirectory() as d:
        stats = dl.download(
            start, end, outdir=d, decompress=False, show_progress=False, **kwargs
        )
        files = sorted(f for f in os.listdir(d) if f.endswith(".gz"))
        leftovers = [f for f in os.listdir(d) if f.endswith(".part")]
        sizes = [os.path.getsize(os.path.join(d, f)) for f in files]
    return stats, files, sizes, leftovers


def main():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    dl.GDELT_BASE_URL = "http://127.0.0.1:%d/gdeltv3/webngrams" % server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = dl.GDELT_BASE_URL

    try:
        # 1. happy path, several minutes fetched concurrently
        stats, files, sizes, leftovers = _run_case(url, ["ok"], minutes=6, workers=4)
        assert stats.requested_minutes == 6, stats
        assert stats.downloaded_gz == 6, stats
        assert stats.missing == 0 and stats.failed == 0, stats
        assert len(files) == 6, files
        assert all(s == len(PAYLOAD) for s in sizes), sizes
        assert not leftovers, leftovers
        assert all(v == 1 for v in HITS.values()), HITS  # exactly once each

        # 2. a 404 is a normal absent minute and must not be retried
        stats, files, _s, leftovers = _run_case(url, ["404"], retries=3)
        assert stats.missing == 1 and stats.failed == 0, stats
        assert stats.downloaded_gz == 0, stats
        assert files == [], files
        assert not leftovers, leftovers
        assert list(HITS.values()) == [1], HITS  # one attempt, no retry

        # 3. a transient 500 is retried and then succeeds
        stats, files, sizes, leftovers = _run_case(url, ["500", "500", "ok"], retries=3)
        assert stats.downloaded_gz == 1 and stats.failed == 0, stats
        assert sizes == [len(PAYLOAD)], sizes
        assert list(HITS.values()) == [3], HITS

        # 4. a persistent 500 is reported as failed, not silently dropped
        stats, files, _s, leftovers = _run_case(url, ["500"], retries=2)
        assert stats.failed == 1 and stats.missing == 0, stats
        assert files == [], files
        assert not leftovers, leftovers
        assert list(HITS.values()) == [3], HITS  # 1 initial + 2 retries

        # 5. a 403 is not retryable either, but 429 ("slow down") is
        stats, _f, _s, _l = _run_case(url, ["403"], retries=2)
        assert stats.missing == 1 and stats.failed == 0, stats
        assert list(HITS.values()) == [1], HITS

        stats, _f, sizes, _l = _run_case(url, ["429", "ok"], retries=2)
        assert stats.downloaded_gz == 1 and stats.failed == 0, stats
        assert list(HITS.values()) == [2], HITS

        # 6. a truncated response must never land as a complete .gz
        stats, files, _s, leftovers = _run_case(url, ["cut"], retries=1)
        assert stats.downloaded_gz == 0, stats
        assert stats.failed == 1, stats
        assert files == [], files
        assert not leftovers, leftovers

        # 7. a truncated first attempt followed by a good one yields a whole file
        stats, files, sizes, leftovers = _run_case(url, ["cut", "ok"], retries=2)
        assert stats.downloaded_gz == 1, stats
        assert sizes == [len(PAYLOAD)], sizes

        # 8. an existing file is not refetched unless overwrite=True
        _reset()
        SCRIPT["20251125100000.webngrams.json.gz"] = ["ok"]
        with tempfile.TemporaryDirectory() as d:
            args = dict(outdir=d, decompress=False, show_progress=False)
            dl.download("2025-11-25T10:00:00", "2025-11-25T10:00:00", **args)
            assert HITS["20251125100000.webngrams.json.gz"] == 1
            dl.download("2025-11-25T10:00:00", "2025-11-25T10:00:00", **args)
            assert HITS["20251125100000.webngrams.json.gz"] == 1, HITS
            dl.download(
                "2025-11-25T10:00:00", "2025-11-25T10:00:00", overwrite=True, **args
            )
            assert HITS["20251125100000.webngrams.json.gz"] == 2, HITS

        print("OK: download retries, 404 handling, atomic writes and concurrency")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
