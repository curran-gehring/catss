"""
Word-align the NT Latin pack to the SBLGNT with eflomal and write nt_align.
**Runs on the mac-mini** (eflomal won't build on Windows), after
lemmatize_vulgate has filled vulgate_words.lemma.

Method (docs/nt-latin-design.md, decision 4):
  * Lemma-to-lemma: Latin LatinCy lemmas (folded norm when LatinCy gave none)
    against accent-stripped SBLGNT lemmas. Both languages inflect heavily and
    the NT is only ~8k verse pairs, so surface forms would be too sparse.
  * One line per alignment unit (several verses when the traditions split
    them differently); latin_only words never enter the corpus.
  * Extra training lines: the OT books Jerome translated from the Greek (the
    OT pack's lxx pivot), Latin lemmas against catss_morph LXX lemmas. Their
    links are thrown away.
  * Symmetrize with grow-diag-final (align_vulgate._gdf), then precision tiers:
      1.0  forward and reverse agree (intersection)
      0.5  grown link whose (Latin lemma, Greek lemma) pair is an intersection
           link at least `min_support` times in the whole corpus
      --   every other grown link is dropped

  nt_align
    id              INTEGER PRIMARY KEY
    vulgate_word_id INTEGER NOT NULL REFERENCES vulgate_words(id)
    book_id, chapter, verse, word_position  -- the SBLGNT word (stable label;
                                            -- positions have gaps)
    greek_surface   TEXT NOT NULL  -- interlinear surface_text, to detect drift
    confidence      REAL NOT NULL
    method          TEXT NOT NULL
    UNIQUE(vulgate_word_id, book_id, chapter, verse, word_position)

Unit verses then move their home (the ESV verse they are shown under) to the
Greek verse holding most of their links.
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

from . import align_vulgate
from .nt_versemap_audit import fold_greek

METHOD = "eflomal-gdf-lemma"

ALIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS nt_align (
    id              INTEGER PRIMARY KEY,
    vulgate_word_id INTEGER NOT NULL REFERENCES vulgate_words(id),
    book_id         INTEGER NOT NULL,
    chapter         INTEGER NOT NULL,
    verse           INTEGER NOT NULL,
    word_position   INTEGER NOT NULL,
    greek_surface   TEXT NOT NULL,
    confidence      REAL NOT NULL,
    method          TEXT NOT NULL,
    UNIQUE (vulgate_word_id, book_id, chapter, verse, word_position)
);
CREATE INDEX IF NOT EXISTS idx_nta_word ON nt_align(vulgate_word_id);
CREATE INDEX IF NOT EXISTS idx_nta_greek ON nt_align(book_id, chapter, verse, word_position);
"""


def fold_latin(s: str) -> str:
    return "".join(s.lower().split()).replace("j", "i").replace("v", "u")


@dataclass
class UnitText:
    unit_id: int
    latin_word_ids: list[int]
    latin_vm_ids: list[int]
    latin_tokens: list[str]
    greek_refs: list[tuple[int, int, int, int, str]]
    greek_tokens: list[str]


@dataclass
class Line:
    lat: list[str]
    grk: list[str]
    links: dict[tuple[int, int], str] = field(default_factory=dict)


def unit_corpus(pack: pathlib.Path, interlinear: pathlib.Path) -> Iterator[UnitText]:
    """Every unit with Greek verses, as parallel token lists."""
    conn = sqlite3.connect(pack)
    il = sqlite3.connect(f"file:{interlinear}?mode=ro", uri=True)
    try:
        greek_of: dict[int, list[tuple[int, int, int]]] = {}
        for uid, bk, ch, v in conn.execute(
                "SELECT unit_id, book_id, chapter, verse FROM nt_unit_greek ORDER BY unit_id, chapter, verse"):
            greek_of.setdefault(uid, []).append((bk, ch, v))
        words: dict[int, list[tuple[int, int, str]]] = {}
        for uid, vm, wid, lemma, norm in conn.execute(
                "SELECT vm.unit_id, vm.id, w.id, w.lemma, w.norm FROM vulgate_words w"
                " JOIN nt_verse_map vm ON vm.id = w.verse_map_id"
                " WHERE w.latin_only = 0 ORDER BY vm.id, w.position"):
            words.setdefault(uid, []).append((vm, wid, fold_latin(lemma or norm)))
        for uid in sorted(greek_of):
            lw = words.get(uid, [])
            refs, toks = [], []
            for bk, ch, v in greek_of[uid]:
                for pos, surface, lemma in il.execute(
                        "SELECT word_position, surface_text, lemma FROM interlinear_words"
                        " WHERE source='SBLGNT' AND book_id=? AND chapter=? AND verse=?"
                        " ORDER BY word_position", (bk, ch, v)):
                    refs.append((bk, ch, v, pos, surface))
                    toks.append(fold_greek(lemma or surface))
            yield UnitText(uid, [w for _, w, _ in lw], [vm for vm, _, _ in lw], [t for *_, t in lw], refs, toks)
    finally:
        conn.close()
        il.close()


def ot_corpus(ot_pack: pathlib.Path, catss_morph: pathlib.Path) -> Iterator[Line]:
    """Training-only lines: Latin lemmas of the OT pack's lxx-pivot verses
    against the LXX lemmas of the same CATSS verse (ids match the shipped packs)."""
    ot = sqlite3.connect(f"file:{ot_pack}?mode=ro", uri=True)
    mo = sqlite3.connect(f"file:{catss_morph}?mode=ro", uri=True)
    try:
        greek: dict[int, list[str]] = {}
        for vid, lemma, surface in mo.execute(
                "SELECT verse_id, lemma_unicode, surface_unicode FROM lxx_morph ORDER BY verse_id, position"):
            tok = fold_greek(lemma or surface or "")
            if tok:
                greek.setdefault(vid, []).append(tok)
        cur_vid, lat = None, []
        for vid, lemma, norm in ot.execute(
                "SELECT vvm.catss_verse_id, w.lemma, w.norm FROM vulgate_words w"
                " JOIN vulgate_verse_map vvm ON vvm.id = w.verse_map_id"
                " WHERE vvm.pivot = 'lxx' AND vvm.catss_verse_id IS NOT NULL ORDER BY vvm.id, w.position"):
            if vid != cur_vid:
                if lat and greek.get(cur_vid):
                    yield Line(lat, greek[cur_vid])
                cur_vid, lat = vid, []
            lat.append(fold_latin(lemma or norm))
        if lat and greek.get(cur_vid):
            yield Line(lat, greek[cur_vid])
    finally:
        ot.close()
        mo.close()


def tier(lines: list[Line], min_support: int = 3) -> list[dict[tuple[int, int], float]]:
    support: Counter = Counter()
    for ln in lines:
        for (i, j), cat in ln.links.items():
            if cat == "intersection":
                support[(ln.lat[i], ln.grk[j])] += 1
    out = []
    for ln in lines:
        kept = {}
        for (i, j), cat in ln.links.items():
            if cat == "intersection":
                kept[(i, j)] = 1.0
            elif support[(ln.lat[i], ln.grk[j])] >= min_support:
                kept[(i, j)] = 0.5
        out.append(kept)
    return out


def refine_homes(homes: dict[int, tuple[int, int]], links: dict[int, list[tuple[int, int]]]):
    """Each verse's home becomes the Greek verse most of its links land in
    (ties: the earlier verse); a verse with no links keeps its home."""
    out = {}
    for vm, home in homes.items():
        counts = Counter(links.get(vm, []))
        if not counts:
            out[vm] = home
            continue
        top = max(counts.values())
        out[vm] = min(r for r, n in counts.items() if n == top)
    return out


def verify(pack: pathlib.Path, interlinear: pathlib.Path) -> dict:
    """Resolve every nt_align link against an interlinear pack."""
    conn = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
    conn.execute("ATTACH DATABASE ? AS il", (f"file:{interlinear}?mode=ro",))
    try:
        links, resolved, mismatched, dangling = conn.execute(
            "SELECT COUNT(*),"
            " SUM(iw.surface_text IS NOT NULL AND iw.surface_text = a.greek_surface),"
            " SUM(iw.surface_text IS NOT NULL AND iw.surface_text <> a.greek_surface),"
            " SUM(iw.surface_text IS NULL)"
            " FROM nt_align a LEFT JOIN il.interlinear_words iw"
            "   ON iw.source = 'SBLGNT' AND iw.book_id = a.book_id AND iw.chapter = a.chapter"
            "  AND iw.verse = a.verse AND iw.word_position = a.word_position").fetchone()
        lo = conn.execute("SELECT COUNT(*) FROM nt_align a JOIN vulgate_words w ON w.id = a.vulgate_word_id"
                          " WHERE w.latin_only = 1").fetchone()[0]
        return {"links": links, "resolved": resolved or 0, "dangling": dangling or 0,
                "mismatched": mismatched or 0, "latin_only_linked": lo}
    finally:
        conn.close()


def align(pack: pathlib.Path, interlinear: pathlib.Path, ot_pack: pathlib.Path | None = None,
          catss_morph: pathlib.Path | None = None, min_support: int = 3,
          run_eflomal=align_vulgate._run_eflomal) -> dict:
    units = [u for u in unit_corpus(pack, interlinear) if u.latin_tokens and u.greek_tokens]
    lines = [Line(u.latin_tokens, u.greek_tokens) for u in units]
    extra = list(ot_corpus(ot_pack, catss_morph)) if ot_pack and catss_morph else []
    corpus = lines + extra
    print(f"  eflomal: {len(lines):,} NT units + {len(extra):,} OT training lines", file=sys.stderr)
    fwd, rev = run_eflomal([" ".join(l.lat) for l in corpus], [" ".join(l.grk) for l in corpus])
    for k, ln in enumerate(corpus):
        ln.links = align_vulgate._gdf(fwd[k], rev[k], len(ln.lat), len(ln.grk))
    tiers = tier(corpus, min_support)

    conn = sqlite3.connect(pack)
    conn.execute("DROP TABLE IF EXISTS nt_align")
    conn.executescript(ALIGN_SCHEMA)
    stats = {"units": len(units), "ot_lines": len(extra), "links": 0, "conf_1": 0, "conf_05": 0,
             "dropped_grown": 0}
    verse_links: dict[int, list[tuple[int, int]]] = {}
    for u, ln, kept in zip(units, lines, tiers):
        stats["dropped_grown"] += len(ln.links) - len(kept)
        for (i, j), conf in kept.items():
            bk, ch, v, pos, surface = u.greek_refs[j]
            conn.execute("INSERT INTO nt_align (vulgate_word_id, book_id, chapter, verse, word_position,"
                         " greek_surface, confidence, method) VALUES (?,?,?,?,?,?,?,?)",
                         (u.latin_word_ids[i], bk, ch, v, pos, surface, conf, METHOD))
            verse_links.setdefault(u.latin_vm_ids[i], []).append((ch, v))
            stats["links"] += 1
            stats["conf_1" if conf == 1.0 else "conf_05"] += 1
    homes = {vm: (ch, v) for vm, ch, v in conn.execute(
        "SELECT id, chapter, verse FROM nt_verse_map WHERE status = 'unit'")}
    moved = 0
    for vm, (ch, v) in refine_homes(homes, verse_links).items():
        if (ch, v) != homes[vm]:
            moved += 1
            conn.execute("UPDATE nt_verse_map SET chapter=?, verse=? WHERE id=?", (ch, v, vm))
    stats["homes_moved"] = moved
    conn.commit()
    conn.close()
    stats["verify"] = verify(pack, interlinear)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="eflomal-align the NT Latin pack to the SBLGNT.")
    ap.add_argument("--pack", type=pathlib.Path, default=pathlib.Path("vulgate_nt.sqlite"))
    ap.add_argument("--interlinear", type=pathlib.Path, required=True)
    ap.add_argument("--ot-pack", type=pathlib.Path, help="shipped vulgate.sqlite (extra training lines)")
    ap.add_argument("--catss-morph", type=pathlib.Path, help="shipped catss_morph.sqlite")
    ap.add_argument("--min-support", type=int, default=3)
    args = ap.parse_args(argv)
    stats = align(args.pack, args.interlinear, args.ot_pack, args.catss_morph, args.min_support)
    print(f"nt_align: {stats['links']:,} links (1.0={stats['conf_1']:,} 0.5={stats['conf_05']:,}; "
          f"{stats['dropped_grown']:,} unsupported grown links dropped); {stats['homes_moved']} homes moved",
          file=sys.stderr)
    v = stats["verify"]
    print(f"verify: {v}", file=sys.stderr)
    bad = v["dangling"] or v["mismatched"] or v["latin_only_linked"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
