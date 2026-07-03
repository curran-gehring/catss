"""
Populate `lemma_glosses` in vulgate.sqlite: LatinCy lemma -> short English
gloss, derived from Whitaker's WORDS dictionary (DICTLINE.GEN, public domain).

DICTLINE is a fixed-width stem file, not a headword list: cols 0-75 hold up
to four principal-part stems, col 76+ holds POS + inflection codes + flags,
and the gloss text starts after the five flag letters (e.g. "X X X A O").
The 4th flag is Whitaker's FREQUENCY code (A most common .. F least, plus
specials) — used to rank competing entries.

Headwords are reconstructed per POS and matched against our lemmas after
LatinCy's orthographic fold (v->u, j->i, lowercase):

    V    stem1+"o" (deponent: +"or"; esse-compounds ship stem1 as-is too)
    N    decl 1: +"a"; decl 2: +"us"/+"um"/bare (var-dependent, so try all);
         decl 3+: stem1 IS the nominative ("rex", "verbero", "dominatio")
    ADJ  +"us" / +"is" / bare  (magnus, fortis, pauper)
    else stem1 as-is (ADV, PREP, CONJ, PRON, NUM, INTERJ)

Rather than encode every declension variant, each entry emits ALL plausible
candidates; a candidate index maps candidate -> best entry (POS-priority,
then frequency, then dictionary order). Our lemma then needs exactly one
lookup, disambiguated by the lemma's majority UPOS in vulgate_words.

Continuation senses (gloss beginning with '|') extend the PREVIOUS entry and
are skipped — we want the primary sense only. Glosses are trimmed to their
first two ';'-separated senses for the word-card line.

Usage:
    python -m catss.gloss_vulgate --db vulgate.sqlite --dictline DICTLINE.GEN
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

# UPOS (LatinCy) -> acceptable Whitaker POS classes, in preference order.
UPOS_TO_POS = {
    "VERB": ("V", "VPAR"),
    "AUX": ("V",),
    "NOUN": ("N",),
    "PROPN": ("N",),
    "ADJ": ("ADJ", "NUM", "VPAR"),
    "ADV": ("ADV",),
    "ADP": ("PREP",),
    "CCONJ": ("CONJ",),
    "SCONJ": ("CONJ",),
    "PRON": ("PRON", "ADJ"),
    "DET": ("PRON", "ADJ"),
    "NUM": ("NUM", "ADJ"),
    "INTJ": ("INTERJ",),
    "PART": ("ADV", "CONJ"),
}
FREQ_RANK = {c: i for i, c in enumerate("ABCDEFINX")}   # A best


def _fold(s: str) -> str:
    return s.lower().replace("v", "u").replace("j", "i")


def _candidates(stem1: str, pos: str, codes: str) -> list[tuple[str, bool]]:
    """(candidate_headword, primary) pairs for one DICTLINE entry.

    `primary` marks the reconstruction the entry's OWN declension/conjugation
    codes predict; the rest are speculative fallbacks. Primary hits outrank
    fallbacks at lookup, so filius's incidental "fili+a" can't shadow the
    real filia entry (whose decl-1 code makes "filia" primary).
    """
    if pos == "V":
        # DICTLINE 2nd-conjugation stems drop the theme vowel ("hab habu
        # habit V 2 1" -> habeo) and conj 5 marks esse-compounds whose
        # stem is the prefix ("abs ab abfu abfut V 5 1" -> absum). No bare
        # stem1 candidate: it collides -sumo verbs onto -sum lemmas
        # (Whitaker's desumo has stem1 "desum", shadowing desum "be
        # lacking" -- caught glossing Ps 22:1 "deerit" as "choose").
        m = re.match(r"\s*V\s+(\d)", codes)
        conj = m.group(1) if m else ""
        if conj == "5":
            return [(stem1 + "um", True)]
        theme = "e" if conj == "2" else ""
        if " DEP" in codes:
            return [(stem1 + theme + "or", True)]
        return [(stem1 + theme + "o", True)]
    if pos == "N":
        m = re.match(r"\s*N\s+(\d)", codes)
        decl = m.group(1) if m else ""
        neuter = " N " in codes[6:]      # gender field after decl/var
        primary = {"1": stem1 + "a",
                   "2": stem1 + ("um" if neuter else "us"),
                   "3": stem1,
                   "4": stem1 + ("u" if neuter else "us"),
                   "5": stem1 + "es"}.get(decl, stem1)
        cands = [stem1, stem1 + "us", stem1 + "a", stem1 + "um", stem1 + "es",
                 stem1 + "u", stem1 + "ae", stem1 + "i"]  # +plural-only nouns
        return [(c, c == primary) for c in dict.fromkeys([primary] + cands)]
    if pos in ("ADJ", "NUM", "PRON"):
        return [(stem1 + "us", True)] + [
            (c, False) for c in (stem1 + "is", stem1, stem1 + "e", stem1 + "a")]
    return [(stem1, True)]


# Closed-class lemmas Whitaker encodes in PACK/special sections that the
# stem reconstruction can't reach, plus high-frequency ordinals. Curated by
# hand; these OVERRIDE any dictionary hit.
CLOSED_CLASS = {
    "is": "he/she/it; this, that; the one mentioned",
    "sui": "himself/herself/itself/themselves",
    "nos": "we; us",
    "uos": "you (plural)",
    "ego": "I; me",
    "tu": "you (singular)",
    "idem": "the same",
    "quid": "what; why",
    "quis": "who; anyone",
    "quisquam": "anyone, anything (at all)",
    "quidam": "a certain one/thing; someone",
    "quicumque": "whoever, whatever",
    "unusquisque": "each one, every single one",
    "uterque": "each of two, both",
    "aliquis": "someone, anyone; something",
    "duo": "two",
    "tres": "three",
    "ambo": "both (together)",
    "primus": "first; foremost, chief",
    "secundus": "second; following; favorable",
    "tertius": "third",
    "quartus": "fourth",
    "quintus": "fifth",
    "sextus": "sixth",
    "septimus": "seventh",
    "octauus": "eighth",
    "nonus": "ninth",
    "decimus": "tenth",
    "uigesimus": "twentieth",
    "ducenti": "two hundred",
    "trecenti": "three hundred",
    "quadringenti": "four hundred",
    "quingenti": "five hundred",
    "sescenti": "six hundred",
    "septingenti": "seven hundred",
    "octingenti": "eight hundred",
    "nongenti": "nine hundred",
    # irregular verbs outside the stem tables
    "possum": "be able, can",
    "inquam": "say (introducing direct quote)",
    "memini": "remember, recall",
    # remaining closed-class pronouns/determiners
    "quisquis": "whoever, whatever",
    "quispiam": "anyone, someone",
    "huiuscemodi": "of this kind",
    # LatinCy lemmatization artifacts: glosses keyed to what the
    # lemmatizer actually emits for these surfaces in the Vulgate
    "immaculo": "unstained, undefiled",     # <- immaculatus
    "uanito": "emptiness, futility, vanity",  # <- vanitas
    "dixit": "say, speak, tell",            # <- dico (perfect kept as lemma)
    # stem-collision fixes: the reconstruction matched the wrong headword
    # for these hyper-frequent words (sum<-sumo, uir<-virus, qui<-qui adv,
    # hic<-hic adv), caught by the top-frequency audit
    "sum": "be; exist",
    "eo": "go, walk; there",
    "qui": "who, which, that",
    "hic": "this; here",
    "uir": "man; husband",
    "tuus": "your, yours (singular)",
    # remaining high-frequency misses
    "assumo": "take up, receive, adopt",
    "gazophylacium": "treasury (of the temple)",
    "propior": "nearer, closer",
    "quisque": "each one, every",
    "semel": "once",
    "bis": "twice",
    "setim": "acacia (shittim) wood",
}


def parse_dictline(path: Path):
    """Yield (candidate_folded, pos, freq_rank, order, gloss)."""
    for order, raw in enumerate(path.read_text(encoding="latin-1").splitlines()):
        if len(raw) < 112:
            continue
        stems = raw[:76].split()
        body = raw[76:110]
        gloss = raw[110:].strip()
        if not stems or not gloss or gloss.startswith("|"):
            continue
        pos = body.split()[0] if body.split() else ""
        if pos not in ("V", "N", "ADJ", "ADV", "PREP", "CONJ", "PRON",
                       "NUM", "INTERJ", "VPAR", "PACK"):
            continue
        stem1 = stems[0]
        if stem1 in ("zzz", "-"):
            continue
        # frequency flag: 4th of the five single-letter flags before the gloss
        flags = raw[100:110].split()
        freq = FREQ_RANK.get(flags[3] if len(flags) >= 4 else "X", 8)
        # primary sense only, trimmed for the word card
        senses = [s.strip() for s in gloss.rstrip(";").split(";") if s.strip()]
        short = "; ".join(senses[:2])
        if len(short) > 60:
            short = senses[0][:60].rstrip(" ,")
        for cand, primary in _candidates(stem1, pos, body):
            yield _fold(cand), pos, freq, order, short, primary


def build_index(dictline: Path) -> dict[str, list[tuple]]:
    idx: dict[str, list[tuple]] = defaultdict(list)
    for cand, pos, freq, order, gloss, primary in parse_dictline(dictline):
        idx[cand].append((pos, freq, order, gloss, primary))
    for entries in idx.values():
        # decl/conj-correct reconstructions first, then freq, then file order
        entries.sort(key=lambda e: (not e[4], e[1], e[2]))
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--dictline", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    idx = build_index(args.dictline)
    print(f"dictionary candidates: {len(idx)}")

    db = sqlite3.connect(args.db)
    # majority UPOS + token count per lemma
    lemmas: dict[str, tuple[str, int]] = {}
    for lemma, upos_counts in _lemma_upos(db).items():
        upos = upos_counts.most_common(1)[0][0]
        lemmas[lemma] = (upos, sum(upos_counts.values()))
    print(f"distinct lemmas: {len(lemmas)}")

    rows, missed = [], []
    for lemma, (upos, ntok) in lemmas.items():
        if upos == "PROPN":
            continue                       # names gloss themselves
        if lemma in CLOSED_CLASS:
            rows.append((lemma, CLOSED_CLASS[lemma]))
            continue
        entries = idx.get(lemma)
        gloss = None
        if entries:
            prefs = UPOS_TO_POS.get(upos, ())
            for want in prefs:             # first acceptable POS wins
                hit = next((e for e in entries if e[0] == want), None)
                if hit:
                    gloss = hit[3]
                    break
            if gloss is None:              # POS mismatch: take best overall
                gloss = entries[0][3]
        if gloss:
            rows.append((lemma, gloss))
        else:
            missed.append((ntok, lemma, upos))

    covered_tok = sum(lemmas[l][1] for l, _ in rows)
    total_tok = sum(n for u, n in lemmas.values() if u != "PROPN")
    print(f"glossed {len(rows)}/{len([1 for u,_ in lemmas.values() if u != 'PROPN'])} "
          f"non-proper lemmas = {covered_tok}/{total_tok} tokens "
          f"({covered_tok/max(total_tok,1):.1%})")
    missed.sort(reverse=True)
    print("top 30 unglossed by token count:")
    for ntok, lemma, upos in missed[:30]:
        print(f"  {ntok:6}  {lemma}  ({upos})")

    if args.dry_run:
        return 0
    db.execute("CREATE TABLE IF NOT EXISTS lemma_glosses ("
               " lemma TEXT PRIMARY KEY, gloss TEXT NOT NULL)")
    db.execute("DELETE FROM lemma_glosses")
    db.executemany("INSERT INTO lemma_glosses VALUES (?,?)", rows)
    db.commit()
    db.close()
    print("lemma_glosses written")
    return 0


def _lemma_upos(db) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for lemma, morph in db.execute(
            "SELECT lemma, morph FROM vulgate_words WHERE lemma IS NOT NULL"):
        upos = (morph or "").split("|", 1)[0] or "X"
        out[lemma][upos] += 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
