"""Known-answer smoke test for BETA decoders."""
from __future__ import annotations

import sys
sys.stdout.reconfigure(encoding="utf-8")

from catss.betacode import greek_to_unicode, hebrew_to_unicode


GREEK_CASES = [
    ("E)GE/NETO",   "ἐγένετο"),
    ("KAI\\",       "καὶ"),
    ("TH=|",        "τῇ"),
    ("A)NH\\R",     "ἀνὴρ"),
    ("A)PO\\",      "ἀπὸ"),
    ("TOU=",        "τοῦ"),
    ("*)ANH\\R",    "Ἀνὴρ"),
    ("LO/GOS",      "λόγος"),
    ("*)IHSOU=S",   "Ἰησοῦς"),
    ("E)N",         "ἐν"),
    ("TO\\N",       "τὸν"),
    ("A)LL'",       "ἀλλʼ"),          # elision → U+02BC modifier apostrophe
    ("KATA\\",      "κατὰ"),
]

HEBREW_CASES = [
    ("W/YHY",       "ויהי"),
    ("B/)RC",       "בארץ"),
    ("M/BYT LXM",   "מבית לחם"),
    ("H/$P+YM",     "השׁפטים"),
    ("YHWH",        "יהוה"),
    ("BN/YW",       "בניו"),
    # holem-waw: canonical order is waw U+05D5 then combining holem U+05B9
    ("$FLOWM",      "שָׁלוֹם"),
]


def run():
    greek_ok = 0
    for beta, expected in GREEK_CASES:
        got = greek_to_unicode(beta)
        mark = "✓" if got == expected else "✗"
        if got == expected: greek_ok += 1
        print(f"  {mark}  {beta:<14}  got={got!r:<22}  expected={expected!r}")
    print(f"Greek: {greek_ok}/{len(GREEK_CASES)}")
    print()

    heb_ok = 0
    for beta, expected in HEBREW_CASES:
        got = hebrew_to_unicode(beta)
        mark = "✓" if got == expected else "✗"
        if got == expected: heb_ok += 1
        print(f"  {mark}  {beta:<14}  got={got!r:<14}  expected={expected!r}")
    print(f"Hebrew: {heb_ok}/{len(HEBREW_CASES)}")

    return 0 if greek_ok == len(GREEK_CASES) and heb_ok == len(HEBREW_CASES) else 1


if __name__ == "__main__":
    raise SystemExit(run())
