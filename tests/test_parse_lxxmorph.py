"""Parser tests for .mlxx files. Fixtures replicate the fixed-width layout:
surface cols 0-24, parse code cols 25-34, lemma cols 35+."""
import pathlib

import pytest

from catss import parse_lxxmorph


def _line(surface: str, parse: str, lemma: str) -> str:
    return f"{surface:<25}{parse:<10}{lemma}"


def _parse(tmp_path: pathlib.Path, lines: list[str]):
    p = tmp_path / "fixture.mlxx"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list(parse_lxxmorph.parse_file(p))


def test_basic_verse(tmp_path):
    verses = _parse(tmp_path, [
        "Gen 1:1",
        _line("E)N", "P", "E)N"),
        _line("A)RXH=|", "N1  DSF", "A)RXH/"),
        "",
        "Gen 1:2",
        _line("KAI\\", "C", "KAI/"),
    ])
    assert [(v.chapter, v.verse, len(v.words)) for v in verses] == [
        (1, 1, 2), (1, 2, 1)]
    w = verses[0].words[1]
    assert (w.surface_beta, w.parse_code, w.lemma_beta) == (
        "A)RXH=|", "N1  DSF", "A)RXH/")
    assert [w.position for w in verses[0].words] == [1, 2]


# Regression: the old header regex `[1-4]?\s*[A-Za-z]+` rejected these,
# silently dropping ~91k words (all of Samuel-Kings, EpJer, Susanna, Bel,
# and the Esther additions).
@pytest.mark.parametrize("header,expect_ch,expect_v", [
    ("1Sam/K 1:1", 1, 1),     # Reigns notation
    ("1/3Kgs 22:54", 22, 54), # 1 Kings = 3 Reigns
    ("EpJer 7", 1, 7),        # single-chapter book, no chapter prefix
    ("SusTh 12", 1, 12),
    ("Bel 2", 1, 2),
    ("Esth 1:1a", 1, 1),      # subverse letter accepted and discarded
])
def test_header_formats(tmp_path, header, expect_ch, expect_v):
    verses = _parse(tmp_path, [header, _line("KAI\\", "C", "KAI/")])
    assert len(verses) == 1
    assert (verses[0].chapter, verses[0].verse) == (expect_ch, expect_v)


def test_esther_subverses_parse_as_separate_blocks(tmp_path):
    # 1:1a and 1:1b both map to (1, 1) with the letter captured; build_db
    # merges them by continuing the position counter.
    verses = _parse(tmp_path, [
        "Esth 1:1a",
        _line("E)N", "P", "E)N"),
        "",
        "Esth 1:1b",
        _line("KAI\\", "C", "KAI/"),
        "",
        "Esth 1:2",
        _line("O(/TE", "C", "O(/TE"),
    ])
    assert [(v.chapter, v.verse, v.subverse) for v in verses] == [
        (1, 1, "a"), (1, 1, "b"), (1, 2, None)]


def test_preverb_appended_to_parse_code(tmp_path):
    verses = _parse(tmp_path, [
        "Num 32:30",
        _line("SUGKATAKLHRONOMHQH/SONTAI", "VC  APS2S", "KLHRONOME/W      SUN   KATA"),
    ])
    w = verses[0].words[0]
    assert w.surface_beta == "SUGKATAKLHRONOMHQH/SONTAI"
    assert w.lemma_beta == "KLHRONOME/W"
    assert w.parse_code == "VC  APS2S +SUN   KATA"


def test_verse_range_header_files_under_first_verse(tmp_path):
    # "TobS 9:3-4", "Dan 5:26-28" — real CCAT range refs
    verses = _parse(tmp_path, [
        "TobS 9:3-4",
        _line("KAI\\", "C", "KAI/"),
    ])
    assert (verses[0].chapter, verses[0].verse) == (9, 3)


def test_bare_header_starts_superscription_as_verse_0(tmp_path):
    # Odes/PsSol/EpJer/Lam/Bel/DanOG: a bare book token introduces a title
    # block belonging to the chapter the NEXT ref header opens.
    verses = _parse(tmp_path, [
        "Od",
        _line("W)|DH\\", "N1  NSF", "W)|DH/"),
        "",
        "Od 5:9",
        _line("KAI\\", "C", "KAI/"),
        "",
        "Od",
        _line("PROSEUXH\\", "N1  NSF", "PROSEUXH/"),
        "",
        "Od 6:3",
        _line("E)N", "P", "E)N"),
    ])
    refs = [(v.chapter, v.verse, v.words[0].surface_beta) for v in verses]
    assert refs == [
        (5, 0, "W)|DH\\"),      # title of ode 5 (which starts at verse 9)
        (5, 9, "KAI\\"),
        (6, 0, "PROSEUXH\\"),
        (6, 3, "E)N"),
    ]


def test_bare_token_not_matching_book_is_ignored_mid_file(tmp_path):
    # a stray single-token data line must NOT become a title header
    verses = _parse(tmp_path, [
        "Gen 1:1",
        _line("E)N", "P", "E)N"),
        "STRAYTOKEN",
        _line("KAI\\", "C", "KAI/"),
    ])
    assert len(verses) == 1
    assert [w.surface_beta for w in verses[0].words] == ["E)N", "KAI\\"]


def test_data_lines_never_match_header():
    # paranoia: a fixed-width data line must not look like a verse header
    assert parse_lxxmorph.VERSE_HEADER.match(
        _line("KAI\\", "C", "KAI/")) is None
