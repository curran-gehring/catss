"""Unit test for lemmatize_vulgate's pure logic. The spaCy/LatinCy run happens
only on the mac-mini; importing the module must NOT require spaCy (the import
is deferred inside lemmatize())."""
import types

from catss import lemmatize_vulgate as lv


def _tok(pos, morph):
    return types.SimpleNamespace(pos_=pos, morph=morph)


def _idtok(idx, text=""):
    return types.SimpleNamespace(idx=idx, text=text)


def test_word_token_heads_enclitic_absorbed_into_head_word():
    # "Dixitque Deus" -> Dixit@0 que@5 Deus@9; "que" belongs to word 0, so it is
    # NOT picked as the head of word 1.
    words = ["Dixitque", "Deus"]
    toks = [_idtok(0, "Dixit"), _idtok(5, "que"), _idtok(9, "Deus")]
    heads = lv._word_token_heads(words, toks)
    assert [h.text for h in heads] == ["Dixit", "Deus"]


def test_word_token_heads_missing_token_does_not_shift_later_words():
    # words at spans [0,3) [4,7) [8,11); no token lands in the middle word.
    words = ["foo", "bar", "baz"]
    toks = [_idtok(0, "foo"), _idtok(8, "baz")]
    heads = lv._word_token_heads(words, toks)
    assert heads[0].text == "foo"
    assert heads[1] is None            # only the missed word is None
    assert heads[2].text == "baz"      # the next word still maps correctly


def test_word_token_heads_one_to_one():
    words = ["In", "principio"]
    toks = [_idtok(0, "In"), _idtok(3, "principio")]
    assert [h.text for h in lv._word_token_heads(words, toks)] == \
        ["In", "principio"]


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
