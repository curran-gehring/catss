"""
Score nt_align against hand-checked gold links (tests/fixtures/nt_gold.tsv).

  precision  shipped links on gold words that hit a required or acceptable
             Greek word (per tier and overall)
  recall     required gold links that were shipped
  coverage   gold words with at least one link; and, over the whole pack,
             non-latin_only Latin words with at least one link
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys


def _refs(col: str) -> set[tuple[int, int, int]]:
    if col.strip() in ("", "-"):
        return set()
    return {tuple(int(x) for x in r.split(":")) for r in col.split(",")}


def evaluate(pack: pathlib.Path, gold: pathlib.Path) -> dict:
    conn = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
    try:
        tiers: dict[str, dict[str, int]] = {}
        required_total = required_hit = words = linked_words = 0
        with open(gold, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.rstrip("\r\n")
                if not line.strip() or line.startswith("#"):
                    continue
                book, ref, pos, surface, req, acc = line.split("\t")
                ch, v = (int(x) for x in ref.split(":"))
                row = conn.execute(
                    "SELECT w.id, w.surface FROM vulgate_words w JOIN nt_verse_map vm ON vm.id = w.verse_map_id"
                    " WHERE vm.book_id = ? AND vm.vul_chapter = ? AND vm.vul_verse = ? AND w.position = ?",
                    (int(book), ch, v, int(pos))).fetchone()
                if row is None or row[1] != surface:
                    raise ValueError(f"{gold}: line {n}: gold word {surface!r} is {row[1] if row else 'missing'!r} in the pack")
                required, acceptable = _refs(req), _refs(acc)
                links = conn.execute("SELECT chapter, verse, word_position, confidence FROM nt_align"
                                     " WHERE vulgate_word_id = ?", (row[0],)).fetchall()
                words += 1
                linked_words += bool(links)
                required_total += len(required)
                got = {(c, vv, p) for c, vv, p, _ in links}
                required_hit += len(required & got)
                for c, vv, p, conf in links:
                    t = tiers.setdefault("1.0" if conf >= 1.0 else "0.5", {"links": 0, "correct": 0})
                    t["links"] += 1
                    t["correct"] += (c, vv, p) in required | acceptable
        total = sum(t["links"] for t in tiers.values())
        correct = sum(t["correct"] for t in tiers.values())
        corpus_words, corpus_linked = conn.execute(
            "SELECT COUNT(*), SUM(EXISTS (SELECT 1 FROM nt_align a WHERE a.vulgate_word_id = w.id))"
            " FROM vulgate_words w WHERE w.latin_only = 0").fetchone()
        return {
            "tiers": tiers, "links": total, "precision": correct / total if total else 0.0,
            "recall": required_hit / required_total if required_total else 0.0,
            "sample_words": words, "sample_coverage": linked_words / words if words else 0.0,
            "corpus": {"words": corpus_words, "linked": corpus_linked or 0},
        }
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score nt_align against the hand-checked gold links.")
    ap.add_argument("--pack", type=pathlib.Path, default=pathlib.Path("vulgate_nt.sqlite"))
    ap.add_argument("--gold", type=pathlib.Path,
                    default=pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "nt_gold.tsv")
    args = ap.parse_args(argv)
    r = evaluate(args.pack, args.gold)
    for k, t in sorted(r["tiers"].items(), reverse=True):
        print(f"  confidence {k}: {t['correct']}/{t['links']} correct ({t['correct'] / t['links']:.1%})")
    print(f"precision {r['precision']:.1%} over {r['links']} links; recall {r['recall']:.1%}; "
          f"sample coverage {r['sample_coverage']:.1%} of {r['sample_words']} words")
    c = r["corpus"]
    print(f"corpus coverage {c['linked']:,}/{c['words']:,} ({c['linked'] / max(c['words'], 1):.1%}) linkable Latin words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
