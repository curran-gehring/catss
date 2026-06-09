"""End-to-end build tests over a synthetic raw/ tree, plus the split guard.

Book stems must exist in catss.books for the loader to pick the files up,
so fixtures borrow real stems (Genesis, Ezra/2Esdras, Esther, Psalms2).
"""
import sqlite3
import textwrap

import pytest

from catss import build_db, split as splitmod
from catss.books import by_osis


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _mlxx_line(surface, parse, lemma):
    return f"{surface:<25}{parse:<10}{lemma}"


@pytest.fixture()
def raw(tmp_path):
    root = tmp_path / "raw"
    _write(root / "parallel" / "01.Genesis.par", """\
        Gen 1:1
        B/R)$YT\tE)N A)RXH=|
        --+ ''\tKAI\\ E)GE/NETO
        W/YHY\t---
        """)
    # 2Esdras morph: ch 1 = Ezra, ch 11 = Neh 1
    (root / "lxxmorph").mkdir(parents=True, exist_ok=True)
    (root / "lxxmorph" / "19.2Esdras.mlxx").write_text(
        "2Esdr 1:1\n"
        + _mlxx_line("KAI\\", "C", "KAI/") + "\n\n"
        + "2Esdr 11:1\n"
        + _mlxx_line("LO/GOI", "N2  NPM", "LO/GOS") + "\n",
        encoding="utf-8")
    # Esther morph with subverses that merge into (1, 1)
    (root / "lxxmorph" / "20.Esther.mlxx").write_text(
        "Esth 1:1a\n"
        + _mlxx_line("E)N", "P", "E)N") + "\n\n"
        + "Esth 1:1b\n"
        + _mlxx_line("ME/SW|", "N2  DSN", "ME/SOS") + "\n",
        encoding="utf-8")
    # Psalms2 morph containing Ps 151 → remapped to the Ps151 book
    (root / "lxxmorph" / "29.Psalms2.mlxx").write_text(
        "Ps 151:1\n"
        + _mlxx_line("MIKRO\\S", "A1  NSM", "MIKRO/S") + "\n",
        encoding="utf-8")
    return root


@pytest.fixture()
def built(raw, tmp_path):
    db = tmp_path / "test.db"
    stats = build_db.build(raw, db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    yield conn, stats
    conn.close()


def test_plus_and_minus_rows_store_null_not_garbage(built):
    conn, _ = built
    plus = conn.execute(
        "SELECT mt_unicode, lxx_unicode FROM alignments WHERE is_lxx_plus=1").fetchone()
    assert plus["mt_unicode"] is None          # was '־־ט'
    assert plus["lxx_unicode"] == "καὶ ἐγένετο"
    minus = conn.execute(
        "SELECT lxx_unicode FROM alignments WHERE is_lxx_minus=1").fetchone()
    assert minus["lxx_unicode"] is None


def test_2esdras_chapter_11_lands_in_nehemiah(built):
    conn, _ = built
    neh = by_osis("Neh").canon_id
    ezra = by_osis("Ezra").canon_id
    rows = conn.execute(
        "SELECT v.book_id, v.chapter, m.surface_unicode FROM lxx_morph m "
        "JOIN verses v ON m.verse_id=v.id ORDER BY v.book_id").fetchall()
    by_book = {r["book_id"]: (r["chapter"], r["surface_unicode"]) for r in rows}
    assert by_book[ezra] == (1, "καὶ")
    assert by_book[neh] == (1, "λόγοι")        # 2Esd 11 → Neh 1
    assert conn.execute(
        "SELECT COUNT(*) FROM verses WHERE book_id=? AND chapter>10",
        (ezra,)).fetchone()[0] == 0            # no phantom Ezra chapters


def test_ps151_morph_remapped_to_own_book(built):
    conn, _ = built
    ps151 = by_osis("Ps151").canon_id
    row = conn.execute(
        "SELECT v.chapter, m.surface_unicode FROM lxx_morph m "
        "JOIN verses v ON m.verse_id=v.id WHERE v.book_id=?", (ps151,)).fetchone()
    assert (row["chapter"], row["surface_unicode"]) == (1, "μικρὸς")


def test_esther_subverses_merge_with_continued_positions(built):
    conn, _ = built
    esth = by_osis("Esth").canon_id
    rows = conn.execute(
        "SELECT m.position, m.surface_unicode FROM lxx_morph m "
        "JOIN verses v ON m.verse_id=v.id "
        "WHERE v.book_id=? AND v.chapter=1 AND v.verse=1 ORDER BY m.position",
        (esth,)).fetchall()
    assert [(r["position"], r["surface_unicode"]) for r in rows] == [
        (1, "ἐν"), (2, "μέσῳ")]                # μέσῳ: medial sigma regression


def test_morph_word_count_is_exact(built):
    conn, stats = built
    assert stats["morph_words"] == conn.execute(
        "SELECT COUNT(*) FROM lxx_morph").fetchone()[0] == 5
    # "missing:" entries are expected (fixture only ships a few books);
    # anything else is a real parse/insert failure.
    real_errors = [e for e in stats["errors"] if not e.startswith("missing:")]
    assert real_errors == []


def test_split_refuses_full_build(built, raw, tmp_path):
    full_db = tmp_path / "test.db"
    with pytest.raises(ValueError, match="FULL build"):
        splitmod.split(full_db, tmp_path / "b.sqlite", tmp_path / "m.sqlite")


def test_split_slim_build(raw, tmp_path):
    slim_db = tmp_path / "slim.db"
    build_db.build(raw, slim_db, slim=True)
    stats = splitmod.split(slim_db, tmp_path / "b.sqlite", tmp_path / "m.sqlite")
    assert stats["base"]["rows"]["alignments"] == 3
    assert stats["base"]["rows"]["lxx_morph"] is None
    assert stats["morph"]["rows"]["lxx_morph"] == 5
    assert stats["morph"]["rows"]["alignments"] is None
    assert stats["base"]["integrity"] == stats["morph"]["integrity"] == "ok"
