# LSTP-03C QA / Review Operator Loop Orchestration

Milestone: v1.3 Production Usability 03C
State: ACCEPTED
Depends on: LSTP-01D = ACCEPTED; LSTP-01E = ACCEPTED; LSTP-02B = ACCEPTED; LSTP-03A = ACCEPTED; LSTP-03B = ACCEPTED
Core reopening: no

## English

### What this milestone is for

After translation execution, an operator must run QA, hand retryable rows back to execution, export human-review work, record human decisions, rerun stale QA, and decide whether the corpus is ready for merge. The accepted low-level commands already implement those decisions. LSTP-03C provides one workspace-oriented interface so an operator does not have to manually reconnect the database and batch-plan paths on every command.

03C does not create a new state machine. It does not weaken QA, choose a human-review decision, automatically accept a candidate, or call a translation provider during retry handoff.

### Commands

All commands start by validating `production-manifest.json`, the ruleset snapshot, batch-plan bytes, batch-material bytes, immutable execution inventory, locale binding, and fingerprints.

```text
bg3loc production qa --workspace WORKSPACE
bg3loc production retry --workspace WORKSPACE --content-uid UID
bg3loc production review-export --workspace WORKSPACE --output review.jsonl
bg3loc production review-resolve --workspace WORKSPACE --content-uid UID --decision accept|revise --reviewer NAME [--note NOTE] [--text TEXT]
bg3loc production report --workspace WORKSPACE
```

- `production qa` runs the accepted 01D QA evaluator for current succeeded rows, prints persisted QA routing counts, and then prints the accepted 01E completion view.
- `production retry` reuses the accepted QA retry handoff. It archives the rejected candidate and reopens only a current `RETRY` row. It never calls a provider.
- `production review-export` reuses the accepted 02B JSONL export and contains no provider credentials or execution configuration.
- `production review-resolve` records an `accept` or `revise` decision through the accepted review store. A revision changes the candidate output, makes previous QA stale, and requires another QA run.
- `production report` is read-only. It shows workspace identity, execution counts, QA counts, completion counts, and category completion counts.

### Fail-closed rules

The operator command must stop before mutation when the workspace manifest or any bound artifact is missing, outside the workspace, relocated through an unsafe link, or fails its recorded integrity binding. Unknown ContentUids, stale QA, the wrong QA route, retry-limit exhaustion, invalid review state, duplicate/stale decisions, and revise-without-text also fail closed through the accepted primitives.

An interrupted provider run remains incomplete; it is never reported as completed merely because orchestration returned. Retryable provider failures may currently be reclaimed immediately in the same worker invocation and can consume `max-attempts` quickly during sustained rate limiting. Backoff policy is outside 03C and must be handled operationally with bounded runs until a later milestone adds it.

### Acceptance gates

The state advances only in this order:

```text
CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED
```

Acceptance requires focused QA/review orchestration tests, a mocked 03A-to-03B-to-03C integration scenario, full regression with zero failures, and a clean repository review.

Acceptance evidence (2026-09-28):

- 77 focused production/state/QA/review tests and 12 subtests passed, including 12 dedicated 03C scenarios.
- The full suite passed with 435 tests and 68 subtests. The Windows subprocess warning found during the first run was fixed and the affected test passed with that warning promoted to an error.
- A fresh workspace was prepared from the retained real corpus: 232,878 total ContentUids, 218,272 classified, 14,606 unresolved, 291 batches, and batch-plan fingerprint `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`. Preparation took 37.802 seconds; the read-only report over 218,272 pending rows took 4.055 seconds. The temporary validation workspace was removed afterward.
- Repository review found no generated workspace files staged for commit and no credentials or machine-specific absolute paths in production source or documentation.

## 繁體中文（台灣）

### 這個里程碑要解決什麼

翻譯執行後，operator 必須執行 QA、把可重試項目交回 execution、匯出人工審核工作、記錄人工決策、重跑已失效的 QA，最後判斷整體資料是否可以合併。既有低階命令已經實作這些決策；LSTP-03C 只提供以 production workspace 為中心的操作介面，讓 operator 不必每次手動重新配對 database 與 batch plan。

03C 不建立第二套狀態機、不降低 QA 嚴格度、不替 reviewer 決定、不自動接受候選，也不會在 retry handoff 時呼叫翻譯 provider。

### 命令

所有命令會先驗證 `production-manifest.json`、ruleset snapshot、batch plan bytes、batch material bytes、execution immutable inventory、locale 與 fingerprint 綁定。

```text
bg3loc production qa --workspace WORKSPACE
bg3loc production retry --workspace WORKSPACE --content-uid UID
bg3loc production review-export --workspace WORKSPACE --output review.jsonl
bg3loc production review-resolve --workspace WORKSPACE --content-uid UID --decision accept|revise --reviewer NAME [--note NOTE] [--text TEXT]
bg3loc production report --workspace WORKSPACE
```

- `production qa` 使用 accepted 01D QA evaluator 處理目前成功的翻譯，顯示 QA routing 與 accepted 01E completion view。
- `production retry` 使用 accepted retry handoff，只能封存目前的 `RETRY` candidate 並重新開放該列；不會呼叫 provider。
- `production review-export` 使用 accepted 02B JSONL export，不輸出 provider credential 或 execution config。
- `production review-resolve` 透過 accepted review store 記錄 `accept` 或 `revise`。`revise` 會改變 candidate、使舊 QA stale，且必須重新執行 QA。
- `production report` 完全唯讀，顯示 workspace identity、execution、QA、completion 與 category breakdown。

### Fail-closed 規則

只要 manifest 或綁定 artifact 缺失、位於 workspace 外、透過不安全 link 搬移，或 integrity binding 不符，operator command 必須在任何 mutation 前停止。未知 ContentUid、stale QA、錯誤 QA route、retry 次數耗盡、無效 review state、重複或過期 decision、revise 未提供文字，也必須沿用 accepted primitive 的 fail-closed 行為。

被中斷的 provider run 只能維持 incomplete，不得因高階 orchestration 返回就被誤報 completed。目前 retryable provider failure 可能在同一次 worker invocation 立刻再次 claim，持續 rate limiting 時可能很快耗盡 `max-attempts`。Backoff 不屬於 03C；在後續 milestone 實作前，operator 應以 bounded run 控制風險。

### 驗收門檻

狀態只能依序前進：

```text
CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED
```

必須完成 QA/review orchestration focused tests、mocked 03A→03B→03C integration、零失敗完整 regression 與乾淨的 repository review，才能標記 ACCEPTED。

驗收證據（2026-09-28）：

- 77 個 production/state/QA/review focused tests 與 12 個 subtests 全部通過，其中包含 12 個專用 03C 情境。
- 完整測試套件共有 435 個 tests 與 68 個 subtests 全部通過。第一次執行發現的 Windows subprocess warning 已修正，且受影響測試已在 warning-as-error 模式下通過。
- 使用保留的真實語料建立全新 workspace：總計 232,878 個 ContentUid、218,272 個已分類、14,606 個 unresolved、291 個 batches；batch-plan fingerprint 為 `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`。Prepare 花費 37.802 秒，對 218,272 個 pending rows 執行唯讀 report 花費 4.055 秒；驗證後已刪除臨時 workspace。
- Repository review 確認沒有 generated workspace 檔案進入 staged changes，production source 與文件也沒有 credential 或本機專屬 absolute path。
