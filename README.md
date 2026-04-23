# catss

Queryable CATSS database. Builds a single SQLite file from the raw
[CATSS](http://ccat.sas.upenn.edu/gopher/text/religion/biblical/) data
distributed by the University of Pennsylvania's Center for Computer
Analysis of Texts (CCAT): morphologically analyzed LXX + Emanuel Tov's
parallel-aligned MT/LXX.

## Install

```bash
cd C:/Dev/catss
python -m venv .venv && source .venv/Scripts/activate
pip install -e .
```

## Build the database

```bash
# 1. download raw CCAT files (~5 MB, one-time)
catss fetch

# 2. parse + build catss.db (93 MB — both BETA and Unicode preserved)
catss build

# ...or for iOS/mobile bundling, drop BETA columns:
catss build --slim --db catss-slim.db    # 80 MB
```

## Query

```bash
catss verse gen 1 1
catss verse ruth 1 1 --format json
catss lemma בְּרֵאשִׁית
catss greek A)RXH=|   # BETA-coded
```

Python:

```python
from catss import query

verse = query.lookup_verse("ruth", 1, 1)
for pair in verse.alignments:
    print(pair.mt_unicode, "↔", pair.lxx_unicode, pair.note)
```

## Known limitations

Tracked for a future pass — these do not block correctness of the
common MT↔LXX + morphology use cases but are worth knowing:

- **Psalms versification divergence.** MT and LXX disagree on verse
  numbering in parts of the Psalter (LXX Pss 9/10, 113/114, 146/147,
  plus subtitle-as-verse-1 offsets). `.par` headers are persisted
  verbatim as-is; consumers matching on `(book, ch, v)` may get
  misaligned hits for a handful of Psalms. Workaround: normalize
  upstream, or use the LXX verse number shown in `[ ]` markup.
- **Hebrew cantillation/accents.** CATSS parallel files ship the
  consonantal text; accent numeric codes are stripped naively and
  angle-bracket references (`<1.7>` etc.) are not filtered.
- **Hebrew `position` is verse-local.** LXX morphology rows use
  `position` as the word-in-verse index. Always query with the
  composite `(book, chapter, verse, position)` key.
- **Slim build flag implemented.** `catss build --slim` drops the five
  BETA columns and VACUUMs. Savings are modest (~17%: 93 → 80 MB)
  because Unicode storage dominates; if further savings are needed,
  dropping `notes_json` and `mt_col_b_beta` (rare) gets you a few more
  MB. Slim builds still work with the Python query API and CLI — BETA
  fields come back as `None`.

## Data attribution

CATSS data © Center for Computer Analysis of Texts, University of
Pennsylvania. Underlying editions: Michigan-Claremont BHS consonantal
text (Hebrew) and TLG LXX based on Rahlfs 1935 (Greek). Morphological
coding and parallel alignment by the CATSS project under Emanuel Tov
(Jerusalem team) and the Philadelphia team.

Redistribution of the **raw** CCAT files is governed by the CATSS user
agreement (`raw/docs/user-declaration.txt`); this repository ships
only a derivative database. Not for commercial use without written
consent from CCAT.

Report encoding errors to `kraft at ccat.sas.upenn.edu`.
