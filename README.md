# catss

Queryable CATSS database. Builds a single SQLite file from the raw
[CATSS](http://ccat.sas.upenn.edu/gopher/text/religion/biblical/) data
distributed by the University of Pennsylvania's Center for Computer
Analysis of Texts (CCAT): morphologically analyzed LXX + Emanuel Tov's
parallel-aligned MT/LXX.

## Install

```bash
git clone https://github.com/curran-gehring/catss.git
cd catss
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
```

## Build the database

```bash
# 1. download raw CCAT files (~5 MB, one-time)
catss fetch

# 2. parse + build catss.db (93 MB — both BETA and Unicode preserved)
catss build

# ...or for iOS/mobile bundling, drop BETA columns:
catss build --slim --db catss-slim.db    # 25 MB
```

Pre-built databases are also available as
[release assets](https://github.com/curran-gehring/catss/releases) if you
prefer not to run the build yourself.

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

LXX morphology rows index words by their position within the verse, so
always query using the composite key `(book, chapter, verse, position)`.

## Known limitations

- **Psalms MT/LXX versification divergence.** MT and LXX disagree on verse
  numbering in parts of the Psalter (LXX Pss 9/10, 113/114, 146/147, plus
  subtitle-as-verse-1 offsets). `.par` headers are persisted verbatim;
  consumers matching on `(book, ch, v)` may get misaligned hits for a
  handful of Psalms. Workaround: normalize upstream, or use the LXX verse
  number shown in `[ ]` markup.
- **Hebrew text is consonantal only.** CATSS ships the unvocalized
  Michigan-Claremont BHS text; accent numeric codes are stripped naively
  and angle-bracket cross-references (`<1.7>` etc.) are not filtered. If
  you need pointed and accented Hebrew, use the
  [Open Scriptures Hebrew Bible](https://github.com/openscriptures/morphhb)
  or Sefaria's BHS edition instead.

## Data attribution

CATSS data © Center for Computer Analysis of Texts, University of
Pennsylvania. Underlying editions: Michigan-Claremont BHS consonantal
text (Hebrew) and TLG LXX based on Rahlfs 1935 (Greek). Morphological
coding and parallel alignment by the CATSS project under Emanuel Tov
(Jerusalem team) and the Philadelphia team.

Redistribution of the **raw** CCAT files is governed by the CATSS user
agreement; this repository ships only the build pipeline (the raw files
and the derived database are not redistributed here). Not for commercial
use without written consent from the CATSS data owners.

The original CCAT coordinator, Robert Kraft (UPenn), passed away in
2023, and CCAT no longer has an active maintainer. For issues with
this SQLite layer or the build pipeline, please open an issue on this
repository.

## License

The source code in this repository is licensed under
[CC BY-NC 4.0](LICENSE). The CATSS data the build pipeline consumes is
governed separately by the CCAT user agreement.
