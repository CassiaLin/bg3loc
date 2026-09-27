# LSTP-03F Production Reporting / Cost / Token Accounting

Milestone: v1.3 Production Usability 03F
State: ACCEPTED
Depends on: LSTP-01C = ACCEPTED; LSTP-01E = ACCEPTED; LSTP-03B = ACCEPTED; LSTP-03C = ACCEPTED; LSTP-03E = ACCEPTED
Core reopening: no

## English

### Purpose

03F lets an operator understand a long-running production workspace without querying SQLite: overall and category progress, run/provider performance, retry and error patterns, provider-reported token usage, known cost under user-supplied pricing, and a clearly labelled remaining-work estimate.

Reporting never changes ContentUid identity, execution transitions, attempt history, QA, review, completion, bridge, rebuild, or finalize decisions. A report is a read-only derived snapshot, not canonical mutable state.

### Existing and new evidence

The accepted database already records runs, provider/model, prompt version, execution configuration hash, attempt and provider request IDs, timestamps, outcome/status, error code, input hash, and output hash. Before 03F it recorded no prompt, completion, total, cached, reasoning, or other provider-specific usage fields. The OpenAI-compatible adapter had the complete decoded response available but retained only translated content and request identity.

03F adds three nullable attempt columns:

```text
prompt_tokens
completion_tokens
total_tokens
```

They store only values explicitly reported by a provider. `input_tokens` and `output_tokens` are accepted aliases for the first two fields. Missing or invalid values remain `NULL`; BG3Loc does not run a tokenizer or estimate failed-request usage.

Cached tokens, reasoning tokens, and other provider-specific fields remain outside the first-version portable schema. They are neither inferred nor folded into the canonical columns unless the provider itself reports the canonical totals.

### Migration

Execution schema 1.1 is a minimal additive migration. Opening an existing database for execution adds only missing nullable usage columns and updates the schema metadata after the columns exist. Existing runs, attempts, content state, translations, and attempt outcomes are preserved. Reporting itself does not migrate or mutate a database; an unmigrated legacy database is still reportable, with historical usage shown as unknown.

### Reporting surface

The existing command is extended instead of duplicated:

```text
bg3loc production report --workspace WORKSPACE [--pricing PRICING.json] [--json REPORT.json]
```

The report contains:

- workspace-level execution, QA, and completion counts with percentages;
- category totals, succeeded/remaining/retry/final-failure, current QA PASS/REVIEW, and MERGE_READY;
- run identity, timing, outcome/error counts, attempts, retries, HTTP 429/5xx and transport failures, average successful latency, and observed successes per minute;
- attempt/error totals and provider-reported usage coverage;
- optional cost and remaining-work estimates.

Queries use aggregate SQL plus the accepted completion/material scan. Reporting does not perform per-ContentUid SQL queries or repeatedly reread batch files.

### Pricing and cost

Pricing is supplied at report time and matched exactly by provider and model. BG3Loc ships only an explicitly fictional example, never a current-price claim. Cost is calculated as:

```text
prompt_tokens / 1,000,000 * inputPerMillion
+ completion_tokens / 1,000,000 * outputPerMillion
```

The report distinguishes known-usage attempts, unknown-usage attempts, priced attempts, and unpriced attempts. Missing usage or pricing is never treated as zero for completeness claims. The result is an accounting estimate from recorded provider usage and the supplied pricing configuration, not a provider invoice. It excludes taxes, credits, discounts, cache pricing, free quota, networking, and currency conversion.

### Remaining estimate

Remaining means rows still executable by the accepted execution state (`pending`, `failed-retryable`, or `invalidated`). Estimates require at least ten succeeded attempts with known prompt and completion usage. A category with at least ten samples uses its own averages; otherwise it falls back to a global sample of at least ten. With fewer samples the estimate is unavailable. Cost estimation also requires exact pricing for the observed successful attempts and is explicitly labelled an estimate, never incurred cost.

### Read-only guarantee

Reporting may create the requested external JSON snapshot but must not change `content_state`, attempts, runs, QA rows, review rows, or execution metadata. First-use additive migration belongs to execution initialization, not report generation.

### Acceptance

03F advances through `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> REAL-CORPUS REPORT PASS -> ACCEPTED`. Acceptance requires migration preservation, provider usage capture, resume accounting, exact pricing tests, known/unknown coverage, estimate thresholds, read-only verification, controlled integration, large-fixture performance, full regression, and the real 218,272-row pending-corpus report.

Acceptance evidence (2026-09-28):

- Targeted reporting/provider/state/execution/QA suites passed, including the additive 1.0-to-1.1 migration, exact cost arithmetic, unknown-usage coverage, ten-sample estimate threshold, business-state read-only snapshot, 3,000-row performance fixture, and the controlled success/429/resume/QA/report chain.
- Full regression passed with `463 passed`, `75 subtests passed`, no failures, and no warnings.
- A fresh canonical workspace reproduced 232,878 total rows, 218,272 classified pending rows, 14,606 unresolved rows, 291 batches, and fingerprint `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`.
- The expanded report completed in 4.485 seconds, below the ten-second target. It reported zero known usage, USD 0.000000 known cost under the fictional example pricing, and an unavailable remaining estimate because there were no succeeded usage samples. The temporary workspace was removed afterward.

Therefore `LSTP-03F Production Reporting / Cost / Token Accounting = ACCEPTED` without reopening the accepted production state machine.

## 繁體中文（台灣）

### 目的

03F 讓 operator 不必直接查 SQLite，就能了解長時間 production workspace：整體與 category 進度、run/provider 表現、retry 與錯誤分布、provider 回報的 token usage、依使用者 pricing 算出的已知成本，以及明確標示的剩餘工作估算。

Reporting 不改變 ContentUid identity、execution transition、attempt history、QA、review、completion、bridge、rebuild 或 finalize decision。Report 是 read-only derived snapshot，不是 canonical mutable state。

### 既有與新增證據

Accepted database 已記錄 run、provider/model、prompt version、execution config hash、attempt/provider request ID、時間、outcome/status、error code、input hash 與 output hash。03F 之前沒有保存 prompt、completion、total、cached、reasoning 或其他 provider-specific usage fields；OpenAI-compatible adapter 雖然拿得到完整 decoded response，原本只保留譯文與 request identity。

03F 在 attempt 增加三個 nullable 欄位：

```text
prompt_tokens
completion_tokens
total_tokens
```

只保存 provider 明確回傳的值。`input_tokens`、`output_tokens` 可作為前兩者的 alias。缺失或無效值維持 `NULL`；BG3Loc 不使用本地 tokenizer，也不估算 failed request usage。

第一版 portable schema 不保存 cached tokens、reasoning tokens 或其他 provider-specific fields；除非 provider 本身回報 canonical totals，否則不推測、也不折算進 canonical columns。

### Migration

Execution schema 1.1 採最小 additive migration。既有 DB 在 execution 初始化時只加入缺少的 nullable usage columns，欄位完成後才更新 schema metadata；既有 runs、attempts、content state、translations 與 outcomes 全部保留。Report 本身不 migration、不 mutation；尚未 migration 的 legacy DB 仍可報告，但歷史 usage 顯示 unknown。

### Reporting surface

擴充既有命令，不建立第二個相同 command：

```text
bg3loc production report --workspace WORKSPACE [--pricing PRICING.json] [--json REPORT.json]
```

Report 包含：

- workspace execution、QA、completion count 與百分比；
- category total、succeeded/remaining/retry/final-failure、目前 QA PASS/REVIEW 與 MERGE_READY；
- run identity、timing、outcome/error count、attempt、retry、HTTP 429/5xx、transport failure、成功 attempt 平均 latency 與 observed successes/minute；
- attempt/error totals與 provider-reported usage coverage；
- 可選 cost 與 remaining-work estimate。

查詢使用 aggregate SQL 加 accepted completion/material 單次掃描，不做 per-ContentUid SQL 或反覆讀取 batch files。

### Pricing 與成本

Pricing 在 report 時由使用者提供，依 provider/model 精確匹配。BG3Loc 只提供明確虛構的 example，不宣稱是現行價格。公式為：

```text
prompt_tokens / 1,000,000 * inputPerMillion
+ completion_tokens / 1,000,000 * outputPerMillion
```

Report 分開顯示 known-usage、unknown-usage、priced 與 unpriced attempts。缺 usage 或 pricing 不會被當成零後宣稱成本完整。結果是根據 provider-reported usage 與 report-time pricing 的 accounting estimate，不是 provider invoice；不包含稅、credits、discounts、cache pricing、free quota、network 或 currency conversion。

### 剩餘估算

Remaining 指 accepted execution state 中仍可執行的 `pending`、`failed-retryable`、`invalidated` rows。至少需要十個具有 prompt/completion usage 的 succeeded attempts。單一 category 有至少十個 sample 時使用 category average，否則需要至少十個 global samples。Sample 不足時顯示 unavailable。Cost estimate 還需要 observed successful attempts 能精確配對 pricing，而且一律標示 estimate，不是已發生成本。

### Read-only 保證

Reporting 可以寫使用者指定的外部 JSON snapshot，但不得改變 `content_state`、attempts、runs、QA rows、review rows或 execution metadata。首次 additive migration 屬於 execution initialization，不屬於 report generation。

### 驗收

03F 依序經過 `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> REAL-CORPUS REPORT PASS -> ACCEPTED`。必須完成 migration preservation、provider usage capture、resume accounting、exact pricing、known/unknown coverage、estimate threshold、read-only、controlled integration、large fixture performance、full regression 與真實 218,272 pending corpus report，才能 ACCEPTED。

2026-09-28 驗收證據：

- Reporting/provider/state/execution/QA targeted suites 全數通過，涵蓋 1.0-to-1.1 additive migration、精確成本公式、unknown usage coverage、十筆 sample 門檻、business-state 唯讀 snapshot、3,000-row 效能 fixture，以及 success/429/resume/QA/report 受控整合鏈。
- 完整回歸為 `463 passed`、`75 subtests passed`、零失敗、零 warnings。
- 使用 canonical inputs 建立 fresh workspace，重現 232,878 total、218,272 classified pending、14,606 unresolved、291 batches，以及 fingerprint `8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326`。
- 擴充後 report 耗時 4.485 秒，低於十秒目標；在虛構範例 pricing 下正確顯示 known usage 為零、known cost 為 USD 0.000000，且因沒有 succeeded usage samples 而將 remaining estimate 標為 unavailable。驗證後已刪除 temporary workspace。

因此 `LSTP-03F Production Reporting / Cost / Token Accounting = ACCEPTED`，且未重新開啟既有 production state machine。
