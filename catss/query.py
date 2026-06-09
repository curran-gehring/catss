"""
Thin query API over catss.db. Stable surface for FirstWord and CLI.

Usage:

    from catss import query
    q = query.CATSS()                    # finds default catss.db
    verse = q.lookup_verse("ruth", 1, 1)
    for row in verse.alignments:
        print(row.mt_unicode, "↔", row.lxx_unicode)

    hits = q.search_lemma("κύριος")      # unicode or BETA both accepted
    for h in hits:
        print(h.ref, h.surface_unicode)
"""
from __future__ import annotations

import pathlib
import sqlite3
from dataclasses import dataclass
from typing import Iterable


DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "catss.db"


@dataclass(frozen=True)
class VerseRef:
    osis: str
    book_display: str
    chapter: int
    verse: int

    def __str__(self) -> str:
        return f"{self.osis} {self.chapter}:{self.verse}"


@dataclass(frozen=True)
class AlignmentPair:
    row_order: int
    mt_beta: str | None
    mt_unicode: str | None
    mt_col_b_beta: str | None
    lxx_beta: str | None
    lxx_unicode: str | None
    is_lxx_minus: bool
    is_lxx_plus: bool
    is_ketiv: bool
    is_qere: bool
    is_transposition: bool
    notes: list[str]


@dataclass(frozen=True)
class MorphWord:
    position: int
    subverse: str | None        # 'a'.. for LXX-addition words (Esth 1:1a)
    surface_beta: str
    surface_unicode: str
    parse_code: str | None
    lemma_beta: str | None
    lemma_unicode: str | None


@dataclass(frozen=True)
class Verse:
    ref: VerseRef
    alignments: list[AlignmentPair]
    lxx_morph: list[MorphWord]


@dataclass(frozen=True)
class LemmaHit:
    ref: VerseRef
    position: int
    surface_beta: str
    surface_unicode: str
    parse_code: str | None


class CATSS:
    def __init__(self, db_path: str | pathlib.Path | None = None) -> None:
        path = pathlib.Path(db_path) if db_path else DEFAULT_DB
        if not path.exists():
            raise FileNotFoundError(
                f"catss.db not found at {path} — run `catss fetch && catss build`."
            )
        # check_same_thread=False so a single CATSS instance can service
        # multiple FastAPI / asyncio worker threads. SQLite itself is still
        # serialized; each caller gets correct results, but don't interleave
        # transactions from different threads on the same connection.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._slim = self._detect_slim()

    def _detect_slim(self) -> bool:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(alignments)")}
        return "mt_beta" not in cols

    # ---- lookups ----------------------------------------------------------

    def lookup_verse(self, book: str, chapter: int, verse: int) -> Verse | None:
        row = self.conn.execute(
            "SELECT v.id, b.osis, b.display_name "
            "FROM verses v JOIN books b ON v.book_id=b.id "
            "WHERE LOWER(b.osis)=LOWER(?) AND v.chapter=? AND v.verse=?",
            (book, chapter, verse),
        ).fetchone()
        if row is None:
            return None

        ref = VerseRef(osis=row["osis"], book_display=row["display_name"],
                       chapter=chapter, verse=verse)

        aligns = [
            AlignmentPair(
                row_order=r["row_order"],
                mt_beta=_col(r, "mt_beta"),
                mt_unicode=r["mt_unicode"],
                mt_col_b_beta=_col(r, "mt_col_b_beta"),
                lxx_beta=_col(r, "lxx_beta"),
                lxx_unicode=r["lxx_unicode"],
                is_lxx_minus=bool(r["is_lxx_minus"]),
                is_lxx_plus=bool(r["is_lxx_plus"]),
                is_ketiv=bool(r["is_ketiv"]),
                is_qere=bool(r["is_qere"]),
                is_transposition=bool(r["is_transposition"]),
                notes=_parse_notes(r["notes_json"]),
            )
            for r in self.conn.execute(
                "SELECT * FROM alignments WHERE verse_id=? ORDER BY row_order",
                (row["id"],),
            )
        ]

        morph = [
            MorphWord(
                position=m["position"],
                subverse=_col(m, "subverse"),
                surface_beta=_col(m, "surface_beta"),
                surface_unicode=m["surface_unicode"],
                parse_code=m["parse_code"],
                lemma_beta=_col(m, "lemma_beta"),
                lemma_unicode=m["lemma_unicode"],
            )
            for m in self.conn.execute(
                "SELECT * FROM lxx_morph WHERE verse_id=? ORDER BY position",
                (row["id"],),
            )
        ]

        return Verse(ref=ref, alignments=aligns, lxx_morph=morph)

    def search_lemma(self, lemma: str, *, limit: int = 500) -> Iterable[LemmaHit]:
        # Slim builds don't have lemma_beta — fall back to unicode-only match.
        where = "m.lemma_unicode=?" if self._slim else "m.lemma_unicode=? OR m.lemma_beta=?"
        params: tuple = (lemma,) if self._slim else (lemma, lemma)
        surface_select = "m.surface_unicode" if self._slim else "m.surface_beta, m.surface_unicode"
        rows = self.conn.execute(
            f"SELECT m.position, {surface_select}, m.parse_code, "
            f"       b.osis, b.display_name, v.chapter, v.verse "
            f"FROM lxx_morph m "
            f"JOIN verses v ON m.verse_id=v.id "
            f"JOIN books b ON v.book_id=b.id "
            f"WHERE {where} LIMIT ?",
            (*params, limit),
        )
        for r in rows:
            yield LemmaHit(
                ref=VerseRef(osis=r["osis"], book_display=r["display_name"],
                             chapter=r["chapter"], verse=r["verse"]),
                position=r["position"],
                surface_beta=_col(r, "surface_beta"),
                surface_unicode=r["surface_unicode"],
                parse_code=r["parse_code"],
            )

    def books(self) -> list[tuple[str, str]]:
        return [(r["osis"], r["display_name"])
                for r in self.conn.execute(
                    "SELECT osis, display_name FROM books ORDER BY id")]


def _parse_notes(raw: str | None) -> list[str]:
    if not raw:
        return []
    import json
    try:
        return list(json.loads(raw))
    except Exception:
        return []


def _col(row: sqlite3.Row, name: str):
    """Safely read a possibly-absent column (for slim builds)."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None
