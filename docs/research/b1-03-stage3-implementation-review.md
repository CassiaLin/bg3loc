# B1-03 Phase 6 Stage 3 — Provenance / QA / Review

2026-10-09 · branch `feat/b1-03-dialogue-context` · HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb`.
Stage 2 Implementation Review ACCEPTED. Stage 0 frozen contracts, Policy A,
2,000 codepoints, DTO and H0/HSE identity/prompt contracts remain unchanged.

**B1-03 Phase 6 Stage 3 — READY FOR IMPLEMENTATION REVIEW**

## Implementation / modified sites (VERIFIED)

| Area | File / function | Result |
| --- | --- | --- |
| Provenance DTO | `src/bg3loc/prompt_provenance.py`: `PromptProvenance` | Optional `dialogue_context_fingerprint` appended after the existing five positional arguments. Old positional calls and B1-02 field meanings remain intact. |
| Single render | `src/bg3loc/translation_send.py`: `prepare_translation_send`, `provenance_for_prepared_send`, `PreparedTranslationSend` | Pure single assembly/render, exact HD input validation and immutable messages/provenance. No transport call. Provider's existing H0/HSE before-send path reuses the same provenance factory, preserving actual bytes and render count. |
| Attempt migration / binding | `src/bg3loc/execution_state.py`: `initialize`, `record_prompt_provenance`, `_validate_hd_send_lease`, `complete_success` | Add nullable dialogue column. `BEGIN IMMEDIATE` checks running/current attempt, live owner, current input, exact sealed context, HD renderer and timezone-aware unexpired lease. Existing binding cannot be overwritten inconsistently. Offline HD success requires dialogue/effective/messages provenance and matching output SHA. Default production success/start/claim guards remain blocked. |
| Callback | `src/bg3loc/execution_runner.py`: before-send `record` callback | Passes independent dialogue FP and current send time without redefining B1-02 `context_fingerprint`. No execution guard removed. |
| Provider | `src/bg3loc/providers/openai_compatible.py`: `translate_with_provenance` | H0/HSE render once and persist existing callback before transport, including error/retry paths. HD public transport remains unconditionally blocked pending complete workspace/activation gates. |
| Retry migration / transaction | `src/bg3loc/qa_state.py`: `initialize`, `handoff_retry`; `commands/translation_qa.run_retry_handoff` | Add nullable `execution_input_hash`. Current input/output/QA ruleset/hash/RETRY route checked, candidate archived and state reopened in the same writer transaction. 1.3 requires the evaluated input/output snapshot. Failure rolls back both archive and reopen; no new context/target or retry-prompt text is created. |
| Semantic routing | `src/bg3loc/dialogue_review.py`: `apply_dialogue_semantic_review`, `semantic_gate_present`; `commands/translation_qa.run_qa`; `qa_state.get_result` | HD technical PASS/REVIEW becomes REVIEW with `DIALOGUE_SEMANTIC_REVIEW_REQUIRED`. Technical FAIL/RETRY and H0/HSE unchanged. Missing/stale HD gate cannot be treated as current QA and skipped. Global technical QA version/hash unchanged. |
| Review source / snapshot | `src/bg3loc/production_review.py`: `resolve`, `get_current_acceptance`; `commands/translation_qa.run_review_export`, `run_review_resolve`; `production_qa_orchestration.resolve_workspace_review` | Current REVIEW/input/output/QA version/QA hash required. 1.3 caller must supply the four review snapshot bindings. Export includes them and source-only grouped context, with snapshot-change checks. Writer transaction rereads current QA/input/material/gate before decisions. |
| REVISE | `ProductionReviewStore.resolve`; `TranslationQaStore.record_result` | Existing technical QA runs before revision. FAIL/RETRY rejects without changing state/QA/review history. Valid 1.3 revision, effective QA and human resolution persist atomically, bound to the resolved output and new QA hash. Legacy revision still makes old QA stale and requires rerun, after precommit technical validation. |
| Completion | `src/bg3loc/production_completion.py`: `derive_production_disposition`, `build_production_completion_view` | HD PASS/missing marker blocked even with an acceptance. REVIEW without current decision waits; current ACCEPT/technically-valid REVISE permits content MERGE_READY. QA/review/input/output mismatches block. SQLite execution/QA/issues/review selection uses one read snapshot. Public 1.3 completion is still blocked; explicitly offline content validation only. |

No finalizer/rebuilder/portable asset implementation was added. Their existing
preflight calls inherit the stronger completion/namespace gates. Direct finalizer
or merge bridge calls cannot bypass them and create no output for these 1.3
offline fixtures.

## SQL migration and history compatibility (VERIFIED)

```sql
ALTER TABLE attempts ADD COLUMN dialogue_context_fingerprint TEXT;
ALTER TABLE qa_rejected_candidates ADD COLUMN execution_input_hash TEXT;
```

Both are nullable/additive and guarded by `PRAGMA table_info`; repeated migration
does not rewrite existing state, attempts, hashes or rejection history. Existing
`attempts.context_fingerprint` remains B1-02 only. Historical NULL stays UNKNOWN,
not inferred baseline/dialogue or backfilled. Existing QA/review input-binding
columns are reused; no new semantic QA SQL schema or global QA version is needed.
The execution DB default remains 1.2, with explicit offline 1.3 migration and the
existing downgrade/in-place conversion rejection preserved.

QA RETRY now acquires the writer transaction before reading the candidate. It
checks the captured execution input/output and persisted QA route/ruleset/hash,
archives the exact current input with text/output/QA evidence, then clears output
and reopens the same input identity within that transaction. A synthetic abort
trigger during reopen proves the archive insert is rolled back too.

## Actual-send provenance validation (VERIFIED offline; execution NOT enabled)

The common preparation core assembles/renders exactly once and returns the same
immutable messages whose SHA is persisted. Synthetic delivery observes a
running attempt with its input, dialogue FP, renderer `dialogue-prompt/1`,
effective hash and actual message fingerprint already stored **before** delivery.
Success, simulated HTTP 500, timeout and retry preserve the correct attempt
records. Retry uses the same current input/context; each attempt has its own
binding. Wrong owner/input/current attempt/expired lease/renderer/context or
inconsistent overwrite fails, leaving unbound fields unfilled. Missing HD
provenance cannot be recorded as baseline or complete offline success.

The test delivery functions are local synthetic functions, not provider HTTP
transport. No 1.3 run or claim is enabled: tests insert fictional running rows
directly into isolated SQLite fixtures. `complete_success(stage3_validation_only=True)`
validates sealed offline foundations and provenance; no CLI or worker passes
that flag. It cannot enable transport. Public HD provider, init, resolver,
start/claim/success, worker, completion and finalize guards remain active.

H0/HSE actual UTF-8 role/content bytes are independently compared with original
HEAD prompt assembly/chat code. Their input/effective/message hashes and
existing provenance values match the frozen goldens; dialogue FP remains NULL.
Evidence: `workspace/b1-03-phase6-stage3/head-parity-provenance.json`.

## Routing, human binding and completion (VERIFIED)

| Family | Technical PASS | Technical REVIEW | Technical RETRY | Technical FAIL |
| --- | --- | --- | --- | --- |
| HD | REVIEW + required marker | REVIEW + required marker | RETRY | FAIL |
| H0 | PASS | REVIEW | RETRY | FAIL |
| HSE | PASS | REVIEW | RETRY | FAIL |

The marker's message explicitly states that human semantic review is required
and that no semantic error was detected. Its policy detail is the frozen
`dialogue-semantic-review/1`. It does not grade meaning, infer branch errors,
speaker identity, contamination, or translation improvement.

1.3 ACCEPT/REVISE requires expected execution input, output, QA input hash and QA
ruleset version from the actual review snapshot. Current route must be REVIEW;
all bindings are checked again in the writer transaction. This prevents an old
human submission from being rebound to a newer context even when output and
technical QA hash are identical. REVISE reruns target-only technical checks;
the newly evaluated QA snapshot and resolution's resolved output are committed
with the revision. Legacy ACCEPT still needs no new arguments; legacy REVISE
obtains source from its explicit/known prepared plan and retains stale-QA rerun
semantics. No game/source-universe fallback is used for revision validation.

Completion selects current decisions by execution input, resolved output, QA
version/hash and REVIEW route. ACCEPT additionally binds the base output;
REVISE retains its original base hash and binds the new resolved candidate.
History NULL is never promoted into a current HD decision.

| HD state | Content disposition |
| --- | --- |
| Technical PASS persisted without semantic gate | BLOCKED / `DIALOGUE_REVIEW_GATE_NOT_APPLIED` |
| REVIEW missing/stale policy marker | BLOCKED |
| Current REVIEW, no valid human decision | WAITING_REVIEW |
| Current REVIEW, current ACCEPT | MERGE_READY |
| Current REVIEW, technically valid current REVISE | MERGE_READY |
| Stale input/output/QA/review or missing bound QA | BLOCKED |
| Technical RETRY / FAIL | WAITING_RETRY / BLOCKED |

`MERGE_READY` in the offline API is a content disposition, not execution,
portability, finalization or activation permission. Public 1.3 entrypoints still
reject the workspace. Tests also prove a forged human-accepted boolean cannot
override a missing PASS/REVIEW gate.

A complete fresh-context fixture keeps target source, output and QA hash
identical while changing a context source variant. Its execution input differs;
an old copied acceptance and an old submitted snapshot are both rejected. The
fictional case-006-style fixture preserves 3 predecessor / 13 successor branches,
waits for human review, and accepts a technically valid manual revision. This
is workflow evidence, not a real case-006 quality replay or semantic verdict.

## Tests, regression and Git state (VERIFIED)

- **53 new Stage 3 synthetic tests passed** (`tests/test_dialogue_stage3.py`).
- Final targeted regression: **221 passed, 16 subtests passed**.
- Full attempted suite: **1,132 passed, 75 subtests passed, 1 failed**. The existing
  fictional HTTP demo failed with sandbox **WinError 10013** on loopback.
  It is **environment-blocked, not PASS**; no escalation or code workaround.
- Final full available regression, excluding that diagnosed demo:
  **1,135 passed, 75 subtests passed**.
- Existing H0/HSE, B1-02 activation/provenance, Stage 0–2, QA/review, completion
  and finalizer tests included. UTF-8 and workspace-owned test temp directories.

Logs and audits stay ignored/local-only:

- `workspace/b1-03-phase6-stage3/pytest-targeted-delivery.txt`
- `workspace/b1-03-phase6-stage3/pytest-full.txt` (blocked demo preserved)
- `workspace/b1-03-phase6-stage3/pytest-full-delivery.txt`
- `workspace/b1-03-phase6-stage3/head-parity-provenance.json`
- `workspace/b1-03-phase6-stage3/starting-file-seals.json`

Only the nine required existing Stage 3 sites above changed; all other starting
file bytes, including accepted Stage 0–2 code/tests/documents/schema/registry,
Phase 3 dirty files and Phase 5 design, are preserved. Existing Stage 2 stop
guards were not relaxed. New files are this report, `dialogue_review.py`,
`translation_send.py` and fictional `test_dialogue_stage3.py`. No proprietary
corpus/assignments/real translations were read or copied by Stage 3 work. No
production provider transport or real translation occurred. The existing demo
attempted only its blocked fictional loopback fixture during full regression.

Stage 3 diff/status (all prior dirty work also remains):

```text
 M src/bg3loc/commands/translation_qa.py
 M src/bg3loc/execution_runner.py
 M src/bg3loc/execution_state.py
 M src/bg3loc/production_completion.py
 M src/bg3loc/production_qa_orchestration.py
 M src/bg3loc/production_review.py
 M src/bg3loc/prompt_provenance.py
 M src/bg3loc/providers/openai_compatible.py
 M src/bg3loc/qa_state.py
?? docs/research/b1-03-stage3-implementation-review.md
?? src/bg3loc/dialogue_review.py
?? src/bg3loc/translation_send.py
?? tests/test_dialogue_stage3.py
```

`git diff --check` passes; nothing staged, committed, pushed or merged.

## Stage 4 readiness assessment

**VERIFIED ready for review:** additive migrations, single-render provenance
core and atomic persistence, retry identity archive, frozen semantic routing,
snapshot-bound human decisions and current completion gates are implemented and
tested. No Contract Change Request or frozen-spec change was needed.

**PROPOSED next work only after separate authorization:** Stage 4 complete prepare
and corpus/build attestation integration, D7 complete payload/path/version/XML/
LOCA/package closure and portability checks, production-shaped offline end-to-end
and concurrency/package/privacy tests, and external/human case-006 replay. Wire
the already tested send core/callback only through those completed verification
gates; do not remove a stop guard as an activation shortcut.

**UNKNOWN / mandatory remaining blockers:** real full 1.3 workspace creation and
attestation, D7 payload semantics/roundtrip/repack, full-workflow portability,
production provider integration/operational costs, human semantic behavior and
case-006 drift mitigation. Independent activation approval remains required.
No limited pilot or synthetic test result proves translation improvement or
general dialogue safety.

**Stage 4 = NOT STARTED · Production Activation = NOT APPROVED**
