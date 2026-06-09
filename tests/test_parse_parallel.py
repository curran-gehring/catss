"""Parser tests for .par files, driven by inline fixtures shaped like the
real CCAT data (verified against raw/parallel/*.par)."""
import pathlib
import textwrap

import pytest

from catss import parse_parallel


def _parse(tmp_path: pathlib.Path, text: str):
    p = tmp_path / "fixture.par"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return list(parse_parallel.parse_file(p))


def test_basic_verse(tmp_path):
    verses = _parse(tmp_path, """\
        Gen 1:1
        B/R)$YT\tE)N A)RXH=|
        BR)\tE)POI/HSEN

        Gen 1:2
        W/H/)RC\tH( ^ DE\\ GH=
        """)
    assert [(v.book, v.chapter, v.verse) for v in verses] == [
        ("Gen", 1, 1), ("Gen", 1, 2)]
    assert verses[0].rows[0].mt_col_a == "B/R)$YT"
    assert verses[0].rows[0].lxx_raw == "E)N A)RXH=|"


def test_single_chapter_book_header(tmp_path):
    # Obadiah: "Obad 1" — no chapter prefix (regression: book was dropped)
    verses = _parse(tmp_path, """\
        Obad 1
        XZWN\tO(/RASIS
        """)
    assert (verses[0].chapter, verses[0].verse) == (1, 1)


@pytest.mark.parametrize("header", ["1Sam/K 1:1", "1/3Kgs 2:5", "Ps151 1"])
def test_reigns_and_ps151_headers(tmp_path, header):
    # Regression: letters-only book token dropped all of Samuel-Kings
    verses = _parse(tmp_path, f"{header}\nDBR\tLO/GOS\n")
    assert len(verses) == 1


def test_lxx_plus_row(tmp_path):
    verses = _parse(tmp_path, """\
        Gen 1:6
        --+ =;W/YHY <1.7>\tKAI\\ E)GE/NETO
        """)
    row = verses[0].rows[0]
    assert row.is_lxx_plus
    assert row.mt_col_b == ";W/YHY <1.7>"


def test_lxx_minus_row(tmp_path):
    verses = _parse(tmp_path, """\
        Gen 1:9
        W/YHY\t---
        KN\t--- ''
        """)
    assert all(r.is_lxx_minus for r in verses[0].rows)


def test_ketiv_qere_flags(tmp_path):
    verses = _parse(tmp_path, """\
        Ruth 3:4
        *HWC) **HYC)\tKAI\\
        **QERE\tKAI\\
        PLAIN\tKAI\\
        """)
    both, qere_only, plain = verses[0].rows
    assert both.is_ketiv and both.is_qere
    assert (not qere_only.is_ketiv) and qere_only.is_qere
    assert not plain.is_ketiv and not plain.is_qere


def test_ketiv_not_flagged_from_col_b(tmp_path):
    # Regression: '*' inside the col-b retroversion flagged 21 rows as ketiv
    verses = _parse(tmp_path, """\
        Gen 46:10
        W/YMW)L =:?W/YMW*)L\tKAI\\ IEMOUHL
        """)
    row = verses[0].rows[0]
    assert not row.is_ketiv
    assert row.mt_col_b == ":?W/YMW*)L"


def test_col_b_at_cell_start(tmp_path):
    # Regression: '=' at index 0 was never split → decoded as garbage col-a
    verses = _parse(tmp_path, """\
        Exod 27:12
        =;W/(MD/YHM <27.12> <sp>\tKAI\\ OI( STU=LOI
        """)
    row = verses[0].rows[0]
    assert row.mt_col_a == ""
    assert row.mt_col_b == ";W/(MD/YHM <27.12> <sp>"


def test_col_b_glued_to_annotation_marks(tmp_path):
    # '=' is not in the Hebrew BETA charset — the first '=' always starts
    # col-b, even glued to ditto marks ("''=W/YHYW") or '?' ("?=?MWLWT").
    verses = _parse(tmp_path, """\
        Deut 26:5
        --+ ''=W/YHYW\tKAI\\ E)GE/NONTO
        --+ ?=?MWLWT\tGENE/SEWS
        """)
    glued, question = verses[0].rows
    assert glued.mt_col_b == "W/YHYW"
    assert question.mt_col_b == "?MWLWT"
    assert glued.is_lxx_plus and question.is_lxx_plus


def test_repeated_verse_blocks_yield_separately(tmp_path):
    # CATSS separates sections within a verse by blank lines; build_db
    # continues row_order across the repeats.
    verses = _parse(tmp_path, """\
        Isa 1:1
        XZWN\tO(/RASIS

        Isa 1:1
        Y$(YHW\tHSAIOU
        """)
    assert [(v.chapter, v.verse) for v in verses] == [(1, 1), (1, 1)]
