"""build_vulgate_nt: the NT Latin pack's verse map, units and words, against a
tiny synthetic interlinear (never the real pack, which is ~165 MB)."""
import hashlib
import sqlite3

import pytest

from catss import build_vulgate_nt as b


def _vul(tmp_path):
    p = tmp_path / "vul.tsv"
    p.write_text("\n".join([
        "Joannes\tJo\t43\t1\t1\tIn principio erat Verbum,",
        "Joannes\tJo\t43\t1\t2\tHoc erat in principio.",
        "Joannes\tJo\t43\t1\t3\tOmnia per ipsum facta sunt.",
        "Joannis I\t1Jo\t69\t5\t7\tQuoniam tres sunt, qui testimonium dant in cælo.",
        "Joannis I\t1Jo\t69\t5\t8\tEt tres sunt in terra : spiritus, et aqua.",
    ]) + "\n", encoding="utf-8")
    return p


def _interlinear(tmp_path):
    p = tmp_path / "bible_interlinear.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE interlinear_words (id INTEGER PRIMARY KEY, book_id INTEGER, chapter INTEGER,"
              " verse INTEGER, word_position INTEGER, source TEXT, surface_text TEXT, lemma TEXT)")
    words = [
        (43, 1, 1, 1, "Ἐν", "ἐν"), (43, 1, 1, 2, "ἀρχῇ", "ἀρχή"), (43, 1, 1, 4, "λόγος", "λόγος"),
        (43, 1, 2, 1, "οὗτος", "οὗτος"), (43, 1, 2, 2, "ἦν", "εἰμί"),
        (62, 5, 7, 1, "ὅτι", "ὅτι"), (62, 5, 7, 2, "τρεῖς", "τρεῖς"),
        (62, 5, 8, 1, "τὸ", "ὁ"), (62, 5, 8, 2, "πνεῦμα", "πνεῦμα"),
    ]
    c.executemany("INSERT INTO interlinear_words (book_id, chapter, verse, word_position, source, surface_text, lemma)"
                  " VALUES (?,?,?,?, 'SBLGNT', ?, ?)", words)
    c.execute("INSERT INTO interlinear_words (book_id, chapter, verse, word_position, source, surface_text, lemma)"
              " VALUES (1, 1, 1, 1, 'WLC', 'x', 'x')")
    c.commit()
    c.close()
    return p


def _units(tmp_path, body="43\t1:3\t\t1:2\tnot in this Greek\n"):
    p = tmp_path / "nt_units.tsv"
    p.write_text("# book\tlatin\tgreek\thome\tnote\n" + body, encoding="utf-8")
    return p


def _spans(tmp_path, body="62\t5:7\t7\t8\tin caelo\n"):
    p = tmp_path / "nt_latin_only_words.tsv"
    p.write_text("# book\tref\tfrom\tto\texpect\n" + body, encoding="utf-8")
    return p


def _build(tmp_path, **kw):
    out = tmp_path / "vulgate_nt.sqlite"
    stats = b.build(_vul(tmp_path), _interlinear(tmp_path), kw.get("units") or _units(tmp_path),
                    kw.get("spans") or _spans(tmp_path), out)
    return out, stats


def test_verse_map_rows_follow_latin_order_with_status_and_home(tmp_path):
    out, stats = _build(tmp_path)
    c = sqlite3.connect(out)
    rows = c.execute("SELECT vul_book, vul_chapter, vul_verse, book_id, chapter, verse, status, text"
                     " FROM nt_verse_map ORDER BY id").fetchall()
    assert rows == [
        ("Jo", 1, 1, 43, 1, 1, "same", "In principio erat Verbum,"),
        ("Jo", 1, 2, 43, 1, 2, "same", "Hoc erat in principio."),
        ("Jo", 1, 3, 43, 1, 2, "latin_only", "Omnia per ipsum facta sunt."),
        ("1Jo", 5, 7, 62, 5, 7, "same", "Quoniam tres sunt, qui testimonium dant in cælo."),
        ("1Jo", 5, 8, 62, 5, 8, "same", "Et tres sunt in terra : spiritus, et aqua."),
    ]
    assert stats["status"] == {"same": 4, "latin_only": 1}


def test_units_list_their_greek_verses_and_latin_only_units_none(tmp_path):
    out, _ = _build(tmp_path)
    c = sqlite3.connect(out)
    got = c.execute("SELECT vm.vul_chapter, vm.vul_verse, g.chapter, g.verse FROM nt_verse_map vm"
                    " LEFT JOIN nt_unit_greek g ON g.unit_id = vm.unit_id ORDER BY vm.id").fetchall()
    assert got == [(1, 1, 1, 1), (1, 2, 1, 2), (1, 3, None, None), (5, 7, 5, 7), (5, 8, 5, 8)]


def test_words_are_tokenized_like_the_ot_pack_and_flag_latin_only(tmp_path):
    out, _ = _build(tmp_path)
    c = sqlite3.connect(out)
    words = c.execute("SELECT vm.vul_verse, w.position, w.surface, w.norm, w.latin_only FROM vulgate_words w"
                      " JOIN nt_verse_map vm ON vm.id = w.verse_map_id WHERE vm.vul_book='1Jo' AND vm.vul_verse=7"
                      " ORDER BY w.position").fetchall()
    assert [w[2] for w in words] == ["Quoniam", "tres", "sunt", "qui", "testimonium", "dant", "in", "caelo"]
    assert [w[4] for w in words] == [0, 0, 0, 0, 0, 0, 1, 1]
    assert c.execute("SELECT SUM(latin_only) FROM vulgate_words w JOIN nt_verse_map vm ON vm.id = w.verse_map_id"
                     " WHERE vm.status='latin_only'").fetchone()[0] == 5   # Omnia per ipsum facta sunt


def test_pack_info_pins_the_interlinear_it_was_built_against(tmp_path):
    out, _ = _build(tmp_path)
    il = tmp_path / "bible_interlinear.sqlite"
    info = dict(sqlite3.connect(out).execute("SELECT key, value FROM pack_info"))
    assert info["interlinear_sha256"] == hashlib.sha256(il.read_bytes()).hexdigest()
    assert info["interlinear_size"] == str(il.stat().st_size)


def test_span_whose_words_do_not_match_fails(tmp_path):
    with pytest.raises(ValueError, match="expected 'in caelo'"):
        _build(tmp_path, spans=_spans(tmp_path, "62\t5:7\t6\t7\tin caelo\n"))


def test_glosses_and_lemmas_tables_have_the_ot_shape(tmp_path):
    out, _ = _build(tmp_path)
    c = sqlite3.connect(out)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vulgate_words)")]
    assert cols == ["id", "verse_map_id", "position", "surface", "norm", "lemma", "morph", "latin_only"]
