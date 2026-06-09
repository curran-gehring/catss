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
# 1. download raw CCAT files (~35 MB, one-time)
catss fetch

# 2. parse + build catss.db (~114 MB — both BETA and Unicode preserved)
catss build

# ...or for iOS/mobile bundling, drop BETA columns:
catss build --slim --db catss-slim.db    # ~94 MB

# 3. (optional) split the slim db into shippable artifacts:
#    base  = alignment only (~28 MB), morph = LXX morphology (~67 MB)
catss split --db catss-slim.db --base catss.sqlite --morph catss_morph.sqlite
```

Pre-built databases are also available as
[release assets](https://github.com/curran-gehring/catss/releases) if you
prefer not to run the build yourself.

## Query

```bash
catss verse gen 1 1
catss verse ruth 1 1 --format json
catss lemma κύριος          # LXX lemma, Unicode...
catss lemma "KU/RIOS"       # ...or BETA-coded (full builds only)
catss books
```

Python:

```python
from catss import query

q = query.CATSS()                       # finds ./catss.db by default
verse = q.lookup_verse("ruth", 1, 1)
for pair in verse.alignments:
    print(pair.mt_unicode, "↔", pair.lxx_unicode, pair.notes)

for hit in q.search_lemma("κύριος", limit=10):
    print(hit.ref, hit.surface_unicode, hit.parse_code)
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
  Michigan-Claremont BHS text; accent numeric codes, angle-bracket
  cross-references (`<1.7>`), and text-critical apparatus tokens are
  stripped during decoding. If you need pointed and accented Hebrew, use
  the [Open Scriptures Hebrew Bible](https://github.com/openscriptures/morphhb)
  or Sefaria's BHS edition instead.
- **Esther addition subverses are merged.** The LXX Esther additions are
  versified `1:1a`, `1:1b`, ... in CCAT's morphology; their words merge
  into the base verse with continued positions (the subverse letter is
  not preserved).
- **Superscriptions are verse 0.** Ode/psalm titles and book prefaces
  (Odes, Psalms of Solomon, EpJer, Lamentations, Bel, OG Daniel) are
  stored as verse 0 of the chapter they introduce.

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
