# B1-03 Phase 6 Stage 4R — Activation Blocker Remediation

Date: 2026-10-10. Status: **READY FOR REVIEW**. Production Activation: **NOT APPROVED**.

## Scope and authority

**VERIFIED**: branch `feat/b1-03-dialogue-context`, HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb`. Prior Phase 3/5 and Stage 0–4
working files were sealed before this work. No commit, push, merge, provider
activation, paid model call, or new real-text translation occurred.

Stage 0 schema/registry/policy bytes remain unchanged. Policy A, 2,000 Unicode
codepoints, whole-set rejection, H0/HSE/HD, `dialogue-prompt/1`, semantic REVIEW,
`production-context-contract/2`, and D7 remain authoritative. No Contract Change
Request was necessary. Existing 1.3 start/claim/worker/provider stop guards remain.

## A. Resolver profiling and remediation

**VERIFIED root cause**: a 1.3 offline resolver originally invoked
`validate_stage2_workspace` during construction and again for every resolution.
That validates all 218,272 execution items and decodes the entire 27,946-target
dialogue material repeatedly. File hashing and JSON schema checks are a small
part of the observed cost; weakening them would not solve the main problem.

Real full-validation cProfile (84.324 s wall; profiling adds overhead):

| Operation | Calls | Cumulative seconds |
| --- | ---: | ---: |
| Full workspace/manifest/execution contract validation | 1 | 84.222 |
| Dialogue DTO decoding | 55,892 | 40.775 |
| Translation input hashing | 218,272 | 30.835 |
| Strict JSON decoding/material scanning | 684,033 | 15.017 |
| B1-02 material verification | 1 | 5.326 |
| DB inventory canonical fingerprint | 1 | 2.297 |
| File SHA256 | 296 | 0.483 |
| JSON schema iteration, including schema loading | 4 | 0.104 |

Cumulative times overlap; they must not be added. Typed decoding,
canonicalization and input hashing call each other. The earlier unprofiled
Stage 4 measurements remain the before benchmark. Full workspace verification
(47.77 s) and QA/review full preflights are not claimed to have been optimized.
The production worker stop guard was already ~0.002 s and remains in place.

**IMPLEMENTED / VERIFIED**: `sealed_snapshot.py::SealedRunSnapshot` replaces
repeated all-material validation with a per-resolver, process-owned snapshot:

1. Pin the complete runtime file closure before full validation: manifest,
   batching plan/materials, ruleset, classification, both context summaries,
   and D7 descriptor. Validate every original fingerprint/schema/binding once,
   within a SQLite read snapshot. Check file SHA before and after capture.
2. On Windows, hold deny-write/delete handles on all 298 runtime files and
   their directory ancestry. Pin the mutable DB with share-read/write but
   deny-delete; SQL updates remain legal, replacing the DB cannot leave the
   resolver reading an obsolete connection. Check file identity and reparse
   attributes at both ends of each use.
3. Store deep immutable typed materials in a read-only per-run mapping. No
   mutable research dictionary, shared global cache, or mtime-based trust.
4. In every resolution, verify all bound DB metadata, the current input/batch,
   and the supplied claim/live attempt/owner. Read `data_version` before and
   after establishing the SQLite snapshot and after committing it. Concurrent
   commits retry with full inventory validation; repeated races fail closed.
5. On every changed DB generation, compare the complete UID/batch/input
   inventory, including other UIDs, additions and removals. Caller-owned writer
   transactions always do this comparison. Output/QA writes may change the
   generation but cannot silently change material identity.
6. A closed or inherited snapshot is unusable. Each process/resume creates a
   new full validated snapshot. Shared thread reads serialize on a per-instance
   lock; close uses that lock too. Release pins explicitly with `close()`.

On hosts without Windows share-denial, rehash the **entire runtime closure** on
each use; no Windows performance claim applies there. A simulated nonlocking
test rejects same-size/same-mtime tampering. Actual POSIX OS behavior and its
performance were not measured on this Windows host.

Runtime validation has always checked the D7 descriptor without reading role
payloads. That boundary is preserved. Finalize separately verifies every D7
payload's size, SHA and semantics; the snapshot does not bypass asset closure.
Pending-state preview claims exist only in the explicit offline fixture path.
Actual-send provenance still verifies live owner/current input/lease in its
writer transaction, before any transport could occur.

### Before / after real corpus benchmark

**VERIFIED**: full real workspace copy; 218,272 execution items, 27,946 dialogue
contexts; 30 HD resolutions, with 29 steady samples. Last run:

| Measurement | Before | After |
| --- | ---: | ---: |
| Resolver construction / full startup | 38.93 s | 50.758 s |
| First resolution / inventory generation check | 40.07 s | 0.441 s |
| Steady resolution mean | 40.07 s | 0.03634 s |
| Steady resolution maximum | — | 0.03880 s |
| Resolution after a legal DB commit | — | 0.433 s |

Before is the Stage 4 observation, not a statistically sampled distribution.
The startup measurement ran alongside regression work; earlier new-design
runs were 41.87/46.88 s. No startup-speed improvement is claimed. The ~1,103x
steady comparison amortizes full validation, rather than eliminating it.
Normal claim/provenance/QA commits incur inventory-generation work, so 0.036 s
must not be presented as total worker throughput. Full-inventory comparison
after commits remains O(N) (~0.43 s here), intentionally preserving coverage.

Local evidence: `workspace/b1-03-phase6-stage4r/resolver-before.prof`,
`profiling-before.txt`, `profiling-breakdown.json`,
`resolver-after-benchmark.json`, `benchmark-resolver.py`.

## B. Production-shaped case-006 replay

**VERIFIED package prepared / EXTERNAL EVALUATION PENDING**:
`workspace/b1-03-phase6-stage4r/case006-replay/`.

Only give ChatGPT **`chatgpt-translation-requests.jsonl`**. It contains two
opaque request IDs and independent formal `messages` arrays: one H0 baseline
and one grouped Dialogue Context request. The original target source/runtime
syntax is preserved. Context is projected by the actual `dialogue-prompt/1`
renderer, with the unchanged seven safety instructions. The context retains
947 codepoints across 3 predecessor and 13 successor source variants.

No prior translations, condition labels, hidden assignments, proof/node IDs,
context fingerprints or resource paths are exported as dialogue fields. The
legacy top-level request fields are preserved to reproduce the production
prompt. Context presence is inherently visible to the translator; the future
reviewer receives independently shuffled neutral variant IDs and no request
IDs or condition mapping.

`assignments-local-only.jsonl`, `replay-local-manifest.json` and the template
remain local. Random IDs/assignment order are persisted and fingerprinted;
do not regenerate the package after sending requests. No extra cases or bulk
external translation were launched.

### Import and blind review procedure

Ask ChatGPT to execute each messages array independently, translate only the
top-level target, and return exactly two JSONL records with `requestId` and
`translationText`. Save the unchanged response file locally. Then:

```python
from pathlib import Path
from bg3loc.dialogue_semantic_replay import (
    import_semantic_replay_responses, validate_semantic_replay_review,
)
package = Path("workspace/b1-03-phase6-stage4r/case006-replay")
import_semantic_replay_responses(
    package, package / "responses.jsonl", translation_source="ChatGPT (record model/date)",
)
# Give ONLY the newly generated blind-review-ready.jsonl to the reviewer.
# Save the completed assessment locally, then validate it:
validate_semantic_replay_review(package, package / "blind-review-completed.jsonl")
```

Run from this checkout in its Python environment (`bg3loc` installed, or
`PYTHONPATH=src`). The package README states the same handoff boundary.
Strict import rejects missing/duplicate/unknown IDs, unknown fields, malformed
text, runtime token or markup changes; no repair or partial blind publication.
The review must preserve original source/translations and fill every closed
assessment field: meaning, drift, unsupported additions, alternatives-as-sequence,
reviewer and notes. Original blind-file tampering fails its import seal.

Import/review validation never unblinds or awards a safety verdict. After a
valid external blind assessment, separate local adjudication must use the
hidden mapping. This one case can establish only the known-risk regression
status; it cannot establish overall safety. **Safety Regression is NOT EVALUATED.**

## C. Real workspace concurrency and finalize rollback

**VERIFIED** on an isolated copy of the real complete 1.3 workspace:

- `BEGIN IMMEDIATE` barrier blocks independent QA and review writers.
  These are isolated SQL contention probes on the real tables, not an
  application lifecycle replay of reviewed real translations.
- A concurrent WAL reader retains its original snapshot across a writer
  commit, then sees the new value only after releasing that read transaction.
- Same-transaction completion and logical snapshot remain consistent across
  218,272 targets. A probe write rolls back correctly; original workspace
  files/DB were not modified. No finalized output or real translation was made.
- Observed pending-workspace barrier time: **57.518 s**, including full
  contract/completion validation and two contention probes.

**LIMITATION / Stage 5 blocker**: this real workspace has **zero reviewed
translations** and all targets are waiting for translation. This is a real
large-inventory barrier measurement, not a completed-workspace merge/rebuild/
repack lock duration. Full reviewed-workload duration remains **NOT MEASURED**;
synthetic subsecond timing is not used to infer it.

`portable_finalize.py::finalize_portable_workspace` now retracts its own newly
published output if SQLite barrier-release/commit fails, and rolls back SQL.
Added offline tests verify a same-transaction QA mutation invalidates the
completion snapshot, rejects publication and restores the prior QA state;
a post-rename commit failure removes the output. Existing tests still cover
blocked concurrent writers, D7 checks, roundtrip/repack payload parity and
repack failure without partial publication.

Local evidence: `real-concurrency-findings.json`, `concurrency-log.txt` and
`concurrency-real/` under the ignored Stage 4R workspace.

## D. Changes and integrity equivalence

Six pre-existing files changed relative to the Stage 4R start seals:

| File / function | Change |
| --- | --- |
| `dialogue_execution_contract.py::validate_stage2_workspace` | Private typed item collector during the existing full validation |
| `translation_request.py::BatchMaterialResolver` | Per-run sealed material resolution and explicit close; legacy path unchanged |
| `execution_state.py::record_prompt_provenance`, `complete_success` | Optional bound snapshot reuse within current writer/owner/input guards |
| `offline_integration.py::run_offline_integration` | Pass its own validated snapshot and release it; static outcomes only |
| `portable_finalize.py::finalize_portable_workspace` | Output rollback on barrier-release failure |
| `tests/test_dialogue_stage2.py` | Existing tamper test also accepts OS denial, then checks closed/resume rejection |

New source: `sealed_snapshot.py`, `dialogue_semantic_replay.py`; new synthetic
tests: `test_dialogue_stage4r.py`; this report is new. Schema/version registry,
prompt assembly/renderer, translation identity, provider and other prior work
are byte-preserved. Additive Stage 3 migrations remain unchanged.

Mutation tests cover manifest stripping, plan/material/ruleset/summary/
classification/D7-descriptor mutation, cross-process deletion, database
replacement, full inventory tampering, metadata stripping, owner mismatch,
startup TOCTOU, commits at both early/late read boundaries, thread concurrency,
resume and nonlocking rehash. Current QA/review/input/output/finalize binding,
H0/HSE parity, HD changes, B1-02 behavior, fallback and privacy stay covered by
the prior suites. There is no new transport path.

## Tests and final audit

- Stage 1–4R targeted run: **252 passed, 1 skipped**; final Stage 4R-only run:
  **33 passed**, including the subsequently added nonlocking fallback case.
- Final full available regression: **1,189 passed, 1 skipped, 75 subtests
  passed**, 113.21 s. H0/HSE parity, HD identity, B1-02, Stage 3 review gates,
  D7 portability, LOCA/repack, whole-set fallback and packaging tests pass.
- Initial full attempt: **1,182 passed, 1 skipped, 75 subtests passed**, with
  the existing fictional HTTP demo failing. Its attempt ledger contains three
  `PROVIDER_TRANSPORT_ERROR` entries with **WinError 10013**. This is explicitly
  **environment-blocked**, not PASS. Only that diagnosed demo file was excluded
  from the final available regression. No production transport was invoked.
- The skip is host refusal to create a symlink. Reparse-attribute rejection
  still passes. Windows process/file share guards, early/late DB read races,
  rollback and atomic publication tests pass.
- Starting-file audit: **368 seals**, exactly six expected prior-file changes,
  no unexpected edits/deletions. Frozen contracts and all other prior file
  bytes are preserved. New source/tests/report contain no real ContentUIDs;
  proprietary material and hidden mappings stay in Git-ignored `workspace/`.
- Git status: **21 modified, 30 untracked**, including all prior-stage work;
  no staged changes, no commit/push/merge. HEAD and branch unchanged.
  `git diff --check` passes. Four Stage 4R files are new; other dirty entries
  are retained work, not attributed to this stage.

Local evidence: `pytest-targeted-final.txt`, `pytest-4r-final.txt`,
`pytest-full.txt`, `pytest-full-final-all.txt`,
`final-source-privacy-audit.json`, `git-status-final.txt` under
`workspace/b1-03-phase6-stage4r/`.

## Remaining Stage 5 blockers / recommendation

1. External case-006 formal-renderer translations, complete blind assessment
   and separate local adjudication. Do not mark safety PASS before these exist.
2. Real reviewed-workload finalize/concurrency/lock measurements, once enough
   independently reviewed translations are available.
3. Review the sealed snapshot equivalence and measured startup/commit costs;
   do not assume steady resolution latency equals worker throughput. Non-Windows
   native behavior/performance remains unmeasured.
4. Independent Stage 5 activation approval, retaining SAFE WITH RESTRICTIONS
   and all prepare/build/D7/semantic-review requirements.

**B1-03 Phase 6 Stage 4R — READY FOR REVIEW**.
Production Activation remains unapproved; Stage 5 was not started.

## Appended case-006 adjudication update — 2026-10-10

**VERIFIED**: the user-provided schema-fixed blind review passed the existing
strict validator. Source/context/translations, request/template fingerprints
and blind-input seals match; local assignment validation and response-to-variant
binding then passed. Baseline and grouped translations are UTF-8 byte-identical.
The bound blind assessment records preserved meaning for both, no unsupported
additions or alternatives-as-sequence error, and `semanticDriftVariant=neither`.

Formal scoped verdict: **NO OBSERVABLE REGRESSION** for the one known-risk case
under `dialogue-prompt/1`. Context worse: 0; context better: 0; no observable
difference: 1. Context-specific degradation and contamination were not observed;
contamination is a derived observation, not a dedicated score or causal proof.

The pending case-006 replay/adjudication requirement in the earlier sections
is now complete **for this case only**. Those sections describe the state at
the original implementation report and remain unchanged as historical evidence.
The original 25-pair pilot's case-006 context-worse observation remains intact.
This replay does not establish GENERAL SAFETY VALIDATED, quality improvement,
or safety for untested branches, and does not remove SAFE WITH RESTRICTIONS.

Independent report:
`docs/research/b1-03-stage4r-case006-semantic-regression-adjudication.md`.
Detailed mapping, texts and assessment remain in the ignored local replay
workspace; this report discloses none of them.

Current status: Stage 4R **CONDITIONALLY ACCEPTED**;
**case-006 SEMANTIC REGRESSION ADJUDICATED**. Remaining Stage 5 requirements are
real reviewed-workload finalize/concurrency measurements, sealed snapshot
integrity/performance acceptance, continued SAFE WITH RESTRICTIONS, and an
independent Activation Review. Stage 5 remains **NOT STARTED**, Production
Activation **NOT APPROVED**, and provider transport guards remain unchanged.

Adjudication-specific validation: **9 targeted tests passed, 24 deselected**;
no new full regression run or provider execution. Starting-file audit confirms
only this report's appended update and the new independent report changed in
the repository. Current Git status: **21 modified, 31 untracked**; prior work,
frozen contracts, original translations/assessments and historical report bytes
are preserved. All unblind details remain Git-ignored and local-only.
