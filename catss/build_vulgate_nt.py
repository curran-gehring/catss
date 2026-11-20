"""
Build the New Testament Latin pack (`vulgate_nt.sqlite`): Clementine NT words
mapped onto the SBLGNT of FirstWord's shipped interlinear pack.

A separate download from the OT `vulgate.sqlite` (see docs/nt-latin-design.md):
the OT pack is keyed to catss ids; this one to interlinear coordinates, so a
rebuild of one never forces the other. `vulgate_words` and `lemma_glosses` keep
the OT shapes, so lemmatize_vulgate and gloss_vulgate run on it unchanged.

  pack_info      key/value: interlinear_sha256, interlinear_size
  nt_verse_map   one row per Clementine NT verse, in Latin reading order
    id, vul_book, vul_chapter, vul_verse,
    book_id, chapter, verse     -- the ESV verse it is shown under ("home")
    unit_id, status, note, text -- status: same | renumbered | unit | latin_only
  nt_unit_greek  the SBLGNT verses of each alignment unit (none for latin_only)
  vulgate_words  as the OT pack, plus latin_only (1 = shown, never linked)

nt_align (the word links) is added by align_vulgate_nt on the mac-mini, after
lemmatize_vulgate has filled lemma/morph.
"""
from __future__ import annotations

import hashlib
import pathlib
import sqlite3
import sys

from . import parse_vulgate
from . import vulgate_nt as vn

DATA = pathlib.Path(__file__).parent / "data"

SCHEMA = """
CREATE TABLE pack_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE nt_verse_map (
    id          INTEGER PRIMARY KEY,
    vul_book    TEXT NOT NULL,
    vul_chapter INTEGER NOT NULL,
    vul_verse   INTEGER NOT NULL,
    book_id     INTEGER NOT NULL,
    chapter     INTEGER NOT NULL,
    verse       INTEGER NOT NULL,
    unit_id     INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('same','renumbered','unit','latin_only')),
    note        TEXT,
    text        TEXT NOT NULL,
    UNIQUE (book_id, vul_chapter, vul_verse)
);
CREATE INDEX idx_ntvm_home ON nt_verse_map(book_id, chapter, verse);
CREATE INDEX idx_ntvm_unit ON nt_verse_map(unit_id);
CREATE TABLE nt_unit_greek (
    unit_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    chapter INTEGER NOT NULL,
    verse   INTEGER NOT NULL,
    PRIMARY KEY (unit_id, chapter, verse),
    UNIQUE (book_id, chapter, verse)
);
CREATE TABLE vulgate_words (
    id           INTEGER PRIMARY KEY,
    verse_map_id INTEGER NOT NULL REFERENCES nt_verse_map(id),
    position     INTEGER NOT NULL,
    surface      TEXT NOT NULL,
    norm         TEXT NOT NULL,
    lemma        TEXT,
    morph        TEXT,
    latin_only   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (verse_map_id, position)
);
CREATE INDEX idx_vw_verse ON vulgate_words(verse_map_id, position);
"""


def load_spans(path: pathlib.Path) -> dict[tuple[int, int, int], list[tuple[int, int, str]]]:
    """Word-level latin_only spans: `book<TAB>ch:v<TAB>from<TAB>to<TAB>expect`
    (positions 1-based, inclusive; expect = the folded surfaces joined by spaces,
    so a tokenizer change fails the build instead of flagging the wrong words)."""
    out: dict[tuple[int, int, int], list[tuple[int, int, str]]] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise ValueError(f"{path}: line {n}: expected 5 tab-separated columns")
            book, ref, lo, hi, expect = parts
            ch, _, v = ref.partition(":")
            out.setdefault((int(book), int(ch), int(v)), []).append((int(lo), int(hi), expect.strip()))
    return out


def _greek_verses(interlinear: pathlib.Path) -> dict[int, list[vn.Ref]]:
    conn = sqlite3.connect(f"file:{interlinear}?mode=ro", uri=True)
    try:
        out: dict[int, list[vn.Ref]] = {}
        for b, ch, v in conn.execute(
                "SELECT DISTINCT book_id, chapter, verse FROM interlinear_words "
                "WHERE source='SBLGNT' ORDER BY book_id, chapter, verse"):
            out.setdefault(b, []).append((ch, v))
        return out
    finally:
        conn.close()


def build(vul_tsv: pathlib.Path, interlinear: pathlib.Path, units_tsv: pathlib.Path,
          spans_tsv: pathlib.Path, out: pathlib.Path) -> dict:
    for p in (vul_tsv, interlinear, units_tsv, spans_tsv):
        if not p.exists():
            raise FileNotFoundError(p)
    latin = vn.parse_nt(vul_tsv)
    greek = _greek_verses(interlinear)
    rows = vn.load_unit_rows(units_tsv)
    spans = load_spans(spans_tsv)

    by_book: dict[int, list[vn.LatinVerse]] = {}
    for lv in latin:
        by_book.setdefault(lv.book_id, []).append(lv)
    unknown = set(rows) - set(by_book)
    if unknown:
        raise ValueError(f"nt_units.tsv names books with no Latin: {sorted(unknown)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    conn.executescript(SCHEMA)
    digest = hashlib.sha256(interlinear.read_bytes()).hexdigest()
    conn.executemany("INSERT INTO pack_info VALUES (?,?)", [
        ("interlinear_sha256", digest), ("interlinear_size", str(interlinear.stat().st_size))])

    stats = {"verses": 0, "words": 0, "latin_only_words": 0, "units": 0, "status": {}}
    unit_id = 0
    used_spans = set()
    for book_id in sorted(by_book):
        verses = by_book[book_id]
        text_of = {(lv.chapter, lv.verse): lv for lv in verses}
        units = vn.resolve_units([(lv.chapter, lv.verse) for lv in verses],
                                 greek.get(book_id, []), rows.get(book_id, []))
        for u in units:
            unit_id += 1
            stats["units"] += 1
            conn.executemany("INSERT INTO nt_unit_greek VALUES (?,?,?,?)",
                             [(unit_id, book_id, ch, v) for ch, v in u.greek])
            for ref, status, home in zip(u.latin, u.status, u.home):
                lv = text_of[ref]
                cur = conn.execute(
                    "INSERT INTO nt_verse_map (vul_book, vul_chapter, vul_verse, book_id, chapter, verse,"
                    " unit_id, status, note, text) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (lv.vul_book, lv.chapter, lv.verse, book_id, home[0], home[1], unit_id, status,
                     u.note or None, lv.text))
                vm_id = cur.lastrowid
                words = parse_vulgate.tokenize_latin(lv.text)
                flags = [status == "latin_only"] * len(words)
                for lo, hi, expect in spans.get((book_id, *ref), []):
                    got = " ".join(s for s, _ in words[lo - 1:hi])
                    if got != expect:
                        raise ValueError(f"latin_only span {book_id} {ref[0]}:{ref[1]} {lo}-{hi}: "
                                         f"expected {expect!r}, found {got!r}")
                    flags[lo - 1:hi] = [True] * (hi - lo + 1)
                    used_spans.add((book_id, *ref))
                for pos, ((surface, norm), flag) in enumerate(zip(words, flags), 1):
                    conn.execute("INSERT INTO vulgate_words (verse_map_id, position, surface, norm, latin_only)"
                                 " VALUES (?,?,?,?,?)", (vm_id, pos, surface, norm, int(flag)))
                stats["words"] += len(words)
                stats["latin_only_words"] += sum(flags)
                stats["verses"] += 1
                stats["status"][status] = stats["status"].get(status, 0) + 1
    missing = set(spans) - used_spans
    if missing:
        raise ValueError(f"latin_only spans name verses with no Latin: {sorted(missing)}")
    conn.commit()
    conn.close()
    stats["pack_size_bytes"] = out.stat().st_size
    return stats


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build the NT Latin pack (verse map + words).")
    ap.add_argument("--vul", type=pathlib.Path, default=pathlib.Path("raw/vulgate/vul.tsv"))
    ap.add_argument("--interlinear", type=pathlib.Path, required=True,
                    help="the SHIPPED bible_interlinear.sqlite (fetch it from the live manifest)")
    ap.add_argument("--units", type=pathlib.Path, default=DATA / "nt_units.tsv")
    ap.add_argument("--spans", type=pathlib.Path, default=DATA / "nt_latin_only_words.tsv")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("vulgate_nt.sqlite"))
    args = ap.parse_args(argv)
    stats = build(args.vul, args.interlinear, args.units, args.spans, args.out)
    print(f"vulgate_nt written: {args.out} ({stats['pack_size_bytes']:,} bytes)", file=sys.stderr)
    print(f"  verses {stats['verses']:,} in {stats['units']:,} units; words {stats['words']:,} "
          f"({stats['latin_only_words']:,} latin_only)", file=sys.stderr)
    for k, v in sorted(stats["status"].items()):
        print(f"  {k:<11} {v:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
