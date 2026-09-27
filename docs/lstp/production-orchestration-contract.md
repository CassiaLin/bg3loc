# LSTP-03A | Production Orchestration Contract / 生產流程編排契約

## Status / 狀態

~~~text
Milestone: v1.3 Production Usability 03A
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
  LSTP-01C Translation Execution and State = ACCEPTED
  LSTP-01D Translation QA and Review Routing = ACCEPTED
  LSTP-01E Production Completion and Merge Readiness = ACCEPTED
  LSTP-01F Final Merge Bridge and Rebuild = ACCEPTED
  LSTP-02B Production Human Review Resolution = ACCEPTED
  LSTP-02C Unclassified Resolution Policy = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

BG3Loc v1.2.0 already has the accepted building blocks needed for large-scale translation production. The remaining usability problem is that an operator must manually connect several commands and keep their paths and provenance aligned.

v1.2.0 已經具備大型翻譯 production 所需的核心能力；目前主要問題不是缺功能，而是操作人員必須自己串接多個命令，並自行確保每一步拿到的是同一條 provenance chain。

03A adds one high-level preparation command that composes the accepted primitives without changing their semantics.

03A 的目標是新增一個高階準備命令，把既有已驗收 primitive 安全地串起來，但不重新定義 classification、batching 或 execution-state 規則。

The intended operator experience is:

~~~text
existing extract + research evidence + ruleset
→ production prepare
→ production workspace ready for translation execution
~~~

The low-level commands remain available for debugging, research reproduction, and advanced operators.

---

## Proposed CLI / 預計 CLI

~~~powershell
bg3loc production prepare `
  --extract workspace/extract/extract-manifest.json `
  --source workspace/extract/normalized/English.jsonl `
  --research-mappings research-output/research-mappings.jsonl `
  --ruleset ruleset.json `
  --output workspace/production
~~~

Optional inputs may include:

~~~text
--story-ledger
--ui-skill-universe
--unclassified-decisions
--max-records CATEGORY=N
~~~

The exact spelling may be refined during implementation, but the semantic contract below must remain stable.

---

## What prepare owns / prepare 負責什麼

For a new production workspace, the command composes these accepted steps:

~~~text
1. functional classification
2. optional unclassified resolution overlay
3. deterministic category-aware batching
4. durable execution-state initialization
5. production manifest generation
~~~

Conceptually:

~~~text
research classify
→ research resolve-unclassified (optional)
→ research batch
→ translation-state init
→ production-manifest.json
~~~

03A must call or reuse the same implementation paths as the accepted low-level commands. It must not maintain a second implementation of classification, resolution, batching, or execution-state semantics.

---

## What prepare does not own / prepare 不負責什麼

03A does not:

~~~text
run a translation provider
run translation workers
run QA
resolve human REVIEW decisions
decide linguistic quality
create MERGE_READY output
run production bridge
rebuild LOCA/PAK
install into the game
hide unresolved classification rows
guess missing evidence
rewrite an existing accepted automatic classification ledger
~~~

Those responsibilities remain with the existing accepted stages.

The high-level command is orchestration, not a new source of truth.

---

## Canonical identity / 正式 identity

`ContentUid` remains the canonical identity from input through execution state.

03A must not create a new row identity based on:

~~~text
batch number
file order
database row id
provider request id
workspace-relative path
~~~

A production workspace may contain many derived files, but ownership remains one primary production owner per `ContentUid`.

---

## Workspace layout / 工作目錄

A successful preparation should create a predictable layout such as:

~~~text
workspace/production/
  production-manifest.json

  classification/
    functional-classification.jsonl
    classification-summary.json

    # present when --unclassified-decisions is supplied
    resolved-classification.jsonl

  batches/
    batch-plan.json
    batch-summary.json
    materials/
      ...
    unresolved.jsonl
    excluded.jsonl

  execution.sqlite3
~~~

Exact supporting filenames should follow the existing low-level outputs wherever possible.

03A should not rename accepted artifact formats merely to make the orchestration layer look cleaner.

---

## Classification selection / 分類輸入選擇

The original automatic classification ledger remains immutable.

If no decision file is supplied:

~~~text
batch input = functional-classification.jsonl
~~~

If `--unclassified-decisions` is supplied:

~~~text
functional-classification.jsonl
+ decision overlay
→ resolved-classification.jsonl

batch input = resolved-classification.jsonl
~~~

The resolver must always receive the original automatic classification ledger as its source classification.

The orchestration layer must never use a prior resolved ledger as though it were the immutable 01A source.

---

## Unresolved policy / 未分類政策

03A must not silently convert unresolved rows into a guessed category.

A preparation run may still succeed with unresolved rows only when those rows remain explicitly outside normal translation batches and the resulting counts are visible in the production manifest.

If an operator provides a decision file, every decision continues to obey 02C:

~~~text
assign
exclude
pending
~~~

Foreign UIDs, duplicate decisions, attempts to override already classified rows, and invalid target categories remain fail-closed errors.

---

## Ruleset binding / Ruleset 綁定

Real production preparation requires a versioned ruleset.

The execution database must be initialized through the existing ruleset-aware `translation-state init` semantics so that effective translation input identity continues to bind:

~~~text
prompt/ruleset version
ruleset fingerprint
source locale
target locale
batch material identity
~~~

03A must not replace this with a weaker workspace-level flag.

The production manifest should record non-secret ruleset identity and hash information. It must never record API keys.

---

## Production manifest / Production manifest

A successful preparation writes `production-manifest.json`.

This manifest is an immutable snapshot of how the workspace was prepared, not a mutable replacement for the execution database.

At minimum it should record:

~~~text
format/version
createdAt or equivalent preparation timestamp
source locale
target locale
extract manifest path + SHA256
normalized source path + SHA256
research mappings path + SHA256
optional structural evidence paths + SHA256
automatic classification path + SHA256
resolved classification path + SHA256 when present
unclassified decisions path + SHA256 when present
classification counts
batch plan path
batchPlanFingerprint
batch counts
unresolved count
excluded count
ruleset path + SHA256
ruleset version/fingerprint
execution database path
execution seeded ContentUid count
~~~

Paths may be stored for operator usability, but cryptographic bindings must not rely on absolute machine-specific paths alone.

---

## Existing workspace behavior / 既有工作目錄行為

03A is fail-closed by default when the requested output workspace already contains production artifacts.

It must not silently overwrite:

~~~text
functional-classification.jsonl
resolved-classification.jsonl
batch-plan.json
execution.sqlite3
production-manifest.json
~~~

The first implementation should prefer an explicit fresh output directory rather than inventing automatic in-place migration semantics.

If a future `--resume` or `--force` mode is added, it requires its own contract and tests.

---

## Failure atomicity / 失敗時完整性

A partially prepared workspace must not look like a successful production workspace.

The final `production-manifest.json` should be written only after all required preparation stages succeed.

If an earlier step fails, the command should:

1. return non-zero;
2. preserve enough intermediate evidence for diagnosis when safe;
3. not claim the workspace is ready;
4. not silently reuse incompatible partial state on the next run.

Implementation may use a staging directory followed by an atomic/final move where practical.

---

## Fail-closed conditions / 安全失敗條件

Preparation must stop rather than guess when any required binding is unsafe or inconsistent, including:

~~~text
missing extract manifest
missing normalized source material
missing research mappings
invalid or incomplete ruleset
source/target locale mismatch between accepted inputs
duplicate ContentUid ownership
foreign ContentUid entering classification/batching
unclassified decision integrity failure
batch material count mismatch
missing batch material
execution-state seeding mismatch
existing incompatible execution database
existing completed production manifest in target workspace
unknown accepted artifact format/version when required for safe binding
~~~

03A must not turn a low-level integrity error into a warning merely to make the high-level command continue.

---

## Determinism / 可重現性

For the same effective inputs and configuration:

~~~text
classification semantics = unchanged
resolved classification semantics = unchanged
batchPlanFingerprint = unchanged
batch membership = unchanged
execution seed identity = unchanged
~~~

The production manifest may contain a preparation timestamp or workspace-relative paths, so the entire manifest file does not need to be byte-for-byte identical across different directories.

It must contain stable hashes/fingerprints that prove the deterministic artifacts are the same.

---

## Low-level compatibility / 與既有命令相容

After `production prepare`, an advanced operator must still be able to use existing commands directly:

~~~text
bg3loc translation-state summary
bg3loc translation-state run-start-openai-compatible
bg3loc translation-state worker-openai-compatible
bg3loc qa run
bg3loc qa review-export
bg3loc production status
bg3loc production bridge
bg3loc rebuild
bg3loc install --dry-run
~~~

03A must produce ordinary accepted artifacts, not orchestration-only private formats.

---

## Public documentation correction discovered during 03A / 03A 發現的文件問題

The current v1.2 large-scale guide shows a `resolve-unclassified` example whose `--classification` path is named `resolved-classification.jsonl`.

The accepted 02C contract requires the resolver source to be the original immutable automatic classification ledger.

Implementation work for 03A should correct that example to use:

~~~text
classification/functional-classification.jsonl
~~~

with the output written separately as:

~~~text
classification/resolved-classification.jsonl
~~~

This is a documentation correction, not a change to 02C semantics.

---

## First implementation acceptance / 第一版驗收條件

03A implementation is accepted only when all of the following pass:

1. one high-level command creates a fresh production workspace from accepted inputs;
2. no-decision path batches the original automatic classification ledger;
3. decision path resolves from the original ledger and batches the derived resolved ledger;
4. the original automatic classification ledger remains unchanged;
5. batch fingerprint matches the equivalent low-level command sequence;
6. batch membership matches the equivalent low-level command sequence;
7. execution database seeds the same ContentUid set and effective input identities as low-level `translation-state init`;
8. production manifest records the required provenance bindings and counts;
9. API keys or other secrets never appear in the manifest;
10. existing incompatible workspace fails closed;
11. missing/inconsistent inputs fail closed;
12. partial failure does not produce a successful final production manifest;
13. existing low-level commands can continue directly from the produced artifacts;
14. targeted tests and full repository regression pass;
15. one real-corpus preparation run and one independent repeat demonstrate stable deterministic fingerprints.

---

## Implementation validation / 實作驗證

03A implementation has passed the targeted orchestration suite and the complete repository regression.

~~~text
targeted:
13 passed
0 failed

full regression:
412 passed
68 subtests passed
0 failed
~~~

The recurring Windows pytest cache warning remains:

~~~text
.pytest_cache
WinError 5
~~~

It is environment/cache related and did not cause a test failure.

Real-corpus preparation and independent-repeat determinism are still required before 03A can be marked ACCEPTED.

---

## Real-corpus acceptance / 真實資料驗收

03A was validated against the same full production corpus previously accepted by LSTP-01A/01B.

Inputs:

~~~text
extract manifest:
workspace/ui-skill-role-real-20260913/extract-absolute/extract-manifest.json

normalized source:
workspace/ui-skill-role-real-20260913/extract-absolute/normalized/English.jsonl

research mappings:
workspace/lstp-01b-entity-evidence-v2/research-mappings.jsonl

story ledger:
workspace/lstp-01b-story-nodeid-v4/story-occurrence-ledger.csv

UI-skill universe:
workspace/lstp-01b-entity-evidence-v2/ui-skill-universe.csv

ruleset:
docs/lstp/ruleset-example.json
~~~

Two independent fresh production workspaces were prepared:

~~~text
workspace/lstp-03a-real-prepare-v1
workspace/lstp-03a-real-prepare-v1-repeat
~~~

Both runs produced the same results:

~~~text
total corpus:        232878
classified:          218272
unclassified:         14606
excluded:                 0
batch count:            291
execution rows:       218272
source locale:       English
target locale:       ChineseTraditional
~~~

Both runs reproduced the previously accepted LSTP-01B batch fingerprint exactly:

~~~text
8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326
~~~

The ruleset binding was also identical in both runs:

~~~text
ruleset version:
example-v1

ruleset fingerprint:
9f5873ddaac532145d129d42b692a2b2ec7d6c1726e57ba7596f21178d4ef397
~~~

This demonstrates that the high-level orchestration layer preserves the accepted 01A/01B semantics and initializes the same 01C execution universe.

### Final regression / 最終回歸

~~~text
targeted:
13 passed
0 failed

full repository regression:
412 passed
68 subtests passed
0 failed
~~~

The recurring Windows pytest cache warning remains environment-related and nonblocking.

### Acceptance decision / 驗收判定

03A acceptance conditions are satisfied:

1. one high-level command creates a fresh production workspace — PASS;
2. accepted classification semantics are reused — PASS;
3. accepted batching semantics are reused — PASS;
4. original automatic classification remains immutable — PASS;
5. execution state is bound to the produced batch plan — PASS;
6. ruleset identity is bound to execution state — PASS;
7. existing workspace fails closed — PASS;
8. locale mismatch fails closed — PASS;
9. equivalent real-corpus inputs reproduce the accepted batch fingerprint — PASS;
10. independent repeat produces identical production counts and deterministic fingerprint — PASS;
11. targeted and full regression remain green — PASS.

~~~text
LSTP-03A Production Orchestration = ACCEPTED
~~~

---

## Deferred / 後續階段

03A intentionally does not define a one-command full translation run.

Possible later v1.3 milestones may add:

~~~text
03B provider execution orchestration
03C QA/review operator loop
03D finalize/bridge/rebuild orchestration
03E production reporting and cost/throughput summaries
03F public clean-room reproduction
~~~

Each should compose accepted primitives rather than collapse safety boundaries.

---

## Contract question / 契約問題

Can BG3Loc reduce large-scale production setup from several manually connected commands to one safe preparation action while preserving every accepted v1.2 provenance, determinism, and fail-closed boundary?

03A exists to make that answer **yes** without reopening the accepted core.
