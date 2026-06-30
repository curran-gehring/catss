"""
Build the Vulgate pack (`vulgate.sqlite`) from raw/vulgate/vul.tsv + catss.db.

The pack is a separate on-demand SQLite file (like catss_morph.sqlite). This
module lands the foundation table:

  vulgate_verse_map
    id             INTEGER PRIMARY KEY
    vul_book       TEXT NOT NULL     -- original Vulgate abbrev (Dn, Bar, Est...)
    vul_chapter    INTEGER NOT NULL
    vul_verse      INTEGER NOT NULL
    catss_osis     TEXT NOT NULL     -- CATSS book the Latin is filed under
    catss_chapter  INTEGER NOT NULL
    catss_verse    INTEGER NOT NULL
    catss_verse_id INTEGER           -- verses.id in catss.db; NULL = no CATSS verse
    pivot          TEXT NOT NULL     -- 'mt' | 'lxx' (alignment side)
    text           TEXT NOT NULL     -- full Clementine Latin verse text
    UNIQUE(vul_book, vul_chapter, vul_verse)

`catss_verse_id` is the join key into the main catss DB; rows where it is NULL
(Esther's Greek additions, anything past a CATSS book's verse range) keep their
Latin text but receive no pivot alignment downstream.

  vulgate_words
    id           INTEGER PRIMARY KEY
    verse_map_id INTEGER NOT NULL REFERENCES vulgate_verse_map(id)
    position     INTEGER NOT NULL      -- 1-based word index in the verse
    surface      TEXT NOT NULL         -- printed Latin form (ligatures folded)
    norm         TEXT NOT NULL         -- lowercased; the eflomal alignment form
    lemma        TEXT                  -- filled by the later LatinCy pass
    morph        TEXT                  -- filled by the later LatinCy pass
    UNIQUE(verse_map_id, position)

vulgate_align (eflomal links to mt_row / lxx_word via the pivot) is added by
align_vulgate.py, which runs on the mac-mini where eflomal is built.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys

from . import parse_vulgate


SCHEMA = """
CREATE TABLE IF NOT EXISTS vulgate_verse_map (
    id             INTEGER PRIMARY KEY,
    vul_book       TEXT NOT NULL,
    vul_chapter    INTEGER NOT NULL,
    vul_verse      INTEGER NOT NULL,
    catss_osis     TEXT NOT NULL,
    catss_chapter  INTEGER NOT NULL,
    catss_verse    INTEGER NOT NULL,
    catss_verse_id INTEGER,
    pivot          TEXT NOT NULL,
    text           TEXT NOT NULL,
    UNIQUE(vul_book, vul_chapter, vul_verse)
);
CREATE INDEX IF NOT EXISTS idx_vvm_catss ON vulgate_verse_map(catss_verse_id);
CREATE INDEX IF NOT EXISTS idx_vvm_ref
    ON vulgate_verse_map(catss_osis, catss_chapter, catss_verse);

CREATE TABLE IF NOT EXISTS vulgate_words (
    id           INTEGER PRIMARY KEY,
    verse_map_id INTEGER NOT NULL REFERENCES vulgate_verse_map(id),
    position     INTEGER NOT NULL,
    surface      TEXT NOT NULL,
    norm         TEXT NOT NULL,
    lemma        TEXT,
    morph        TEXT,
    UNIQUE(verse_map_id, position)
);
CREATE INDEX IF NOT EXISTS idx_vw_verse ON vulgate_words(verse_map_id, position);
CREATE INDEX IF NOT EXISTS idx_vw_norm ON vulgate_words(norm);
"""


def _load_catss_verse_index(catss_db: pathlib.Path) -> dict[tuple[str, int, int], int]:
    """Map (osis, chapter, verse) -> verses.id from the built catss DB."""
    conn = sqlite3.connect(catss_db)
    try:
        rows = conn.execute(
            "SELECT b.osis, v.chapter, v.verse, v.id "
            "FROM verses v JOIN books b ON b.id = v.book_id"
        ).fetchall()
    finally:
        conn.close()
    return {(osis, ch, v): vid for osis, ch, v, vid in rows}


def build(raw_root: pathlib.Path, catss_db: pathlib.Path, pack_path: pathlib.Path) -> dict:
    """Build the Vulgate pack. Returns a stats dict."""
    vul_tsv = raw_root / "vulgate" / "vul.tsv"
    if not vul_tsv.exists():
        raise FileNotFoundError(f"missing Vulgate source: {vul_tsv}")
    if not catss_db.exists():
        raise FileNotFoundError(f"missing catss DB (build it first): {catss_db}")

    catss_index = _load_catss_verse_index(catss_db)

    pack_path.parent.mkdir(parents=True, exist_ok=True)
    if pack_path.exists():
        pack_path.unlink()
    conn = sqlite3.connect(pack_path)
    conn.executescript(SCHEMA)

    stats = {
        "verses": 0,
        "resolved": 0,        # catss_verse_id found
        "orphaned": 0,        # no CATSS counterpart
        "words": 0,
        "by_pivot": {"mt": 0, "lxx": 0},
        "orphans_by_book": {},
    }

    for vv in parse_vulgate.parse_file(vul_tsv):
        catss_verse_id = catss_index.get(
            (vv.catss_osis, vv.catss_chapter, vv.catss_verse)
        )
        cur = conn.execute(
            "INSERT INTO vulgate_verse_map "
            "(vul_book, vul_chapter, vul_verse, catss_osis, catss_chapter, "
            " catss_verse, catss_verse_id, pivot, text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                vv.vul_book, vv.vul_chapter, vv.vul_verse,
                vv.catss_osis, vv.catss_chapter, vv.catss_verse,
                catss_verse_id, vv.pivot, vv.text,
            ),
        )
        verse_map_id = cur.lastrowid
        for pos, (surface, norm) in enumerate(parse_vulgate.tokenize_latin(vv.text), 1):
            conn.execute(
                "INSERT INTO vulgate_words "
                "(verse_map_id, position, surface, norm) VALUES (?,?,?,?)",
                (verse_map_id, pos, surface, norm),
            )
            stats["words"] += 1

        stats["verses"] += 1
        stats["by_pivot"][vv.pivot] = stats["by_pivot"].get(vv.pivot, 0) + 1
        if catss_verse_id is None:
            stats["orphaned"] += 1
            stats["orphans_by_book"][vv.catss_osis] = (
                stats["orphans_by_book"].get(vv.catss_osis, 0) + 1
            )
        else:
            stats["resolved"] += 1

    conn.commit()
    conn.close()
    stats["pack_size_bytes"] = pack_path.stat().st_size
    return stats


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build the Vulgate verse-map pack.")
    ap.add_argument("--raw", default="raw", type=pathlib.Path,
                    help="raw/ root containing vulgate/vul.tsv")
    ap.add_argument("--catss-db", default="catss.db", type=pathlib.Path,
                    help="built catss DB to resolve verse ids against")
    ap.add_argument("--out", default="vulgate.sqlite", type=pathlib.Path,
                    help="output pack path")
    args = ap.parse_args(argv)

    stats = build(args.raw, args.catss_db, args.out)
    print(f"Vulgate pack written: {args.out} ({stats['pack_size_bytes']:,} bytes)",
          file=sys.stderr)
    print(f"  verses:   {stats['verses']:,}", file=sys.stderr)
    print(f"  resolved: {stats['resolved']:,}  "
          f"orphaned: {stats['orphaned']:,}", file=sys.stderr)
    print(f"  words:    {stats['words']:,}", file=sys.stderr)
    print(f"  pivot:    mt={stats['by_pivot'].get('mt', 0):,}  "
          f"lxx={stats['by_pivot'].get('lxx', 0):,}", file=sys.stderr)
    if stats["orphans_by_book"]:
        worst = sorted(stats["orphans_by_book"].items(),
                       key=lambda kv: -kv[1])
        print("  orphans by book: "
              + ", ".join(f"{b}={n}" for b, n in worst), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
