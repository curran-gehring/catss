"""align_vulgate_nt: unit corpora, precision tiers, home refinement, link
verification. eflomal itself only runs on the mac-mini, so it is injected."""
import os
import pathlib
import sqlite3

import pytest

from catss import align_vulgate_nt as an
from catss import build_vulgate_nt as b
from tests.test_build_vulgate_nt import _interlinear, _spans, _units, _vul


def _pack(tmp_path, units=None):
    out = tmp_path / "vulgate_nt.sqlite"
    b.build(_vul(tmp_path), _interlinear(tmp_path), units or _units(tmp_path), _spans(tmp_path), out)
    c = sqlite3.connect(out)
    lemmas = {"In": "in", "principio": "principium", "erat": "sum", "Verbum": "uerbum",
              "Hoc": "hic", "Quoniam": "quoniam", "tres": "tres", "Et": "et", "spiritus": "spiritus"}
    for wid, surface in c.execute("SELECT id, surface FROM vulgate_words").fetchall():
        c.execute("UPDATE vulgate_words SET lemma=? WHERE id=?", (lemmas.get(surface), wid))
    c.commit()
    c.close()
    return out


def test_unit_corpus_skips_latin_only_words_and_keeps_greek_coordinates(tmp_path):
    pack = _pack(tmp_path)
    units = list(an.unit_corpus(pack, tmp_path / "bible_interlinear.sqlite"))
    assert len(units) == 4          # Jo 1:1, 1:2, 1Jo 5:7, 5:8 (Jo 1:3 is latin_only)
    u = units[2]                    # 1 John 5:7: "in caelo" flagged latin_only
    assert u.latin_tokens == ["quoniam", "tres", "sunt", "qui", "testimonium", "dant"]
    assert u.greek_refs == [(62, 5, 7, 1, "ὅτι"), (62, 5, 7, 2, "τρεῖς")]
    assert u.greek_tokens == ["οτι", "τρεισ"]
    # a word with no lemma falls back to its folded norm
    assert units[0].latin_tokens == ["in", "principium", "sum", "uerbum"]


def test_tiers_keep_intersections_and_only_supported_grown_links():
    lines = [
        an.Line(["deus"], ["θεοσ"], {(0, 0): "intersection"}),
        an.Line(["deus"], ["θεοσ"], {(0, 0): "intersection"}),
        an.Line(["deus"], ["θεοσ"], {(0, 0): "intersection"}),
        an.Line(["deus", "et"], ["θεοσ", "και"], {(0, 0): "grown", (1, 1): "grown"}),
    ]
    tiers = an.tier(lines, min_support=3)
    assert tiers[0] == {(0, 0): 1.0}
    assert tiers[3] == {(0, 0): 0.5}          # deus~θεος seen 3x as intersection; et~και never


def test_home_moves_to_the_greek_verse_holding_most_links():
    links = {10: [(5, 2), (5, 2), (5, 1)], 11: [], 12: [(5, 1), (5, 2)]}
    homes = {10: (5, 1), 11: (5, 1), 12: (5, 2)}
    assert an.refine_homes(homes, links) == {10: (5, 2), 11: (5, 1), 12: (5, 1)}


def test_verify_counts_dangling_and_mismatched_links(tmp_path):
    pack = _pack(tmp_path)
    il = tmp_path / "bible_interlinear.sqlite"
    c = sqlite3.connect(pack)
    c.executescript(an.ALIGN_SCHEMA)
    wid = c.execute("SELECT id FROM vulgate_words WHERE surface='Verbum'").fetchone()[0]
    c.executemany("INSERT INTO nt_align (vulgate_word_id, book_id, chapter, verse, word_position, greek_surface,"
                  " confidence, method) VALUES (?,?,?,?,?,?,?,?)", [
                      (wid, 43, 1, 1, 4, "λόγος", 1.0, "t"),     # resolves
                      (wid, 43, 1, 1, 3, "ἦν", 0.5, "t"),        # no word 3 in 1:1 (positions have gaps)
                      (wid, 43, 1, 1, 2, "ἀρχή", 0.5, "t"),      # surface differs
                  ])
    c.commit()
    c.close()
    assert an.verify(pack, il) == {"links": 3, "resolved": 1, "dangling": 1, "mismatched": 1,
                                   "latin_only_linked": 0}


SHIPPED_PACK = os.environ.get("FW_VULGATE_NT")
SHIPPED_IL = os.environ.get("FW_INTERLINEAR")


@pytest.mark.skipif(not (SHIPPED_PACK and SHIPPED_IL),
                    reason="set FW_VULGATE_NT and FW_INTERLINEAR to the built pack and the shipped interlinear")
def test_every_link_in_the_built_pack_resolves_against_the_shipped_interlinear():
    got = an.verify(pathlib.Path(SHIPPED_PACK), pathlib.Path(SHIPPED_IL))
    assert got["links"] > 0
    assert got["dangling"] == 0 and got["mismatched"] == 0 and got["latin_only_linked"] == 0
    assert got["resolved"] == got["links"]
