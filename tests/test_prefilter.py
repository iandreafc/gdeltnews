"""Self-check for the byte-level pre-filter in load_and_filter_data.

The loader skips json.loads for lines that can't pass the language/URL
filters, using raw-byte substring checks. Those checks must be *necessary*
conditions: they may let extra lines through (re-checked after parsing) but
must never drop a line the real filter would keep. This test compares the
fast loader against a naive parse-everything reference on tricky inputs.

Run: python tests/test_prefilter.py   (no framework needed)
"""

import gzip
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from gdeltnews.wordmatch import load_and_filter_data, _normalize_url_filters


def _naive(lines, language_filter, url_filter):
    """Reference: parse every line, then filter. Returns {url: n_kept}."""
    url_filters = _normalize_url_filters(url_filter)
    out = {}
    for line in lines:
        entry = json.loads(line)
        if language_filter is not None and entry.get("lang") != language_filter:
            continue
        url = entry.get("url", "")
        if not url:
            continue
        if url_filters is not None and not any(f in url for f in url_filters):
            continue
        out[url] = out.get(url, 0) + 1
    return out


def _rec(date, ngram, lang, url, pre="p", post="q"):
    return json.dumps({
        "date": date, "ngram": ngram, "lang": lang,
        "type": 1, "pos": 0, "pre": pre, "post": post, "url": url,
    })


LINES = [
    # kept: lang it + repubblica.it
    _rec("2025-11-25T10:00:00Z", "a", "it", "https://www.repubblica.it/x"),
    _rec("2025-11-25T10:00:00Z", "b", "it", "https://www.repubblica.it/x"),
    # dropped: wrong lang
    _rec("2025-11-25T10:00:00Z", "c", "en", "https://www.repubblica.it/y"),
    # dropped: wrong url
    _rec("2025-11-25T10:00:00Z", "d", "it", "https://www.other.com/z"),
    # kept: corriere.it
    _rec("2025-11-25T10:00:00Z", "e", "it", "https://www.corriere.it/w"),
    # tricky: english line whose TEXT contains the word "it" (so the raw bytes
    # contain 'it', but not the JSON token '"it"'); must still be dropped.
    _rec("2025-11-25T10:00:00Z", "grab it now", "en",
         "https://www.repubblica.it/q", pre="take it", post="it is here"),
    # tricky: lang 'it' but url quotes-adjacent oddities; must be kept
    _rec("2025-11-25T10:00:00Z", "f", "it", "https://repubblica.it/a?b=it"),
    # empty url -> dropped
    _rec("2025-11-25T10:00:00Z", "g", "it", ""),
]


def _run_case(lines, language_filter, url_filter):
    with tempfile.TemporaryDirectory() as d:
        for name, opener in (("t.json", open), ("t.json.gz", gzip.open)):
            path = os.path.join(d, name)
            with opener(path, "wt", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            articles, order = load_and_filter_data(
                path, language_filter=language_filter, url_filter=url_filter
            )
            got = {u: len(v) for u, v in articles.items()}
            want = _naive(lines, language_filter, url_filter)
            assert got == want, f"{name}: got {got} want {want}"
            # url_order must list kept URLs in first-seen order, no dups
            assert order == list(dict.fromkeys(order))
            assert set(order) == set(want)


def main():
    cases = [
        ("it", ["repubblica.it", "corriere.it"]),
        ("it", None),
        (None, ["repubblica.it"]),
        (None, None),
        ("en", ["repubblica.it"]),
    ]
    for lang, urls in cases:
        _run_case(LINES, lang, urls)
    print("OK: prefilter matches naive full-parse on all cases")


if __name__ == "__main__":
    main()
