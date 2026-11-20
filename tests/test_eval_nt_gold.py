"""eval_nt_gold: precision / recall / coverage of nt_align against hand-checked gold."""
import sqlite3

from catss import align_vulgate_nt as an
from catss import eval_nt_gold as ev
from tests.test_align_vulgate_nt import _pack


def test_scores_by_tier_and_coverage(tmp_path):
    pack = _pack(tmp_path)
    c = sqlite3.connect(pack)
    c.executescript(an.ALIGN_SCHEMA)
    wid = {s: i for s, i in c.execute(
        "SELECT w.surface, w.id FROM vulgate_words w JOIN nt_verse_map vm ON vm.id = w.verse_map_id"
        " WHERE vm.vul_book='Jo' AND vm.vul_verse=1")}
    c.executemany("INSERT INTO nt_align (vulgate_word_id, book_id, chapter, verse, word_position, greek_surface,"
                  " confidence, method) VALUES (?,43,1,1,?,?,?,'t')", [
                      (wid["In"], 1, "Ἐν", 1.0),          # right
                      (wid["principio"], 2, "ἀρχῇ", 1.0),  # right
                      (wid["Verbum"], 2, "ἀρχῇ", 0.5),     # wrong
                      (wid["Verbum"], 4, "λόγος", 0.5),    # right
                  ])
    c.commit()
    c.close()
    gold = tmp_path / "gold.tsv"
    gold.write_text("# book\tref\tpos\tsurface\trequired\tacceptable\n"
                    "43\t1:1\t1\tIn\t1:1:1\t-\n"
                    "43\t1:1\t2\tprincipio\t1:1:2\t-\n"
                    "43\t1:1\t3\terat\t-\t-\n"
                    "43\t1:1\t4\tVerbum\t1:1:4\t-\n", encoding="utf-8")
    r = ev.evaluate(pack, gold)
    assert r["tiers"]["1.0"] == {"links": 2, "correct": 2}
    assert r["tiers"]["0.5"] == {"links": 2, "correct": 1}
    assert r["precision"] == 3 / 4
    assert r["recall"] == 3 / 3
    assert r["sample_coverage"] == 3 / 4
    assert r["corpus"]["words"] == 4 + 4 + 6 + 8   # every non-latin_only Latin word in the pack
    assert r["corpus"]["linked"] == 3


def test_gold_word_whose_surface_differs_fails(tmp_path):
    pack = _pack(tmp_path)
    sqlite3.connect(pack).executescript(an.ALIGN_SCHEMA)
    gold = tmp_path / "gold.tsv"
    gold.write_text("43\t1:1\t1\tPrincipio\t1:1:1\t-\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="Principio"):
        ev.evaluate(pack, gold)
