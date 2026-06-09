"""
Build catss.db from the downloaded raw/ files.

Schema (SQLite):

  books
    id                INTEGER PRIMARY KEY     -- canonical Bible book ID (1..39, 70+ deutero)
    osis              TEXT UNIQUE NOT NULL
    par_file          TEXT
    mlxx_file         TEXT
    display_name      TEXT NOT NULL

  verses
    id                INTEGER PRIMARY KEY
    book_id           INTEGER NOT NULL REFERENCES books(id)
    chapter           INTEGER NOT NULL
    verse             INTEGER NOT NULL
    UNIQUE(book_id, chapter, verse)

  alignments
    id                INTEGER PRIMARY KEY
    verse_id          INTEGER NOT NULL REFERENCES verses(id)
    row_order         INTEGER NOT NULL
    mt_beta           TEXT              -- raw col-a BETA
    mt_col_b_beta     TEXT              -- retroversion (col-b), if any
    lxx_beta          TEXT              -- raw Greek BETA
    mt_unicode        TEXT              -- decoded Hebrew
    lxx_unicode       TEXT              -- decoded Greek
    is_lxx_minus      INTEGER NOT NULL DEFAULT 0
    is_lxx_plus       INTEGER NOT NULL DEFAULT 0
    is_ketiv          INTEGER NOT NULL DEFAULT 0
    is_qere           INTEGER NOT NULL DEFAULT 0
    is_transposition  INTEGER NOT NULL DEFAULT 0
    notes_json        TEXT              -- ["g", "p", ...]

  lxx_morph
    id                INTEGER PRIMARY KEY
    verse_id          INTEGER NOT NULL REFERENCES verses(id)
    position          INTEGER NOT NULL         -- 1-based word-in-verse
    surface_beta      TEXT NOT NULL
    surface_unicode   TEXT NOT NULL
    parse_code        TEXT
    lemma_beta        TEXT
    lemma_unicode     TEXT
    UNIQUE(verse_id, position)

Indices on (book_id, chapter, verse), (lemma_unicode), (surface_unicode).
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

from . import books as bookreg
from . import parse_parallel, parse_lxxmorph
from .betacode import hebrew_to_unicode, greek_to_unicode


SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id           INTEGER PRIMARY KEY,
    osis         TEXT UNIQUE NOT NULL,
    par_file     TEXT,
    mlxx_file    TEXT,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verses (
    id        INTEGER PRIMARY KEY,
    book_id   INTEGER NOT NULL REFERENCES books(id),
    chapter   INTEGER NOT NULL,
    verse     INTEGER NOT NULL,
    UNIQUE(book_id, chapter, verse)
);
CREATE INDEX IF NOT EXISTS idx_verses_ref ON verses(book_id, chapter, verse);

CREATE TABLE IF NOT EXISTS alignments (
    id                INTEGER PRIMARY KEY,
    verse_id          INTEGER NOT NULL REFERENCES verses(id),
    row_order         INTEGER NOT NULL,
    mt_beta           TEXT,
    mt_col_b_beta     TEXT,
    lxx_beta          TEXT,
    mt_unicode        TEXT,
    lxx_unicode       TEXT,
    is_lxx_minus      INTEGER NOT NULL DEFAULT 0,
    is_lxx_plus       INTEGER NOT NULL DEFAULT 0,
    is_ketiv          INTEGER NOT NULL DEFAULT 0,
    is_qere           INTEGER NOT NULL DEFAULT 0,
    is_transposition  INTEGER NOT NULL DEFAULT 0,
    notes_json        TEXT,
    UNIQUE(verse_id, row_order)
);
CREATE INDEX IF NOT EXISTS idx_align_verse ON alignments(verse_id, row_order);

CREATE TABLE IF NOT EXISTS lxx_morph (
    id               INTEGER PRIMARY KEY,
    verse_id         INTEGER NOT NULL REFERENCES verses(id),
    position         INTEGER NOT NULL,
    surface_beta     TEXT NOT NULL,
    surface_unicode  TEXT NOT NULL,
    parse_code       TEXT,
    lemma_beta       TEXT,
    lemma_unicode    TEXT,
    UNIQUE(verse_id, position)
);
CREATE INDEX IF NOT EXISTS idx_morph_verse ON lxx_morph(verse_id, position);
CREATE INDEX IF NOT EXISTS idx_morph_lemma ON lxx_morph(lemma_unicode);
CREATE INDEX IF NOT EXISTS idx_morph_surface ON lxx_morph(surface_unicode);
"""


def build(raw_root: pathlib.Path, db_path: pathlib.Path, *, slim: bool = False) -> dict:
    """
    Build catss.db from raw files. Returns a stats dict.

    slim: when True, drop BETA columns (mt_beta, mt_col_b_beta, lxx_beta,
          surface_beta, lemma_beta) and run VACUUM at the end. Unicode and
          annotation flags/notes are preserved. Typical size delta: ~114 MB
          → ~94 MB. Intended for iOS/mobile bundling (see `catss split`).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    stats = {
        "books": 0, "verses": 0, "alignments": 0, "morph_words": 0,
        "slim": slim, "errors": [],
    }

    _load_books(conn, stats)
    _load_parallel(conn, raw_root / "parallel", stats)
    _load_lxxmorph(conn, raw_root / "lxxmorph", stats)

    if slim:
        _strip_beta_columns(conn)

    _final_stats(conn, stats)

    conn.commit()
    if slim:
        conn.execute("VACUUM")
    conn.close()
    stats["db_size_bytes"] = db_path.stat().st_size
    return stats


def _strip_beta_columns(conn: sqlite3.Connection) -> None:
    """Null out the BETA columns and drop them via table rebuild."""
    # SQLite supports DROP COLUMN natively since 3.35 (2021). Use it.
    for col in ("mt_beta", "mt_col_b_beta", "lxx_beta"):
        try:
            conn.execute(f"ALTER TABLE alignments DROP COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    for col in ("surface_beta", "lemma_beta"):
        try:
            conn.execute(f"ALTER TABLE lxx_morph DROP COLUMN {col}")
        except sqlite3.OperationalError:
            pass


def _load_books(conn: sqlite3.Connection, stats: dict) -> None:
    seen: set[str] = set()
    for b in bookreg.all_books():
        if b.osis in seen:
            continue
        seen.add(b.osis)
        mlxx = ",".join(b.mlxx_files) if b.mlxx_files else None
        conn.execute(
            "INSERT INTO books (id, osis, par_file, mlxx_file, display_name) "
            "VALUES (?, ?, ?, ?, ?)",
            (b.canon_id, b.osis, b.par_file, mlxx, b.display),
        )
        stats["books"] += 1


def _load_parallel(conn: sqlite3.Connection, par_dir: pathlib.Path, stats: dict) -> None:
    for b in bookreg.all_books():
        if b.par_file is None:
            continue
        path = par_dir / f"{b.par_file}.par"
        if not path.exists():
            stats["errors"].append(f"missing: {path}")
            continue

        print(f"  parallel: {path.name}", file=sys.stderr)
        for verse in parse_parallel.parse_file(path):
            verse_id = _ensure_verse(conn, b.canon_id, verse.chapter, verse.verse)
            # A few books (e.g. 1Esdras, Isaiah) emit the same (ch, v)
            # across separated blocks — CATSS uses blank-line-separated
            # sections *within* a verse. Continue row_order from the
            # highest existing row so repeated blocks append rather than
            # collide on the UNIQUE(verse_id, row_order) constraint.
            start_order = (conn.execute(
                "SELECT COALESCE(MAX(row_order), 0) FROM alignments WHERE verse_id=?",
                (verse_id,),
            ).fetchone()[0])
            for offset, row in enumerate(verse.rows, 1):
                order = start_order + offset
                conn.execute(
                    "INSERT INTO alignments "
                    "(verse_id, row_order, mt_beta, mt_col_b_beta, lxx_beta, "
                    " mt_unicode, lxx_unicode, is_lxx_minus, is_lxx_plus, "
                    " is_ketiv, is_qere, is_transposition, notes_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        verse_id, order,
                        row.mt_col_a or None,
                        row.mt_col_b,
                        row.lxx_raw or None,
                        # `or None`: marker-only cells ('--+', '---', "''")
                        # decode to "" — store NULL, not empty/garbage text.
                        # Plus rows have NO MT counterpart by definition:
                        # anything after '--+' is annotation/retroversion
                        # (kept raw in mt_beta / mt_col_b_beta), never MT.
                        None if row.is_lxx_plus
                        else (hebrew_to_unicode(row.mt_col_a) or None) if row.mt_col_a else None,
                        (greek_to_unicode(row.lxx_raw) or None) if row.lxx_raw else None,
                        int(row.is_lxx_minus),
                        int(row.is_lxx_plus),
                        int(row.is_ketiv),
                        int(row.is_qere),
                        int(row.is_transposition),
                        json.dumps(row.notes) if row.notes else None,
                    ),
                )
                stats["alignments"] += 1


def _morph_book_remap(stem: str, book_id: int, chapter: int) -> tuple[int, int]:
    """
    Two CCAT .mlxx files pack content belonging to a different canonical
    book than the one the file is registered under:

      19.2Esdras — Greek 2 Esdras = Ezra (ch 1-10) + Nehemiah (ch 11-23,
                   Neh 1 = 2Esd 11). Without the split, Nehemiah had zero
                   morphology and Ezra grew 13 phantom chapters.
      29.Psalms2 — ends with Ps 151, which the .par side registers as its
                   own book (Ps151, single chapter).
    """
    if stem == "19.2Esdras" and chapter >= 11:
        return bookreg.by_osis("Neh").canon_id, chapter - 10
    if stem == "29.Psalms2" and chapter == 151:
        return bookreg.by_osis("Ps151").canon_id, 1
    return book_id, chapter


def _load_lxxmorph(conn: sqlite3.Connection, mlxx_dir: pathlib.Path, stats: dict) -> None:
    for b in bookreg.all_books():
        if not b.mlxx_files:
            continue
        for stem in b.mlxx_files:
            path = mlxx_dir / f"{stem}.mlxx"
            if not path.exists():
                continue
            print(f"  lxxmorph: {path.name}", file=sys.stderr)
            for mverse in parse_lxxmorph.parse_file(path):
                book_id, chapter = _morph_book_remap(stem, b.canon_id, mverse.chapter)
                verse_id = _ensure_verse(conn, book_id, chapter, mverse.verse)
                # Esther's addition subverses (1:1a, 1:1b, ...) arrive as
                # separate parsed verses that merge into one (ch, v) — their
                # positions must continue, not restart at 1.
                start_pos = conn.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM lxx_morph WHERE verse_id=?",
                    (verse_id,),
                ).fetchone()[0]
                for w in mverse.words:
                    try:
                        conn.execute(
                            "INSERT INTO lxx_morph "
                            "(verse_id, position, surface_beta, surface_unicode, "
                            " parse_code, lemma_beta, lemma_unicode) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (
                                verse_id, start_pos + w.position,
                                w.surface_beta,
                                greek_to_unicode(w.surface_beta),
                                w.parse_code or None,
                                w.lemma_beta or None,
                                greek_to_unicode(w.lemma_beta) if w.lemma_beta else None,
                            ),
                        )
                        stats["morph_words"] += 1
                    except sqlite3.Error as e:
                        stats["errors"].append(f"{path.name}:{w.line_no}: {e}")


def _ensure_verse(conn: sqlite3.Connection, book_id: int, ch: int, v: int) -> int:
    row = conn.execute(
        "SELECT id FROM verses WHERE book_id=? AND chapter=? AND verse=?",
        (book_id, ch, v),
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO verses (book_id, chapter, verse) VALUES (?,?,?)",
        (book_id, ch, v),
    )
    return cur.lastrowid


def _final_stats(conn: sqlite3.Connection, stats: dict) -> None:
    stats["verses"] = conn.execute("SELECT COUNT(*) FROM verses").fetchone()[0]
