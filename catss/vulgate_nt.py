"""
The New Testament Latin (Clementine) verse map against the SBLGNT of the shipped
FirstWord interlinear pack (book ids 40-66, ESV versification).

Clementine and SBLGNT disagree in places: verses the Greek omits (Acts 8:37),
passages the Greek keeps out of its text (John 7:53-8:11), chapter seams in
different places (Mark 8:39 = ESV 9:1) and verses split at different words
(John 6:51-52 = ESV 6:51). So the map is a list of ALIGNMENT UNITS: one or more
Latin verses aligned together with zero or more Greek verses. Word links may
cross verse lines inside a unit.

Every Latin verse gets one status:
  same        1:1 with the Greek verse of the same number
  renumbered  1:1 with a Greek verse of another number
  unit        its unit holds more than one verse on either side
  latin_only  no Greek in the interlinear pack; shown, never linked

and a HOME: the ESV verse it is shown under. A 1:1 verse's home is its Greek
verse; a latin_only verse's home is given in the curated file (its own number
when ESV prints it, else the verse it follows); a unit verse starts on the
unit's first Greek verse (or a curated home) and align_vulgate_nt refines it to
the verse holding most of its linked Greek words.

A row whose home is `pairwise` pairs its Latin and Greek ranges verse by verse
(a run of 1:1 renumbered verses, e.g. Mark 9 one ahead of ESV).

Only exceptions are curated (catss/data/nt_units.tsv); every other Latin verse
must have a same-numbered Greek verse, and every Greek verse must land in
exactly one unit. Anything else fails loudly.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

# Clementine abbreviation (column 2 of raw/vulgate/vul.tsv) -> FirstWord book id.
NT_BOOKS: dict[str, int] = {
    "Mt": 40, "Mc": 41, "Lc": 42, "Jo": 43, "Act": 44, "Rom": 45,
    "1Cor": 46, "2Cor": 47, "Gal": 48, "Eph": 49, "Phlp": 50, "Col": 51,
    "1Thes": 52, "2Thes": 53, "1Tim": 54, "2Tim": 55, "Tit": 56, "Phlm": 57,
    "Hbr": 58, "Jac": 59, "1Ptr": 60, "2Ptr": 61, "1Jo": 62, "2Jo": 63,
    "3Jo": 64, "Jud": 65, "Apc": 66,
}

Ref = tuple[int, int]   # (chapter, verse)


@dataclass(frozen=True)
class LatinVerse:
    book_id: int
    chapter: int
    verse: int
    vul_book: str
    text: str


@dataclass(frozen=True)
class UnitRow:
    """One curated line of nt_units.tsv (refs are within the row's book)."""
    latin: str
    greek: str
    home: str
    note: str


@dataclass
class Unit:
    latin: list[Ref]
    greek: list[Ref]
    status: list[str] = field(default_factory=list)   # per Latin verse
    home: list[Ref] = field(default_factory=list)     # per Latin verse
    note: str = ""


def parse_nt(path: pathlib.Path) -> list[LatinVerse]:
    """NT verses of vul.tsv in file order, first occurrence of each ref kept
    (the file emits every verse three times)."""
    out: list[LatinVerse] = []
    seen: set[tuple[int, int, int]] = set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 6:
                raise ValueError(f"{path}: line {n}: expected 6 columns, got {len(parts)}")
            abbrev = parts[1]
            book_id = NT_BOOKS.get(abbrev)
            if book_id is None:
                continue
            key = (book_id, int(parts[3]), int(parts[4]))
            if key in seen:
                continue
            seen.add(key)
            out.append(LatinVerse(book_id, key[1], key[2], abbrev, parts[5].strip()))
    return out


def load_unit_rows(path: pathlib.Path) -> dict[int, list[UnitRow]]:
    """Curated exceptions: `book<TAB>latin<TAB>greek<TAB>home<TAB>note`, `#` comments."""
    rows: dict[int, list[UnitRow]] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise ValueError(f"{path}: line {n}: expected 5 tab-separated columns, got {len(parts)}")
            book, latin, greek, home, note = (p.strip() for p in parts)
            if not latin:
                raise ValueError(f"{path}: line {n}: empty latin column")
            rows.setdefault(int(book), []).append(UnitRow(latin, greek, home, note))
    return rows


def _ref(s: str) -> Ref:
    ch, _, v = s.strip().partition(":")
    if not v:
        raise ValueError(f"bad ref {s!r}: expected chapter:verse")
    return int(ch), int(v)


def _expand(spec: str, order: list[Ref], side: str) -> list[Ref]:
    """`6:51,6:52` or `16:9-20` or `7:53-8:11`, expanded against `order`."""
    out: list[Ref] = []
    index = {r: i for i, r in enumerate(order)}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if "-" in part:
            a, _, b = part.partition("-")
            start = _ref(a)
            end = _ref(b) if ":" in b else (start[0], int(b))
            for r in (start, end):
                if r not in index:
                    raise ValueError(f"unknown {side} verse {r[0]}:{r[1]} in {spec!r}")
            out.extend(order[index[start]:index[end] + 1])
        else:
            r = _ref(part)
            if r not in index:
                raise ValueError(f"unknown {side} verse {r[0]}:{r[1]} in {spec!r}")
            out.append(r)
    return out


def resolve_units(latin: list[Ref], greek: list[Ref], rows: list[UnitRow]) -> list[Unit]:
    """One book's units, in Latin order. `latin` and `greek` are that book's
    verses in reading order; `rows` its curated exceptions."""
    curated: list[Unit] = []
    used_lat: set[Ref] = set()
    used_grk: set[Ref] = set()
    for row in rows:
        lat = _expand(row.latin, latin, "Latin")
        grk = _expand(row.greek, greek, "Greek") if row.greek else []
        for r in lat:
            if r in used_lat:
                raise ValueError(f"Latin verse {r[0]}:{r[1]} listed twice")
            used_lat.add(r)
        for r in grk:
            if r in used_grk:
                raise ValueError(f"Greek verse {r[0]}:{r[1]} listed twice")
            used_grk.add(r)
        if row.home == "pairwise":
            if len(lat) != len(grk):
                raise ValueError(f"pairwise row {row.latin!r} pairs {len(lat)} Latin with {len(grk)} Greek verses")
            for lr, gr in zip(lat, grk):
                curated.append(Unit([lr], [gr], ["same" if lr == gr else "renumbered"], [gr], row.note))
            continue
        homes = [_ref(h) for h in row.home.split(",") if h.strip()]
        if not grk:
            if len(homes) == 1:
                homes = homes * len(lat)
            if len(homes) != len(lat):
                raise ValueError(f"latin_only {row.latin!r} needs a home for each verse (or one for all)")
            status = ["latin_only"] * len(lat)
        elif len(lat) == 1 and len(grk) == 1:
            homes = [grk[0]]
            status = ["same" if lat[0] == grk[0] else "renumbered"]
        else:
            if not homes:
                homes = [grk[0]] * len(lat)
            if len(homes) != len(lat):
                raise ValueError(f"unit {row.latin!r} gives {len(homes)} homes for {len(lat)} Latin verses")
            status = ["unit"] * len(lat)
        curated.append(Unit(lat, grk, status, homes, row.note))

    grk_set = set(greek)
    by_first_lat = {u.latin[0]: u for u in curated}
    units: list[Unit] = []
    for r in latin:
        if r in by_first_lat:
            units.append(by_first_lat[r])
        elif r in used_lat:
            continue
        elif r in grk_set and r not in used_grk:
            used_grk.add(r)
            units.append(Unit([r], [r], ["same"], [r]))
        else:
            raise ValueError(f"Latin verse {r[0]}:{r[1]} has no same-numbered Greek verse and no curated unit")
    left = [g for g in greek if g not in used_grk]
    if left:
        raise ValueError("Greek verse(s) in no unit: " + ", ".join(f"{c}:{v}" for c, v in left))
    return units
