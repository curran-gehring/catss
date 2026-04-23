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

# 2. parse + build catss.db
catss build
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
