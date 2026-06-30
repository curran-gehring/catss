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
