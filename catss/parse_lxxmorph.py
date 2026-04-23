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

            # CATSS .mlxx is a fixed-width format:
            #   cols  0-24   surface (25 chars, space-padded)
            #   cols 25-34   parse code (10 chars — "V1  PAN", "RA  DSF",
            #                 "VBI AMI3S" — internal single spaces stay)
            #   cols 35+     lemma [optional space+preverb...]
            #
            # Splitting on 2+ spaces is WRONG: a row like "V1  PAN" has
            # two spaces inside the parse-code column that look like a
            # field boundary but are not. Slice by column instead, with a
            # whitespace fallback for malformed rows.
            if len(line) >= 35:
                surface = line[0:25].rstrip()
                parse_code = line[25:35].strip()
                tail = line[35:].strip()
                if not tail:
                    continue
                tail_parts = tail.split(None, 1)
                lemma = tail_parts[0]
                preverb = tail_parts[1] if len(tail_parts) > 1 else None
                if preverb:
                    parse_code = f"{parse_code} +{preverb}"
            else:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                surface = parts[0]
                parse_code = parts[1]
                lemma = parts[2]
                preverb = " ".join(parts[3:]) if len(parts) > 3 else None
                if preverb:
                    parse_code = f"{parse_code} +{preverb}"

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
