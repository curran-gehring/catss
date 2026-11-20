"""gloss_vulgate headword reconstruction for the verb shapes the NT exposed."""
from catss import gloss_vulgate as gv


def _heads(stem1, codes, perfect=None):
    return [c for c, _ in gv._candidates(stem1, "V", codes, perfect)]


def test_impersonal_verbs_reconstruct_their_third_person_headword():
    assert "oportet" in _heads("oport", "V      2 1 IMPERS       ")
    assert "decet" in _heads("dec", "V      2 1 IMPERS       ")
    assert "accidit" in _heads("accid", "V      3 1 IMPERS       ")


def test_defective_perfect_headword_is_a_fallback_never_primary():
    cands = gv._candidates("coepi", "V", "V      3 1 X            ", "coep")
    assert ("coepi", False) in cands
    assert cands[0] == ("coepio", True)


def test_regular_verbs_are_unchanged():
    assert gv._candidates("hab", "V", "V      2 1 X            ", "habu") == [("habeo", True)]
    assert gv._candidates("abs", "V", "V      5 1 X            ") == [("absum", True)]


def test_impersonal_keeps_the_regular_headword_as_fallback():
    # LatinCy cites some impersonals in the 1st person (aduesperasco).
    assert gv._candidates("advesperasc", "V", "V      3 1 IMPERS       ") == [("advesperascit", True), ("advesperasco", False)]


def test_perfect_fallback_only_for_the_defective_encoding():
    # relinquo's perfect stem must not make "reliqui" (the rest) read as "leave behind".
    assert [c for c, _ in gv._candidates("relinqu", "V", "V      3 1 X            ", "reliqu")] == ["relinquo"]
