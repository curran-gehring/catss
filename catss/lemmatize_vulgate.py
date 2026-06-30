"""
Backfill vulgate_words.lemma and .morph with LatinCy. **Runs on the mac-mini**
(needs spaCy + the `la_core_web_lg` model).

We feed the model our already-stored token surfaces (not the raw text) as a
pre-tokenized Doc, so the model's tagger / morphologizer / lemmatizer run with
verse context while staying 1:1 with vulgate_words.position — no retokenization
drift. lemma is the predicted lemma; morph packs UPOS + the UD feature string
(e.g. "VERB Mood=Ind|Number=Sing|Person=3|Tense=Pres").
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


def lemmatize(pack_path: pathlib.Path, model: str = MODEL) -> dict:
    """Fill lemma/morph for every vulgate_words row. Returns a stats dict."""
    if not pack_path.exists():
        raise FileNotFoundError(f"missing Vulgate pack: {pack_path}")

    import spacy
    from spacy.tokens import Doc

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

    stats = {"verses": len(verses), "words": 0, "lemmatized": 0}

    def _run(component_docs):
        docs = component_docs
        for _name, proc in nlp.pipeline:
            docs = list(proc.pipe(docs))
        return docs

    for start in range(0, len(verses), CHUNK):
        chunk = verses[start:start + CHUNK]
        docs = [Doc(nlp.vocab, words=words) for _ids, words in chunk]
        docs = _run(docs)
        for (word_ids, _words), doc in zip(chunk, docs):
            for wid, token in zip(word_ids, doc):
                lemma = token.lemma_ or None
                pack.execute(
                    "UPDATE vulgate_words SET lemma=?, morph=? WHERE id=?",
                    (lemma, _morph_string(token), wid),
                )
                stats["words"] += 1
                if lemma:
                    stats["lemmatized"] += 1
        print(f"  lemmatized {min(start + CHUNK, len(verses)):,}/"
              f"{len(verses):,} verses", file=sys.stderr)

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
          f"words across {stats['verses']:,} verses", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
