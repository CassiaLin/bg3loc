# Research preservation census — 2026-09-09

## Status

This census records what is currently confirmed to survive in the user's ChatGPT File Library and what is still only referenced by surviving workbooks.

## Confirmed surviving workbooks

The following four research/translation workbooks are confirmed present:

1. `bg3-english-only-full-translation-review.xlsx`
   - formal boundary: 14,194 unique `ContentUid`
   - `ContextEvidence`: 679 evidence-backed targets
2. `phase4w-bark-human-review.xlsx`
   - 289 Bark targets
   - 277 `SingleSpeaker`
   - 12 `SharedSpeaker`
   - preserves `EvidenceReference`, `SharedSetMembers`, package/path, DialogUUID, NodeUUID, speaker evidence and review decisions
3. `phase4ad-quest-human-review.xlsx`
   - 94 Quest/Journal targets
   - 7 `QuestTitle`
   - 87 `QuestDescription`
   - all have `StrongQuestProgressContext`
   - all 94 were missing from Traditional Chinese XML at review-package construction time
4. `bg3-four-language-translator-table-filled.xlsx`
   - formal boundary: 14,194 rows
   - 706 reusable Traditional Chinese exact references
   - 1,069 Traditional Chinese conflict targets
   - 13 Simplified Chinese same-UID references
   - 29 Russian same-UID references
   - 1,803 rows with any auxiliary reference
   - 10,382 reviewer translations filled

## External evidence explicitly referenced but not found in File Library search

The Bark workbook `EvidenceReference.SourceReport` explicitly points to:

- `reports/phase4u-target-context-evidence.csv`
- `reports/phase4v-review-readiness.csv`

A File Library search on 2026-09-09 did not find standalone files with those names. Therefore their current preservation state is:

`NOT CONFIRMED / MUST PRESERVE IF FOUND IN OLD WORKSPACE`

The surviving Bark workbook preserves substantial selected evidence derived from those reports, but not necessarily every candidate, negative result, or traversal step contained in the original reports.

## Current preservation classes

### SAFE TO RECONSTRUCT after Windows Tier 1 acceptance

- raw LOCA extracts
- LOCA → XML conversion products
- basic `ContentUid`/text/version normalized records
- basic English ↔ target-locale alignment
- basic translation workbooks generated from current game resources

### SAFE TO ARCHIVE, NOT DELETE YET

- the four confirmed workbooks above
- the translation-team delivery package containing derived workbook partitions

These are no longer the only copy of the migration logic, but remain the current authoritative historical research baseline until clean-install context reconstruction is verified.

### MUST PRESERVE IF FOUND

- `phase4u-target-context-evidence.csv`
- `phase4v-review-readiness.csv`
- any provider/patch-overlay candidate inventory
- any rejected-candidate or negative-evidence reports
- any resource/handle traversal traces not embedded in the four workbooks
- evidence used to derive `BG3-OFFICIAL-PATCH-OVERLAY`
- evidence used to derive `BG3-OFFICIAL-PATCH-OVERLAY-MATERIALIZATION`
- evidence used to derive `BG3-STAT-DIRECT-LOCALIZATION-REFERENCE`

## Important limitation

The four File Library workbooks can be searched and read through ChatGPT, but File Library references are not exposed as raw `.xlsx` filesystem paths to the local execution environment. Therefore `scripts/extract-research-baseline.py` cannot be executed directly against those library references in this session.

To produce byte-derived `research-baseline.jsonl` and source-workbook SHA-256 manifests, the original `.xlsx` files must be present as local files in a machine/workspace where the extractor runs.

Until that extraction is run, this census is an evidence-backed inventory, not a byte-level migration artifact.
