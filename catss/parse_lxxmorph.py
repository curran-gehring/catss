"""
Parser for CATSS LXX morphology files (.mlxx).

Each word occupies one line. The format shipped in CCAT's lxxmorph/
directory is (tab or whitespace separated):

  <ref>  <surface BETA>  <parse code>  <lemma BETA>

A blank line separates verses (not always consistently). Verse reference
blocks look like:

  Gen 1:1

Example (BETA):
  Gen 1:1
  E)N           P           E)N
  A)RXH=|       N2 DSF      A)RXH/
  E)POI/HSEN    V AAI3S     POIE/W
  ...

We parse permissively — CATSS .mlxx files use whitespace runs rather than
strict tabs, so we split on /\s{2,}/ and fall back to single-space splits
on short lines.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Iterator


VERSE_HEADER = re.compile(r"^\s*([1-4]?\s*[A-Za-z]+)\s+(\d+):(\d+)\s*$")


@dataclass
class MorphWord:
    line_no: int
    position: int               # 1-based word-in-verse index
    surface_beta: str
    parse_code: str             # e.g. "V AAI3S", "N2 DSF"
    lemma_beta: str


@dataclass
class MorphVerse:
    book: str
    chapter: int
    verse: int
    words: list[MorphWord] = field(default_factory=list)


def parse_file(path: pathlib.Path) -> Iterator[MorphVerse]:
    current: MorphVerse | None = None
    word_pos = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip():
                if current is not None and current.words:
                    yield current
                current = None
                word_pos = 0
                continue

            m = VERSE_HEADER.match(line)
            if m:
                if current is not None and current.words:
                    yield current
                current = MorphVerse(book=m.group(1).strip(),
                                     chapter=int(m.group(2)),
                                     verse=int(m.group(3)))
                word_pos = 0
                continue

            if current is None:
                continue

            fields = re.split(r"\s{2,}|\t+", line.strip())
            if len(fields) < 3:
                fields = line.strip().split()
            if len(fields) < 3:
                continue

            # Canonical order: surface, parse, lemma.
            # Some files put the parse code as two tokens ("N2", "DSF") —
            # collapse fields[1..-1] as parse + lemma.
            surface = fields[0]
            lemma = fields[-1]
            parse_code = " ".join(fields[1:-1]) if len(fields) > 2 else ""

            word_pos += 1
            current.words.append(MorphWord(
                line_no=line_no,
                position=word_pos,
                surface_beta=surface,
                parse_code=parse_code,
                lemma_beta=lemma,
            ))

    if current is not None and current.words:
        yield current
