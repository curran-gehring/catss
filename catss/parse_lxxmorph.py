r"""
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


# Mirrors parse_parallel.VERSE_HEADER, with .mlxx-specific extensions.
# The book token must allow digits and "/" — Samuel–Kings carry the LXX
# Kingdoms notation ("1Sam/K", "1/3Kgs"); the old `[1-4]?\s*[A-Za-z]+` token
# rejected those headers, so all four books of Samuel–Kings (~80k words)
# were silently dropped. The chapter is optional: single-chapter books
# (EpJer, Susanna, Bel) label verses "EpJer 1" with no "chapter:" prefix.
# A trailing subverse letter ("Esth 1:1a" — the LXX Esther additions) is
# accepted and discarded; consecutive subverses merge into the base verse.
# A verse range ("TobS 9:3-4", "Dan 5:26-28") files under its first verse.
VERSE_HEADER = re.compile(
    r"^\s*([0-9A-Za-z][0-9A-Za-z/]*)\s+(?:(\d+):)?(\d+)(?:-\d+)?([a-z])?\s*$")

# A bare book token on its own line ("Od", "PsSol", "EpJer", "Lam", "Bel",
# "Dan") introduces a SUPERSCRIPTION/title block — the ode/psalm title or
# book preface — whose words belong to the chapter announced by the NEXT
# ref header. We emit them as verse 0 of that chapter. Guard: mid-file, the
# token must equal the book token of the surrounding ref headers, so a
# stray data word can never be mistaken for a title header.
BARE_HEADER = re.compile(r"^\s*([0-9A-Za-z][0-9A-Za-z/]*)\s*$")


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
    title_words: list[MorphWord] | None = None   # open superscription buffer
    title_book = ""
    last_book: str | None = None
    last_chapter = 0
    word_pos = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip():
                if current is not None and current.words:
                    yield current
                    current = None
                    word_pos = 0
                # an open title buffer survives blank lines — it is closed
                # by the ref header that follows it
                continue

            m = VERSE_HEADER.match(line)
            if m:
                if current is not None and current.words:
                    yield current
                book = m.group(1).strip()
                # group(2) (chapter) is None for single-chapter books → ch 1.
                chapter = int(m.group(2)) if m.group(2) else 1
                if title_words:
                    # superscription belongs to the chapter this header opens
                    yield MorphVerse(book=title_book, chapter=chapter,
                                     verse=0, words=title_words)
                title_words = None
                last_book = book
                last_chapter = chapter
                current = MorphVerse(book=book, chapter=chapter,
                                     verse=int(m.group(3)))
                word_pos = 0
                continue

            bm = BARE_HEADER.match(line)
            if bm and (last_book is None or bm.group(1) == last_book):
                if current is not None and current.words:
                    yield current
                current = None
                title_book = bm.group(1)
                title_words = []
                word_pos = 0
                continue

            target = title_words if title_words is not None else (
                current.words if current is not None else None)
            if target is None:
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
            target.append(MorphWord(
                line_no=line_no,
                position=word_pos,
                surface_beta=surface,
                parse_code=parse_code,
                lemma_beta=lemma,
            ))

    if current is not None and current.words:
        yield current
    if title_words:
        # A trailing title with no following ref header doesn't occur in the
        # CCAT corpus; if one ever does, file it after the last chapter
        # rather than dropping it silently.
        yield MorphVerse(book=title_book, chapter=last_chapter + 1,
                         verse=0, words=title_words)
