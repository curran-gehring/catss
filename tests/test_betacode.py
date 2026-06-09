"""Known-answer tests for the BETA decoders, including regression cases
for the 2026-06 audit findings (mid-word sigma, marker leakage)."""
import pytest

from catss.betacode import greek_to_unicode, hebrew_to_unicode


# ---------------------------------------------------------------------------
# Greek — basics

GREEK_CASES = [
    ("E)GE/NETO",   "ἐγένετο"),
    ("KAI\\",       "καὶ"),
    ("TH=|",        "τῇ"),
    ("A)NH\\R",     "ἀνὴρ"),
    ("A)PO\\",      "ἀπὸ"),
    ("TOU=",        "τοῦ"),
    ("*)ANH\\R",    "Ἀνὴρ"),
    ("LO/GOS",      "λόγος"),
    ("*)IHSOU=S",   "Ἰησοῦς"),
    ("E)N",         "ἐν"),
    ("TO\\N",       "τὸν"),
    ("A)LL'",       "ἀλλʼ"),          # elision → U+02BC modifier apostrophe
    ("KATA\\",      "κατὰ"),
    ("QEO\\S",      "θεὸς"),          # final sigma after accented vowel
]


@pytest.mark.parametrize("beta,expected", GREEK_CASES)
def test_greek_basic(beta, expected):
    assert greek_to_unicode(beta) == expected


# Regression: σ before an ACCENTED vowel must stay medial. The old
# _fix_final_sigma class excluded tonos (U+03AC..) and polytonic (U+1F00+)
# blocks, finalizing 12,876 words (μέςῳ, χρυςίον, ...).
GREEK_MEDIAL_SIGMA = [
    ("ME/SW|",        "μέσῳ"),
    ("XRUSI/ON",      "χρυσίον"),
    ("PARADEI/SW|",   "παραδείσῳ"),
    ("BLASTHSA/TW",   "βλαστησάτω"),
    ("ZWSW=N",        "ζωσῶν"),
    ("MWUSH=S",       "μωυσῆς"),
]


@pytest.mark.parametrize("beta,expected", GREEK_MEDIAL_SIGMA)
def test_greek_medial_sigma_before_accented_vowel(beta, expected):
    assert greek_to_unicode(beta) == expected


def test_greek_final_sigma_still_applied_at_word_end_and_before_space():
    assert greek_to_unicode("LO/GOS KAI\\ LO/GOS") == "λόγος καὶ λόγος"


# Regression: '' is a CATSS ditto mark, not an elision — 5,450 minus rows
# decoded it as ʼʼ.
@pytest.mark.parametrize("beta", ["''", "--- ''", "--+ ''"])
def test_greek_ditto_and_dash_markers_strip_to_empty(beta):
    assert greek_to_unicode(beta) == ""


def test_greek_angle_ref_stripped():
    assert greek_to_unicode("KAI\\ <13.14>") == "καὶ"


# ---------------------------------------------------------------------------
# Hebrew — basics

HEBREW_CASES = [
    ("W/YHY",       "ויהי"),
    ("B/)RC",       "בארץ"),
    ("M/BYT LXM",   "מבית לחם"),
    ("H/$P+YM",     "השׁפטים"),
    ("YHWH",        "יהוה"),
    ("BN/YW",       "בניו"),
    # holem-waw: canonical order is waw U+05D5 then combining holem U+05B9
    ("$FLOWM",      "שָׁלוֹם"),
]


@pytest.mark.parametrize("beta,expected", HEBREW_CASES)
def test_hebrew_basic(beta, expected):
    assert hebrew_to_unicode(beta) == expected


# Regression: '--+' (LXX plus) is TWO dashes + '+'; the old -{3,} strip
# missed it and 13,693 rows decoded as maqaf-maqaf-tet ('־־ט').
@pytest.mark.parametrize("beta", ["--+", "--+ ''", "--", "---"])
def test_hebrew_dash_markers_strip_to_empty(beta):
    assert hebrew_to_unicode(beta) == ""


# Regression: the '.' inside <1.7>-style cross-refs injected a dagesh
# (U+05BC) into 214 rows.
def test_hebrew_angle_ref_does_not_inject_dagesh():
    assert hebrew_to_unicode("W/YHY <1.7>") == "ויהי"
    assert hebrew_to_unicode("--+ '' <28.5>") == ""
    assert hebrew_to_unicode("M/MN/Y <22.12> <sp>") == "ממני"


# Regression: lowercase annotation codes (.wy, .dr, q1a) and '.'-led note
# tokens decoded as dagesh/ayin/alef garbage; unclosed '<ju8.26' refs leaked.
def test_hebrew_note_codes_stripped():
    assert hebrew_to_unicode("W/DPQW/M .wy <sp>") == "ודפקום"
    assert hebrew_to_unicode(".m .wy .w <c13.8>") == ""
    assert hebrew_to_unicode("W/(TH .() <q1a>") == "ועתה"
    assert hebrew_to_unicode("W/(NQYM <ju8.26 ge41.42 c18.7") == "וענקים"
    assert hebrew_to_unicode("L/)WYL <6.12 16.27> .dr .w") == "לאויל"
    # text-critical brackets and unclosed braces are apparatus, not text
    assert hebrew_to_unicode("NKWXH 3 [..]K*X* 9") == "נכוחה"
    assert hebrew_to_unicode("W/PSL {...L)") == "ופסל"
    assert hebrew_to_unicode("W/)L 3 [..] 4") == "ואל"


def test_greek_note_codes_stripped():
    assert greek_to_unicode("KAI\\ .tr") == "καὶ"


def test_hebrew_maqaf_preserved():
    assert hebrew_to_unicode("(L-PNY") == "על־פני"


def test_hebrew_final_letters():
    assert hebrew_to_unicode("$LWM") == "שׁלום"      # mem sofit
    assert hebrew_to_unicode("B/N")  == "בן"          # nun sofit
