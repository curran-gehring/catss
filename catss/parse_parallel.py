"""
Parser for CATSS parallel-aligned MT/LXX files (.par).

Format:

  <blank line>
  <Book> C:V                              <-- verse header
  <mt col>\\t<lxx col>                    <-- one alignment row
  <mt col>\\t<lxx col>
  ...
  <blank line>
  <Book> C:V+1
  ...

The MT column may contain:
  - surface BETA-coded Hebrew
  - column-b retroversion starting with ' =' (e.g. ' =B/' after primary)
  - annotation markers: *, **, ^, --- (minus), --+ (plus), {...}, etc.

The LXX column may contain:
  - surface BETA-coded Greek
  - '---' meaning "Hebrew counterpart lacking in LXX"
  - {...WORDS} meaning "equivalent reflected elsewhere"
  - continuation '^^^' for multi-line joins

We emit a flat list of AlignmentRow per verse with the raw BETA strings
preserved, plus parsed flags. Consumers decode BETA via `betacode.py`.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Iterator


# The chapter is optional: single-chapter books (Obadiah — the only one in the
# Hebrew OT) label verses as "Obad 1" with no "chapter:" prefix. Without the
# optional group those headers never matched and the whole book was dropped.
#
# The book token must allow digits and "/", not just letters: the Reigns books
# carry the LXX Kingdoms notation in their headers — "1Sam/K", "2Sam/K",
# "1/3Kgs" (1 Kings = 3 Reigns), "2/4Kgs" (2 Kings = 4 Reigns) — and Psalm 151
# is labeled "Ps151". The old letters-only token choked on the "/" and the
# trailing digits, so every header in those five files failed to match and all
# of Samuel–Kings (plus Ps 151) was silently dropped from the build. The book
# itself is assigned from the FILE (see build_db `_load_parallel`), so this
# token is informational; only the chapter/verse groups must parse.
VERSE_HEADER = re.compile(r"^\s*([0-9A-Za-z][0-9A-Za-z/]*)\s+(?:(\d+):)?(\d+)\s*$")


@dataclass
class AlignmentRow:
    line_no: int            # line number in source file (for error reports)
    mt_raw: str             # left column, raw BETA including markup
    lxx_raw: str            # right column, raw BETA including markup
    mt_col_a: str           # primary MT reading (markup stripped)
    mt_col_b: str | None    # column-b retroversion (after ' =') if present
    is_lxx_minus: bool      # LXX has no counterpart ('---' in Greek col)
    is_lxx_plus: bool       # '--+' in Hebrew col — LXX added it
    is_ketiv: bool
    is_qere: bool
    is_transposition: bool  # '~~~' marker
    notes: list[str] = field(default_factory=list)

    @property
    def has_retroversion(self) -> bool:
        return self.mt_col_b is not None


@dataclass
class Verse:
    book: str               # as written in the .par header
    chapter: int
    verse: int
    rows: list[AlignmentRow]


def parse_file(path: pathlib.Path) -> Iterator[Verse]:
    """Yield Verse objects in document order."""
    current: Verse | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                if current is not None and current.rows:
                    yield current
                    current = None
                continue

            m = VERSE_HEADER.match(line)
            if m:
                if current is not None and current.rows:
                    yield current
                book = m.group(1).strip()
                # group(2) (chapter) is None for single-chapter books → ch 1.
                chapter = int(m.group(2)) if m.group(2) else 1
                current = Verse(book=book, chapter=chapter,
                                verse=int(m.group(3)), rows=[])
                continue

            if current is None:
                # stray line before first header — skip
                continue

            row = _parse_row(line, line_no)
            if row is not None:
                current.rows.append(row)

    if current is not None and current.rows:
        yield current


def _parse_row(line: str, line_no: int) -> AlignmentRow | None:
    if "\t" in line:
        mt, lxx = line.split("\t", 1)
    else:
        # some rows have no Greek counterpart and use spaces only
        # CATSS standard uses tabs; treat as split on runs of 2+ spaces.
        parts = re.split(r"\s{2,}", line, maxsplit=1)
        if len(parts) == 2:
            mt, lxx = parts
        else:
            mt, lxx = line, ""

    mt = mt.strip()
    lxx = lxx.strip()
    if not mt and not lxx:
        return None

    # Column-b retroversion: starts with ' =' after the col-a text.
    # Examples:
    #   )LYMLK =:)BYMLK .lb
    #   B/YMY =B/
    mt_a, mt_b = _split_col_ab(mt)

    is_lxx_minus = bool(re.match(r"^-{3}($|\s|\{)", lxx))
    is_lxx_plus = mt_a.startswith("--+")
    # Ketiv/qere are NOT mutually exclusive — a single row can carry
    # both, e.g. `*HWC) **HYC)` (ketiv with a following qere form). Detect
    # each independently. A '*' that's part of '**' must not count for ketiv.
    _mt_ketiv_probe = re.sub(r"\*\*", "", mt)
    is_ketiv = "*" in _mt_ketiv_probe
    is_qere = "**" in mt
    is_transposition = "~~~" in mt or "~~~" in lxx

    notes: list[str] = []
    # surface {TAG} flags
    for tag in re.findall(r"\{([^{}]+)\}", mt + " " + lxx):
        notes.append(tag)

    return AlignmentRow(
        line_no=line_no,
        mt_raw=mt,
        lxx_raw=lxx,
        mt_col_a=_strip_col_b(mt_a),
        mt_col_b=mt_b,
        is_lxx_minus=is_lxx_minus,
        is_lxx_plus=is_lxx_plus,
        is_ketiv=is_ketiv,
        is_qere=is_qere,
        is_transposition=is_transposition,
        notes=notes,
    )


def _split_col_ab(mt: str) -> tuple[str, str | None]:
    """
    Split column a and column b. Column b is introduced by ' =' as a word
    (not '=' inside a token like '=:' or '=%'). CATSS convention: the
    retroversion starts after whitespace with '=' followed by a non-space.
    """
    # Find ' =' that's followed by a non-whitespace char *and* looks like
    # the canonical col-b introducer.
    idx = _find_colb_start(mt)
    if idx < 0:
        return mt, None
    return mt[:idx].rstrip(), mt[idx + 1 :].strip()


def _find_colb_start(mt: str) -> int:
    # Look for the first standalone '=' that introduces col-b. It must be
    # preceded by whitespace and followed by a non-whitespace character.
    for i, ch in enumerate(mt):
        if ch != "=":
            continue
        if i == 0:
            continue
        if not mt[i - 1].isspace():
            continue
        if i + 1 < len(mt) and mt[i + 1].isspace():
            continue
        return i
    return -1


def _strip_col_b(mt_a: str) -> str:
    return mt_a.strip()
