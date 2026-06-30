"""
Canonical book registry. Keyed by CATSS file prefix (e.g. '10.Ruth').

Covers the 45 .par parallel files + the 62 .mlxx LXX-morph files. OT
book_ids roughly follow the Protestant / Hebrew canon order but are NOT
the standard numbering: DanOG holds 27, so Dan=28 and every book from
Hosea on is shifted +1 (Mal=40). JoshA/JudgA sit at 61/62; 70+ holds
deuterocanonicals / LXX-only books. Downstream consumers (FirstWord's
remap_catss_bookids) remap these to their own canon — anyone else must
map by `osis`, never by assuming standard book numbers.

A few single books are split across multiple mlxx files (Gen 1/2, Psalms 1/2,
Isaiah 1/2, Jer 1/2, Ezek 1/2); we flatten each into one canonical book with
multiple source files. Distinct from that, books that survive in two whole
Greek editions — Daniel, Susanna, Bel — are kept as SEPARATE books (e.g.
Daniel: "Dan" = Theodotion, the canonical one carrying its MT↔LXX parallel +
morph; "DanOG" = Old Greek, morph only), not flattened.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    canon_id: int             # stable internal ID
    osis: str                 # OSIS-style abbreviation
    par_file: str | None      # parallel filename stem
    mlxx_files: tuple[str, ...]  # one or more lxxmorph filename stems
    display: str


def _b(canon_id, osis, par, mlxx, display) -> Book:
    if isinstance(mlxx, str):
        mlxx = (mlxx,)
    elif mlxx is None:
        mlxx = ()
    return Book(canon_id, osis, par, tuple(mlxx), display)


_BOOKS: tuple[Book, ...] = (
    # ---- Hebrew canon (1-39) ----
    _b( 1, "Gen",    "01.Genesis",  ("01.Gen.1", "02.Gen.2"),        "Genesis"),
    _b( 2, "Exod",   "02.Exodus",   "03.Exod",                        "Exodus"),
    _b( 3, "Lev",    "03.Lev",      "04.Lev",                         "Leviticus"),
    _b( 4, "Num",    "04.Num",      "05.Num",                         "Numbers"),
    _b( 5, "Deut",   "05.Deut",     "06.Deut",                        "Deuteronomy"),
    _b( 6, "Josh",   "06.JoshB",    "07.JoshB",                       "Joshua (B)"),
    _b(61, "JoshA",  "07.JoshA",    "08.JoshA",                       "Joshua (A)"),
    _b( 7, "Judg",   "08.JudgesB",  "09.JudgesB",                     "Judges (B)"),
    _b(62, "JudgA",  "09.JudgesA",  "10.JudgesA",                     "Judges (A)"),
    _b( 8, "Ruth",   "10.Ruth",     "11.Ruth",                        "Ruth"),
    _b( 9, "1Sam",   "11.1Sam",     "12.1Sam",                        "1 Samuel"),
    _b(10, "2Sam",   "12.2Sam",     "13.2Sam",                        "2 Samuel"),
    _b(11, "1Kgs",   "13.1Kings",   "14.1Kings",                      "1 Kings"),
    _b(12, "2Kgs",   "14.2Kings",   "15.2Kings",                      "2 Kings"),
    _b(13, "1Chr",   "15.1Chron",   "16.1Chron",                      "1 Chronicles"),
    _b(14, "2Chr",   "16.2Chron",   "17.2Chron",                      "2 Chronicles"),
    _b(15, "Ezra",   "18.Ezra",     "19.2Esdras",                     "Ezra"),   # 2Esdras mlxx covers Ezra+Neh
    _b(16, "Neh",    "19.Neh",      (),                                "Nehemiah"),
    _b(17, "Esth",   "18.Esther",   "20.Esther",                      "Esther"),
    _b(18, "Job",    "26.Job",      "34.Job",                         "Job"),
    _b(19, "Ps",     "20.Psalms",   ("28.Psalms1", "29.Psalms2"),     "Psalms"),
    _b(20, "Prov",   "23.Prov",     "31.Proverbs",                    "Proverbs"),
    _b(21, "Eccl",   "24.Qoh",      "32.Qoheleth",                    "Ecclesiastes (Qoheleth)"),
    _b(22, "Song",   "25.Cant",     "33.Canticles",                   "Song of Songs"),
    _b(23, "Isa",    "40.Isaiah",   ("50.Isaiah1", "51.Isaiah2"),     "Isaiah"),
    _b(24, "Jer",    "41.Jer",      ("52.Jer1",    "53.Jer2"),        "Jeremiah"),
    _b(25, "Lam",    "43.Lam",      "56.Lam",                         "Lamentations"),
    _b(26, "Ezek",   "44.Ezekiel",  ("57.Ezek1",   "58.Ezek2"),       "Ezekiel"),
    # Daniel: CCAT ships an MT↔LXX parallel in BOTH editions (45.DanielOG,
    # 46.DanielTh). We make THEODOTION the canonical Daniel (osis "Dan" →
    # FW book 27 via remap_catss_bookids), carrying its parallel + morph just
    # like every other book — this is what the FW Parallel + LXX tabs read, and
    # it matches the Theodotion edition the bible_interlinear Greek interlinear
    # uses for Daniel. The Old Greek stays as a morph-only side book (osis
    # "DanOG" → id+1000, never queried by FW).
    _b(27, "DanOG",  None,          "61.DanielOG",                    "Daniel (OG)"),
    _b(28, "Dan",    "46.DanielTh", "62.DanielTh",                    "Daniel"),
    _b(29, "Hos",    "28.Hosea",    "38.Hosea",                       "Hosea"),
    _b(30, "Joel",   "31.Joel",     "41.Joel",                        "Joel"),
    _b(31, "Amos",   "30.Amos",     "40.Amos",                        "Amos"),
    _b(32, "Obad",   "33.Obadiah",  "43.Obadiah",                     "Obadiah"),
    _b(33, "Jonah",  "32.Jonah",    "42.Jonah",                       "Jonah"),
    _b(34, "Mic",    "29.Micah",    "39.Micah",                       "Micah"),
    _b(35, "Nah",    "34.Nahum",    "44.Nahum",                       "Nahum"),
    _b(36, "Hab",    "35.Hab",      "45.Habakkuk",                    "Habakkuk"),
    _b(37, "Zeph",   "36.Zeph",     "46.Zeph",                        "Zephaniah"),
    _b(38, "Hag",    "37.Haggai",   "47.Haggai",                      "Haggai"),
    _b(39, "Zech",   "38.Zech",     "48.Zech",                        "Zechariah"),
    _b(40, "Mal",    "39.Malachi",  "49.Malachi",                     "Malachi"),

    # ---- Deuterocanonical / LXX-only ----
    _b(70, "1Esd",   "17.1Esdras",  "18.1Esdras",                     "1 Esdras"),
    _b(71, "Ps151",  "22.Ps151",    (),                                "Psalm 151"),
    _b(72, "Sir",    "27.Sirach",   "36.Sirach",                      "Sirach"),
    _b(73, "Bar",    "42.Baruch",   "54.Baruch",                      "Baruch"),
    _b(74, "EpJer",  None,          "55.EpJer",                       "Epistle of Jeremiah"),
    _b(75, "Jdt",    None,          "21.Judith",                      "Judith"),
    _b(76, "TobBA",  None,          "22.TobitBA",                     "Tobit (B/A)"),
    _b(77, "TobS",   None,          "23.TobitS",                      "Tobit (Sinaiticus)"),
    _b(78, "1Macc",  None,          "24.1Macc",                       "1 Maccabees"),
    _b(79, "2Macc",  None,          "25.2Macc",                       "2 Maccabees"),
    _b(80, "3Macc",  None,          "26.3Macc",                       "3 Maccabees"),
    _b(81, "4Macc",  None,          "27.4Macc",                       "4 Maccabees"),
    _b(82, "Odes",   None,          "30.Odes",                        "Odes"),
    _b(83, "Wis",    None,          "35.Wisdom",                      "Wisdom"),
    _b(84, "PsSol",  None,          "37.PsSol",                       "Psalms of Solomon"),
    _b(85, "SusOG",  None,          "63.SusOG",                       "Susanna (OG)"),
    _b(86, "SusTh",  None,          "64.SusTh",                       "Susanna (Theodotion)"),
    _b(87, "BelOG",  None,          "59.BelOG",                       "Bel and Dragon (OG)"),
    _b(88, "BelTh",  None,          "60.BelTh",                       "Bel and Dragon (Theodotion)"),
)


def by_osis(osis: str) -> Book | None:
    lower = osis.lower()
    for b in _BOOKS:
        if b.osis.lower() == lower:
            return b
    return None


def by_par(stem: str) -> Book | None:
    for b in _BOOKS:
        if b.par_file == stem:
            return b
    return None


def all_par_stems() -> list[str]:
    return [b.par_file for b in _BOOKS if b.par_file]


def all_mlxx_stems() -> list[str]:
    stems: list[str] = []
    for b in _BOOKS:
        stems.extend(b.mlxx_files)
    return stems


def all_books() -> tuple[Book, ...]:
    return _BOOKS


# ---------------------------------------------------------------------------
# Vulgate alignment pivot
# ---------------------------------------------------------------------------
# Which CATSS column the Latin Vulgate word-aligns against. Jerome rendered
# most of the OT from the Hebrew (the *Hebraica veritas*) -> pivot 'mt'. But
# the Gallican Psalter — the Psalms carried by the Clementine / liturgical
# Vulgate — and the deuterocanonical / Greek-only material descend from the
# LXX -> pivot 'lxx' (and follow LXX versification, e.g. Psalm numbering).
#
# Latin links to this ONE pivot; the counterpart language is then reached
# transitively through the existing hand-curated MT<->LXX `alignments` rows,
# so we never run two independent (noisy) alignments per book.
_VULGATE_LXX_PIVOT: frozenset[str] = frozenset({
    "Ps",      # Gallican Psalter: LXX/Hexapla base, LXX numbering
    "Ps151",
    "1Esd",    # Vulgate appendix "3 Esdras" = Greek 1 Esdras
    "Sir", "Bar", "EpJer", "Jdt", "TobBA", "TobS",
    "1Macc", "2Macc",
    "Wis",
    "SusOG", "SusTh", "BelOG", "BelTh",
    # NOT in the Vulgate canon (3Macc/4Macc/Odes/PsSol/DanOG): no Latin to
    # align — coverage filtering drops them at build time regardless of pivot.
})


def vulgate_pivot(osis: str) -> str:
    """Return 'lxx' if the Vulgate form of this book descends from the Greek,
    else 'mt'. Books the Vulgate lacks still return a value, but receive no
    Latin rows at build time (the verse-coverage filter drops them)."""
    return "lxx" if osis in _VULGATE_LXX_PIVOT else "mt"
