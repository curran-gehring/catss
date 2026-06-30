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


# Closed-corpus lemma overrides. The Vulgate is a fixed text, so the model's
# residual failures are fully enumerable: a handful of perfect-system compound
# verbs that la_core_web_lg self-lemmatizes (returns its own folded surface)
# even after the lowercased retry. Each target below is the SAME headword the
# model already assigns to other (present/imperfect/future) inflections of that
# verb elsewhere in this pack — e.g. it lemmatizes "projecit"->"proicio" but
# "projecerim"->"proiecerim" — so the override only makes these stragglers
# consistent with the model's own output; it introduces no outside authority.
# Keys are the _norm_latin-folded surface; the comment cites a sibling form the
# model lemmatized correctly to the same target.
_LEMMA_OVERRIDES = {
    "iustificasti": "iustifico",  # cf. justificabitur, justificetur -> iustifico
    "proiecerim":   "proicio",    # cf. projecit, projeci            -> proicio
    "proieceram":   "proicio",
    "euulsero":     "euello",     # cf. evellet, evellam             -> euello
    "eieceram":     "eicio",      # cf. ejecit, ejecerunt            -> eicio
    "deiecerint":   "deicio",     # cf. dejecit, dejecisti           -> deicio
    "accersiuit":   "accerso",    # cf. accersitis, accersito        -> accerso
}


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
             "mismatches": 0, "recased": 0, "overridden": 0}

    texts = (" ".join(words) for _ids, words in verses)
    done = 0
    for (word_ids, words), doc in zip(verses, nlp.pipe(texts, batch_size=CHUNK)):
        # Map each stored word to its head Doc token by ABSOLUTE char offset.
        # The text we fed is " ".join(words), so word k occupies a known
        # [start, end) span; token.idx is that token's offset into the same
        # string (the v->u/j->i fold is length-preserving, so offsets are
        # exact). The head is the first non-space token starting inside the
        # word's span; EncliticSplitter sub-tokens (e.g. "que" after "Dixit")
        # share the span and are skipped. Using absolute offsets — not a running
        # counter — means a token that fails to land in a word's span leaves
        # that one word NULL without shifting any later word's mapping.
        toks = [t for t in doc if not t.is_space and t.text.strip()]
        starts = []
        pos = 0
        for w in words:
            starts.append(pos)
            pos += len(w) + 1   # + the single-space separator
        ti = 0
        for wid, wsurf, w_start in zip(word_ids, words, starts):
            w_end = w_start + len(wsurf)
            while ti < len(toks) and toks[ti].idx < w_start:
                ti += 1
            head = (toks[ti] if ti < len(toks) and toks[ti].idx < w_end
                    else None)
            if head is not None:
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
                    folded = _norm_latin(wsurf)
                    retry = nlp(wsurf.lower())
                    rlem = retry[0].lemma_ if len(retry) else None
                    if rlem and rlem != folded:
                        lemma = rlem
                        stats["recased"] += 1
                    elif folded in _LEMMA_OVERRIDES:
                        # retry couldn't resolve it; use the enumerated override
                        lemma = _LEMMA_OVERRIDES[folded]
                        stats["overridden"] += 1
                pack.execute(
                    "UPDATE vulgate_words SET lemma=?, morph=? WHERE id=?",
                    (lemma, _morph_string(head), wid),
                )
                if lemma:
                    stats["lemmatized"] += 1
            else:
                # No token started inside this word's span (shouldn't happen
                # for space-joined, punctuation-free surfaces). Leave lemma/morph
                # NULL for THIS word only — the next word resyncs by absolute
                # offset, so a miss can't shift any following word. Reported.
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
          f"{stats['recased']:,} recovered via lowercased retry, "
          f"{stats['overridden']:,} via closed-corpus override)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
