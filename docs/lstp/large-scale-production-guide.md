# Large-Scale Translation Production / 大規模翻譯生產指南

> **English / 繁體中文**

This guide is for projects that want BG3Loc to manage tens of thousands of translation rows with deterministic batching, resumable execution, QA routing, merge readiness, and safe rebuild.

本指南適合需要處理數萬至數十萬筆文字的翻譯專案：BG3Loc 會負責可重現分批、中斷續跑、QA 分流、合併就緒判定，以及安全重建。

For a small or manually managed translation project, use the simpler [`workflow`](../e2e/high-level-cli.md) path instead.

如果只是小型或人工管理的翻譯專案，請優先使用較簡單的 [`workflow`](../e2e/high-level-cli.md) 流程。

New to BG3Loc? Start with the [public getting started guide](../getting-started.md). It shows how to create every required input from your own BG3 installation. The technical sections below assume those inputs already exist.

第一次使用？請先看[公開新手指南](../getting-started.md)，其中說明如何從自己的 BG3 安裝產生必要輸入。下方技術章節假定輸入已備妥。

---

## What the large-scale path does / 大型流程做什麼

~~~text
scan + extract + research evidence
→ functional classification
→ category-aware batching
→ durable translation execution
→ automatic QA routing
→ production completion view
→ finalize gate + MERGE_READY bridge
→ validated rebuild / repack
→ install dry-run
→ optional real install
~~~

The canonical identity remains `ContentUid` from beginning to end.

從頭到尾都以 `ContentUid` 作為唯一正式 identity；batch、attempt、provider request 都不會取代它。

---

## Before you start / 開始前

Complete the normal BG3Loc installation and archive-backend setup from the repository README.

先依 repository README 完成 BG3Loc 與 archive backend 安裝。

You need:

~~~text
extract-manifest.json
normalized source locale JSONL
research-mappings.jsonl
~~~

Create research mappings from your own game installation with `bg3loc research scan` followed by `bg3loc research map`. The latter also produces story and UI/skill structural ledgers when evidence is available; `production prepare` treats those as optional. BG3Loc does not ship Larian's proprietary localization corpus.

先對自己的遊戲安裝執行 `bg3loc research scan`，再執行 `bg3loc research map` 產生 `research-mappings.jsonl`。後者在有證據時也會產生 story 與 UI/skill 結構 ledger；`production prepare` 將兩者視為可選。BG3Loc 不內附 Larian 的遊戲文本。

## Recommended operator workflow / 建議的 operator 流程

For a new v1.3 production workspace, use the workspace-oriented commands below. They keep the batch plan, ruleset snapshot, execution database, QA evidence, and human-review evidence on one validated provenance chain.

新的 v1.3 production workspace 建議使用以下高階命令。batch plan、ruleset snapshot、execution database、QA evidence 與人工審核 evidence 都會維持在同一條經驗證的 provenance chain。

### 1. Prepare once / 建立 workspace

~~~powershell
bg3loc production prepare `
  --extract workspace/extract/extract-manifest.json `
  --source workspace/extract/normalized/English.jsonl `
  --research-mappings research-output/research-mappings.jsonl `
  --ruleset ruleset.json `
  --output workspace/production
~~~

Preparation fails if the output is not fresh. It writes a relocatable manifest and binds the ruleset snapshot, batch plan, batch materials, locales, and immutable execution inventory.

### 2. Execute or resume translation / 執行或續跑翻譯

~~~powershell
$env:BG3LOC_API_KEY = "your-api-key"

bg3loc production execute-openai-compatible `
  --workspace workspace/production `
  --base-url "https://your-provider.example/v1" `
  --model "your-model" `
  --run-id "run-001" `
  --worker-id "worker-01" `
  --max-items 1000
~~~

Use a new run ID to resume later. A bounded `--max-items` run is recommended while learning a provider's quota and rate limits. Production execution honors `Retry-After` and otherwise uses bounded exponential backoff, so a short rate-limit window does not immediately consume the retry budget.

### 3. Run QA / 執行 QA

~~~powershell
bg3loc production qa --workspace workspace/production
~~~

QA records the current automatic routing evidence. Run it again after new translations or reviewed revisions.

### 4. Handle RETRY and human review / 處理 RETRY 與人工審核

~~~powershell
bg3loc production retry `
  --workspace workspace/production `
  --content-uid <ContentUid>
~~~

This archives the rejected candidate and reopens the existing execution row. It does not call a provider. Run `production execute-openai-compatible` later with a new run ID.

Export and resolve human-review candidates separately:

~~~powershell
bg3loc production review-export `
  --workspace workspace/production `
  --output workspace/production/review.jsonl

bg3loc production review-resolve `
  --workspace workspace/production `
  --content-uid <ContentUid> `
  --decision accept `
  --reviewer "<reviewer-name>" `
  --note "<review note>"
~~~

For a revision, use `--decision revise --text "<revised translation>"`. A revision always makes the old QA stale; run `production qa` again. BG3Loc never chooses or records a human decision automatically.

### 5. Report and repeat until ready / 查看報表並重複處理

~~~powershell
bg3loc production report --workspace workspace/production
~~~

The read-only report shows workspace and category progress, run/provider/model results,
attempts, retries and errors, latency/observed throughput, and provider-reported token
usage. To save the same snapshot as JSON and calculate known cost from an explicitly
supplied price table:

~~~powershell
bg3loc production report `
  --workspace workspace/production `
  --pricing docs/lstp/pricing-example.json `
  --json workspace/production-report.json
~~~

The tracked price file is fictional syntax documentation, not current provider pricing.
Use your own exact provider/model entries. Missing usage or pricing remains visibly
unknown; BG3Loc does not treat it as zero or present the result as a provider invoice.
Remaining estimates require at least ten succeeded attempts with known prompt and
completion usage.

報表完全唯讀，包含 workspace/category 進度、run/provider/model 結果、attempt、retry、
錯誤、latency、observed throughput，以及 provider-reported token usage。成本只依 report
執行時提供的精確 provider/model pricing 計算；範例價格是虛構格式示範，不是現行報價。
缺少 usage 或 pricing 時會明確顯示 unknown，不會當作零，也不會宣稱是 provider invoice。

~~~text
production report
-> retry/provider resume where needed
-> review export/resolve where needed
-> production qa after new or revised candidates
-> production report
~~~

Only `MERGE_READY` rows may continue to bridge and rebuild. `WAITING_TRANSLATION`, `WAITING_RETRY`, `WAITING_REVIEW`, and `BLOCKED` remain visible and are never silently accepted.

### 6. Finalize / 產生最終語言檔

~~~powershell
bg3loc production finalize `
  --workspace workspace/production `
  --output workspace/final-output
~~~

Finalize first recalculates the completion view. It reports every blocking disposition and creates no output while any classified production row is waiting or blocked. When ready, it reuses the accepted bridge and rebuild pipeline, verifies the LOCA/PAK artifacts, and writes `production-final-manifest.json` last. The output directory must be fresh.

Finalize 會先重新計算 completion view；只要任何已分類 production row 仍在等待或 blocked，就會列出真正的 disposition 並且不建立 output。全部 ready 時才沿用 accepted bridge/rebuild pipeline，驗證 LOCA/PAK，最後寫入 `production-final-manifest.json`。Output directory 必須是 fresh。

### 7. Install / 安裝

Use the rebuild manifest inside the finalized output for the existing install dry-run, and apply only after reviewing that preflight:

~~~powershell
bg3loc install `
  --rebuild workspace/final-output/rebuild/rebuild-manifest.json `
  --scan <scan-manifest.json> `
  --dry-run
~~~

### Advanced: rate limiting and pacing / 進階：限流與節奏

The defaults are suitable for a single production worker: two-second exponential fallback capped at 60 seconds, with provider `Retry-After` taking precedence. Operators may tune them without changing attempt accounting:

~~~powershell
bg3loc production execute-openai-compatible `
  ... `
  --retry-backoff-base-seconds 2 `
  --retry-backoff-max-seconds 60 `
  --min-request-interval-seconds 0.5
~~~

`max-items` remains the attempt budget; sleeping does not count as an item. Pacing is per worker. Multiple workers do not share a global provider quota or rate-limit clock.

The lower-level `research`, `translation-state`, `qa`, and `production status` commands documented below remain available for diagnosis and advanced operation. They inspect the same files and SQLite state; the workspace commands do not create a second state machine.

---

## 1. Classify the corpus / 功能分類

Example:

~~~powershell
bg3loc research classify `
  --extract-manifest workspace/extract/extract-manifest.json `
  --research-mappings research-output/research-mappings.jsonl `
  --output-dir workspace/production/classification
~~~

This produces `functional-classification.jsonl` and a summary.

這一步只決定每個 `ContentUid` 的 production category，不翻譯文字。

Rows that cannot be classified deterministically stay `other / unclassified`; BG3Loc does not guess.

Before batching, unresolved rows may be resolved through an auditable operator overlay without modifying the original 01A ledger:

~~~text
original functional-classification.jsonl
+ unclassified-decisions.jsonl
→ resolved-classification.jsonl
~~~

Supported decisions:

~~~text
assign   -> move one unresolved ContentUid into a normal production category
exclude  -> explicitly keep it out of translation production
pending  -> leave it unresolved for later
~~~

Example decision JSONL:

~~~json
{"ContentUid":"h...","action":"assign","category":"item","reviewer":"reviewer-a","note":"confirmed from game structure","decidedAt":"2026-09-27T01:00:00Z"}
{"ContentUid":"h...","action":"exclude","reviewer":"reviewer-a","note":"not translation content","decidedAt":"2026-09-27T01:01:00Z"}
{"ContentUid":"h...","action":"pending","note":"needs more evidence"}
~~~

Apply the overlay:

~~~powershell
bg3loc research resolve-unclassified `
  --classification workspace/production/classification/functional-classification.jsonl `
  --decisions workspace/production/unclassified-decisions.jsonl `
  --output workspace/production/classification/resolved-classification.jsonl
~~~

The original classification file remains unchanged. `assign` is allowed only for normal batchable production categories. Already-classified rows cannot be overridden through this command.

原始 01A classification ledger 不會被改寫；人工決議只形成新的衍生 ledger。

---

## 2. Build deterministic batches / 建立可重現批次

Use the normalized source-locale JSONL recorded by your extract output.

以下以 English 為例；實際檔名請依自己的 source locale 調整。

~~~powershell
bg3loc research batch `
  --classification workspace/production/classification/functional-classification.jsonl `
  --source workspace/extract/normalized/English.jsonl `
  --research-mappings research-output/research-mappings.jsonl `
  --output-dir workspace/production/batches
~~~

Normal batches contain only classified, production-owned rows. Unresolved rows remain separate.

同一 `ContentUid` 只會進一個正式 batch。

---

## 3. Prepare translation rules / 準備翻譯規則

Large-scale provider execution requires a versioned ruleset JSON.

大型 provider 執行需要一份有版本的 ruleset JSON；可從 [`ruleset-example.json`](ruleset-example.json) 複製後修改。

The ruleset declares:

~~~text
source locale
target locale
common translation rules
rules for every production category you use
optional glossary
~~~

Change the ruleset version whenever a change should invalidate earlier effective translation inputs.

如果規則變更應使舊翻譯輸入失效，請同步更新 ruleset version。

---

## 4. Initialize durable state / 建立可續跑狀態

~~~powershell
bg3loc translation-state init `
  --batch-plan workspace/production/batches/batch-plan.json `
  --db workspace/production/execution.sqlite3 `
  --ruleset ruleset.json
~~~

Check progress at any time:

~~~powershell
bg3loc translation-state summary --db workspace/production/execution.sqlite3
~~~

The SQLite database is the canonical mutable execution state. Keep it backed up.

SQLite database 是翻譯執行中的 canonical mutable state，請納入備份。

---

## 5. Run an OpenAI-compatible provider / 執行翻譯 provider

BG3Loc currently provides an OpenAI-compatible chat adapter. The API key is read from an environment variable and is not written into provenance hashes.

目前內建 OpenAI-compatible chat adapter。API key 從環境變數讀取，不會寫進 provenance hash。

Example:

~~~powershell
$env:BG3LOC_API_KEY = "your-api-key"

bg3loc translation-state run-start-openai-compatible `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json `
  --ruleset ruleset.json `
  --base-url "https://your-provider.example/v1" `
  --model "your-model" `
  --run-id "run-001"

bg3loc translation-state worker-openai-compatible `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json `
  --ruleset ruleset.json `
  --base-url "https://your-provider.example/v1" `
  --model "your-model" `
  --run-id "run-001" `
  --worker-id "worker-01"
~~~

Provider/model/base URL must match the run that was started. Retry and lease state are persisted per `ContentUid`.

中斷後可重新執行 worker；已成功且仍有效的項目不需要全部重翻。

When the run is done:

~~~powershell
bg3loc translation-state run-finish `
  --db workspace/production/execution.sqlite3 `
  --run-id "run-001"
~~~

---

## 6. Run QA / 執行 QA

~~~powershell
bg3loc qa run `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json

bg3loc qa summary --db workspace/production/execution.sqlite3
~~~

QA routes each checked translation to:

~~~text
PASS
RETRY
REVIEW
FAIL
~~~

For RETRY rows, inspect the current QA result and hand the candidate back to translation execution:

~~~powershell
bg3loc qa retry-handoff `
  --db workspace/production/execution.sqlite3 `
  --content-uid <ContentUid>
~~~

Rows needing human judgment can be listed or exported with:

~~~powershell
bg3loc qa review-list `
  --db workspace/production/execution.sqlite3 `
  --limit 50

bg3loc qa review-export `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json `
  --output workspace/production/review.jsonl
~~~

After a human checks one current REVIEW candidate, record one of two decisions:

~~~powershell
# Keep the current translation and approve it.
bg3loc qa review-resolve `
  --db workspace/production/execution.sqlite3 `
  --content-uid <ContentUid> `
  --decision accept `
  --reviewer "<reviewer-name>" `
  --note "<why this is acceptable>"

# Or replace the current translation.
bg3loc qa review-resolve `
  --db workspace/production/execution.sqlite3 `
  --content-uid <ContentUid> `
  --decision revise `
  --reviewer "<reviewer-name>" `
  --text "<revised translation>" `
  --note "<why it was revised>"
~~~

`accept` preserves the original automatic REVIEW evidence and adds a human approval bound to the current QA ruleset, QA input hash, and output hash. That exact current candidate may then become `MERGE_READY`.

`revise` changes the translation output and therefore makes the old QA stale. Run `bg3loc qa run` again before checking production readiness.

人工 `accept` 不會把原本的自動 QA 偽造成 PASS；原 REVIEW 與 issue 仍保留。人工 `revise` 後則一定重新 QA。

---

## 7. Check production completion / 檢查完成度

~~~powershell
bg3loc production status `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json
~~~

Every classified row receives exactly one disposition:

~~~text
MERGE_READY
WAITING_TRANSLATION
WAITING_RETRY
WAITING_REVIEW
BLOCKED
~~~

Export unresolved rows when needed:

~~~powershell
bg3loc production unresolved `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json `
  --output workspace/production/unresolved.jsonl
~~~

Only `MERGE_READY` is allowed into the rebuild bridge.

---

## 8. Bridge only safe rows / 只橋接可合併資料

~~~powershell
bg3loc production bridge `
  --db workspace/production/execution.sqlite3 `
  --batch-plan workspace/production/batches/batch-plan.json `
  --extract workspace/extract/extract-manifest.json `
  --output workspace/production/bridge
~~~

The bridge creates:

~~~text
accepted-target.jsonl
merge-ready-binding.jsonl
validate-manifest.json
bridge-manifest.json
~~~

It recalculates the current 01E completion view and refuses unsafe or stale bindings.

bridge 不是把「所有翻譯成功的文字」直接塞回遊戲；它只接受當下真正 `MERGE_READY` 的項目。

---

## 9. Rebuild and repack / 重建語言包

~~~powershell
bg3loc rebuild `
  --validate workspace/production/bridge/validate-manifest.json `
  --extract workspace/extract/extract-manifest.json `
  --container repack `
  --output workspace/production/rebuild
~~~

Successful rebuild validates accepted text/version, semantic round-trip, UID-set integrity, untouched baseline integrity, archive structure, and repacked LOCA payload.

未列在 accepted target 裡的 target-baseline row 應保持不變。

---

## 10. Dry-run before installing / 安裝前一定先預演

Use the scan manifest that belongs to the same extraction/baseline chain:

~~~powershell
bg3loc install `
  --rebuild workspace/production/rebuild/rebuild-manifest.json `
  --scan <scan-manifest.json> `
  --dry-run
~~~

Only after a successful dry-run should a user consider real install:

~~~powershell
bg3loc install `
  --rebuild workspace/production/rebuild/rebuild-manifest.json `
  --scan <scan-manifest.json>
~~~

Real install creates backup/rollback metadata. A game update can invalidate prior scan/extract/rebuild evidence; regenerate it instead of bypassing checks.

---

## Public large-scale workflow status / 公開大型流程狀態

The two previously identified operator gaps are now covered:

~~~text
REVIEW resolution
→ qa review-export / qa review-resolve

other / unclassified resolution
→ research resolve-unclassified
~~~

`assign`, `exclude`, and `pending` decisions are auditable and do not rewrite the original automatic classification ledger.

Batching writes unresolved and explicitly excluded rows separately:

~~~text
unresolved.jsonl
excluded.jsonl
~~~

At this point the documented large-scale operator workflow has no known release-blocking gap. Locale-specific QA and project-specific linguistic policies remain optional extensions, not core workflow blockers.

目前公開大型 production 操作流程已沒有已知 release blocker；語言專屬 QA 與各翻譯專案自己的文字規範仍屬可擴充層。

---

## Design and acceptance documents / 設計與驗收文件

- [01A Functional Classification](functional-classification.md)
- [01B Category-Aware Batching](category-aware-batching.md)
- [01C Translation Execution and State](translation-execution-state.md)
- [01D Translation QA and Review Routing](translation-qa-review-routing.md)
- [01E Production Completion and Merge Readiness](production-completion-merge-readiness.md)
- [01F Final Merge Bridge and Rebuild](final-merge-bridge-rebuild.md)
- [03C QA / Review Operator Loop Orchestration](qa-review-orchestration-contract.md)
- [03D Finalize / Bridge / Rebuild Orchestration](finalize-rebuild-orchestration-contract.md)
- [03E Execution Policy](execution-policy-contract.md)
