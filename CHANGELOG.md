# Changelog

[繁體中文（台灣）](CHANGELOG.zh-TW.md)

## 1.4.0rc1 - Unreleased (local RC candidate)

This release candidate has not been published or tagged. Its accepted first-version scope is Windows Basic with manual/external AI XLSX or JSONL returns, technical Validate, Rebuild, and the default workflow Dry-run. Apply/Rollback and in-game loading require separate authorization and acceptance.

### Integrity and packaging
- Canonical locale/material roles (A1), scan-bound PAK freshness (A6), and complete repack entry/SHA checks (A8).
- Prepare-time basic-source-baseline/1 receipt and current validation/rebuild/install eligibility (M2-B1/B2); preserve historical results and isolate failed candidates. Old workspaces without a receipt require fresh Prepare/Validate while retaining edited returns.
- Retain Provider error privacy (A2), Legacy Review/QA evidence binding (A5), full pytest CI configuration, and public synthetic sdist fixtures (A3/A4). These do not activate automatic Provider workflows.
- Set package/runtime version to 1.4.0rc1 and new research-export producer stamp to bg3loc-1.4.0rc1; request IDs, prompt bytes, request fingerprints and frozen contracts remain unchanged. Existing exports/history are not rewritten.

### Scope and pending gates
- B1-03 stays OFF with production transport blocked. Production/Provider, B1-02 activation, Legacy Production Finalize (A7 implementation DEFERRED), native Linux/macOS and general dialogue safety are outside first Basic acceptance.
- Four GitHub-hosted jobs remain NOT VERIFIED. HTTP WinError 10013 is environment-blocked, not PASS; Windows long paths, host symlink permissions and three research BOM schemas remain documented limitations.
- Stable/release publication, Windows Native real-installation read-only acceptance, and separately authorized small-scope game-load/Apply/Rollback remain pending. Use one operator and retain original Extract/baseline paths.

See docs/releases/v1.4.0rc1.md for the RC boundary. Earlier version entries below retain their original dates and acceptance evidence.

## 1.3.0 - 2026-09-28

### Added
- A production workflow for larger localization projects: functional classification, category-aware batching, and resumable execution with an OpenAI-compatible provider.
- QA routes (PASS / RETRY / REVIEW / FAIL), human review decisions, and completion-gated finalize/rebuild.

### Reliability and safety
- Bounded retry pacing with `Retry-After` and exponential backoff for temporary provider failures.
- Explicit decisions for unclassified rows; they are not silently treated as translated.

### Reporting
- Read-only progress and error reports, provider-reported token usage, and optional estimates using user-supplied prices.

### Documentation and public release
- Newcomer, ruleset, and troubleshooting guides, plus a fictional end-to-end smoke demo that does not create installable game content.
- A new public Git history containing the sanitized product tree rather than private development ancestry or game-derived corpus.

### Validation
- 464 tests and 75 subtests passed on the public repository; wheel and source distribution clean-room demos passed.


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
