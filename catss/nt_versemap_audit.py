"""
Propose NT Latin <-> Greek verse units from the text itself, and audit the
curated map (catss/data/nt_units.tsv) against that proposal.

Verse numbers are not a safe join between the Clementine and SBLGNT: Mark 9,
John 6:51-72, Acts 7 and 14 and others carry different words under the same
number. So a monotone dynamic-programming verse aligner (Gale-Church style,
units 1:0, 0:1, 1:1, 2:1, 1:2, 2:2, 3:1, 1:3) scores candidate units with IBM
Model 1 lexical tables trained in both directions on the same-numbered verse
pairs. Tokens are folded Latin stems (first five letters) and accent-stripped
SBLGNT lemmas; that is coarse, but it only has to tell neighbouring verses
apart.

The proposal is evidence for a human, not the map: the curated file is
reviewed by hand, and `disagreements` reports every Latin verse whose unit
differs between the two, so a shift nobody reviewed cannot slip through.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

import numpy as np

NULL = "<null>"
FLOOR = 1e-6          # probability of a pair never seen in training
NULL_COST = -9.0      # per token left without any counterpart (a 1:0 / 0:1 unit)
MOVE_PENALTY = -2.0   # per unit that is not 1:1
MOVES = [(1, 1), (1, 0), (0, 1), (2, 1), (1, 2), (2, 2), (3, 1), (1, 3)]


def fold_greek(s: str) -> str:
    d = unicodedata.normalize("NFD", s.lower())
    d = "".join(c for c in d if not unicodedata.combining(c))
    return d.replace("ς", "σ")


_LATIN_FOLD = str.maketrans({"æ": "ae", "œ": "oe", "ë": "e", "j": "i", "v": "u"})


def fold_latin(s: str) -> str:
    letters = re.sub(r"[^a-z]", "", s.lower().translate(_LATIN_FOLD))
    return letters[:5]


class Ibm1:
    """t(src | trg) with a NULL target, dense over the training vocabularies."""

    def __init__(self, src_vocab: dict[str, int], trg_vocab: dict[str, int], table: np.ndarray):
        self.src_vocab = src_vocab
        self.trg_vocab = trg_vocab
        self.table = table          # [src, trg]; last trg column is NULL

    @classmethod
    def train(cls, src: list[list[str]], trg: list[list[str]], iterations: int = 6) -> "Ibm1":
        sv: dict[str, int] = {}
        tv: dict[str, int] = {}
        s_ids = [np.array([sv.setdefault(w, len(sv)) for w in s], dtype=np.int64) for s in src]
        t_ids = [np.array([tv.setdefault(w, len(tv)) for w in t], dtype=np.int64) for t in trg]
        null = tv.setdefault(NULL, len(tv))
        t_ids = [np.append(t, null) for t in t_ids]
        table = np.full((len(sv), len(tv)), 1.0 / len(sv), dtype=np.float32)
        for _ in range(iterations):
            counts = np.zeros_like(table)
            for s, t in zip(s_ids, t_ids):
                if not len(s):
                    continue
                sub = table[np.ix_(s, t)]
                post = sub / sub.sum(axis=1, keepdims=True)
                np.add.at(counts, (s[:, None], t[None, :]), post)
            totals = counts.sum(axis=0, keepdims=True)
            totals[totals == 0] = 1.0
            table = counts / totals
        return cls(sv, tv, table)

    def prob(self, s: str, t: str) -> float:
        si, ti = self.src_vocab.get(s), self.trg_vocab.get(t)
        if si is None or ti is None:
            return FLOOR
        return max(float(self.table[si, ti]), FLOOR)

    def ids(self, words: list[str], side: str) -> np.ndarray:
        """Vocabulary ids; a word unseen in training maps to the FLOOR row/column."""
        vocab, unk = (self.src_vocab, len(self.src_vocab)) if side == "src" else (self.trg_vocab, len(self.trg_vocab))
        return np.array([vocab.get(w, unk) for w in words], dtype=np.int64)

    @property
    def padded(self) -> np.ndarray:
        """The table with one more row and column of FLOOR for unseen words."""
        if getattr(self, "_padded", None) is None:
            s, t = self.table.shape
            pad = np.full((s + 1, t + 1), FLOOR, dtype=np.float32)
            pad[:s, :t] = np.maximum(self.table, FLOOR)
            self._padded = pad
        return self._padded

    def sums(self, src_ids: np.ndarray, trg_ids: np.ndarray) -> np.ndarray:
        """For each src token, the sum over trg tokens of t(src|trg) (NULL excluded)."""
        return self.padded[np.ix_(src_ids, trg_ids)].sum(axis=1, dtype=np.float64)


@dataclass
class Pair:
    fwd: Ibm1   # t(latin | greek)
    bwd: Ibm1   # t(greek | latin)

    @classmethod
    def train(cls, lat: list[list[str]], grk: list[list[str]], iterations: int = 6) -> "Pair":
        return cls(Ibm1.train(lat, grk, iterations), Ibm1.train(grk, lat, iterations))

    def score(self, lat: list[str], grk: list[str]) -> float:
        """Log-likelihood of a unit, both directions; an empty side costs NULL_COST per token."""
        return _Scorer(self, [lat], [grk]).unit((0,), (0,)) if lat and grk             else NULL_COST * (len(lat) + len(grk))


class _Scorer:
    """Unit scores for one book, built from cached per-verse-pair sums.

    NULL helps training absorb function words, but it is left out of the score:
    a word with no counterpart in the unit must cost more than leaving its verse
    unaligned, or a 1:0 unit could never win.
    """

    def __init__(self, pair: Pair, lat: list[list[str]], grk: list[list[str]]):
        self.pair = pair
        self.lf = [pair.fwd.ids(v, "src") for v in lat]   # Latin as fwd source
        self.gf = [pair.fwd.ids(v, "trg") for v in grk]
        self.gb = [pair.bwd.ids(v, "src") for v in grk]   # Greek as bwd source
        self.lb = [pair.bwd.ids(v, "trg") for v in lat]
        self.f: dict[tuple[int, int], np.ndarray] = {}
        self.b: dict[tuple[int, int], np.ndarray] = {}

    def _f(self, i, j):
        if (i, j) not in self.f:
            self.f[(i, j)] = self.pair.fwd.sums(self.lf[i], self.gf[j])
        return self.f[(i, j)]

    def _b(self, i, j):
        if (i, j) not in self.b:
            self.b[(i, j)] = self.pair.bwd.sums(self.gb[j], self.lb[i])
        return self.b[(i, j)]

    def unit(self, li: tuple[int, ...], gj: tuple[int, ...]) -> float:
        nl = sum(len(self.lf[i]) for i in li)
        ng = sum(len(self.gf[j]) for j in gj)
        if not nl or not ng:
            return NULL_COST * (nl + ng)
        total = 0.0
        for i in li:
            if len(self.lf[i]):
                v = sum(self._f(i, j) for j in gj) / ng
                total += float(np.log(np.maximum(v, FLOOR)).sum())
        for j in gj:
            if len(self.gb[j]):
                v = sum(self._b(i, j) for i in li) / nl
                total += float(np.log(np.maximum(v, FLOOR)).sum())
        return total


def propose(lat: list[list[str]], grk: list[list[str]], pair: Pair,
            band: int | None = None) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    """Best monotone segmentation of one book into units of verse indexes."""
    n, m = len(lat), len(grk)
    if band is None:
        band = abs(n - m) + 12
    scorer = _Scorer(pair, lat, grk)

    best: dict[tuple[int, int], float] = {(0, 0): 0.0}
    back: dict[tuple[int, int], tuple[int, int]] = {}
    for i in range(n + 1):
        centre = i * m / n if n else 0
        for j in range(max(0, int(centre - band)), min(m, int(centre + band) + 1) + 1):
            if (i, j) == (0, 0):
                continue
            top = -math.inf
            arg = None
            for a, b in MOVES:
                pi, pj = i - a, j - b
                prev = best.get((pi, pj))
                if prev is None:
                    continue
                s = prev + scorer.unit(tuple(range(pi, i)), tuple(range(pj, j)))                     + (0.0 if (a, b) == (1, 1) else MOVE_PENALTY)
                if s > top:
                    top, arg = s, (a, b)
            if arg is not None:
                best[(i, j)] = top
                back[(i, j)] = arg
    if (n, m) not in best:
        raise ValueError(f"verse aligner found no path through a {n}x{m} book (band {band})")
    out = []
    i, j = n, m
    while (i, j) != (0, 0):
        a, b = back[(i, j)]
        out.append((tuple(range(i - a, i)), tuple(range(j - b, j))))
        i, j = i - a, j - b
    return out[::-1]


def disagreements(curated, proposed, latin, greek):
    """Latin verses whose Greek set differs between the curated units and the
    proposal: [(latin_ref, curated_greek, proposed_greek)] in Latin order."""
    cur = {}
    for u in curated:
        for r in u.latin:
            cur[r] = list(u.greek)
    prop = {}
    for li, gi in proposed:
        g = [greek[j] for j in gi]
        for i in li:
            prop[latin[i]] = g
    return [(r, cur.get(r, []), prop.get(r, [])) for r in latin if cur.get(r, []) != prop.get(r, [])]


def load_greek(interlinear) -> dict[int, list[tuple[int, int, list[str]]]]:
    """SBLGNT verses of the interlinear pack per book: [(chapter, verse, folded lemmas)]."""
    import sqlite3
    conn = sqlite3.connect(f"file:{interlinear}?mode=ro", uri=True)
    try:
        out: dict[int, list] = {}
        cur = None
        for b, ch, v, lemma in conn.execute(
                "SELECT book_id, chapter, verse, lemma FROM interlinear_words "
                "WHERE source='SBLGNT' ORDER BY book_id, chapter, verse, word_position"):
            if cur is None or cur[:3] != (b, ch, v):
                cur = (b, ch, v, [])
                out.setdefault(b, []).append((ch, v, cur[3]))
            if lemma:
                cur[3].append(fold_greek(lemma))
        return out
    finally:
        conn.close()


def run(vul_tsv, interlinear, units_tsv=None, iterations: int = 6):
    """Train on same-numbered pairs, propose units for every book, and return
    (proposals per book, disagreements per book against the curated file)."""
    from . import parse_vulgate
    from . import vulgate_nt as vn

    latin = vn.parse_nt(vul_tsv)
    lat_by_book: dict[int, list[tuple[int, int, list[str]]]] = {}
    for lv in latin:
        toks = [fold_latin(norm) for _s, norm in parse_vulgate.tokenize_latin(lv.text)]
        lat_by_book.setdefault(lv.book_id, []).append((lv.chapter, lv.verse, [t for t in toks if t]))
    grk_by_book = load_greek(interlinear)

    train_l, train_g = [], []
    for b, lverses in lat_by_book.items():
        g = {(ch, v): toks for ch, v, toks in grk_by_book.get(b, [])}
        for ch, v, toks in lverses:
            if (ch, v) in g:
                train_l.append(toks)
                train_g.append(g[(ch, v)])
    pair = Pair.train(train_l, train_g, iterations)

    rows = vn.load_unit_rows(units_tsv) if units_tsv else {}
    proposals, disagree = {}, {}
    for b in sorted(lat_by_book):
        lv, gv = lat_by_book[b], grk_by_book.get(b, [])
        lrefs = [(ch, v) for ch, v, _ in lv]
        grefs = [(ch, v) for ch, v, _ in gv]
        prop = propose([t for *_, t in lv], [t for *_, t in gv], pair)
        proposals[b] = [([lrefs[i] for i in li], [grefs[j] for j in gj]) for li, gj in prop]
        if units_tsv is not None:
            curated = vn.resolve_units(lrefs, grefs, rows.get(b, []))
            disagree[b] = disagreements(curated, prop, lrefs, grefs)
    return proposals, disagree


def main(argv=None) -> int:
    import argparse
    import pathlib
    import sys

    ap = argparse.ArgumentParser(description="Propose NT Latin/Greek verse units and audit nt_units.tsv.")
    ap.add_argument("--vul", type=pathlib.Path, default=pathlib.Path("raw/vulgate/vul.tsv"))
    ap.add_argument("--interlinear", type=pathlib.Path, required=True)
    ap.add_argument("--units", type=pathlib.Path, help="curated nt_units.tsv to audit")
    ap.add_argument("--draft", action="store_true", help="print every non-identity proposal as TSV")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    proposals, disagree = run(args.vul, args.interlinear, args.units)
    if args.draft:
        for b, units in proposals.items():
            for lat, grk in units:
                if len(lat) == 1 and grk == lat:
                    continue
                fmt = lambda rs: ",".join(f"{c}:{v}" for c, v in rs)
                print(f"{b}\t{fmt(lat)}\t{fmt(grk)}\t\t")
    total = sum(len(d) for d in disagree.values())
    for b, d in disagree.items():
        for r, cur, prop in d:
            fmt = lambda rs: ",".join(f"{c}:{v}" for c, v in rs) or "-"
            print(f"DISAGREE {b} {r[0]}:{r[1]} curated={fmt(cur)} proposed={fmt(prop)}", file=sys.stderr)
    if args.units is not None:
        print(f"{total} Latin verse(s) where the curated map and the verse aligner disagree", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
