"""Unit tests for the pure-logic parts of align_vulgate (the eflomal run
itself only happens on the mac-mini). Importing the module must NOT require
eflomal — the import is deferred inside _run_eflomal."""
from catss import align_vulgate as av


def test_parse_links():
    assert av._parse_links("0-0 2-3 4-5\n") == [(0, 0), (2, 3), (4, 5)]
    assert av._parse_links("\n") == []


def test_split_hebrew_splits_morpheme_slashes():
    # CATSS joins prefixes with '/'; each becomes its own token.
    assert av._split_hebrew("W/H/ARC") == ["W", "H", "ARC"]
    assert av._split_hebrew("  BR   ") == ["BR"]
    assert av._split_hebrew("") == []


def test_gdfa_intersection_and_grow():
    # fwd and rev agree on (0,0); fwd has extra (1,2), rev has extra (1,1).
    fwd = [(0, 0), (1, 2)]
    rev = [(0, 0), (1, 1)]
    align = av._gdfa(fwd, rev, n_src=2, n_trg=3)
    # the agreed link is the intersection
    assert align[(0, 0)] == "intersection"
    # union points adjacent to the intersection get grown in
    assert (1, 1) in align and (1, 2) in align
    assert all(align[p] == "grown" for p in [(1, 1), (1, 2)])


def test_gdfa_final_and_adds_unaligned_union_point():
    # A union point with BOTH endpoints otherwise unaligned, not diag-adjacent
    # to the intersection, is added by the final-and pass.
    fwd = [(0, 0), (2, 2)]
    rev = [(0, 0)]
    align = av._gdfa(fwd, rev, n_src=3, n_trg=3)
    assert align[(0, 0)] == "intersection"
    assert align.get((2, 2)) == "grown"  # final-and: 2 and 2 both free


def test_gdfa_empty():
    assert av._gdfa([], [], 2, 2) == {}
