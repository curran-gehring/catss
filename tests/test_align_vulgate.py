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


def test_gdf_intersection_and_grow():
    # fwd and rev agree on (0,0); fwd has extra (1,2), rev has extra (1,1).
    fwd = [(0, 0), (1, 2)]
    rev = [(0, 0), (1, 1)]
    align = av._gdf(fwd, rev, n_src=2, n_trg=3)
    # the agreed link is the intersection
    assert align[(0, 0)] == "intersection"
    # union points adjacent to the intersection get grown in
    assert (1, 1) in align and (1, 2) in align
    assert all(align[p] == "grown" for p in [(1, 1), (1, 2)])


def test_gdf_final_adds_union_point_with_one_free_endpoint():
    # (2,0): trg 0 is already aligned (to src 0) but src 2 is free, and it is
    # NOT adjacent to the intersection. The OR-final pass must still add it;
    # the stricter '-and' variant would wrongly drop it.
    fwd = [(0, 0), (2, 0)]
    rev = [(0, 0)]
    align = av._gdf(fwd, rev, n_src=3, n_trg=3)
    assert align[(0, 0)] == "intersection"
    assert align.get((2, 0)) == "grown"


def test_gdf_final_adds_fully_free_union_point():
    fwd = [(0, 0), (2, 2)]
    rev = [(0, 0)]
    align = av._gdf(fwd, rev, n_src=3, n_trg=3)
    assert align.get((2, 2)) == "grown"


def test_gdf_empty():
    assert av._gdf([], [], 2, 2) == {}
