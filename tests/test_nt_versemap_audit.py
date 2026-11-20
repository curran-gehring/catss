"""The verse aligner that proposes NT Latin/Greek units and audits the curated map."""
import math

from catss import nt_versemap_audit as au
from catss import vulgate_nt as vn


def test_fold_greek_strips_accents_case_and_final_sigma():
    assert au.fold_greek("Λόγος") == "λογοσ"
    assert au.fold_greek("ἀρχή") == "αρχη"


def test_fold_latin_stems_and_normalizes_orthography():
    assert au.fold_latin("Judæorum") == "iudae"
    assert au.fold_latin("vivus") == "uiuus"[:5]


def _toy():
    # Latin word i translates Greek word i; verses are bags of those words.
    lat = [["a", "b"], ["c"], ["d", "e"], ["f", "g"]]
    grk = [["A", "B"], ["C"], ["D", "E"], ["F", "G"]]
    return lat, grk


def test_ibm1_learns_the_obvious_translation():
    lat = [["a", "b"], ["a", "c"], ["b", "c"]]
    grk = [["A", "B"], ["A", "C"], ["B", "C"]]
    model = au.Ibm1.train(lat, grk, iterations=8)
    assert model.prob("a", "A") > 0.5
    assert model.prob("a", "A") > model.prob("a", "B")


def _model():
    lat, grk = _toy()
    pairs_l = lat + [["x"], ["y", "z"]]
    pairs_g = grk + [["X"], ["Y", "Z"]]
    return au.Pair.train(pairs_l * 3, pairs_g * 3, iterations=8)


def test_identity_when_verses_line_up():
    lat, grk = _toy()
    units = au.propose(lat, grk, _model())
    assert units == [((0,), (0,)), ((1,), (1,)), ((2,), (2,)), ((3,), (3,))]


def test_latin_verse_split_in_two_becomes_a_two_to_one_unit():
    lat = [["a", "b"], ["c", "d"], ["e"], ["f", "g"]]   # Greek verse 1 = "C D E"
    grk = [["A", "B"], ["C", "D", "E"], ["F", "G"]]
    units = au.propose(lat, grk, _model())
    assert units == [((0,), (0,)), ((1, 2), (1,)), ((3,), (2,))]


def test_latin_only_verse_is_one_to_zero():
    lat = [["a", "b"], ["x"], ["c"]]
    grk = [["A", "B"], ["C"]]
    units = au.propose(lat, grk, _model())
    assert units == [((0,), (0,)), ((1,), ()), ((2,), (1,))]


def test_disagreements_compare_each_latin_verses_greek_set():
    latin = [(1, 1), (1, 2), (1, 3)]
    greek = [(1, 1), (1, 2), (1, 3)]
    curated = vn.resolve_units(latin, greek, rows=[])
    proposed = [((0,), (0,)), ((1, 2), (1, 2))]
    got = au.disagreements(curated, proposed, latin, greek)
    assert got == [((1, 2), [(1, 2)], [(1, 2), (1, 3)]),
                   ((1, 3), [(1, 3)], [(1, 2), (1, 3)])]


def test_unit_score_prefers_true_translation_over_neighbour():
    m = _model()
    assert m.score(["a", "b"], ["A", "B"]) > m.score(["a", "b"], ["C"])
    assert math.isfinite(m.score(["a"], []))
