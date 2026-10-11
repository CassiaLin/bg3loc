# B1-03 Phase 6 Stage 2 — Request / Prompt / Identity / Config

2026-10-09 · `feat/b1-03-dialogue-context` · HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb`.
Stage 1 Implementation Review ACCEPTED. All accepted Stage 0/1 files and prior
Phase 3/5 work retain their starting bytes. No Policy A, budget, registry version,
B1-02 contract, production default or project version change.

**B1-03 Phase 6 Stage 2 — READY FOR IMPLEMENTATION REVIEW**

## Implementation and evidence (VERIFIED)

| Area | Files / functions | Result |
| --- | --- | --- |
| Request | `src/bg3loc/translation_request.py`: `TranslationRequest.__post_init__`, `BatchMaterialResolver.__init__`, `_load_batch`, `resolve` | Optional immutable `dialogue_context` appended after existing constructor fields. Strict typed DTO/source binding. Both families rejected. Resolver requires supported namespace and bound input parameters; offline 1.3 resolution additionally validates current material/DB seals and claimed identity. |
| Grouped projection | `src/bg3loc/dialogue_prompt.py`: `DialoguePromptAlternative`, `DialoguePromptContext`, `project_dialogue_context` | Frozen tuples preserve every native alternative group and source variant. Wire contains relation type/semantics and source text only. No related UID, native IDs, speaker, proof, fingerprint, versions, budgets or resource paths. |
| Prompt | `src/bg3loc/prompt_assembly.py`: `AssembledTranslationPrompt`, `assemble_translation_prompt`; `src/bg3loc/chat_prompt.py`: `render_chat_messages` | Only HD adds the safe grouped object, renderer/safety policy in effective identity, and the exact seven Stage 0 instructions in frozen order. Target source remains the only translation target. Context-only tokens do not become required target tokens. H0/HSE branches emit no new fields/nulls. |
| Item identity | `src/bg3loc/translation_identity.py`: `translation_input_hash`; `dialogue_execution_contract.dialogue_identity_descriptor` | H0 exact old eight-field payload; HSE exact existing version/descriptor; HD adds only `translation-input/3` and the frozen dialogue descriptor. Proof-only changes invalidate HD without changing prompt bytes. No batch IDs, paths, timestamps, global corpus or finalize-assets hashes enter HD. |
| Config / namespace | `src/bg3loc/dialogue_execution_contract.py`: `execution_context_contract_v2`, `validate_context_contract_v2`; `src/bg3loc/providers/openai_compatible.py`: `openai_compatible_execution_config_hash` | `production-context-contract/2` contains separate sameEntity/dialogue families; optional sameEntity is the original exact nested B1-02 contract. Fixed renderer/safety/semantic-review policy and material fingerprints bound. Unknown/stripped/mismatched namespace contracts fail. Legacy config hash branch unchanged. |
| Manifest / seals | `dialogue_execution_contract.validate_manifest_1_3`, `validate_stage2_workspace`, `contained_file` | Strict frozen schema, true integer/constant types, closed objects, UTF-8/duplicate-key/nonfinite checks. Cross-checks source/evidence binding, six input digests, family contracts, classification, plan/material/summary counts and fingerprints, ruleset/locales, current per-item input hashes and exact DB inventory. |
| DB foundations | `src/bg3loc/execution_state.py`: `initialize`, `start_run`, `claim_next`, `complete_success` | Default schema remains 1.2. Explicit fresh offline `initialize(schema_version="1.3")` creates foundation tables only. No implicit 1.2↔1.3 conversion/downgrade. 1.3 execution/start/claim/success blocked. No Stage 3 SQL columns or provenance migrations added. |
| Entrypoint guards | `src/bg3loc/commands/translation_state.py`: `load_execution_items`, `run_init`, `_sealed_execution_contract`; `src/bg3loc/production_workspace.py`: `verify_production_workspace`; `src/bg3loc/execution_runner.py`: `run_worker`; provider `translate_with_provenance` | Default 1.3 init/resolver/start/worker/provider execution fail closed. Legacy rows with a dialogue key, including null, are refused. Both keys fail first. Existing DB namespace also prevents fallback after manifest/summary stripping, including all-absent material. |
| Stage 1 consumption | `src/bg3loc/dialogue_stage2_preview.py`: `read_stage1_contexts_for_validation` | Reads actual sealed staging envelopes, validates exact prepared inventory/target hashes/DTOs/material/summary, returns read-only typed contexts. Does not reinterpret the staging marker as a production manifest or create execution items/DBs. |

Runtime schema additions are **byte-identical copies** of accepted frozen schemas:
`schemas/production-manifest-v1.3.schema.json` and
`schemas/production-finalize-assets-v1.schema.json`. The original documentation
schemas/registry are unchanged. Existing setuptools schema packaging includes
these files; runtime code does not depend on documentation paths.
Their canonical schema fingerprints are pinned in the validator, so an existing
SchemaStore directory override cannot silently supply a more permissive schema.

The second schema validates the asset **bundle declaration**, its file SHA and
self fingerprint/locales/origin-extract binding only. No asset payload/version
index/XML/LOCA/package reader, rebuilder, portability or repacking is implemented.
Source/evidence binding recomputes the exact Stage 0 H(C) object from the pinned
raw source/extract/evidence file receipts; it does not authenticate the truth of
upstream build attestations without a completed prepared-workspace producer.

## H0/HSE exact byte parity (VERIFIED)

Besides frozen goldens, a local check loads the original `HEAD` prompt assembly,
chat renderer and item-identity code into isolated Python modules, supplies the
same fictional H0/HSE fixtures, and compares the **actual role/content UTF-8
bytes**, effective hashes and input hashes against the new code. Both are exact.
Evidence: `workspace/b1-03-phase6-stage2/head-byte-parity.json`.

| Fixture | System UTF-8 bytes | User UTF-8 bytes | Original HEAD bytes/hash equality |
| --- | ---: | ---: | --- |
| H0 | 360 | 200 | PASS |
| HSE | 719 | 372 | PASS |

H0 input `c8813418c5c77f1fef21f70044cf846492efcf9d7a0722d9601a719dc692c0ba`,
effective `1e3bc4f371833c4af0f6b9acaa8bec6e2339861ee4be5ac59ed17b42a0f755ad`,
message fingerprint `947b5aeb0665f4e6aab8a567521ff9f1f0715d0c2a45a42d188fa2114e4ebd0a`.

HSE input `ecac61e8705b82aa4c25ab2d06df8f46cbbd56581f27b7ddf6f3c42ae5f757d6`,
effective `71b4354ae590aaafb48346a0e6f50b579f5f3a17af9a0afe1f9de5e0a463bdd0`,
message fingerprint `d57ec01aaa0b5321aaf46472752c1641fb11c174da899bb76c5d4e70566be9f8`.

HD tests independently reconstruct the exact frozen input payload. Adding,
removing or changing context/native proof changes item identity; absence returns
H0. Proof-only changes leave effective prompt and actual chat messages identical.
Existing seed reconciliation retains success only for the same input identity;
changed/added/removed HD inputs invalidate it. Old claimed input cannot resolve
new material. Per-item HSE inside a mixed 1.3 namespace retains its original
payload, rather than being wrapped in HD or a generic context item identity.

These are identity/integrity checks, not Stage 3 QA/review approval. No 1.3 success,
QA or review is authorized for production by this implementation.

## Grouped safety / leakage evidence (VERIFIED)

The JSON wire is exactly:

```json
{
  "relationType": "nativeChild",
  "relationSemantics": "possibleStructuralAlternatives",
  "possiblePredecessors": [{"sourceVariants": [{"sourceText": "Fictional source."}]}],
  "possibleSuccessors": []
}
```

It appears under top-level `dialogueContext`; legacy `ContentUid`, category,
batching contextGroupKeys and target source remain at the top level. Source text
is preserved as untrusted JSON data. Related metadata is not projected. Safety
instructions are compared verbatim against the registry and checked for local
assembly/renderer/hash consistency. Tests exercise injection-like source text,
related protected tokens, equal text across nodes, multiple variants within one
alternative, and a fictional **3 predecessor / 13 successor** case-006-style
representation. No alternatives are converted into previousLine/nextLine or a
unique runtime sequence. No model semantic/injection-resistance verdict is made.

Real local-only Stage 1 envelopes were independently consumed and dry rendered
against existing prepared target material, without reading game archives or an
original full source universe:

- Exact inventory: **218,272** targets; no added execution items.
- Dry rendered contexts: **27,946**.
- Preserved alternative groups: **50,763**; source variants: **72,033**.
- All grouped object/variant keys match the source-only projection.
- Provider calls: **0**; execution items created: **0**; 1.3 workspaces published: **0**.
- Aggregate ordered dry-render fingerprint:
  `70ca847d2bac785843b61bd1cd8af159e60e01632d1302e3f9c74fbd42fbca1b`.

Evidence: `workspace/b1-03-phase6-stage2/real-stage1-dry-render-validation.json`.
This aggregate follows the existing plan iteration order; the item/material
identity contracts themselves exclude batch partition identity and use canonical
UID/group/variant order, as verified by synthetic split/order tests.

## Isolation and fail-closed boundaries (VERIFIED)

`validate_stage2_workspace` returns a distinct `Stage2WorkspaceValidation`, never
an executable `ProductionWorkspaceBinding`. Its synthetic fixtures contain
schema-correct D7 descriptors whose payloads are deliberately absent. They are
labelled offline fixtures; passing descriptor/material/DB foundation checks is
not full D7 validation or execution permission.

Only explicitly named `stage2_validation_only=True` loader/resolver paths accept
those fixtures, with exact sealed input parameters and current claimed hash.
There is no CLI switch to execute them. Default `verify_production_workspace`,
`run_init`, resolver, worker/start/claim/success and HD provider transport remain
blocked. A worker also rejects an offline resolver bound method before claiming.
Direct HD provider calls return `CONTEXT_CONTRACT_MISMATCH` before assembly,
before-send callbacks or transport. Tests assert zero provider-mock calls and
zero attempts in declared 1.3 fixtures. No mutable config bypass enables sends.

DB foundation metadata includes `schemaVersion=1.3`, the existing generic
`executionContextContractFingerprint`, explicit namespace version and dialogue
material fingerprint, plus exact legacy plan/ruleset/prompt/locale bindings.
The new metadata keys are declarations/bindings, not new policy/DTO versions.
No hash prefix is used to infer a context mode. In-place sealed 1.3 reconciliation
or implicit DB version upgrade/downgrade is refused.

## Tests and Git state (VERIFIED)

- **61 new Stage 2 synthetic tests passed** (`tests/test_dialogue_stage2.py`).
- Final targeted suite: **296 passed**; includes Stage 0/1, H0/HSE identities,
  same-entity prompt, B1-02 activation and production context regressions.
- Full attempted suite: **1,071 passed, 75 subtests passed, 1 failed**. The failure
  is the existing fictional HTTP demo's sandbox **WinError 10013** loopback socket
  restriction; it is **environment-blocked, not PASS**.
- After the final additional Stage 2 cases/guards (including nullable legacy
  contracts and frozen schema override protection), the full available suite
  with that diagnosed demo excluded: **1,082 passed, 75 subtests passed**.
- UTF-8 and workspace-owned Python/pytest temporary directories were used.
  No production code/test fixture was modified to disguise the demo failure.

Logs: `workspace/b1-03-phase6-stage2/pytest-targeted-delivery.txt`, `pytest-full.txt`,
`pytest-full-delivery.txt`. The blocked existing demo attempted only its fictional
local HTTP fixture; no external provider calls or real-text translations occurred.

Pre-existing files changed only for the nine authorized Stage 2 integration sites
listed above. Starting-file SHA audit preserves the accepted DTO/adapter/
materializer/staged prepare/Stage 1 tests/report, Stage 0 documents/registry/
schemas/tests, Phase 5 design, Phase 3 dirty files and prior research CLI changes.
QA/review, attempt provenance schema, finalizer and rebuilder files are unchanged.

New files: three Stage 2 modules (`dialogue_prompt.py`,
`dialogue_execution_contract.py`, `dialogue_stage2_preview.py`), two exact runtime
schema copies, synthetic Stage 2 tests, and this report. All generated proprietary
data stays under ignored `workspace/`. Git remains dirty with all prior work;
nothing staged, committed, pushed or merged. `git diff --check` passes.

Stage 2 diff/status, separate from preserved prior dirty work:

```text
 M src/bg3loc/chat_prompt.py
 M src/bg3loc/commands/translation_state.py
 M src/bg3loc/execution_runner.py
 M src/bg3loc/execution_state.py
 M src/bg3loc/production_workspace.py
 M src/bg3loc/prompt_assembly.py
 M src/bg3loc/providers/openai_compatible.py
 M src/bg3loc/translation_identity.py
 M src/bg3loc/translation_request.py
?? docs/research/b1-03-stage2-implementation-review.md
?? schemas/production-finalize-assets-v1.schema.json
?? schemas/production-manifest-v1.3.schema.json
?? src/bg3loc/dialogue_execution_contract.py
?? src/bg3loc/dialogue_prompt.py
?? src/bg3loc/dialogue_stage2_preview.py
?? tests/test_dialogue_stage2.py
```

## Remaining integration blockers / Stage 3 readiness

**VERIFIED ready for review:** request, grouped renderer, H0/HSE/HD item identity,
config namespace, strict manifest/DB/material foundation checks and fail-closed
entrypoints are implemented and tested. Stage 1 material can be read for offline
validation. No Contract Change Request was required and no frozen spec changed.

**PROPOSED next step, only after separate authorization:** Stage 3 actual-send
provenance and additive nullable columns, identity-bound rejection archive,
semantic REVIEW routing and current QA/review/completion safeguards. Preserve
all current stop guards until the necessary verification replaces them; do not
turn execution on with a configuration flag or one-line guard removal.

**UNKNOWN / mandatory later blockers:** actual complete 1.3 prepare publication,
authoritative corpus/build/extract attestation, Stage 3 gates, D7 asset payload
closure/semantic/path/roundtrip/repack verification, Stage 4 package/portability
and human production-shaped case-006 evaluation, operational preflight costs,
and Stage 5 explicit production activation review. Offline resolver currently
revalidates complete prepared seals on each resolution; production throughput
is not asserted. No translation-quality improvement or broad safety claim.

**Stage 3 = NOT STARTED · Production Activation = NOT APPROVED**
