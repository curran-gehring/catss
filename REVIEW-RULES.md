# catss review rules

Sent to the adversarial review lenses when a diff touches a matching path. Each rule records a defect that shipped or was caught once. Add a rule when a reviewer could have seen the defect in the diff.

## CCAT parsers (morphology and parallel)
paths: catss/parse_lxxmorph.py catss/parse_parallel.py

- `.mlxx` is a fixed-width format (surface `[0:25]`, parse code `[25:35]`, tail after). Whitespace splitting corrupted compound-verb lemmas such as `οἰκέω` from `παροικῆσαι`.
- A line or header the regex does not match must be counted and raised or reported, never skipped. A header regex that missed Samuel-Kings, EpJer, Susanna, Bel and the Esther-addition headers silently dropped 91,681 morphology words (Nehemiah had zero morphology). Verse headers may carry a subverse letter (`1:1a`) and ranges.
- `.par` lines have a column-a / column-b split: col-b is introduced by whitespace + `=` + non-whitespace. A plain tab split puts the retroverted col-b text in the MT column, and `=` markers leaked into col-b. Ketiv detection produced false positives.
- Apparatus must not be decoded as text: `<x.y>` cross-references, lowercase note codes and `[..]` apparatus injected dagesh characters; the `--+` plus-rows (13,693) and `''` were mis-decoded (correct: `־־ט` and `ʼʼ`).

## BETA code decoding
paths: catss/betacode.py

- Greek diacritics FOLLOW the vowel (`E)GE/NETO`); only after `*` (capital) do they precede the letter.
- Sigma is final only at the end of a word. Every non-final `ς` reached the shipped database (12,876 words) and broke lemma search (`μέςῳ`); the final-sigma fix-up must run per word, after the whole token is decoded.
- Hebrew sofit forms are applied per token in a post-pass (kaf, mem, nun, pe, zade). The holem-waw mark must follow its base consonant in canonical order, and dagesh is a combining mark that is not folded into precomposed forms.

## Database build and split
paths: catss/build_db.py catss/split.py catss/books.py

- Book ids are CATSS ids, not canon numbering (Daniel = 28, minor prophets shifted by one; 2Esdras ch 11-23 is Nehemiah, which had zero morphology while misfiled under Ezra). Map by `osis`, never by id arithmetic, and keep `UNIQUE (book_id, chapter, verse)`, `UNIQUE (verse_id, position)` and `UNIQUE (verse_id, row_order)`; a missing alignments UNIQUE once let duplicate rows in.
- Superscriptions and prefaces are stored as verse 0 of the chapter they introduce. Addition words keep their letter in `subverse` (`1:1a`); do not merge subverses into the base verse or drop them.
- `catss split` must keep refusing a non-slim source (`_assert_slim` raises). A full build split into the shippable files once produced a 26.7 MB base instead of ~22 MB.

## Repository contents
paths: raw/* *.sqlite *.db

- Raw CCAT files, `raw/docs/` and built databases are never committed: the data is governed by the CCAT user agreement (they were scrubbed from history before the repo went public). The repo carries only the build pipeline.
