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
grow-diag-final (OR final pass); intersection links get confidence 1.0,
grown links 0.5.

  vulgate_align
    id              INTEGER PRIMARY KEY
    vulgate_word_id INTEGER NOT NULL REFERENCES vulgate_words(id)
    target_kind     TEXT NOT NULL     -- 'mt_row' | 'lxx_word'
    target_id       INTEGER NOT NULL  -- alignments.id | lxx_morph.id in catss.db
    target_sub      INTEGER NOT NULL  -- mt: 0-based token index into
                                      --     _split_hebrew(mt_unicode), which
                                      --     splits on '/' AND whitespace; lxx: 0
    pivot           TEXT NOT NULL     -- 'mt' | 'lxx'
    method          TEXT NOT NULL     -- 'eflomal-gdf'
    confidence      REAL NOT NULL
    UNIQUE(vulgate_word_id, target_kind, target_id, target_sub)

The Hebrew has no per-word stable id in catss.db — the `alignments` row is the
finest CATSS unit. We still feed eflomal sub-row tokens (CATSS joins prefixes
with '/', and one alignment cell may hold several space-separated Hebrew words)
because that gives far better co-occurrence statistics, and `target_sub` records
which sub-row token a Latin word hit, so distinct links to the same row are
preserved rather than collapsed by the unique key. Consumers that only want
row-level highlighting ignore target_sub; those wanting the exact token MUST
tokenize mt_unicode the same way the producer did — split on '/' AND whitespace,
markers (*, **) retained, i.e. reuse `_split_hebrew` — and index by it. Splitting
on '/' alone desyncs the index on ketiv/qere and any multi-word Hebrew cell.
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
    target_sub      INTEGER NOT NULL DEFAULT 0,
    pivot           TEXT NOT NULL,
    method          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    UNIQUE(vulgate_word_id, target_kind, target_id, target_sub)
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
    """Return (tokens, target_ids, target_subs) for the pivot side of one verse.

    Token i came from target_ids[i] (an lxx_morph.id for lxx, an alignments.id
    for mt) at sub-index target_subs[i]. lxx words are already 1:1 with their
    id, so sub is always 0. An mt row split into several Hebrew morphemes keeps
    the same id but a distinct sub per morpheme, so links to the same row stay
    individually addressable.
    """
    tokens: list[str] = []
    target_ids: list[int] = []
    target_subs: list[int] = []
    if pivot == "lxx":
        for wid, surf in catss.execute(
            "SELECT id, surface_unicode FROM lxx_morph "
            "WHERE verse_id=? ORDER BY position", (verse_id,)
        ):
            # Collapse any internal whitespace so each lxx token stays a single
            # space-delimited unit in the eflomal target line — keeps the 1:1
            # token<->target_id invariant the link decoder relies on (no-op for
            # real LXX surfaces, which are single words; defensive guard only).
            surf = "".join((surf or "").split())
            if surf:
                tokens.append(surf)
                target_ids.append(wid)
                target_subs.append(0)
    else:  # mt
        for aid, mt in catss.execute(
            "SELECT id, mt_unicode FROM alignments "
            "WHERE verse_id=? AND mt_unicode IS NOT NULL ORDER BY row_order",
            (verse_id,)
        ):
            for sub, tok in enumerate(_split_hebrew(mt or "")):
                tokens.append(tok)
                target_ids.append(aid)
                target_subs.append(sub)
    return tokens, target_ids, target_subs


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
        # Build the two latin lists in lockstep, collapsing any internal/edge
        # whitespace in a norm and DROPPING degenerate empty norms from BOTH —
        # otherwise " ".join(latin_norms) would yield a different token count
        # than len(latin_ids), and eflomal's indices would attach links to the
        # wrong Latin word. Real norms (from tokenize_latin) are single
        # non-empty tokens, so this is a no-op guard on current data.
        latin_ids: list[int] = []
        latin_norms: list[str] = []
        for wid, norm in words:
            tok = "".join((norm or "").split())
            if not tok:
                continue
            latin_ids.append(wid)
            latin_norms.append(tok)
        if not latin_ids:
            continue
        toks, tgt_ids, tgt_subs = _pivot_tokens(catss, pivot, catss_verse_id)
        if not toks:
            continue
        yield latin_ids, latin_norms, tgt_ids, tgt_subs, toks


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


def _gdf(fwd: list[tuple[int, int]], rev: list[tuple[int, int]],
         n_src: int, n_trg: int) -> dict[tuple[int, int], str]:
    """grow-diag-final symmetrization. Returns {(i,j): 'intersection'|'grown'}.

    Start from the intersection (high precision), grow into diagonal/adjacent
    union neighbours, then a FINAL pass adds any remaining union point with at
    least ONE free endpoint. (The stricter '-and' variant — both endpoints
    free — drops a union link whenever its counterpart position is already
    taken, costing real recall; we use the standard OR final.)
    """
    # Filter to in-bounds links up front so EVERY downstream set (intersection
    # seed, union, and the final pass) is guaranteed valid as a list index into
    # latin_ids / tgt_ids — a malformed or out-of-range eflomal link is dropped
    # rather than crashing align() or negative-indexing the wrong token. Real
    # eflomal output is always in range, so this is a no-op guard on live data.
    def _ok(p):
        i, j = p
        return 0 <= i < n_src and 0 <= j < n_trg
    e2f = {p for p in fwd if _ok(p)}
    f2e = {p for p in rev if _ok(p)}
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
        if (i, j) not in align and (i not in aligned_src or j not in aligned_trg):
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
    # Drop-and-recreate so a schema change (e.g. a new column) always takes
    # effect on a re-run; this table is owned entirely by this step.
    pack.execute("DROP TABLE IF EXISTS vulgate_align")
    pack.executescript(ALIGN_SCHEMA)

    stats = {"by_pivot": {}, "links": 0, "intersection": 0, "grown": 0}

    for pivot in pivots:
        pairs = list(_gather_pairs(pack, catss, pivot))
        if not pairs:
            stats["by_pivot"][pivot] = {"verses": 0, "links": 0}
            continue
        src_lines = [" ".join(p[1]) for p in pairs]   # latin norms
        trg_lines = [" ".join(p[4]) for p in pairs]   # pivot tokens
        print(f"  eflomal[{pivot}]: {len(pairs):,} verse pairs ...",
              file=sys.stderr)
        fwd, rev = _run_eflomal(src_lines, trg_lines)

        kind = "lxx_word" if pivot == "lxx" else "mt_row"
        plinks = 0
        for line_i, (latin_ids, latin_norms, tgt_ids, tgt_subs, toks) in enumerate(pairs):
            links = _gdf(fwd[line_i], rev[line_i], len(latin_ids), len(toks))
            for (i, j), cat in links.items():
                conf = 1.0 if cat == "intersection" else 0.5
                pack.execute(
                    "INSERT INTO vulgate_align "
                    "(vulgate_word_id, target_kind, target_id, target_sub, "
                    " pivot, method, confidence) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(vulgate_word_id, target_kind, target_id, target_sub) "
                    "DO UPDATE SET confidence=MAX(confidence, excluded.confidence)",
                    (latin_ids[i], kind, tgt_ids[j], tgt_subs[j],
                     pivot, "eflomal-gdf", conf),
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
