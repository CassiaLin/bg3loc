# Changelog

[繁體中文（台灣）](CHANGELOG.zh-TW.md)

## Unreleased — v1.3 development

- Added workspace-oriented production prepare, resumable OpenAI-compatible execution, QA and human review, completion-gated finalize/rebuild, and retry pacing.
- Added read-only production progress, provider token usage, and optional user-priced cost reports.
- Added a newcomer workflow, ruleset and troubleshooting guides, plus a fictional package smoke demo.


## 1.2.0 - 2026-09-27

### Added
- Added a large-scale translation production workflow for tens or hundreds of thousands of `ContentUid` rows.
- Added deterministic functional classification and category-aware batching.
- Added resumable translation execution state with provider attempt history, retry, lease, and recovery.
- Added automatic QA routing: PASS / RETRY / REVIEW / FAIL.
- Added production completion and a merge-ready bridge so only safe rows can enter rebuild.
- Added human REVIEW resolution: accept the current candidate or revise it; revised output must pass QA again.
- Added auditable `assign`, `exclude`, and `pending` decisions for `other / unclassified` rows.

### Safety and reproducibility
- Every `ContentUid` keeps one production owner; batches, provider requests, and review queues never create a second translation job.
- Human REVIEW approval is bound to the QA ruleset, QA input hash, and output hash; any change invalidates the old approval.
- The resolved classification ledger is bound into the batch fingerprint through its SHA-256.
- Explicitly excluded rows are exported separately from still-unresolved rows.

### Acceptance
- LSTP-01A through 01F: accepted.
- Public Large-Scale Workflow Integration 02A: complete.
- Production Human Review Resolution 02B: accepted.
- Unclassified Resolution Policy 02C: accepted.
- Final integrated regression: `408 passed`, `68 subtests passed`, `0 failed`.
## 1.1.0 - 2026-09-20

### Added
- Added the public end-to-end translation workflow and high-level project/workflow CLI.
- Added schema-backed project configuration and workflow state.
- Added `basic`, `context`, and `full` evidence profiles plus `standard` and `blind-first` translation strategies.
- Added explicit ContentUid scope for small or controlled translation projects.
- Added Bark, Quest, UI/Skill, multilingual, and Taiwan-usage review workflows.
- Added reproducible research mapping generated from the user's own BG3 installation.
- Hardened release packaging so source distributions include public documentation and schemas.

### Acceptance
- E2E-01A through 01F completed.
- Windows clean-room real-game workflow passed scan / extract / prepare / validate / rebuild / install dry-run.
- Release regression baseline at the time: `294 passed`.

## 1.0.0 - 2026-09-11

### Added
- Complete `scan` → `extract` → `build` → `validate` → `rebuild` → `install` processing workflow.
- Works with any game language pairs found in your game without being forced to use specific ones.
- Different ways to translate: basic, with context, or translating without seeing the original translation first.
- Support for Excel (XLSX) and spreadsheet (CSV) translation files that keep the original text safe and make sure game codes aren't broken.
- Checks to make sure the game's compressed package files are rebuilt correctly.
- Safe testing mode (`install --dry-run`), automatic backups, safety checks, and the ability to undo changes.
- Passed real testing on Windows with the ability to completely undo the changes.
- Tested and works with translating English to French as a proof of concept.
- Standard MIT license.

### Platform and validation status
- Windows 11 is the primary tested platform.
- Requires Python 3.11 or newer (tested on 3.12).
- Requires `Divine.exe` (a third-party unpacking tool from LSLib 1.20.4) on Windows.
- Linux/Proton and macOS have not been fully tested yet.
- We do not guarantee it works on every single system.

### Data boundary
- We do not share official Baldur's Gate 3 text or translation files.
- You must get the game's language files directly from your own game.
- You must download the third-party unpacking tool separately.

## 1.0.0-rc1 - 2026-09-10

### Added
- The full `scan` → `extract` → `build` → `validate` → `rebuild` → `install` processing workflow.
- Basic, context, and blind-first translation modes.
- Works with whatever languages you have installed.
- Can automatically find where Baldur's Gate 3 is installed on Steam.
- Added support for the third-party unpacking tool (LSLib).
- Added CSV and XLSX spreadsheet formats for translation.
- Added checks to protect game codes and formatting.
- Safe testing, backups, and undo features.

### Validation and safety
- Tested the Windows 11 processing workflow on a real Steam game.
- Tested the full process from `scan` to `install`, including undoing the changes.
- Added safety checks so the backend tool stops if something is wrong, rather than pretending it worked.
- Cleaned up warning messages when you only translate part of the text.

### Current validated environment
- Windows 11 is our main testing platform.
- Python 3.12 is tested; Python 3.11+ is supported.
- LSLib 1.20.4 is our tested third-party unpacking tool.
- Steam version of Baldur's Gate 3 is our tested game version.

### Current limitations
- Linux/Proton and macOS are not fully tested.
- This test version doesn't mean it works on all platforms.

### Data boundary
- We do not share official game text.
- You extract game files from your own game.
- You get the third-party unpacking tool separately.
