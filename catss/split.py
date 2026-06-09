"""Split a (slim) catss DB into two shippable artifacts.

The slim build packs both the MT↔LXX parallel alignment AND the per-word
LXX morphology into one ~94 MB file. Only the alignment drives a shipped
feature (the Parallel tab); the morphology is ~67 MB / ~70% of the file
and feeds optional, opt-in features. So we ship two artifacts:

  base  — books + verses + alignments (+ their indexes). ~28 MB. Small
          enough to bundle inside the iOS app so the Parallel/alignment
          tab works on first launch with no download.

  morph — books + verses + lxx_morph (+ their indexes). ~67 MB. The LXX
          word-level parsing + lemma concordance. Optional download,
          fetched only when the user enables those features in Settings.

Both are derived from ONE already-built slim DB (`catss build --slim`, or
the currently-shipped catss.sqlite), so their schema matches exactly what
the app expects — we just drop the table the artifact doesn't need and
VACUUM to reclaim the freed pages. `books` and `verses` are kept in both
(verses is joined by every query; books by the lemma concordance) and are
negligible (<0.4 MB).
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3


_COUNT_TABLES = ("books", "verses", "alignments", "lxx_morph")


def _derive(src: pathlib.Path, dst: pathlib.Path, *, drop_table: str) -> dict:
    """Copy `src`, drop `drop_table` (its indexes go with it), VACUUM."""
    if dst.exists():
        dst.unlink()
    shutil.copyfile(src, dst)
    conn = sqlite3.connect(dst)
    try:
        conn.execute(f"DROP TABLE IF EXISTS {drop_table}")
        conn.commit()
        conn.execute("VACUUM")
        counts: dict[str, int | None] = {}
        for t in _COUNT_TABLES:
            try:
                counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[t] = None  # dropped in this artifact
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return {
        "path": str(dst),
        "size_bytes": dst.stat().st_size,
        "rows": counts,
        "integrity": integrity,
    }


def _assert_slim(src: pathlib.Path) -> None:
    """Refuse a full (non-slim) source db.

    Splitting a full build silently ships the BETA columns — ~5 MB of dead
    weight in the bundled base artifact. This exact mistake produced a
    26.7 MB catss.sqlite (vs ~22 MB slim) once already; fail loudly instead.
    """
    conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(alignments)")}
    finally:
        conn.close()
    if "mt_beta" in cols:
        raise ValueError(
            f"{src} is a FULL build (has BETA columns). Split only slim dbs: "
            f"rebuild with `catss build --slim --db {src}` first."
        )


def split(src_db: pathlib.Path, base_db: pathlib.Path,
          morph_db: pathlib.Path) -> dict:
    """Produce the base (alignment) and morph artifacts from `src_db`."""
    if not src_db.exists():
        raise FileNotFoundError(src_db)
    _assert_slim(src_db)
    return {
        "source": {"path": str(src_db), "size_bytes": src_db.stat().st_size},
        "base": _derive(src_db, base_db, drop_table="lxx_morph"),
        "morph": _derive(src_db, morph_db, drop_table="alignments"),
    }
