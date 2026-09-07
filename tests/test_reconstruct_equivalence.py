"""Self-check that the optimized reconstruct_sentence is output-identical.

`reconstruct_sentence` was sped up by indexing candidate overlaps instead of
trying every overlap length against every fragment. The speedup is only worth
anything if it changes nothing: this test keeps a verbatim copy of the original
quadratic implementation as `_reference` and fuzzes both with the same inputs,
asserting byte-identical output.

Rules the fast path must preserve:
  - the fragment with the largest overlap wins;
  - ties go to the lowest index;
  - within one fragment, an append beats a prepend of equal length;
  - fragments that never overlap are dropped (unless keep_unmerged=True).

Run: python tests/test_reconstruct_equivalence.py   (no framework needed)
"""

import os
import random
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from gdeltnews.wordmatch import reconstruct_sentence


def _reference(
    fragments: List[str], positions: Optional[List[int]] = None
) -> str:
    """Verbatim copy of the pre-optimization implementation (v1.0.22)."""
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]

    words_list = [frag.split() for frag in fragments]
    n = len(words_list)

    if positions is not None and len(positions) != n:
        positions = None

    used = {0}
    result_words = words_list[0][:]

    if positions is not None:
        min_pos = max_pos = positions[0]

    while len(used) < n:
        best_fragment = -1
        best_overlap = 0
        best_is_prefix = False

        result_len = len(result_words)

        for idx, words in enumerate(words_list):
            if idx in used:
                continue

            max_k = min(result_len, len(words))
            if max_k == 0:
                continue

            can_append = True
            can_prepend = True
            if positions is not None:
                p = positions[idx]
                can_append = p >= max_pos
                can_prepend = p <= min_pos
                if not can_append and not can_prepend:
                    continue

            if max_k <= best_overlap:
                continue

            if can_append:
                for k in range(max_k, best_overlap, -1):
                    if result_words[-k:] == words[:k]:
                        best_fragment = idx
                        best_overlap = k
                        best_is_prefix = False
                        break

            if can_prepend and max_k > best_overlap:
                for k in range(max_k, best_overlap, -1):
                    if result_words[:k] == words[-k:]:
                        best_fragment = idx
                        best_overlap = k
                        best_is_prefix = True
                        break

        if best_fragment == -1:
            break

        fragment_words = words_list[best_fragment]

        if best_is_prefix:
            if best_overlap > 0:
                result_words = fragment_words[:-best_overlap] + result_words
            else:
                result_words = fragment_words + result_words
        else:
            if best_overlap > 0:
                result_words.extend(fragment_words[best_overlap:])
            else:
                result_words.extend(fragment_words)

        used.add(best_fragment)

        if positions is not None:
            p = positions[best_fragment]
            min_pos = min(min_pos, p)
            max_pos = max(max_pos, p)

    return " ".join(result_words)


def _fuzz(trials=1500, seed=20260907):
    """Random fragment sets, including the degenerate shapes that break ties.

    Small vocabularies are the interesting case: they manufacture accidental
    overlaps, so the tie-breaking rules actually get exercised.
    """
    rng = random.Random(seed)
    checked = 0
    for _ in range(trials):
        vocab_size = rng.choice([2, 4, 20, 200])
        vocab = ["w%d" % i for i in range(vocab_size)]
        n = rng.randint(2, 70)
        max_len = rng.randint(1, 12)

        article = [rng.choice(vocab) for _ in range(n + max_len)]
        fragments = [
            " ".join(article[i:i + rng.randint(1, max_len)]) for i in range(n)
        ]
        # Empty fragments are reachable: an entry with blank pre/ngram/post.
        if rng.random() < 0.2:
            fragments[rng.randrange(n)] = ""
        if rng.random() < 0.5:
            rng.shuffle(fragments)

        positions = sorted(rng.randint(0, 300) for _ in range(n))
        for pos in (positions, None, list(reversed(positions))):
            want = _reference(fragments, pos)
            got = reconstruct_sentence(fragments, pos)
            assert got == want, (
                "mismatch\n  fragments=%r\n  positions=%r\n  ref =%r\n  got =%r"
                % (fragments, pos, want, got)
            )
            checked += 1
    return checked


def _edge_cases():
    cases = [
        ([], None),
        (["solo"], None),
        (["", ""], [0, 1]),
        (["a b c", "a b c"], [0, 0]),
        (["a b c", "b c d"], [0, 1]),
        # no overlap at all: everything after the first fragment is dropped
        (["a b", "x y", "p q"], [0, 1, 2]),
        # length mismatch between fragments and positions -> positions ignored
        (["a b", "b c"], [0]),
        # prepend path: the earlier fragment arrives second
        (["c d e", "a b c d"], [5, 1]),
    ]
    for fragments, pos in cases:
        want = _reference(fragments, pos)
        got = reconstruct_sentence(fragments, pos)
        assert got == want, (fragments, pos, want, got)
    return len(cases)


def _keep_unmerged():
    """The opt-in flag must only ever add the leftovers, never reorder."""
    fragments = ["a b c", "b c d", "x y z"]
    positions = [0, 1, 99]

    default = reconstruct_sentence(fragments, positions)
    assert default == "a b c d", default

    kept = reconstruct_sentence(fragments, positions, keep_unmerged=True)
    assert kept == "a b c d x y z", kept

    # Nothing left over -> the flag is a no-op.
    assert reconstruct_sentence(["a b", "b c"], [0, 1], keep_unmerged=True) == (
        reconstruct_sentence(["a b", "b c"], [0, 1])
    )


def main():
    n_edge = _edge_cases()
    _keep_unmerged()
    n_fuzz = _fuzz()
    print(
        "OK: optimized reconstruct_sentence matches the reference "
        "on %d edge cases and %d fuzz comparisons" % (n_edge, n_fuzz)
    )


if __name__ == "__main__":
    main()
