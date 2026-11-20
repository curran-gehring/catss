# NT Latin (Clementine) aligned to SBLGNT: design note

Status: approved by Curran 2026-11-19.

## Ground truth measured today

The packs were fetched from the live manifest with SHA-256 verified.
- Interlinear pack: etag 0b96e69b. The local `%APPDATA%` copy is stale (ef9e346c).
- Vulgate pack: etag 8118558d.

**SBLGNT in the shipped interlinear**
- 136,922 words across 7,914 verses, books 40–66.
- `word_position` has gaps in 2,244 verses. Mt 1:6, for example, skips 10–11, where words absent from SBLGNT were dropped. Positions are stable labels, not indexes.
- Mark 16:9–20 and Romans 16:25–27 are missing from the pack, although SBLGNT prints both. This is a gap in the interlinear pack and is out of scope here.

**Latin NT**
- 7,951 verses, 126,569 tokens.
- Source: catss `raw/vulgate/vul.tsv`, the same file the OT pack used. Its verses and order match FirstWord's `vulgata_clementina_verses.tsv`. The only difference is the poetic `[ ]` brackets, which the tokenizer drops.

## 1. Link key

`nt_align` links a Latin word to `(book_id, chapter, verse, word_position)` and stores `greek_surface`. `pack_info` records the sha256 and etag of the interlinear pack it was built against.

**Build gate.** A test resolves every link against the published interlinear pack, and every stored surface must equal `surface_text`. It must find zero dangling links and zero mismatches. `ship_vulgate_nt` repeats the check against the live manifest's interlinear before uploading.

**App fail-safe.** The app checks the surface when it reads a link. If the surface doesn't match, it hides the link and never shows a wrong Greek word.

## 2. Pack: separate download, `vulgate_nt.sqlite` (manifest key `vulgate_nt`)

**Recommendation: separate.** Reasons:
- **Different dependency.** The OT pack is keyed to catss ids. The NT pack is keyed to interlinear coordinates. With separate packs, a rebuild of one never forces a rebuild or re-download of the other.
- **OT row ids stay unchanged by construction.** `vulgate.sqlite` is not touched.
- **Installed builds are unaffected.** They don't know the key, so they never download the pack and never read it. This includes the paused iOS app. A combined pack would also need placeholder values in the OT map's NOT NULL `catss_osis` and `pivot` columns.

**Cost**

| Option | Who downloads what |
|---|---|
| Separate (recommended) | Users who already have the OT Latin download only the new pack, estimated 25–30 MB, when they open an NT Latin tab. Nothing is re-downloaded. New users with the Latin switch on get both packs, about 105 MB + 25–30 MB. |
| One combined pack | Everyone with the Latin pack, on every platform, re-downloads about 130–135 MB, including installed builds that can't use the NT rows. |

**Schema.** The NT pack reuses the OT `vulgate_words` and `lemma_glosses` shapes, so `lemmatize_vulgate` and `gloss_vulgate` run unchanged with `--pack`.

```
pack_info(key PK, value)                  -- interlinear sha256/etag, built_at
nt_verse_map(id, vul_book, vul_chapter, vul_verse,
             book_id, chapter, verse,     -- ESV "home" verse it is shown under
             seq, unit_id, status, note, text)
nt_unit_greek(unit_id, book_id, chapter, verse)
vulgate_words(id, verse_map_id, position, surface, norm, lemma, morph,
              latin_only INTEGER NOT NULL DEFAULT 0)
nt_align(id, vulgate_word_id, book_id, chapter, verse, word_position,
         greek_surface, confidence, method, UNIQUE(word, coordinate))
lemma_glosses(lemma, gloss, gloss_full)
```

## 3. Versification and textual differences

**Alignment units.** One or more Latin verses are aligned together with one or more Greek verses. Links may cross verse lines inside a unit, which handles verses split at different points.

**Status values.** Each Latin verse gets one status: `same`, `renumbered` (1:1 under another number), `unit` (more than one verse on either side), or `latin_only`. Latin-only verses are shown but never linked.

**Home verse.** Each Latin verse is shown under one ESV verse: the one holding most of its linked Greek words, or else the unit's first verse. A Latin-only verse whose number ESV skips (Acts 8:37, for example) is shown after the preceding verse and labelled with its Vulgate number.

**How the map is built.** A dynamic-programming verse aligner per book proposes units (1:0, 0:1, 1:1, 1:2, 2:1, 2:2), scored by a lemma translation table. I review every unit that isn't `same` by hand and freeze it in a checked-in `data/nt_units.tsv`. The aligner then runs in a test, and fails if it finds a shift the TSV doesn't cover.

**Invariants**
- Every Latin verse appears exactly once in the map.
- Every one of the 7,914 Greek verses belongs to exactly one unit.

**Your cases**

| Passage | Decision |
|---|---|
| 1 John 5:7–8 | One 2:2 unit. The Comma words are flagged `latin_only` at the word level and kept out of alignment: "in cælo : Pater, Verbum, et Spiritus Sanctus : et hi tres unum sunt. Et tres sunt, qui testimonium dant in terra". "Quoniam tres sunt, qui testimonium dant" and 5:8's witnesses still link. |
| Mark 16:9–20 (12 verses) | Latin-only (gap in our pack). Shown at its own numbers. It links automatically once the interlinear pack is fixed and this pack is rebuilt. |
| John 7:53–8:11 (12 verses) | Latin-only (SBLGNT keeps the passage in its apparatus). Shown at its own numbers. |
| Acts 8:37 | Latin-only, shown after 8:36 and labelled "8:37 (Vulg.)". |
| 3 John 14–15 | Unit: Latin 14 ↔ ESV 14–15; home verse 14. |
| Revelation 12:18 / 13:1 | Unit: Latin 12:17–18 ↔ ESV 12:17 ("stetit supra arenam maris" is the end of ESV 12:17). 13:1 is `same`. |
| 2 Corinthians 13:12–14 | Unit: Latin 12 ↔ ESV 12–13. Latin 13 ↔ ESV 14 (`renumbered`). |
| Romans 16:25–27 | Same place in both texts, so it doesn't need moving. It's Latin-only for now because of the pack gap. Romans 16:24 is Latin-only (textual). |

**Preliminary buckets**

These come from a quick IBM-1 content probe. The final counts will come with the build.

| Bucket | Latin verses |
|---|---|
| Same number, content confirmed | 7,837 |
| Same number, content belongs to a neighbour (blocks in Mt 17, Mk 9, Jn 6, Acts 7, Acts 14, 2 Cor 13, Lk 9:42–43; Mt 25:23 is probably probe noise) | 68 |
| No same-numbered Greek verse | 46 |
| – textual omissions (Mt 17:21, 18:11, 23:14; Mk 7:16, 9:44, 9:46, 11:26, 15:28; Lk 17:36, 23:17; Jn 5:4; Acts 8:37, 15:34, 24:7, 28:29; Rom 16:24; in the Vulgate, Mk 9's are at 9:43 and 9:45 and Mt 17's at 17:20) | 16 |
| – Pericope adulterae | 12 |
| – pack gap (Mk 16:9–20, Rom 16:25–27) | 15 |
| – seams (Mk 8:39 = ESV 9:1, Jn 6:72 = ESV 6:71, Rev 12:18) | 3 |
| Greek numbers with no Latin number (all renumbering: Mt 17:27, Mk 4:41, 9:50, Jn 11:57, Acts 7:60, 14:28, 2 Cor 1:24, 13:14, 3 Jn 15) | 9 |

Acts 7:59 Latin also carries "Saulus autem erat consentiens neci ejus", which is ESV 8:1a, so one unit crosses a chapter line.

## 4. Alignment method

**Tokens**
- Align lemma to lemma, not surface to surface. Both languages are heavily inflected, and the NT alone is about 8k verse pairs.
- Latin lemmas come from the same LatinCy pass as the OT. Greek lemmas are SBLGNT `lemma`.
- Both sides are lowercased with accents removed.

**Training data**
- The NT corpus.
- The OT verses Jerome translated from Greek: the lxx pivot, 7,009 verses and about 103k Latin words. Their Latin lemmas are paired with the `lxx_morph` lemmas from catss_morph.
- The OT pairs are used for training only, and their links are thrown away. This roughly doubles the Latin–Greek data, which matters more than a priors file.
- If needed, a priors file of OT intersection lemma pairs is a second lever.
- **Strong's: not used.** It adds nothing over the Greek lemma, and Latin has no Strong's numbers.

**Confidence tiers (precision first)**

| Confidence | Rule |
|---|---|
| 1.0 | eflomal forward ∩ reverse links |
| 0.5 | grow-diag-final links whose (Latin lemma, Greek lemma) pair is also an intersection link at least 3 times elsewhere in the corpus |
| not shipped | every other grown link |

The 1.0/0.5 meaning is the same as in the OT, so the app is unchanged.

**Gold standard**
- I hand-annotate John 1:1–5, Matthew 5:3–12, Romans 3:21–26, Hebrews 1:1–4 and Revelation 1:4–8 (about 330 Latin words) into `tests/fixtures/nt_gold.tsv`.
- Rule: a link is correct if the Latin word translates that Greek word, or the article of the noun it translates.
- I report precision and recall per tier, and coverage (Latin words with at least one link; all words and content words) on the samples and on the full corpus.
- **Bar:** the shipped links are at least 90% precise on the samples. If the 0.5 tier pulls them below that, only 1.0 links ship. The next levers are dropping article-only links and adding priors.

**Pipeline**

| Order | Step | Where it runs |
|---|---|---|
| 1 | `build_vulgate_nt` | anywhere |
| 2 | `lemmatize_vulgate --pack` | mac-mini |
| 3 | `align_vulgate_nt` | mac-mini (eflomal 1.0.0b2 is in its `.venv`) |
| 4 | `gloss_vulgate --pack` | anywhere |

## Licensing (checked today)

- **SBLGNT is now CC BY 4.0.** The body of sblgnt.com/license is the CC BY 4.0 legal code, and Faithlife/SBLGNT v1.1 (2022-12-19) says the same. Redistributing a derived alignment table is allowed with attribution, a licence notice, and an indication that it was modified.
  - Our Acknowledgements row still says "Used under the SBLGNT End User License Agreement". It should be updated to CC BY 4.0 and say that we added a word alignment.
- **LatinCy (la_core_web_lg) is MIT**, by Patrick J. Burns. The model card says nothing about whether its training treebanks (LASLA, UD Latin) constrain the outputs. I'll check those licences before shipping.
- **Whitaker's WORDS** grants "any and all use of program and data", but it is not a standard licence.
- **Missing credits.** LatinCy and WORDS already feed the shipped OT pack, but neither is in Acknowledgements. Add both rows.
