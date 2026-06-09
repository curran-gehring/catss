"""
CATSS Michigan-Claremont BETA-code decoders for Hebrew and Greek.

References: raw/docs/betacode.txt (CCAT's official mapping).

Design:
  - hebrew_to_unicode(beta)  → Unicode Hebrew with vowel points
  - greek_to_unicode(beta)   → Unicode polytonic Greek

The output is intended for display; we deliberately do not fold dagesh or
other diacritics into precomposed forms when a safe combining sequence
exists, because downstream consumers (iOS, SQLite full-text) handle NFC
normalization themselves.

Hebrew notes:
  - '/' = morphological separator → stripped (kept as an explicit
    morpheme boundary via hebrew_split_morphemes()).
  - '-' = maqqeph → Unicode maqaf U+05BE.
  - '.' after a consonant = dagesh → U+05BC.
  - ',' = rafe → U+05BF.
  - '*' = ketiv marker, '**' = qere marker (stripped from surface form).
  - Accents/cantillation (numeric codes 00..95) are ignored by default;
    the MT consonantal text is what CATSS actually ships in .par files.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Hebrew

_HEBREW_CONSONANTS: dict[str, str] = {
    ")": "א",   # alef
    "B": "ב",   # bet
    "G": "ג",   # gimel
    "D": "ד",   # dalet
    "H": "ה",   # he
    "W": "ו",   # waw
    "Z": "ז",   # zayin
    "X": "ח",   # het
    "+": "ט",   # tet
    "Y": "י",   # yod
    "K": "כ",   # kaf (non-final — finals chosen at render time)
    "L": "ל",   # lamed
    "M": "מ",   # mem
    "N": "נ",   # nun
    "S": "ס",   # samek
    "(": "ע",   # ayin
    "P": "פ",   # pe
    "C": "צ",   # zade
    "Q": "ק",   # qof
    "R": "ר",   # resh
    "#": "ש",   # sin/shin (unpointed — we don't add dot by default)
    "&": "שׂ",  # sin (left dot)
    "$": "שׁ",  # shin (right dot)
    "T": "ת",   # taw
}

# Finals, applied during word-final fixup.
_HEBREW_FINALS: dict[str, str] = {
    "כ": "ך",   # kaf → kaf sofit
    "מ": "ם",   # mem → mem sofit
    "נ": "ן",   # nun → nun sofit
    "פ": "ף",   # pe → pe sofit
    "צ": "ץ",   # zade → zade sofit
}

_HEBREW_VOWELS: dict[str, str] = {
    "A":  "ַ",   # patah
    "F":  "ָ",   # qametz
    "I":  "ִ",   # hireq
    "E":  "ֶ",   # segol
    '"':  "ֵ",   # tsere
    "O":  "ֹ",   # holam
    "U":  "ֻ",   # qibbuts
    ":":  "ְ",   # schwa
}

# Compound schwas: ":A" ":F" ":E" handled in the main loop.
_HEBREW_COMPOUND: dict[str, str] = {
    ":A": "ֲ",  # hataf-patah
    ":F": "ֳ",  # hataf-qametz
    ":E": "ֱ",  # hataf-segol
}

_HEBREW_PUNCT: dict[str, str] = {
    "-": "־",   # maqaf
}


def hebrew_to_unicode(beta: str, *, strip_markers: bool = True) -> str:
    """
    Convert a CATSS Michigan-Claremont BETA string to Unicode Hebrew.

    strip_markers: remove morphological separators (/), ketiv/qere markers (*/**),
                   and CATSS-specific annotation glyphs ({...}, ---, --+, ^, etc.).
                   When False, '/' is preserved as U+05BE-less space for callers
                   that want to see morpheme boundaries.
    """
    if not beta:
        return ""

    if strip_markers:
        beta = _strip_catss_markers(beta)

    out: list[str] = []
    i = 0
    n = len(beta)
    while i < n:
        ch = beta[i]

        # 2-char compound schwa
        if ch == ":" and i + 1 < n and beta[i + 1] in "AFE":
            out.append(_HEBREW_COMPOUND[beta[i : i + 2]])
            i += 2
            continue

        # holem-waw "OW" → waw with holem above. Unicode canonical
        # order is base consonant first, then combining mark, so the
        # waw must be emitted BEFORE the holem (previous order was
        # backwards and broke NFC normalization + searches).
        if ch == "O" and i + 1 < n and beta[i + 1] == "W":
            out.append(_HEBREW_CONSONANTS["W"])
            out.append(_HEBREW_VOWELS["O"])
            i += 2
            continue

        # shureq: W. → waw + dagesh
        if ch == "W" and i + 1 < n and beta[i + 1] == ".":
            out.append(_HEBREW_CONSONANTS["W"])
            out.append("ּ")  # dagesh
            i += 2
            continue

        # dagesh after a consonant
        if ch == "." and out:
            out.append("ּ")
            i += 1
            continue

        # rafe
        if ch == "," and out:
            out.append("ֿ")
            i += 1
            continue

        if ch in _HEBREW_CONSONANTS:
            out.append(_HEBREW_CONSONANTS[ch])
        elif ch in _HEBREW_VOWELS:
            out.append(_HEBREW_VOWELS[ch])
        elif ch in _HEBREW_PUNCT:
            out.append(_HEBREW_PUNCT[ch])
        elif ch == "/":
            if not strip_markers:
                out.append("​")   # zero-width space; preserves morpheme boundary
        elif ch == " ":
            out.append(" ")
        elif ch.isdigit():
            # accent/cantillation codes are multi-digit; skip pair
            if i + 1 < n and beta[i + 1].isdigit():
                i += 1
            pass
        # unknown char: drop silently (CATSS has occasional stray markup)

        i += 1

    import re
    import unicodedata
    result = unicodedata.normalize("NFC", _apply_hebrew_finals("".join(out)))
    # dropped annotation tokens can leave runs of separator spaces behind
    return re.sub(r"\s+", " ", result).strip()


def _apply_hebrew_finals(s: str) -> str:
    """Replace word-final kaf/mem/nun/pe/zade with their sofit forms."""
    if not s:
        return s
    chars = list(s)
    # Walk backwards; convert last consonant in each word
    import re
    # Find word ends: whitespace, maqaf, string end
    tokens: list[str] = re.split(r"(\s+|־)", s)
    for idx, tok in enumerate(tokens):
        if not tok or tok.isspace() or tok == "־":
            continue
        # last Hebrew consonant position
        last_cons = -1
        for j in range(len(tok) - 1, -1, -1):
            if tok[j] in _HEBREW_FINALS:
                last_cons = j
                break
            if "א" <= tok[j] <= "ת":   # any Hebrew letter
                break
        if last_cons >= 0:
            tokens[idx] = tok[:last_cons] + _HEBREW_FINALS[tok[last_cons]] + tok[last_cons + 1 :]
    return "".join(tokens)


def _drop_annotation_tokens(beta: str) -> str:
    """Drop whitespace-delimited tokens that are apparatus, not text.

    CATSS text is ALL CAPS, so a token is annotation if it contains a
    lowercase letter (.wy, .dr, q1a, unclosed '<ju8.26' refs...), starts
    with '.' (note codes like '.()'), or carries text-critical brackets /
    leftover braces ('[..]K*X*', unclosed '{...L)'). Balanced {...} and
    <...> groups are removed before tokenization, so any surviving brace
    is unbalanced apparatus. Their '.' / '(' / ')' would otherwise decode
    as dagesh / ayin / alef.
    """
    import re
    return " ".join(
        t for t in beta.split()
        if not re.search(r"[a-z\[\]{}]", t)
        and not t.startswith(".")
        and not t.isdigit()   # bare apparatus numbers ('NKWXH 3 ... 9')
    )


def _strip_catss_markers(beta: str) -> str:
    """Remove CATSS alignment/annotation markup, leaving only MT/LXX text."""
    import re
    # Remove {...X} and {X} annotations
    beta = re.sub(r"\{[^{}]*\}", "", beta)
    # Remove <1.7>-style cross-references and <sp>-style notes. The '.'
    # inside them would otherwise be read as a dagesh on the preceding text.
    beta = re.sub(r"<[^<>]*>", "", beta)
    beta = _drop_annotation_tokens(beta)
    # Remove leading column-b retroversion markers "= ..." only if caller wants col-a
    # (callers who want col-b use parse_parallel.py directly — don't strip here)
    # Remove ---, --+, --, ^^^. The plus marker is only TWO dashes ('--+'),
    # so the run length must be 2+, not 3+ — a single '-' (maqqeph) survives.
    beta = re.sub(r"-{2,}\+?", "", beta)
    beta = beta.replace("^", "")
    # '' is a CATSS ditto/placeholder mark, not text
    beta = beta.replace("''", "")
    # Ketiv * / qere ** — drop the marker, keep the text that follows
    beta = re.sub(r"\*\*?", "", beta)
    # Continuation markers and stray punctuation
    beta = beta.replace("~", "")
    # Collapse whitespace
    beta = re.sub(r"\s+", " ", beta).strip()
    return beta


# ---------------------------------------------------------------------------
# Greek

_GREEK_LETTERS_LOWER: dict[str, str] = {
    "A": "α", "B": "β", "G": "γ", "D": "δ", "E": "ε",
    "Z": "ζ", "H": "η", "Q": "θ", "I": "ι", "K": "κ",
    "L": "λ", "M": "μ", "N": "ν", "C": "ξ", "O": "ο",
    "P": "π", "R": "ρ", "S": "σ", "J": "ς", "T": "τ",
    "U": "υ", "F": "φ", "X": "χ", "Y": "ψ", "W": "ω",
    "V": "ϝ",
}

_GREEK_LETTERS_UPPER: dict[str, str] = {
    k: v.upper() for k, v in _GREEK_LETTERS_LOWER.items()
}

# Combining diacritics
_SMOOTH = "̓"
_ROUGH = "̔"
_ACUTE = "́"
_GRAVE = "̀"
_CIRC = "͂"
_DIAER = "̈"
_IOTA_SUB = "ͅ"


_DIACRITIC_CHARS = {
    ")": _SMOOTH,
    "(": _ROUGH,
    "/": _ACUTE,
    "\\": _GRAVE,
    "=": _CIRC,
    "+": _DIAER,
    "|": _IOTA_SUB,
}


def greek_to_unicode(beta: str) -> str:
    r"""
    Convert CATSS BETA-coded Greek (TLG-compatible) to Unicode polytonic Greek.

    In TLG/CATSS BETA, accents and breathings *follow* the letter they
    modify — except after the capital marker '*', where they precede the
    letter. So we look ahead after each letter and greedily absorb the
    contiguous run of diacritic chars.

    Examples:
      E)GE/NETO    → ἐγένετο       ( ')' after E, '/' after second E )
      KAI\         → καὶ           ( '\' after I )
      TH=|         → τῇ            ( '=' and '|' after H )
      *)ANH\R      → Ἀνήρ          ( '*' then ')' for capital-with-smooth )
    """
    if not beta:
        return ""

    beta = _strip_catss_markers_greek(beta)

    out: list[str] = []
    i = 0
    n = len(beta)

    while i < n:
        ch = beta[i]

        # capital marker: consume any diacritics that follow before the letter
        if ch == "*":
            i += 1
            leading: list[str] = []
            while i < n and beta[i] in _DIACRITIC_CHARS:
                leading.append(_DIACRITIC_CHARS[beta[i]])
                i += 1
            if i >= n or beta[i] not in _GREEK_LETTERS_LOWER:
                continue
            out.append(_GREEK_LETTERS_UPPER[beta[i]])
            out.extend(leading)
            i += 1
            # consume trailing diacritics too (rare but possible)
            while i < n and beta[i] in _DIACRITIC_CHARS:
                out.append(_DIACRITIC_CHARS[beta[i]])
                i += 1
            continue

        if ch in _GREEK_LETTERS_LOWER:
            out.append(_GREEK_LETTERS_LOWER[ch])
            i += 1
            while i < n and beta[i] in _DIACRITIC_CHARS:
                out.append(_DIACRITIC_CHARS[beta[i]])
                i += 1
            continue

        if ch == " ":
            out.append(" ")
            i += 1
            continue

        if ch == "-":
            out.append("-")
            i += 1
            continue

        if ch == "'":
            # TLG canonical is U+02BC MODIFIER LETTER APOSTROPHE for
            # elisions, not U+2019 RIGHT SINGLE QUOTATION MARK.
            out.append("ʼ")
            i += 1
            continue

        # stray diacritic with no host letter (rare) — drop
        if ch in _DIACRITIC_CHARS:
            i += 1
            continue

        if ch.isdigit():
            i += 1
            continue

        # unknown: skip
        i += 1

    import re
    import unicodedata
    result = unicodedata.normalize("NFC", "".join(out))
    result = re.sub(r"\s+", " ", result).strip()
    return _fix_final_sigma(result)


def _fix_final_sigma(s: str) -> str:
    import re
    # Convert σ to ς at end of word. \w is Unicode-aware and covers ALL
    # Greek letters including accented/polytonic forms (ά U+03AC, ῳ U+1FF3,
    # ...). The previous class [α-ωΑ-Ω...] excluded those blocks, so any σ
    # directly before an accented vowel was wrongly finalized (μέςῳ).
    return re.sub(r"σ(?!\w)", "ς", s)


def _strip_catss_markers_greek(beta: str) -> str:
    import re
    beta = re.sub(r"\{[^{}]*\}", "", beta)
    beta = re.sub(r"<[^<>]*>", "", beta)
    beta = re.sub(r"-{2,}\+?", "", beta)
    beta = _drop_annotation_tokens(beta)
    beta = beta.replace("^", "")
    # '' is a CATSS ditto/placeholder mark — strip BEFORE the decoder maps
    # a lone ' (elision) to U+02BC.
    beta = beta.replace("''", "")
    beta = beta.replace("~", "")
    beta = re.sub(r"\s+", " ", beta).strip()
    return beta
