# LSTP-03D Finalize / Bridge / Rebuild Orchestration

Milestone: v1.3 Production Usability 03D
State: ACCEPTED
Depends on: LSTP-01E Production Completion = ACCEPTED; LSTP-01F Bridge/Rebuild = ACCEPTED; LSTP-03A = ACCEPTED; LSTP-03B = ACCEPTED; LSTP-03C = ACCEPTED
Core reopening: no

## English

### User goal

After translation and QA, an operator needs two direct answers: whether the classified production set is ready, and, when it is ready, a safe way to produce the final localization artifact. The operator should not need to manually connect completion dispositions, bridge JSONL files, validation manifests, LOCA serialization, and PAK rebuilding.

03D adds one workspace command:

```text
bg3loc production finalize --workspace WORKSPACE --output OUTPUT
```

The command composes the accepted 01E completion view, 01F final-merge bridge, and existing rebuild pipeline. It does not define a new completion state, QA rule, accepted-target format, or rebuilder.

### Completion gate

Before creating the output directory or invoking the bridge, finalize validates the production workspace and recalculates the accepted completion view. Every row in the classified production execution inventory must currently be `MERGE_READY`. The following counts must all be zero:

```text
WAITING_TRANSLATION
WAITING_RETRY
WAITING_REVIEW
BLOCKED
```

The required universe is the accepted 01E execution/batch-plan universe. Unclassified or explicitly excluded source rows that were never seeded into production execution are not incorrectly required to become `MERGE_READY`.

If the gate fails, the error reports every non-zero disposition count. No bridge directory, rebuild output, or final manifest is created.

### Finalize pipeline

On a ready workspace, finalize performs this sequence:

```text
verify production workspace
-> verify recorded extract-manifest provenance
-> accepted 01E completion gate
-> accepted 01F build_final_merge_bridge()
-> validate the bridge/rebuild handoff manifest and its bound files
-> existing run_rebuild()
-> verify rebuild PASS evidence and artifact hashes
-> write production-final-manifest.json last
```

The bridge's strict `validate-manifest.json` is the accepted validate-compatible handoff defined by 01F. The existing rebuilder performs semantic round-trip, accepted-text, UID-set, untouched-record, and repack integrity validation.

### Output and failure behavior

`OUTPUT` must be absent or an empty directory. Finalize never silently reuses a non-empty or partially failed output. Intermediate bridge and rebuild artifacts may remain after a failure for diagnosis, but `production-final-manifest.json` exists only after the complete pipeline succeeds. A retry uses a fresh output directory.

The final manifest is an immutable provenance snapshot. It records locale identity, production workspace identity, batch/ruleset/inventory fingerprints, the completion snapshot, bridge and validate hashes, rebuild provenance, and each LOCA/PAK artifact path and SHA-256. It never records provider credentials.

### Acceptance gates

03D advances through `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED`. Acceptance requires fail-closed disposition tests, artifact-substitution tests, a controlled 03A-to-03D E2E, a real-corpus pending-translation gate check, performance evidence, full regression, and a clean repository audit.

Acceptance evidence (2026-09-28):

- 25 focused finalize/prepare/bridge/rebuild tests and 8 subtests passed.
- The controlled E2E used one provenance chain for prepare, mocked provider execution, QA REVIEW, human revision, QA rerun, bridge, rebuild, and final manifest creation.
- Final repository regression passed with 456 tests and 72 subtests, with no failures or warnings.
- The retained real corpus produced 232,878 total rows, 218,272 classified rows, 14,606 unresolved rows, 291 batches, and fingerprint `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`.
- Real-corpus report took 4.030 seconds. Finalize readiness took 3.779 seconds and stopped before output creation with `WAITING_TRANSLATION=218272`.
- The temporary real-corpus workspace and attempted final-output path were absent after validation.

## 繁體中文（台灣）

### 使用者目標

翻譯與 QA 完成後，operator 需要兩個直接答案：目前已分類的 production set 是否已經完成；若完成，如何安全產生最終語言檔。使用者不應自行串接 completion disposition、bridge JSONL、validation manifest、LOCA serialization 與 PAK rebuild。

03D 新增一個 workspace command：

```text
bg3loc production finalize --workspace WORKSPACE --output OUTPUT
```

此命令只組合 accepted 01E completion view、01F final-merge bridge 與既有 rebuild pipeline；不建立新的 completion state、QA 規則、accepted-target 格式或第二套 rebuilder。

### Completion gate

Finalize 在建立輸出目錄或呼叫 bridge 前，會先驗證 production workspace 並重新計算 accepted completion view。classified production execution inventory 中的每一列都必須是目前的 `MERGE_READY`，下列計數必須全部為零：

```text
WAITING_TRANSLATION
WAITING_RETRY
WAITING_REVIEW
BLOCKED
```

需要完成的 universe 是 accepted 01E execution/batch-plan universe。從未進入 production execution 的 unclassified 或 explicit excluded source rows，不會被錯誤要求變成 `MERGE_READY`。

若 gate 未通過，錯誤會列出所有非零 disposition count，而且不會建立 bridge、rebuild 或 final manifest。

### Finalize pipeline

Ready workspace 會依序執行：

```text
驗證 production workspace
-> 驗證 manifest 記錄的 extract-manifest provenance
-> accepted 01E completion gate
-> accepted 01F build_final_merge_bridge()
-> 驗證 bridge/rebuild handoff manifest 與綁定檔案
-> 既有 run_rebuild()
-> 驗證 rebuild PASS evidence 與 artifact hashes
-> 最後才寫 production-final-manifest.json
```

Bridge 的 strict `validate-manifest.json` 是 01F accepted validate-compatible handoff；既有 rebuilder 負責 semantic round-trip、accepted-text、UID-set、untouched-record 與 repack integrity validation。

### 輸出與失敗行為

`OUTPUT` 必須不存在或為空目錄。Finalize 不會默默沿用非空或先前失敗的輸出。失敗後可以保留 bridge/rebuild 中間產物供診斷，但只有整條 pipeline 成功後才會產生 `production-final-manifest.json`；重試必須改用 fresh output。

Final manifest 是 immutable provenance snapshot，記錄 locale、production workspace identity、batch/ruleset/inventory fingerprint、completion snapshot、bridge/validate hash、rebuild provenance，以及每個 LOCA/PAK artifact 的 path 與 SHA-256；不記錄 provider credential。

### 驗收門檻

03D 依序經過 `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED`。必須完成 disposition fail-closed、artifact substitution、controlled 03A→03D E2E、真實語料 pending-translation gate、效能證據、完整 regression 與乾淨 repository audit，才能 ACCEPTED。

驗收證據（2026-09-28）：

- 25 個 finalize/prepare/bridge/rebuild focused tests 與 8 個 subtests 全部通過。
- Controlled E2E 使用同一條 provenance chain 完成 prepare、mock provider execution、QA REVIEW、人工 revise、QA rerun、bridge、rebuild 與 final manifest。
- 最終 repository regression 為 456 tests、72 subtests，零失敗、零 warning。
- 保留的真實語料結果為 232,878 total、218,272 classified、14,606 unresolved、291 batches，fingerprint 為 `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`。
- 真實語料 report 花費 4.030 秒；finalize readiness gate 花費 3.779 秒，並在建立 output 前以 `WAITING_TRANSLATION=218272` 正確停止。
- 驗證完成後，temporary real-corpus workspace 與嘗試的 final-output path 都不存在。
