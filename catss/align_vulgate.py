"""
Word-align the Latin Vulgate to its CATSS pivot with eflomal, then write
vulgate_align into the pack. **Runs on the mac-mini** (eflomal won't build on
Windows). The output is "silver" machine alignment, distinct from the gold,
hand-curated MT<->LXX alignment CATSS ships.

Strategy (single pivot, ride the gold cross-alignment — see books.vulgate_pivot):
each Latin verse aligns to ONE language, and the other is reached transitively
through CATSS's existing alignment rows. So:

  pivot = 'mt'  -> Latin aligns to the Hebrew of the parallel `alignments` rows;
                   target_kind 'mt_row' (an alignments.id). That row already
                   carries its gold LXX counterpart, so the Greek comes free.
  pivot = 'lxx' -> Latin aligns to `lxx_morph` words (deuterocanon, Psalms,
                   Greek-only books); target_kind 'lxx_word' (an lxx_morph.id).

eflomal runs once per pivot over the whole corpus, producing forward and
reverse links (both in source-target orientation). We symmetrize with
grow-diag-final-and; intersection links get confidence 1.0, grown links 0.5.

  vulgate_align
    id              INTEGER PRIMARY KEY
    vulgate_word_id INTEGER NOT NULL REFERENCES vulgate_words(id)
    target_kind     TEXT NOT NULL     -- 'mt_row' | 'lxx_word'
    target_id       INTEGER NOT NULL  -- alignments.id | lxx_morph.id in catss.db
    pivot           TEXT NOT NULL     -- 'mt' | 'lxx'
    method          TEXT NOT NULL     -- 'eflomal-gdfa'
    confidence      REAL NOT NULL
    UNIQUE(vulgate_word_id, target_kind, target_id)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
import tempfile


ALIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS vulgate_align (
    id              INTEGER PRIMARY KEY,
    vulgate_word_id INTEGER NOT NULL REFERENCES vulgate_words(id),
    target_kind     TEXT NOT NULL,
    target_id       INTEGER NOT NULL,
    pivot           TEXT NOT NULL,
    method          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    UNIQUE(vulgate_word_id, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS idx_va_word ON vulgate_align(vulgate_word_id);
CREATE INDEX IF NOT EXISTS idx_va_target ON vulgate_align(target_kind, target_id);
"""

_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
              (0, 1), (1, -1), (1, 0), (1, 1)]


def _split_hebrew(text: str) -> list[str]:
    """Hebrew cell -> word tokens. CATSS joins prefixes with '/'; split those
    and whitespace so each morpheme is its own alignment token."""
    return [t for t in text.replace("/", " ").split() if t.strip()]


def _pivot_tokens(catss: sqlite3.Connection, pivot: str, verse_id: int):
    """Return (tokens, target_ids) for the pivot side of one CATSS verse.

    Token i was produced by target_ids[i] (an alignments.id for mt, an
    lxx_morph.id for lxx). For mt, one row can yield several tokens that all
    point back to the same row id.
    """
    tokens: list[str] = []
    target_ids: list[int] = []
    if pivot == "lxx":
        for wid, surf in catss.execute(
            "SELECT id, surface_unicode FROM lxx_morph "
            "WHERE verse_id=? ORDER BY position", (verse_id,)
        ):
            surf = (surf or "").strip()
            if surf:
                tokens.append(surf)
                target_ids.append(wid)
    else:  # mt
        for aid, mt in catss.execute(
            "SELECT id, mt_unicode FROM alignments "
            "WHERE verse_id=? AND mt_unicode IS NOT NULL ORDER BY row_order",
            (verse_id,)
        ):
            for tok in _split_hebrew(mt or ""):
                tokens.append(tok)
                target_ids.append(aid)
    return tokens, target_ids


def _gather_pairs(pack: sqlite3.Connection, catss: sqlite3.Connection, pivot: str):
    """Build the parallel corpus for one pivot.

    Yields, only for verses with a resolved catss_verse_id AND non-empty text
    on both sides: (latin_word_ids, latin_norms, pivot_target_ids, pivot_toks).
    """
    rows = pack.execute(
        "SELECT id, catss_verse_id FROM vulgate_verse_map "
        "WHERE pivot=? AND catss_verse_id IS NOT NULL ORDER BY id", (pivot,)
    ).fetchall()
    for verse_map_id, catss_verse_id in rows:
        words = pack.execute(
            "SELECT id, norm FROM vulgate_words "
            "WHERE verse_map_id=? ORDER BY position", (verse_map_id,)
        ).fetchall()
        if not words:
            continue
        latin_ids = [w[0] for w in words]
        latin_norms = [w[1] for w in words]
        toks, tgt_ids = _pivot_tokens(catss, pivot, catss_verse_id)
        if not toks:
            continue
        yield latin_ids, latin_norms, tgt_ids, toks


def _run_eflomal(src_lines: list[str], trg_lines: list[str]):
    """Run eflomal over a corpus; return per-line forward and reverse link
    lists (each a list of (src_idx, trg_idx) tuples)."""
    from eflomal import Aligner

    aligner = Aligner()
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "src")
        tp = os.path.join(d, "trg")
        ff = os.path.join(d, "fwd")
        rf = os.path.join(d, "rev")
        with open(sp, "w", encoding="utf-8") as f:
            f.write("\n".join(src_lines) + "\n")
        with open(tp, "w", encoding="utf-8") as f:
            f.write("\n".join(trg_lines) + "\n")
        with open(sp, encoding="utf-8") as s, open(tp, encoding="utf-8") as t:
            aligner.align(s, t, links_filename_fwd=ff,
                          links_filename_rev=rf, quiet=True)
        fwd = [_parse_links(l) for l in open(ff, encoding="utf-8")]
        rev = [_parse_links(l) for l in open(rf, encoding="utf-8")]
    return fwd, rev


def _parse_links(line: str) -> list[tuple[int, int]]:
    out = []
    for pair in line.split():
        i, _, j = pair.partition("-")
        if j:
            out.append((int(i), int(j)))
    return out


def _gdfa(fwd: list[tuple[int, int]], rev: list[tuple[int, int]],
          n_src: int, n_trg: int) -> dict[tuple[int, int], str]:
    """grow-diag-final-and symmetrization. Returns {(i,j): 'intersection'|'grown'}."""
    e2f, f2e = set(fwd), set(rev)
    union = e2f | f2e
    align: dict[tuple[int, int], str] = {p: "intersection" for p in (e2f & f2e)}
    aligned_src = {i for i, _ in align}
    aligned_trg = {j for _, j in align}

    added = True
    while added:
        added = False
        for (i, j) in list(align.keys()):
            for di, dj in _NEIGHBORS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < n_src and 0 <= nj < n_trg):
                    continue
                if (ni, nj) in align or (ni, nj) not in union:
                    continue
                if ni not in aligned_src or nj not in aligned_trg:
                    align[(ni, nj)] = "grown"
                    aligned_src.add(ni)
                    aligned_trg.add(nj)
                    added = True

    for (i, j) in union:
        if (i, j) not in align and i not in aligned_src and j not in aligned_trg:
            align[(i, j)] = "grown"
            aligned_src.add(i)
            aligned_trg.add(j)

    return align


def align(pack_path: pathlib.Path, catss_db: pathlib.Path,
          pivots=("lxx", "mt")) -> dict:
    """Align Latin to each pivot and write vulgate_align. Returns a stats dict."""
    if not pack_path.exists():
        raise FileNotFoundError(f"missing Vulgate pack (build it first): {pack_path}")
    if not catss_db.exists():
        raise FileNotFoundError(f"missing catss DB: {catss_db}")

    pack = sqlite3.connect(pack_path)
    catss = sqlite3.connect(catss_db)
    pack.executescript(ALIGN_SCHEMA)
    pack.execute("DELETE FROM vulgate_align")  # idempotent rebuild

    stats = {"by_pivot": {}, "links": 0, "intersection": 0, "grown": 0}

    for pivot in pivots:
        pairs = list(_gather_pairs(pack, catss, pivot))
        if not pairs:
            stats["by_pivot"][pivot] = {"verses": 0, "links": 0}
            continue
        src_lines = [" ".join(p[1]) for p in pairs]
        trg_lines = [" ".join(p[3]) for p in pairs]
        print(f"  eflomal[{pivot}]: {len(pairs):,} verse pairs ...",
              file=sys.stderr)
        fwd, rev = _run_eflomal(src_lines, trg_lines)

        kind = "lxx_word" if pivot == "lxx" else "mt_row"
        plinks = 0
        for line_i, (latin_ids, latin_norms, tgt_ids, toks) in enumerate(pairs):
            links = _gdfa(fwd[line_i], rev[line_i], len(latin_ids), len(toks))
            for (i, j), cat in links.items():
                conf = 1.0 if cat == "intersection" else 0.5
                pack.execute(
                    "INSERT INTO vulgate_align "
                    "(vulgate_word_id, target_kind, target_id, pivot, method, confidence) "
                    "VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(vulgate_word_id, target_kind, target_id) "
                    "DO UPDATE SET confidence=MAX(confidence, excluded.confidence)",
                    (latin_ids[i], kind, tgt_ids[j], pivot, "eflomal-gdfa", conf),
                )
                stats[cat] += 1
                plinks += 1
        stats["by_pivot"][pivot] = {"verses": len(pairs), "links": plinks}
        stats["links"] += plinks

    pack.commit()
    pack.close()
    catss.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="eflomal-align the Vulgate to its CATSS pivot.")
    ap.add_argument("--pack", default="vulgate.sqlite", type=pathlib.Path)
    ap.add_argument("--catss-db", default="catss.db", type=pathlib.Path)
    args = ap.parse_args(argv)

    stats = align(args.pack, args.catss_db)
    print(f"vulgate_align: {stats['links']:,} links "
          f"(intersection={stats['intersection']:,} grown={stats['grown']:,})",
          file=sys.stderr)
    for pivot, s in stats["by_pivot"].items():
        print(f"  {pivot}: {s['verses']:,} verses -> {s['links']:,} links",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
