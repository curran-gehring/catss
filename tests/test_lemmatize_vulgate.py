"""Unit test for lemmatize_vulgate's pure logic. The spaCy/LatinCy run happens
only on the mac-mini; importing the module must NOT require spaCy (the import
is deferred inside lemmatize())."""
import types

from catss import lemmatize_vulgate as lv


def _tok(pos, morph):
    return types.SimpleNamespace(pos_=pos, morph=morph)


def test_morph_string_packs_pos_and_features():
    assert lv._morph_string(_tok("VERB", "Mood=Ind|Tense=Pres")) == \
        "VERB|Mood=Ind|Tense=Pres"


def test_morph_string_pos_only_when_no_features():
    assert lv._morph_string(_tok("NOUN", "")) == "NOUN"


def test_morph_string_none_when_empty():
    assert lv._morph_string(_tok("", "")) is None


def test_norm_latin_folds_v_u_j_i_and_lowercases():
    assert lv._norm_latin("Vade") == "uade"
    assert lv._norm_latin("ejus") == "eius"
    assert lv._norm_latin("Judicavit") == "iudicauit"
    assert lv._norm_latin("terram") == "terram"  # no v/j: lowercase only


def test_lemma_override_keys_are_already_folded():
    # Keys are matched against _norm_latin(surface); a key containing a raw
    # v/j or uppercase could never match and would be dead code.
    for key in lv._LEMMA_OVERRIDES:
        assert key == lv._norm_latin(key), f"override key not folded: {key}"


def test_lemma_override_targets_are_folded_headwords():
    # Targets are stored as lemmas, so they must also be in folded orthography.
    for target in lv._LEMMA_OVERRIDES.values():
        assert target == lv._norm_latin(target), f"override target raw v/j: {target}"
