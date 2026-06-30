"""
Parser for the Clementine Latin Vulgate TSV (raw/vulgate/vul.tsv).

Source: theunpleasantowl/vul-complete `vul.tsv` (archived 2026-03; text from
the Clementine Text Project = public domain). One row per verse:

    fullLatinName \t abbrev \t book# \t chapter \t verse \t text

Two things make this file CATSS-specific:

  1. **Triplication.** Every verse is emitted three times, byte-identical
     (107,427 lines = 3 x 35,809 unique verses). We dedup on the (abbrev,
     chapter, verse) ref and keep the first occurrence.

  2. **Versification splits.** The Vulgate packs material inline that CATSS
     keys as separate books (see `_map_ref`). Daniel 13/14 are Susanna / Bel;
     Baruch 6 is the Letter of Jeremiah. We rewrite those refs to the CATSS
     book so the Latin can later ride the gold MT<->LXX cross-alignment.

NT books and any OT book CATSS does not carry are dropped (no alignment
target). Each surviving verse is filed under a CATSS book (`catss_osis`) and
tagged with its alignment pivot ('mt' or 'lxx') via `books.vulgate_pivot`.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Iterator

from . import books as bookreg


# Vulgate abbrev (col 2 of vul.tsv) -> CATSS osis. Books absent from this map
# (the entire NT: Mt, Mc, Lc, Jo, Act, Rom ... Apc) have no CATSS counterpart
# and are dropped. Note 1Esd/Ps151 are NOT here: this Clementine edition has
# no separate 3-Esdras and stops at Ps 150, so neither receives Latin.
_VUL_TO_CATSS: dict[str, str] = {
    "Gn": "Gen", "Ex": "Exod", "Lv": "Lev", "Nm": "Num", "Dt": "Deut",
    "Jos": "Josh", "Jdc": "Judg", "Rt": "Ruth",
    "1Rg": "1Sam", "2Rg": "2Sam", "3Rg": "1Kgs", "4Rg": "2Kgs",
    "1Par": "1Chr", "2Par": "2Chr",
    "Esr": "Ezra", "Neh": "Neh",
    "Tob": "TobBA",   # Jerome's Latin Tobit vs Greek B/A: same book, divergent
    "Jdt": "Jdt", "Est": "Esth", "Job": "Job",
    "Ps": "Ps", "Pr": "Prov", "Ecl": "Eccl", "Ct": "Song",
    "Sap": "Wis", "Sir": "Sir",
    "Is": "Isa", "Jr": "Jer", "Lam": "Lam",
    "Bar": "Bar",     # ch 6 -> EpJer (see _map_ref)
    "Ez": "Ezek",
    "Dn": "Dan",      # ch 13 -> SusTh, ch 14 -> BelTh (see _map_ref)
    "Os": "Hos", "Joel": "Joel", "Am": "Amos", "Abd": "Obad",
    "Jon": "Jonah", "Mch": "Mic", "Nah": "Nah", "Hab": "Hab",
    "Soph": "Zeph", "Agg": "Hag", "Zach": "Zech", "Mal": "Mal",
    "1Mcc": "1Macc", "2Mcc": "2Macc",
}


@dataclass(frozen=True)
class VulgateVerse:
    vul_book: str        # original Vulgate abbrev, e.g. "Dn"
    vul_chapter: int
    vul_verse: int
    catss_osis: str      # CATSS book the Latin is filed under
    catss_chapter: int
    catss_verse: int
    pivot: str           # 'mt' | 'lxx'
    text: str


def _map_ref(abbrev: str, chapter: int, verse: int) -> tuple[str, int, int] | None:
    """Rewrite a Vulgate (abbrev, ch, v) ref to its CATSS (osis, ch, v), or
    None if the book has no CATSS counterpart.

    The Vulgate stores three deuterocanonical units inline that CATSS keys as
    standalone books. We split them out here so the verse map points at the
    book CATSS actually aligns:

      - Daniel 13 = Susanna           -> SusTh (Theodotion), one chapter
      - Daniel 14 = Bel and the Dragon -> BelTh (Theodotion), one chapter
      - Baruch 6  = Letter of Jeremiah -> EpJer, one chapter

    Daniel 1-12 (incl. the ch-3 Prayer of Azariah / Song of the Three, which
    Theodotion also carries inline) stays Daniel. Esther needs no split: its
    Greek additions (Vulgate ch 11-16, and 10:4+) simply have no verse in the
    CATSS Hebrew Esther (ch 1-10 only), so they resolve to no pivot downstream
    while keeping their Latin text.
    """
    osis = _VUL_TO_CATSS.get(abbrev)
    if osis is None:
        return None
    if osis == "Dan":
        if chapter == 13:
            return ("SusTh", 1, verse)       # Susanna: direct (Vulg 13:65 has no Th v65)
        if chapter == 14:
            # Bel: Theodotion v1 is the Astyages/Cyrus prologue the Vulgate
            # omits, so the whole book is shifted +1 (verified exact end to
            # end: Vulg 14:1 = BelTh 2 ... 14:41 = BelTh 42). Vulg 14:42 (a
            # closing royal proclamation Theodotion lacks) orphans at BelTh 43.
            return ("BelTh", 1, verse + 1)
        return ("Dan", chapter, verse)
    if osis == "Bar" and chapter == 6:
        return ("EpJer", 1, verse)
    # Joel & Malachi carry the classic Latin-vs-Hebrew chapter division. CATSS
    # follows MT (BHS) versification; the Clementine Vulgate uses the older
    # Latin one. These are exact, whole-block shifts (verified against the
    # CATSS verse counts) — without them an entire chapter of each book would
    # orphan. Sporadic single-verse drift in other books (Num 16/17, Sirach,
    # Tobit, Judith) is left to orphan: no clean closed-form remap exists.
    if osis == "Joel":
        if chapter == 2 and verse >= 28:
            return ("Joel", 3, verse - 27)   # Vulg 2:28-32 -> MT 3:1-5
        if chapter == 3:
            return ("Joel", 4, verse)        # Vulg ch 3 -> MT ch 4
        return ("Joel", chapter, verse)
    if osis == "Mal":
        if chapter == 4:
            return ("Mal", 3, verse + 18)    # Vulg 4:1-6 -> MT 3:19-24
        return ("Mal", chapter, verse)
    return (osis, chapter, verse)


def parse_file(path: pathlib.Path) -> Iterator[VulgateVerse]:
    """Yield one VulgateVerse per unique CATSS-mapped verse.

    Dedups the x3 triplication on the original (vul_book, ch, v) ref. Lines
    for NT / unmapped books are skipped. Malformed lines (wrong column count,
    non-integer ch/v) are skipped silently rather than aborting the build.
    """
    seen: set[tuple[str, int, int]] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 6:
                continue
            abbrev = cols[1].strip()
            try:
                chapter = int(cols[3])
                verse = int(cols[4])
            except ValueError:
                continue
            ref = (abbrev, chapter, verse)
            if ref in seen:
                continue
            seen.add(ref)

            mapped = _map_ref(abbrev, chapter, verse)
            if mapped is None:
                continue
            catss_osis, catss_ch, catss_v = mapped
            text = cols[5].strip()
            yield VulgateVerse(
                vul_book=abbrev,
                vul_chapter=chapter,
                vul_verse=verse,
                catss_osis=catss_osis,
                catss_chapter=catss_ch,
                catss_verse=catss_v,
                pivot=bookreg.vulgate_pivot(catss_osis),
                text=text,
            )
