# B1-03 Phase 6 Stage 1 — Typed Material & Prepare

2026-10-09 · `feat/b1-03-dialogue-context` · base HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb`.
Stage 0 Contract Review ACCEPTED; this implementation preserves the accepted
contract files and all their versions. No Stage 2–5 implementation or activation.

## Implemented scope (VERIFIED)

| Deliverable | Implementation | Contract boundary |
| --- | --- | --- |
| Deep immutable DTO / strict decoder | `src/bg3loc/dialogue_context.py`: `DialogueContext`, `DialogueTargetBinding`, `DialogueTargetProof`, `DialogueAlternative`, `DialogueSourceVariant`, `NativeChildProof`, `DialogueBudgetContract`, `decode_dialogue_context`, `dialogue_context_from_material` | Frozen slotted dataclasses, nested tuples; detached wire copies. Closed objects, exact primitive types/versions, target/source/English binding, native origins, directional Child endpoints, canonical ordering, complete nonblank variants, original codepoint count and both fingerprints. |
| Public evidence adapter | `src/bg3loc/dialogue_materialization.py`: `DialogueEvidenceAdapter.from_records`, `.from_workspace`, `sealed_evidence_rows` | Complete P1 dialogue/node/occurrence/edge universe, plus full English source map. Strict existing public evidence schema, native assertion hashes, ownership and declared structural status checks. Five P1 ledgers sealed, including unused targetEvidence. Research graph dictionaries are never imported/trusted. |
| Policy A materialization | `DialogueEvidenceAdapter.materialize`, `materialize_inventory` | Native Child/direct localized only, no structural-node traversal or references. Whole-dialogue and node conflicts, incompatible target occurrences, fallback identity and incomplete English alternatives excluded. Bark and other categories absent. All valid directional alternatives/occurrence variants retained. |
| Budget / deterministic summary | Same materializer | Original source variants in both directions, Python `len`, markup/whitespace/non-BMP included. Exactly 2,000 permitted; above it rejects the entire set. No branch cap, text truncation, additional execution items or baseline identity changes. |
| Explicit staged prepare | `src/bg3loc/dialogue_stage_prepare.py`: `prepare_dialogue_stage`, `load_prepared_inventory`; `src/bg3loc/commands/research.py`: `run_dialogue_stage_prepare` | Separate opt-in research command. Existing prepare defaults unchanged. Inputs read-only; target inventory/text/category/count checked. Pinned input bytes rechecked before atomic fresh-output publication; existing output refused. |

No runtime schema registration is needed for this Stage 1 DTO: the production
decoder implements the accepted closed DTO contract directly, and synthetic
tests validate its output against the unchanged Stage 0 documentation schema.
The adapter uses the already packaged P1 public evidence schema. Documentation
registry/schema files are not runtime dependencies.

### Evidence producer canonicalization (VERIFIED implementation)

The frozen DTO's evidence/context fingerprint projections are implemented
exactly as Stage 0. The opaque producer proof fields use the following
deterministic native assertion aggregation, without changing their schema:

- Occurrence assertion: P1 occurrence row excluding `provenance`, `schemaVersion`,
  `recordType`, `evidenceId`. It retains dialogue/node/whole-node definition,
  UID/version/field role/line ID and native conditional variant fingerprint.
  Each assertion uses Stage 0 H(C). Identical resource duplicates collapse;
  all distinct assertion fingerprints remain, sorted and unique per node/UID.
- `sourceOccurrenceFingerprint`: H(C(sorted unique target occurrence fingerprints)).
- Child assertion: P1 original edge row excluding the same transport/provenance
  fields and derived `structuralStatus`. Native from/to, owning definition,
  child index and full native reference parameters remain bound.
  `edgeDefinitionFingerprint`: H(C(sorted unique Child assertion fingerprints))
  for the scoped node pair. The P1 `definitionFingerprint` is the owning node
  definition; it is not mislabeled as the edge fingerprint.
- Native dialogue/node definition fingerprints remain the P1 full-definition
  values, including opaque native definition closures. Speaker fields are never
  consulted for selection, inferred as actors, or emitted in the DTO.
- Summary `inputDigests.source`: H(C(full UID→SHA256(original UTF-8 source) map)).
  Four evidence input digests: H(C(sorted unique H(C(full sealed family row))))
  including transport provenance and derived status. `classification`: H(C(the
  exact prepared UID→category projection)). Original ledger semantic seals and
  all input file bytes are additionally checked; these input digests are not
  claims of cryptographic source authentication.
- Material fingerprint: H(C(exact prepared UID→contextFingerprint/`absent` map));
  summary fingerprint excludes only itself. Summary has the frozen closed fields,
  no timestamps/absolute paths. Costs/cardinality stats cover present contexts.

Input order and batch partitioning do not affect DTO ordering or output order.
Equal text at different nodes/directions/UIDs stays distinct and is counted again.
Normal absence is omitted, never serialized null. Malformed-present is fatal.
Two context keys, including two nulls, fail `BOTH_CONTEXT_FAMILIES` first.
Existing B1-02 material is validated with its existing prepare-side decoder and
left untouched; this staged package is not a merged execution material.

## Staged path and runtime isolation (VERIFIED)

```text
python -m bg3loc research dialogue-stage-prepare --enable-dialogue-context \
  --evidence-dir workspace/b1-03-final-research \
  --source-snapshot workspace/p5-public-isolated/extract/normalized/English.jsonl \
  --batch-plan workspace/p5-real-prepare-a/batches/batch-plan.json \
  --output-dir workspace/b1-03-phase6-stage1/staged-real-a
```

Output files:

- `stage1-manifest.json`: staging marker `NOT_EXECUTABLE`, `localOnly=true`,
  `productionActivation=false`, hashes of staging records and summary.
- `stage1-target-contexts.jsonl`: canonical UID order; target is nested with
  UID/category/source SHA, optional full validated `dialogueContext`.
  It lacks execution material's top-level target/source/batch columns.
- `dialogue-context-materialization-summary.json`: frozen summary contract.
- `README.txt`: local-only and runtime boundary notice.

The staging marker is not a production manifest/version. There is no
`production-manifest.json`, `batch-plan.json`, `batches/materials`, execution DB,
HD identity, renderer, D5 gate or D7 asset bundle. Synthetic tests pass this
manifest to the existing execution loader and `run_init`; both reject missing
`batchPlanFingerprint`, and no DB is created. No consumer was extended to accept
Stage 1 artifacts. Existing default prepare, H0/HSE, prompts, TranslationRequest,
QA/review, attempts, finalizer and rebuilder implementations remain unchanged.

## Real local corpus validation (VERIFIED)

All proprietary data remains beneath ignored `workspace/`. No game archive is
reopened and no raw data is copied into tracked paths. The complete English
universe has 232,878 rows; the four evidence ledgers have 18,757 dialogue,
374,082 node, 352,465 occurrence and 417,563 edge rows. P1 targetEvidence is also
integrity checked without trusting its research relation verdicts as DTOs.

| Materialization result | Count |
| --- | ---: |
| Prepared targets, all categories | 218,272 |
| Eligible category `dialogue_general` | 166,036 |
| Complete candidates before budget | 27,949 |
| Present after 2,000 budget | 27,946 |
| Whole-set budget exclusions | 3 |
| Bark targets / present | 9,894 / 0 |
| Unsupported categories, including bark | 52,236 |
| Structural conflict absence | 119,775 |
| No localized relation | 18,220 |
| No dialogue occurrence | 86 |
| Incompatible occurrences | 4 |
| Incomplete English context | 2 |

Counts partition the exact 218,272 inventory. Phase 2's aggregated conflict/
no-relation reasons also included bark; Stage 1 reports bark under the frozen
`UNSUPPORTED_CATEGORY` reason. Context coverage/candidate exclusions match
Policy A, rather than changing its reliability rules.

Present source codepoints mean **162.36355829098977**, p95 **470**, max **1,975**.
Source variant cardinality mean **2.5775781865025404**, p95 **8**, max **32**.

Case-006 target-source binding identifies exactly one staged target. Its context
is retained with **947 codepoints**, **3 predecessor** and **13 successor source
variants**. This preserves the known drift case for later regression; it does
not evaluate or fix semantic drift, and budget does not eliminate that risk.
No hidden assignment key or translations are embedded in the staging artifacts.

Local artifacts and validation records:

- `workspace/b1-03-phase6-stage1/staged-real-a/`
- `workspace/b1-03-phase6-stage1/staged-real-split/`
- `workspace/b1-03-phase6-stage1/real-validation-checks.json`
- `workspace/b1-03-phase6-stage1/starting-file-seals.json`

Material fingerprint:
`850580acc8d822a91f38b37f3bc7e5f383d59583b55c6072ea0ddf8d12ebdc39`.
Summary fingerprint:
`03ae257f69539d47a71e16bd29571e014ad0f220ecfddea51007f37cab0a23c9`.

Two complete real prepares using 291 versus 1,289 batches produce byte-identical
records, summary, staging manifest and README. Record file SHA256 is
`c011dd614accb7da68a5edd4fd08b5295fbf934f2d31915e39fd6ebb3684a8ca`.
All 27,946 emitted DTOs are independently decoded again against the complete
English snapshot; every emitted variant matches its original English source,
and inventory, category counts, material and summary fingerprints are recomputed.

## Validation / regression (VERIFIED)

`tests/test_dialogue_stage1.py` has **85 passing synthetic cases** using fictional
native LSJ evidence only. It covers
DTO immutability, closed schema at every object level, exact versions/types,
duplicate JSON keys/NaN/Infinity/UTF-8/invalid Unicode, native ownership/origins/
Child endpoints, branch and conditional occurrence completeness, conflicting
definitions, target/source mismatch, incomplete English, canonical group/UID/
occurrence order, equal text preservation, 1999/2000/2001, markup/whitespace/non-BMP
counting, whole-set absence, malformed-present/both-family failures, input-copy
isolation, input seals, deterministic summary/material hashes and batch splits,
fresh-output publication and execution rejection without DB creation.

Final available suite: **1,021 passed, 75 subtests passed**, with the existing
`tests/test_public_demo.py` excluded after its environment failure was diagnosed.
No provider or pipeline implementation was changed to make a test pass.

Full attempted suite initially encountered cp950/default temporary-directory
restrictions. UTF-8 with workspace-owned Python/pytest temporary directories
resolved those. The remaining existing fictional HTTP demo failed because the
sandbox rejects its local loopback socket with **WinError 10013**; it is an
environment-blocked test, not reported as passed. Its failure is preserved in
`workspace/b1-03-phase6-stage1/pytest-full-utf8.txt`; final available suite output
is `workspace/b1-03-phase6-stage1/pytest-final.txt`. H0/HSE, B1-02 activation,
same-entity prompt and default production prepare regression tests are included.
No external provider calls were made; only the existing fictional demo attempted
its blocked local HTTP fixture during testing.

`git diff --check` passes. Prior-file SHA snapshots show only the authorized
research CLI file changed among pre-existing files. Phase 3 dirty files,
Phase 5 design, Stage 0 contract/registry/schemas/tests and all other tracked
runtime files retain their original bytes. No commit, push or merge.

Git status at delivery (nothing staged):

```text
 M src/bg3loc/commands/research.py                         # Stage 1 opt-in only
 M src/bg3loc/research/dialogue_pilot.py                   # prior Phase 3, preserved
 M tests/test_dialogue_policy_evaluation.py               # prior Phase 3, preserved
?? docs/research/b1-03-production-contract-freeze.md       # prior Stage 0, preserved
?? docs/research/b1-03-production-integration-design.md    # prior Phase 5, preserved
?? docs/research/b1-03-stage0-contracts/                   # prior Stage 0, preserved
?? tests/test_b1_03_stage0_contracts.py                    # prior Stage 0, preserved
?? docs/research/b1-03-stage1-implementation-review.md
?? src/bg3loc/dialogue_context.py
?? src/bg3loc/dialogue_materialization.py
?? src/bg3loc/dialogue_stage_prepare.py
?? tests/test_dialogue_stage1.py
```

All generated real artifacts are ignored by Git; the Stage 1 additions contain
only implementation, aggregate documentation and fictional synthetic fixtures.

## Stage 2 readiness assessment

**VERIFIED:** DTO, public adapter, budget/materializer and isolated opt-in staged
prepare are implemented and reviewable. No accepted Stage 0 contract amendment
was needed. Stage 1 is not an executable 1.3 workspace or production activation.

**PROPOSED next implementation, only after separate authorization:** review these
producer/decoder contracts, then follow the accepted Stage 2 Request/render/
identity/config scope: append the optional request field, grouped safety
projection, exact H0/HSE branches plus HD, and Manifest/DB/start/worker guards.
Full corpus/extract/source-evidence attestation and required D7 asset/preflight
closure remain mandatory before any executable 1.3 workspace can be published.
Do not attach Stage 1 material to legacy execution or bypass these requirements.
Stage 3 provenance/QA/review, Stage 4 regression/portability/package and Stage 5
activation review remain separately authorized future work.

**UNKNOWN / not verified here:** production 1.3 portability and all corpus-build
attestation/runtime gates, grouped production prompt behavior, provider/model
semantic effects, case-006 drift prevention and final activation. The finite
safety pilot remains SAFE WITH RESTRICTIONS; no translation improvement or
general safety claim follows from materialization tests.

**B1-03 Phase 6 Stage 1 — READY FOR IMPLEMENTATION REVIEW**
