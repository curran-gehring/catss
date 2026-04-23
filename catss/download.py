"""Download CATSS raw files from CCAT. Safe to re-run; skips existing."""
from __future__ import annotations

import pathlib
import sys

import httpx

from .books import all_par_stems, all_mlxx_stems

CCAT_BASE = "http://ccat.sas.upenn.edu/gopher/text/religion/biblical"

DOCS = [
    ("parallel/00.ReadMe.txt",             "docs/parallel-readme.txt"),
    ("parallel/00.ReadReParallel.txt",     "docs/parallel-re.txt"),
    ("parallel/00.betacode.txt",           "docs/parallel-betacode.txt"),
    ("parallel/00.user-declaration.txt",   "docs/user-declaration.txt"),
    ("lxxmorph/0-readme.txt",              "docs/lxxmorph-readme.txt"),
    ("lxxmorph/0-betacode.txt",            "docs/lxxmorph-betacode.txt"),
]


def fetch_all(root: pathlib.Path) -> None:
    root = pathlib.Path(root)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "parallel").mkdir(parents=True, exist_ok=True)
    (root / "lxxmorph").mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for rel, dest in DOCS:
            _fetch_one(client, rel, root / dest)

        for stem in all_par_stems():
            _fetch_one(client, f"parallel/{stem}.par", root / "parallel" / f"{stem}.par")

        for stem in all_mlxx_stems():
            _fetch_one(client, f"lxxmorph/{stem}.mlxx", root / "lxxmorph" / f"{stem}.mlxx")


def _fetch_one(client: httpx.Client, rel: str, dest: pathlib.Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    url = f"{CCAT_BASE}/{rel}"
    print(f"  fetch {url}", file=sys.stderr)
    resp = client.get(url)
    if resp.status_code == 404:
        print(f"    (skip: 404)", file=sys.stderr)
        return
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
