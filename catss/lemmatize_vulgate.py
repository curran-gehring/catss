"""
Backfill vulgate_words.lemma and .morph with LatinCy. **Runs on the mac-mini**
(needs spaCy + the `la_core_web_lg` model).

We run the FULL native pipeline on cleaned verse text (our stored surfaces
joined by spaces), not a pre-tokenized Doc: LatinCy's normalizer (v->u, j->i)
runs during tokenization, and the lemmatizer needs that normalized form — a
pre-tokenized Doc skips it and mislemmatizes (e.g. "creavit"->"creauit" instead
of "creo", "ejus"->"js" instead of "is").

The normalizer is length-preserving and the EncliticSplitter splits a trailing
-que/-ne/-ve into its own token ("Dixitque" -> "Dixit"+"que"), so the Doc has
>= our word count. We re-merge by character length: each stored word maps to
one-or-more consecutive Doc tokens, and we take the lemma/morph of the head
(first) sub-token — the main word, with the enclitic following. Because our
surfaces carry no punctuation and are space-joined, the tokenizer never crosses
a word boundary, so the lengths line up exactly. lemma is the predicted lemma;
morph packs UPOS + the UD feature string
(e.g. "VERB|Mood=Ind|Number=Sing|Person=3|Tense=Pres").
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from itertools import groupby

MODEL = "la_core_web_lg"
CHUNK = 500     # verses per pipeline batch


def _morph_string(token) -> str | None:
    feats = str(token.morph)
    parts = [p for p in (token.pos_, feats) if p]
    return "|".join(parts) or None


def _norm_latin(s: str) -> str:
    """LatinCy's length-preserving orthographic fold (v->u, j->i), lowercased —
    the form the lemmatizer falls back to when it can't resolve a headword."""
    return s.lower().replace("v", "u").replace("j", "i")


def lemmatize(pack_path: pathlib.Path, model: str = MODEL) -> dict:
    """Fill lemma/morph for every vulgate_words row. Returns a stats dict."""
    if not pack_path.exists():
        raise FileNotFoundError(f"missing Vulgate pack: {pack_path}")

    import spacy

    nlp = spacy.load(model)

    pack = sqlite3.connect(pack_path)
    rows = pack.execute(
        "SELECT verse_map_id, id, surface FROM vulgate_words "
        "ORDER BY verse_map_id, position"
    ).fetchall()

    # Group the flat word list back into verses, preserving order.
    verses: list[tuple[list[int], list[str]]] = []
    for _vmid, grp in groupby(rows, key=lambda r: r[0]):
        g = list(grp)
        verses.append(([r[1] for r in g], [r[2] for r in g]))

    stats = {"verses": len(verses), "words": 0, "lemmatized": 0,
             "mismatches": 0, "recased": 0}

    texts = (" ".join(words) for _ids, words in verses)
    done = 0
    for (word_ids, words), doc in zip(verses, nlp.pipe(texts, batch_size=CHUNK)):
        dtoks = [t for t in doc if not t.is_space and t.text.strip()]
        di = 0
        for wid, wsurf in zip(word_ids, words):
            head = dtoks[di] if di < len(dtoks) else None
            # consume one-or-more sub-tokens until their (length-preserving,
            # normalized) text covers this word — EncliticSplitter may split it
            acc = 0
            target = len(wsurf)
            while di < len(dtoks) and acc < target:
                acc += len(dtoks[di].text)
                di += 1
            if head is not None and acc == target:
                lemma = head.lemma_ or None
                # A capitalized (usually verse-initial) verb often gets the
                # model's fallback self-lemma — the normalized surface — instead
                # of the real headword (e.g. "Vade"->"uade" not "uado"). When the
                # lemma of a finite verb is just its own folded surface, re-run
                # the lowercased surface in isolation and prefer a real (non-self)
                # lemma. Leaves correct 1sg-present self-lemmas (uideo, uenio)
                # unchanged, since the retry returns the same form.
                if lemma and head.pos_ in ("VERB", "AUX") \
                        and lemma == _norm_latin(wsurf):
                    retry = nlp(wsurf.lower())
                    if len(retry):
                        rlem = retry[0].lemma_
                        if rlem and rlem != _norm_latin(wsurf):
                            lemma = rlem
                            stats["recased"] = stats.get("recased", 0) + 1
                pack.execute(
                    "UPDATE vulgate_words SET lemma=?, morph=? WHERE id=?",
                    (lemma, _morph_string(head), wid),
                )
                if lemma:
                    stats["lemmatized"] += 1
            else:
                # Length desync — should not happen: the normalizer is
                # length-preserving (v->u, j->i) and surfaces are space-joined,
                # punctuation-free, so the tokenizer never crosses a word
                # boundary. If it ever did, this word's lemma/morph stays NULL
                # and di may sit mid-word; the per-verse di reset (outer loop)
                # bounds any cascade to this verse. mismatches is reported.
                stats["mismatches"] += 1
            stats["words"] += 1
        done += 1
        if done % 5000 == 0:
            print(f"  lemmatized {done:,}/{len(verses):,} verses", file=sys.stderr)

    pack.commit()
    pack.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LatinCy-lemmatize the Vulgate pack.")
    ap.add_argument("--pack", default="vulgate.sqlite", type=pathlib.Path)
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args(argv)

    stats = lemmatize(args.pack, args.model)
    print(f"vulgate_words lemmatized: {stats['lemmatized']:,}/{stats['words']:,} "
          f"words across {stats['verses']:,} verses "
          f"({stats['mismatches']:,} length-mismatch skips, "
          f"{stats['recased']:,} verb lemmas recovered via lowercased retry)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
