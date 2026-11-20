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
- **Six `.par` verse headers are not the Hebrew Bible's numbers.** The
  parallel files head these verses differently from BHS. Headers are
  persisted verbatim, so the `alignments` rows hang on `verses` numbered
  as the files number them, and a consumer that joins the alignment to a
  Hebrew or English Bible on `(book, chapter, verse)` is one verse off
  there:
  - Lamentations 1: the Greek prologue is headed `1:1`, so the alignment
    rows of Hebrew 1:1-22 are stored as 1:2-23 (and the chapter has a
    verse 23).
  - Joshua 22: Hebrew 22:21 has no header of its own and runs on under
    `22:20`, so the chapter has 33 headers for 34 verses. `22:20` holds
    Hebrew 22:20-21, and the headers `22:21` to `22:33` head Hebrew
    22:22-34.
  - Deuteronomy 28:65, Ezekiel 34:28 and Daniel (Th) 7:21 each hold the
    verse before them as well (28:64, 34:27, 7:20, which have no
    alignment rows of their own).
  - Numbers `6:45` is a mistyped header: its one row is the first word of
    Numbers 26:45.

  The morphology files number these chapters the usual way (the
  Lamentations prologue is verse 0 there, as the superscriptions entry
  below says), so in these places one `verses` row carries the alignment
  of one verse and the `lxx_morph` words of another: Lamentations 1:1 has
  the prologue's alignment rows and the morphology of "πῶς ἐκάθισεν".
  Workaround: renumber the alignment's verses before joining. The list
  was found by comparing every verse's Hebrew with the Westminster
  Leningrad Codex; no other verse of the 39 Hebrew-canon books is
  numbered differently.
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
- **Superscriptions are verse 0 in the morphology.** Ode/psalm titles and
  book prefaces (Odes, Psalms of Solomon, EpJer, Lamentations, Bel, OG
  Daniel) are stored as verse 0 of the chapter they introduce. This is
  the `lxx_morph` side; the alignment keeps its own headers (see the
  `.par` headers entry above for the Lamentations prologue).

## New Testament Latin pack (`vulgate_nt.sqlite`)

The Clementine Vulgate New Testament, word-aligned to the SBL Greek New
Testament as it ships in FirstWord's `bible_interlinear.sqlite`. A separate
download from the OT `vulgate.sqlite`; design and decisions are in
[docs/nt-latin-design.md](docs/nt-latin-design.md).

Build against the **shipped** interlinear pack (fetch it from the live
FirstWord manifest and check its sha256), never an old local copy:

```bash
# 1. verse map + words (any machine)
python -m catss.build_vulgate_nt --interlinear bible_interlinear.sqlite --out vulgate_nt.sqlite
# 2. audit the curated verse map (catss/data/nt_units.tsv); must exit 0
python -m catss.nt_versemap_audit --interlinear bible_interlinear.sqlite --units catss/data/nt_units.tsv
# 3. LatinCy lemma + parse (mac-mini: spaCy + la_core_web_lg)
python -m catss.lemmatize_vulgate --pack vulgate_nt.sqlite
# 4. eflomal alignment (mac-mini); the OT pack and catss_morph add training lines.
#    Exits non-zero unless every link resolves against the interlinear.
python -m catss.align_vulgate_nt --pack vulgate_nt.sqlite --interlinear bible_interlinear.sqlite     --ot-pack vulgate.sqlite --catss-morph catss_morph.sqlite
# 5. Whitaker's WORDS glosses (DICTLINE.GEN from mk270/whitakers-words)
python -m catss.gloss_vulgate --db vulgate_nt.sqlite --dictline DICTLINE.GEN
# 6. quality report against the hand-checked gold links
python -m catss.eval_nt_gold --pack vulgate_nt.sqlite
# 7. the resolution test against the shipped interlinear
FW_VULGATE_NT=vulgate_nt.sqlite FW_INTERLINEAR=bible_interlinear.sqlite python -m pytest tests/test_align_vulgate_nt.py
```

Links name the Greek word by `(book_id, chapter, verse, word_position)` and
store its surface, so a rebuilt interlinear pack never silently re-points a
link: rebuild this pack whenever the interlinear's SBLGNT rows change.

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

The NT Latin pack also uses: the SBL Greek New Testament, Copyright 2010 by
the Society of Biblical Literature and Logos Bible Software, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (Greek forms are
copied unmodified; the word alignment is added); the Clementine Vulgate
(public domain); lemmas and parsing from the
[LatinCy](https://huggingface.co/latincy/la_core_web_lg) model (MIT, Patrick
J. Burns); glosses from William Whitaker's WORDS ("freely given for any and
all use of program and data").

The original CCAT coordinator, Robert Kraft (UPenn), passed away in
2023, and CCAT no longer has an active maintainer. For issues with
this SQLite layer or the build pipeline, please open an issue on this
repository.

## License

The source code in this repository is licensed under
[CC BY-NC 4.0](LICENSE). The CATSS data the build pipeline consumes is
governed separately by the CCAT user agreement.
