"""Self-check for the Boolean query matcher in filtermerge.

Terms must match as whole words. The old substring matcher made a query for
`butti` (the politician Alessio Butti) hit `debutti`, `buttiamo`, `farabutti`
and surnames like `Gabutti` / `Buttigieg`, which is ~30% junk on a real corpus.

Run: python tests/test_query_match.py   (no framework needed)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from gdeltnews.filtermerge import build_query_expr, text_matches_query


def _m(query, text):
    expr, phrases = build_query_expr(query)
    return text_matches_query(text, expr, phrases)


def main():
    # --- whole-word terms, no substring bleed ---
    assert _m("butti", "Il sottosegretario Butti ha detto")
    assert _m("butti", "BUTTI, Alessio")                      # case-insensitive
    assert _m("butti", "parla Butti.")                        # punctuation is a boundary
    for junk in ("i debutti della stagione", "buttiamo via tutto", "che farabutti",
                 "Marco Gabutti", "Pete Buttigieg", "Libutti"):
        assert not _m("butti", junk), junk

    # --- phrases: boundaries on both ends, inner space kept ---
    assert _m('"alessio butti"', "parla Alessio Butti oggi")
    assert not _m('"alessio butti"', "Alessio Buttiglione")
    assert not _m('"alessio butti"', "Alessio  Butti")         # collapsed upstream by _clean_text

    # --- non-word edges keep working (no boundary asserted on that side).
    # Only quoted terms can carry punctuation; boolean.py rejects it unquoted.
    assert _m('"c++"', "scritto in c++ e rust")
    assert _m('".net"', "il framework .net")
    assert _m('"e-commerce"', "un e-commerce nuovo")

    # --- accented / unicode word chars count as word chars ---
    assert not _m("citta", "cittadino")
    assert _m("città", "la città di Roma")
    assert not _m("meloni", "Melonita")

    # --- boolean structure still evaluated correctly ---
    q = ('"alessio butti" OR (butti AND (sottosegretario OR senatore OR "palazzo chigi" '
         'OR politica OR meloni))')
    assert _m(q, "Alessio Butti al lavoro")                    # left branch
    assert _m(q, "Butti e la politica italiana")               # right branch
    assert not _m(q, "I debutti della politica con Meloni")    # substring-only: now rejected
    assert not _m(q, "Butti senza contesto rilevante")         # butti alone is not enough
    assert not _m(q, "la politica di Meloni in senato")        # no butti at all

    assert _m("meloni AND NOT salvini", "solo Meloni")
    assert not _m("meloni AND NOT salvini", "Meloni e Salvini")
    assert _m("((elezioni OR voto) AND regionali) OR (fico aNd nOt veneto)", "voto regionali")

    # --- terms boolean.py would eat as TRUE/FALSE literals stay real searches ---
    for word in ("true", "false", "none"):
        assert _m(word, "the %s story" % word), word
        assert not _m(word, "una notizia qualsiasi"), word
    assert _m("false AND meloni", "false claim by Meloni")
    assert not _m("false AND meloni", "Meloni parla")          # was: always False
    assert not _m("true", "una notizia qualsiasi")             # was: matched everything
    assert _m("0 OR meloni", "Meloni al governo")
    assert _m('"true story" AND none', "a true story, none the less")

    # --- reserved-token shielding must not corrupt real phrase placeholders ---
    q2 = '"palazzo chigi" AND ("innovazione tecnologica" OR none)'
    assert _m(q2, "a palazzo chigi si parla di innovazione tecnologica")
    assert not _m(q2, "innovazione tecnologica al ministero")

    # --- unquoted punctuation is rejected loudly, quoted works ---
    for bad in ("centro-destra", "d'italia", "butti meloni", "(butti AND meloni", "butti OR"):
        try:
            build_query_expr(bad)
        except ValueError as exc:
            assert "double-quoted" in str(exc), exc
        else:
            raise AssertionError("expected ValueError for %r" % bad)

    # --- empty query matches everything ---
    assert _m(None, "qualsiasi cosa") and _m("   ", "qualsiasi cosa")

    print("test_query_match: OK")


if __name__ == "__main__":
    main()
