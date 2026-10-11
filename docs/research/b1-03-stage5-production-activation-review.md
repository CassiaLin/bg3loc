# B1-03 Phase 6 Stage 5 — Independent Production Activation Review

Date: 2026-10-10. Branch: `feat/b1-03-dialogue-context`.
HEAD: `896b4870b3a24d8506e6d751db3d4602925fb8fb`.
Review authorization only; Production Activation **NOT AUTHORIZED**.

## 1. Executive decision

**ACTIVATION DEFERRED — REMEDIATION REQUIRED**.

This is the sole formal recommendation. It follows a fresh source/contract
inspection, new isolated negative probes, existing regression reruns and
read-only verification of real sealed assets. It is not a second external
human review and does not reuse prior PASS labels as an activation decision.

**VERIFIED blocker S5-B1**: `ProductionReviewStore.resolve` permits an ACCEPT or
REVISE after actual candidate bytes change while their declared output hash
stays unchanged. All six H0/HSE/HD × ACCEPT/REVISE synthetic negative probes
failed the expected rejection. ACCEPT remains BLOCKED downstream by completion;
REVISE produces a new QA-valid candidate and becomes MERGE_READY, but its base
decision was authorized from stale actual bytes. This is a decision-binding/
audit defect, not evidence that the corrupt ACCEPT text bypassed finalization.

**VERIFIED blocker S5-B2**: 155.55 s per ACCEPT, with repeated full validation
including one pass under the SQLite writer transaction, makes corpus-scale
mandatory HD review operationally unacceptable. Review export also revalidates
the whole material inside its per-item loop. That loop's total latency is not
measured, but its cost structure is explicit in code.

**UNKNOWN blocker S5-B3**: normal 1.3 provider/worker integration, sustained
multi-process throughput and operational cutover/recovery remain unverified.
Current stop guards intentionally prevent execution. Merely deleting guards
would not complete integration: the normal provider callback does not supply
the input parameters required by the HD provenance core.

No production code, tests, frozen contracts or stop guards were changed in
this review. Correctness remediation and performance work require separate
authorization. Production Activation must not be approved while S5-B1 persists.

## 2. Authority and evidence scope

Reviewed authorities: Stage 0 contract freeze/registry/closed schemas; Stage
1 typed material, Stage 2 request/prompt/identity, Stage 3 provenance/review,
Stage 4 portability, Stage 4R remediation, case-006 adjudication, and final
engineering acceptance reports. Their NOT IMPLEMENTED / NOT STARTED markers
describe historical stages, not present runtime authorization.

Evidence labels: **VERIFIED** = inspected code or executed check; **PROPOSED** =
review recommendation, not implemented/approved; **UNKNOWN** = insufficient
evidence. Integrity fingerprints bind declared data, not digital-signature
authenticity or protection against an administrator rewriting all evidence.

Fresh read-only real verification passed for Manifest 1.3, **218,272 targets**,
**27,946 HD contexts**, app 1086940/build 25605617/game 4.1.1.7631656. Runtime
validation took 38.14 s; D7 payload/semantic verification 6.43 s. The existing
synthetic published LOCA/PAK hashes and all **8 non-LOCA entry SHA** values were
independently rechecked. These are engineering/content-integrity facts, not
human approval of the synthetic translations.

Code links below use this checkout's absolute paths. Function names identify
the precise path, not an imagined future API.

## 3. Contract compliance matrix

| Requirement | Result and actual implementation | Tests / scope |
| --- | --- | --- |
| Policy A direct native Child | PASS: [dialogue_materialization.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/dialogue_materialization.py:135), `DialogueEvidenceAdapter.from_records/materialize`: verified child UUID/ownership, native origins, conflicts/incompatible occurrences excluded, localized direct neighbors only; no speaker inference, control traversal or reference expansion | `test_dialogue_stage1.py`: `test_complete_branches_variants_occurrences_and_no_text_deduplication`, `test_structural_conflicts_fallback_and_incompatible_occurrences`, `test_no_speaker_inference_no_control_crossing_no_references_and_bark_baseline`; full ledger/source-universe preparation |
| 2,000 codepoints / whole-set fallback | PASS: same adapter `materialize` sums raw variant text in both directions; >2000 returns BUDGET_EXCEEDED, no partial branches; [dialogue_context.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/dialogue_context.py:244) recomputes count | `test_raw_codepoint_boundaries_whole_set`, incomplete-set test, Unicode/markup/whitespace cases; real material count 27,946 |
| Immutable DTO / target binding | PASS: `DialogueContext`/nested frozen dataclasses, strict versions/types/order, directional proof, source/evidence/context fingerprints; `decode_dialogue_context` | Stage 1 deep immutable, strict transport, target binding, malformed-present and fingerprint tests; execution cannot independently authenticate native proof without prepared evidence |
| H0/HSE exact parity | PASS: [translation_identity.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/translation_identity.py:38) keeps H0 eight-field payload and existing HSE branch; unchanged legacy renderer logic | Stage 2 `test_h0_hse_frozen_input_effective_and_actual_message_parity`; full legacy/B1-02 regressions; synthetic golden bytes, not a claim of network validation |
| HD identity / proof binding | PASS: same hash function uses `translation-input/3`, descriptor from `dialogue_identity_descriptor`; [translation_send.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/translation_send.py:11) verifies HD hash before single-render provenance | `test_hd_changes_and_baseline_absence`, exact payload, policy dimensions, proof-only change, identical-output stale-context tests |
| Context-family exclusion | PASS: [translation_request.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/translation_request.py:32), DTO material entry guard and hash dispatch reject both families, including malformed-present keys; absent keys omitted | Stage 1 absent/malformed/both-family tests; Stage 2 both-family request/hash tests; no serialized null additions |
| Source-only grouped prompt | PASS: [dialogue_prompt.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/dialogue_prompt.py:64), `project_dialogue_context`; [prompt_assembly.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/prompt_assembly.py:126), `assemble_translation_prompt`; [chat_prompt.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/chat_prompt.py:18), `render_chat_messages` preserve grouping and frozen seven instructions | Stage 2 source-only projection/injection/no-related-metadata/three-and-thirteen variants tests; code/registry fingerprint consistency |
| Manifest / execution DB 1.3 | PASS foundations: [dialogue_execution_contract.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/dialogue_execution_contract.py:98), `validate_manifest_1_3/validate_stage2_workspace`; [execution_state.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/execution_state.py:60), `initialize` additive columns and version guards | Stage 2 namespace/downgrade/strip/inventory tests; Stage 3 migrations idempotent and NULL remains UNKNOWN; normal execution intentionally unsupported |
| Prepare attestation / atomic publish | PASS: [production_dialogue_prepare.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_dialogue_prepare.py:29), `attest/prepare_dialogue_workspace` cross-check build/extract/source XML/LOCA/package and complete evidence, recheck seals, checkpoint and rename fresh staging | Stage 4 complete prepare, mismatch-no-publication, batch determinism tests; fresh real read-only validation confirms sealed declarations |
| Complete D7 portability | PASS Windows: [portable_assets.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/portable_assets.py:116), `create_finalize_assets/verify_finalize_assets` complete package inventory, UID/version indexes, baseline XML/LOCA, size/SHA/semantic/path validation | Stage 4 relocation/cwd/blank/target-only/source-only/version/path collision/tamper tests; real 9-entry bundle independently checked |
| HD technical PASS → REVIEW | PASS: [dialogue_review.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/dialogue_review.py:22), `apply_dialogue_semantic_review`; [commands/translation_qa.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/translation_qa.py:110), `run_qa`; current QA selector flags missing gate stale | Stage 3 route matrix, rerouting, RETRY/FAIL unchanged, missing gate cannot be overridden; marker is a review requirement, not detected error |
| Current human ACCEPT/REVISE | **FAIL** actual base-byte binding: [production_review.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_review.py:76), `resolve` compares stored hashes/rule/input/route, but not SHA(actual current text); [qa_state.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/qa_state.py:340), `get_result` does not fetch actual text | Existing snapshot/race/revised-technical-failure tests PASS; new six independent stale-byte probes FAIL. Do not call the whole requirement PASS |
| Completion / finalize byte integrity | PASS containment: [production_completion.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_completion.py:249), `build_production_completion_view` validates all 1.3 output bytes, HD gate/current acceptance; [portable_finalize.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/portable_finalize.py:36), `finalize_portable_workspace` checks again under BEGIN IMMEDIATE and before atomic publish | Stage 3 gate/bypass/stale acceptance; engineering H0/HSE unbound-byte tests; full-size synthetic zero/half/full-review and rollback cases. REVISE probe creates a new valid candidate, but does not repair stale-base authorization |
| Legacy 1.0–1.2 | PASS regression scope: version-specific branches preserve old request/hash/prompt/finalize semantics; 1.3 byte check does not apply to legacy workspaces | Existing full suite plus Stage 2 legacy null-contract/material/downgrade tests; legacy data portability is not retroactively guaranteed |

## 4. Code-path review and new finding

Current production boundary:

`prepare_production_workspace` → complete 1.3 prepared artifacts;
`run_init/start_run/claim_next/run_worker/provider` → **STOP** for 1.3;
explicit offline resolver/send core → provenance/QA/review fixtures;
current completion → portable finalize → verified native artifacts.

Actual stop sites were inspected:

- [production_workspace.py:124](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_workspace.py:124): `verify_production_workspace` recognizes then rejects production 1.3 execution.
- [commands/translation_state.py:222](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/translation_state.py:222): `run_init`; `_sealed_execution_contract` at 484 also rejects 1.3.
- [execution_state.py:175](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/execution_state.py:175): `start_run`; `claim_next` at 263 and default `complete_success` at 375 retain guards.
- [execution_runner.py:107](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/execution_runner.py:107): `run_worker` rejects metadata/offline resolver and HD before send.
- [providers/openai_compatible.py:135](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/providers/openai_compatible.py:135): HD returns failure before transport. Later provenance callback uses `provenance_for_prepared_send` without HD input parameters; guard removal alone would still fail that core check.
- [execution_state.py:682](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/execution_state.py:682): `record_prompt_provenance` uses a writer transaction/current owner/input/lease and prevents inconsistent overwrites. Tested offline core is not a deployed 1.3 provider path.
- [qa_state.py:222](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/qa_state.py:222): `handoff_retry` archives current execution input identity in the same transaction as reopening.

**S5-B1 reproduced** in isolated complete synthetic 1.3 workspaces:

1. Create an actual technical REVIEW result for a source-copy fixture, applying
   the frozen semantic gate for HD; bind correct input/output/ruleset/QA hashes.
2. Change only `content_state.translated_text`; leave declared output hash and
   QA/review snapshot tokens unchanged.
3. Submit ACCEPT or REVISE with the expected old tokens through the actual
   `ProductionReviewStore.resolve` API.

| Family | ACCEPT result | REVISE result |
| --- | --- | --- |
| H0 | API writes decision; completion BLOCKED | API writes decision from stale base; new valid candidate MERGE_READY |
| HSE | Same | Same |
| HD | Same | Same |

Expected rejection occurred in **0 / 6** cases. The corruption is not a full
malicious recomputation of all integrity seals; it is one inconsistent candidate
field. For REVISE the new text passes technical QA and has current bindings;
the problem is stale actual base authorization/history. The probes did not
call provider transport, finalize, or install outputs. No game UID/source is
included here. Source remains unchanged so remediation is still pending.

## 5. Safety evidence and retained restrictions

| Evidence | Supported conclusion | Unsupported inference |
| --- | --- | --- |
| Original 25-pair pilot | SAFE WITH RESTRICTIONS; context worse 1, better 0, identical 23, one other difference | Quality improvement or general safety |
| Original case-006 | A real context-worse observation remains | Rewriting that history because a later pair matched |
| New grouped-renderer case-006 | Accepted scoped NO OBSERVABLE REGRESSION; byte-identical baseline/context, bound blind assessment | Renderer causally fixed risk, or every branch safe |
| General dialogue safety | **NOT VALIDATED** | Treating single-case or synthetic load tests as universal approval |

Every HD technical PASS/REVIEW must have the semantic REVIEW issue and a current
human ACCEPT/REVISE before merging. H0/HSE routes remain their existing policy;
bark/whole-set fallback remain baseline. Context remains source-side/read-only,
with possible alternatives rather than a temporal dialogue sequence. No review
gate may be disabled to meet a throughput target.

## 6. Operational risk decisions

Each classification is a review decision, not a new frozen threshold.

| Measured item | Classification | Reason / required restriction |
| --- | --- | --- |
| ~61 s startup | ACCEPTABLE WITH RESTRICTIONS | Once per sealed review/run session, visibly reported; no per-item replay; still full validation |
| 1.957 s sampled lifecycle | ACCEPTABLE WITH RESTRICTIONS | Small controlled single-worker planning only; 12 static samples, no provider latency or measured full worker throughput |
| 155.55 s single ACCEPT | **BLOCKS ACTIVATION** | Mandatory HD review cannot reasonably scale with this machine delay and a long writer-held second full validation; remediate before activation |
| 248.40 s full finalize | ACCEPTABLE WITH RESTRICTIONS | Planned offline/maintenance operation on a complete reviewed workspace; not interactive finalize; translated-text variability remains unmeasured |
| 185.00 s writer barrier | ACCEPTABLE WITH RESTRICTIONS | Drain claims, pause QA/review writers, allow WAL readers; explicit timeout/retry/maintenance procedures and operator acceptance required |
| O(N) inventory reconciliation | REQUIRES REMEDIATION | Correctness coverage stays mandatory; measured ~0.61 s after commits, repeated at worker phases; establish equivalently safe reuse and contention budget or explicitly bound workloads |
| Sustained multi-worker throughput UNKNOWN | **BLOCKS ACTIVATION** of multi-worker scope | No sustained claim/send/retry/churn benchmark; current per-instance mutex/process checks are not a throughput test. A future single-worker scope could avoid this expansion only after other blockers close |

If all 27,946 HD targets require one ACCEPT at 155.55 s, machine decision time
alone projects to **1,207.5 hours**, about **151 eight-hour days**, ~23 decisions/
hour. This arithmetic excludes human reading and is not a measured corpus
review run. Parallel reviewers do not eliminate the writer-transaction scan;
do not promise proportional speedup. Review export's per-item full verification
at `commands/translation_qa.py` around line 303 is another scaling concern.

The large engineering fixture had 215,754 programmatic synthetic decisions,
not actual API-mediated human reviews. Its PASS therefore validates completion/
lock/repack cardinality, not review usability or real semantic coverage.

## 7. Platform / release scope

| Candidate scope | What current evidence permits | What it cannot permit / needed confirmation |
| --- | --- | --- |
| Windows-only restricted activation | Windows native sharing, reparse/mapped-writer tests, full sealed assets and synthetic finalize evidence exist | Not eligible now: S5-B1/B2 and actual transport integration remain. Future confirmation needs exact host/filesystem/backend, initially bounded single worker, all HD reviews and maintenance/rollback plan |
| Offline-only release | Existing source/packaging and explicitly labeled local offline engineering/research artifacts can be inspected | This is not the formal recommendation and no release/publish is authorized. No actual provider requests, proprietary corpus distribution or synthetic game installation; approval still needed for any release |
| Activation deferred | Preserve guarded branch/workspace, correct review decision integrity and performance, rerun review | **Selected formal disposition**; does not disable legacy approved workflows or authorize new 1.3 execution |

Native Linux/macOS: **UNKNOWN**, no full actual OS/backend run. Simulated
nonlocking capture/rehash tests on Windows are algorithm evidence, not native
POSIX acceptance. Windows evidence cannot be promoted to cross-platform PASS.

## 8. Activation gate matrix

PASS is limited to the stated evidence; UNKNOWN is never promoted to PASS.

| Gate | Status | Boundary / effect |
| --- | --- | --- |
| Source/build attestation | PASS | Prepare source/scan/extract/evidence cross-check; fresh real declaration/runtime verification |
| Full material and D7 closure | PASS | Complete real 218,272/27,946 material and 9-entry bundle; all role SHA/size/semantics |
| Prompt and identity integrity | PASS | Static contract correspondence and fresh H0/HSE/HD regression |
| Actual-send provenance | **UNKNOWN** for production 1.3 | Single-render offline core + legacy/mock transport tests pass; normal HD worker/provider path is stopped and incompletely wired |
| Technical QA and semantic REVIEW | PASS routing contract | Actual frozen matrix, missing gate stale/BLOCKED, retry archive binding; not proof of translation meaning |
| Human decision binding | **FAIL** | Six stale actual-base byte probes violate rejection expectation; must fix before approval |
| Completion/finalize guards | PASS tested containment | Stale ACCEPT blocked; actual-byte, current identity/review and publication checks. Does not cure stale-base REVISE authorization |
| Portable rebuild/repack | PASS Windows measured corpus | Fresh artifact hash/non-LOCA verification, prior full native roundtrip/repack and relocation tests; backend scope explicit |
| Output privacy | PASS local/package scope | Corpus/unblind artifacts ignored, package scan/clean install evidence; synthetic review labels retained; no public data uploaded |
| Operational throughput | **FAIL** corpus review readiness | Review delay and writer-held full scans; proposed restrictions do not approve this cost |
| Multi-worker concurrency | **UNKNOWN** sustained execution | Writer-barrier/WAL and per-instance tests pass; no sustained production workers/churn/load |
| Platform support | **UNKNOWN** overall | Windows scoped tests PASS; native Linux/macOS UNKNOWN |
| Semantic risk restrictions | PASS retained requirement | SAFE WITH RESTRICTIONS and mandatory HD review; GENERAL SAFETY remains NOT VALIDATED |
| Release/recovery/rollback | **UNKNOWN** activation operations | Controlled rollback/atomicity tested; no reviewed cutover/kill-switch/in-flight recovery/deployed release rehearsal |

## 9. Separate Stage 5 remediation proposal — not implementation

**PROPOSED S5-R1 — decision integrity (priority blocker)**:
verify actual current base text SHA against declared/current/expected output
hash inside the same decision writer transaction, for every family in 1.3.
Ensure the current QA snapshot belongs to those exact bytes/input/ruleset;
reject stale ACCEPT and stale-base REVISE without updating state, QA or history.
Keep REVISE technical QA and HD semantic gate, NULL=UNKNOWN, and legacy 1.0–1.2
contract semantics. Add the six failing probes as automated regression plus
concurrent byte/hash/QA changes and rollback assertions. No schema/policy bump
is proposed; if frozen semantics genuinely conflict, request a Contract Change
Review rather than silently relaxing them.

**PROPOSED S5-R2 — review/export performance**:
reuse an explicitly owned fully validated sealed session snapshot in review
and batch export, not an unversioned/global cache. Existing
`SealedRunSnapshot.current_item` can supply current immutable material, but
the design must prove owner/process/close, file pins or full rehash, manifest/
source binding, current DB inventory generation and transaction byte/QA/route
binding before substituting any full checks. Keep mutation/downgrade/stripping/
TOCTOU/retry/current-human-review protections. Retain detailed old/new benchmarks
on real material. Proposed interactive target: warm p95 ≤2 s, subject to user
approval; cold startup separate. No automatic approval or reduced reviews.

**PROPOSED S5-R3 — scoped execution/operations validation**:
design the normal 1.3 worker/provider callback path against existing functions,
including bound HD input parameters, single-render actual-send provenance,
current owner/lease and success/failure/retry durability. Do not enable it by
deleting guards or reusing offline validation flags. First validate via an
isolated mocked transport with the intended normal code path under separate
implementation authorization. Any paid/real text request requires a further
explicit authorization. Measure representative worker/churn contention and
define limits/backoff; stage a Windows-only initial envelope if approved.

**PROPOSED S5-R4 — recovery/readiness plan**:
document stop/drain/backup with SQLite-consistent snapshots, resumable identities,
maintenance exclusion, operator timeouts, artifact verification, withdrawal and
recovery steps. Rehearse crash/failure windows on isolated fixtures; retain old
baseline assets and never write the game directory automatically.

No item above was implemented in this review. No security check was bypassed.

## 10. Regression and remaining blockers

Fresh targeted Stage 0–4R: **318 passed, 1 skipped**. Full available:
**1,202 passed, 1 skipped, 75 subtests passed**. Existing HTTP demo retried:
**WinError 10013 / environment-blocked**, not PASS; excluded from available
count. Symlink creation is host-skipped; reparse/native mapped-section tests
pass. All established regressions passing does not cover the newly probed
failure: **six independent rejection probes FAIL**, described in section 4.

Fresh real read-only validation and artifact SHA checks pass. The prior wheel/
sdist/fresh clean-install audit was inspected as preserved evidence, not rerun
or represented as a new build. Original freeze/schema/runtime-copy consistency
tests ran fresh. No existing regression assertion was weakened or edited.

Remaining activation blockers: S5-B1 actual base-byte decision binding;
S5-B2 review/export capacity; S5-B3 normal guarded execution integration and
scoped throughput; deployment/recovery/platform decisions in gate UNKNOWN rows.
Case-006's limited replay blocker stays resolved; no broader semantic promise.

## 11. Explicit approval actions and Git

Required from the user, in order:

1. Review this **DEFERRED** decision and separately authorize a bounded S5-R1/R2
   remediation implementation. This review authorization is not that permission.
2. Review corrected code/negative probes/real performance and accept documented
   operating limits; separately authorize any R3/R4 implementation/tests.
3. Define exact Windows/backend/filesystem/worker/review/data scope, risks,
   maintenance and recovery ownership. Native other platforms remain excluded
   until tested or explicitly deferred.
4. Re-run an independent activation review after blockers close; only then
   provide an explicit Production Activation authorization. A review verdict
   alone cannot enable guards, deployment, release or paid/provider calls.

HEAD and branch unchanged. Starting preservation seals cover **375 files**.
The only repository addition is this report; production/test/frozen-contract
bytes and all prior dirty work remain unchanged. Local probes/metrics/logs stay
ignored under `workspace/b1-03-stage5-review/`. Final audit/Git status are saved
there; no commit, push, merge, guard removal, deployment or official translation.
Final preservation audit confirms all **375 prior files byte unchanged** and
only this report added. Git status: **21 modified, 34 untracked**, retaining all
earlier dirty work. `git diff --check` passes; no staged changes were introduced.

Local evidence: `review-binding-all-family-repro-local.json`, isolated probe
fixtures/logs, `independent-real-evidence-validation.json`,
`review-capacity-projection.json`, `pytest-targeted.txt`,
`pytest-full-available.txt`, `pytest-http-demo.txt`,
`http-demo-environment-blocked.json`, `final-preservation-audit.json`.

**B1-03 Phase 6 Stage 5 — ACTIVATION DECISION READY FOR REVIEW**.
Production Activation remains subject to separate explicit authorization.
