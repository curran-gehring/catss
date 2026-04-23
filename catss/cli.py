"""CLI entry point: `catss fetch | build | verse | lemma`."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Force UTF-8 stdout on Windows — the default cp1252 trips on polytonic Greek.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catss")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="download raw CATSS files from CCAT")
    p_fetch.add_argument("--raw", default="raw", help="target dir (default: ./raw)")

    p_build = sub.add_parser("build", help="build catss.db from raw/")
    p_build.add_argument("--raw", default="raw")
    p_build.add_argument("--db", default="catss.db")
    p_build.add_argument("--slim", action="store_true",
                         help="drop BETA columns + VACUUM; ~45% smaller db for iOS")

    p_verse = sub.add_parser("verse", help="show MT↔LXX alignment for a verse")
    p_verse.add_argument("book")
    p_verse.add_argument("chapter", type=int)
    p_verse.add_argument("verse", type=int)
    p_verse.add_argument("--db", default="catss.db")
    p_verse.add_argument("--format", choices=("pretty", "json"), default="pretty")

    p_lemma = sub.add_parser("lemma", help="find every LXX occurrence of a lemma")
    p_lemma.add_argument("lemma")
    p_lemma.add_argument("--db", default="catss.db")
    p_lemma.add_argument("--limit", type=int, default=100)

    p_books = sub.add_parser("books", help="list all books in the database")
    p_books.add_argument("--db", default="catss.db")

    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        from . import download
        download.fetch_all(pathlib.Path(args.raw))
        print("done", file=sys.stderr)
        return 0

    if args.cmd == "build":
        from . import build_db
        stats = build_db.build(pathlib.Path(args.raw), pathlib.Path(args.db),
                               slim=args.slim)
        print(json.dumps(stats, indent=2), file=sys.stderr)
        return 0

    if args.cmd == "verse":
        from . import query
        q = query.CATSS(args.db)
        v = q.lookup_verse(args.book, args.chapter, args.verse)
        if v is None:
            print(f"not found: {args.book} {args.chapter}:{args.verse}", file=sys.stderr)
            return 1
        if args.format == "json":
            print(json.dumps(_verse_as_dict(v), ensure_ascii=False, indent=2))
        else:
            _print_verse_pretty(v)
        return 0

    if args.cmd == "lemma":
        from . import query
        q = query.CATSS(args.db)
        for hit in q.search_lemma(args.lemma, limit=args.limit):
            print(f"{hit.ref}  [{hit.position}]  {hit.surface_unicode}  ({hit.parse_code})")
        return 0

    if args.cmd == "books":
        from . import query
        q = query.CATSS(args.db)
        for osis, display in q.books():
            print(f"{osis:10s}  {display}")
        return 0

    return 2


def _verse_as_dict(v) -> dict:
    return {
        "ref": str(v.ref),
        "alignments": [
            {
                "mt_beta": a.mt_beta,
                "mt_unicode": a.mt_unicode,
                "mt_col_b_beta": a.mt_col_b_beta,
                "lxx_beta": a.lxx_beta,
                "lxx_unicode": a.lxx_unicode,
                "flags": {
                    "lxx_minus": a.is_lxx_minus,
                    "lxx_plus": a.is_lxx_plus,
                    "ketiv": a.is_ketiv,
                    "qere": a.is_qere,
                    "transposition": a.is_transposition,
                },
                "notes": a.notes,
            }
            for a in v.alignments
        ],
        "lxx_morph": [
            {
                "position": m.position,
                "surface": m.surface_unicode,
                "parse": m.parse_code,
                "lemma": m.lemma_unicode,
            }
            for m in v.lxx_morph
        ],
    }


def _print_verse_pretty(v) -> None:
    print(f"\n{v.ref}  ({v.ref.book_display})\n")
    if v.alignments:
        print("  MT ↔ LXX alignment:")
        for a in v.alignments:
            mt = a.mt_unicode or ""
            lxx = a.lxx_unicode or ""
            flags = []
            if a.is_lxx_minus: flags.append("LXX−")
            if a.is_lxx_plus:  flags.append("LXX+")
            if a.is_ketiv:     flags.append("K")
            if a.is_qere:      flags.append("Q")
            if a.is_transposition: flags.append("↔")
            flag_str = f"  [{','.join(flags)}]" if flags else ""
            retro = f"  (=col-b: {a.mt_col_b_beta})" if a.mt_col_b_beta else ""
            print(f"    {mt:<30}  ↔  {lxx}{flag_str}{retro}")
    if v.lxx_morph:
        print("\n  LXX morphology:")
        for m in v.lxx_morph:
            print(f"    {m.position:3d}. {m.surface_unicode:<18}  {m.parse_code or '':<12}  {m.lemma_unicode or ''}")
    print()


if __name__ == "__main__":
    sys.exit(main())
