# LSTP-01C | Translation Execution and State / 翻譯執行與狀態追蹤

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 01C
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

LSTP-01B 已經把 218,272 筆可翻譯內容切成可重現的 batch。  
LSTP-01C 接著處理真正大量翻譯時最容易出問題的部分：

- 翻到一半程式中斷；
- API 暫時失敗；
- 同一批需要重試；
- 某幾筆失敗但其他已完成；
- 換 provider / model 後繼續；
- 重開機後要接著跑，不是全部重來；
- 要知道某一筆譯文到底是哪次執行產生的。

LSTP-01B already creates deterministic translation batches.  
LSTP-01C defines how those batches are executed, resumed, retried, and audited.

這一階段管理的是「執行狀態」，不是翻譯品質。  
This stage manages execution state, not linguistic quality.

---

## The most important rule / 最重要的規則

Translation identity remains:

~~~text
ContentUid
~~~

Never:

~~~text
batchId
row number
attempt number
provider request ID
~~~

batchId may change when a new batching plan is created.  
A completed translation must still be recoverable by ContentUid.

batchId 可以因重新分批而改變，但已完成譯文不能因此失聯。

---

## Three things must stay separate / 三種資料要分開

### 1. Batch plan / 分批計畫

Produced by LSTP-01B.

Examples:

~~~text
batchPlanFingerprint
batchId
ContentUid membership
primaryCategory
grouping evidence
~~~

This is the work plan.  
這是「要做哪些工作」。

### 2. Translation result / 翻譯成果

The durable result is tied to ContentUid.

Example:

~~~text
ContentUid
SourceText
TranslatedText
TranslationStatus
~~~

This is the content we want to keep.  
這是「真正要保存的成果」。

### 3. Execution state / 執行紀錄

Examples:

~~~text
runId
attemptId
provider
model
startedAt
finishedAt
error
retryCount
request metadata
~~~

This explains how a result was produced.  
這是「這次怎麼跑出來的」。

These three surfaces must not be collapsed into one file or identity.  
三者不能混成同一種 identity。

---

## Run / 一次執行

A translation run represents one execution session against one batch plan.

Suggested identity:

~~~text
runId
~~~

A run binds at least:

~~~text
batchPlanFingerprint
source input hash
translation rules / prompt version
provider configuration identity
model identity
execution schema version
~~~

A new run does not automatically erase older results.  
新的 run 不代表舊成果失效或被刪除。

---

## Attempt / 一次嘗試

One ContentUid may need more than one attempt.

Example:

~~~text
ContentUid h...
attempt 1 → timeout
attempt 2 → provider 429
attempt 3 → success
~~~

Each attempt is append-only history.

建議欄位：

~~~text
attemptId
runId
ContentUid
batchId
attemptNumber
provider
model
startedAt
finishedAt
outcome
errorCode
errorMessage
providerRequestId
inputHash
outputHash
~~~

batchId is recorded for audit only.  
It must not become the key used to recover the translation.

---

## Translation status / 翻譯狀態

Recommended v1 states:

~~~text
pending
running
succeeded
failed-retryable
failed-final
skipped
invalidated
~~~

pending means ready to run.  
pending 代表尚未執行。

running means an attempt is currently in progress.  
running 代表目前有一次 attempt 正在執行。

succeeded means a translation result has been produced and stored.  
這不代表語言 QA 已通過。

failed-retryable is for temporary failures such as timeout, connection reset, 429, provider 5xx, or temporary provider unavailability.

failed-final means automatic execution should stop for this row, for example unsupported configuration, deterministic malformed request, or retry-limit exhaustion.

skipped means explicitly not executed in this run.

invalidated means a previous success no longer matches the current effective input or project policy.

Invalidation must always be explicit.  
不能因為重新跑程式就偷偷把舊譯文視為失效。

---

## Resume / 中斷續跑

Restarting the process must not restart completed work.

~~~text
load batch plan
↓
load durable translation state
↓
for each ContentUid
    succeeded + still valid → skip
    retryable failure      → retry
    pending                → run
    failed-final           → leave blocked
↓
continue only unfinished work
~~~

A crash after 150,000 completed rows must not require translating those 150,000 rows again.  
翻到 15 萬筆後斷線，不應從第 1 筆重跑。

---

## Checkpointing / Checkpoint

State should be written incrementally.

Recommended behavior:

~~~text
one ContentUid reaches a terminal attempt outcome
→ persist attempt record
→ persist current translation state
→ then continue
~~~

Do not wait until an entire 500- or 1,000-row batch finishes before saving state.  
不要等整個 batch 跑完才存檔。

---

## Retry rules / 重試規則

Retry policy must be explicit and reproducible.

Retryable transport/provider errors may include:

~~~text
timeout
connection reset
429
temporary 5xx
provider unavailable
~~~

Non-retryable request errors may include:

~~~text
invalid credentials
unsupported model
invalid payload
schema mismatch
~~~

Translation-output validation failures, such as empty required output or malformed structured output, are a third class.  
They may be retried according to project policy, but must not be recorded as transport failures.

---

## Retry limit / 重試上限

v1 should support a configurable maximum attempt count.

Example:

~~~text
maxAttemptsPerContentUid = 3
~~~

When the limit is reached:

~~~text
failed-retryable
→ failed-final
~~~

Manual reset may reopen the item later, but that must be explicit and auditable.

---

## Rate limits / API 額度與限流

Provider rate limits belong to execution policy, not batching.

The execution layer may control:

~~~text
requests per second
concurrency
backoff
retry-after
provider-specific quota windows
~~~

These settings must not change ContentUid identity, batch membership, or translation ownership.

---

## Concurrency / 平行執行

Parallel execution is allowed, but two workers must never successfully claim the same ContentUid at the same time.

v1 uses an atomic database claim / lease.

Conceptually:

~~~text
BEGIN
find one executable ContentUid with no live lease
claim it for worker A with lease expiry
COMMIT
~~~

Only the worker holding the current live lease may finalize that attempt.

If a worker dies, the lease eventually expires and the ContentUid becomes claimable again.  
Lease expiry does not count as a translation failure by itself; the abandoned attempt/run is recorded separately during recovery.

The claim is temporary execution state, not translation identity.

---

## Provider and model records / Provider 與模型紀錄

Every successful result should record which execution configuration produced it.

At minimum:

~~~text
provider
model
providerModelId if different
promptVersion
temperature or equivalent settings when applicable
maxOutputTokens when applicable
~~~

Do not assume every provider exposes the same controls.

---

## Prompt and rule version / Prompt 與規則版本

For large-scale production, prompt changes matter.

A successful translation should be traceable to:

~~~text
promptVersion
category rule version
glossary hash if used
project rule-set hash if used
~~~

The full prompt text does not need to be duplicated on every row.  
It may live in a versioned execution configuration referenced by hash/version.

---

## Prompt assembly / Prompt 組裝

Provider 不應自己偷偷決定翻譯規則。  
The provider adapter must not secretly own translation policy.

在送給 provider 前，BG3Loc 先建立一個穩定的 provider-neutral translation request，再套用 versioned rule set。

Translation request 包含：

~~~text
ContentUid
SourceText
primaryCategory
batchId
attemptNumber
canonicalGroupKey
contextGroupKeys
protectedTokens
~~~

其中 protectedTokens 直接由既有 protected-syntax parser 從 SourceText 擷取，例如：

~~~text
{PLAYER}
%s
%1$d
~~~

這些 runtime token 必須原樣保留。

### Rule set / 規則組

Rule set 至少分成：

~~~text
common rules
category rules
optional glossary
rule-set version
~~~

例如：

~~~text
common:
  preserve meaning
  preserve protected syntax

bark:
  keep short reactive lines concise

item:
  use stable item terminology
~~~

實際規則內容可以之後再由專案設定提供；01C 先固定「怎麼組、怎麼追蹤版本」。

### Deterministic fingerprints / 可重現指紋

每份 rule set 會產生：

~~~text
rulesetFingerprint
~~~

每一筆真正送出的 effective prompt/input 會再產生：

~~~text
effectivePromptHash
~~~

effectivePromptHash 綁定：

~~~text
ContentUid
SourceText
primaryCategory
effective instructions
glossary
protectedTokens
contextGroupKeys
rulesetFingerprint
~~~

相同資料與規則必須得到相同 hash。  
只要 category rule、glossary、source text 或 protected syntax 等有效輸入改變，hash 就應跟著改變。

### Fail closed / 缺規則時停止

如果某個 primaryCategory 沒有對應 category rules，BG3Loc 不應靜默退回 generic prompt。

~~~text
missing category rules
→ fail closed
→ 不送 provider
~~~

這避免 20 多萬筆大量翻譯中，某一類因設定漏掉而偷偷套錯規則。

### Provider boundary / Provider 邊界

真正的 provider adapter 之後只能負責：

~~~text
stable assembled request
→ provider-specific API payload
→ provider response
→ TranslationSuccess / TranslationFailure
~~~

它不應自行改寫 category ownership、ContentUid identity、retry policy 或 project translation rules。

---

## Input hash / 輸入指紋

Before reusing an existing success, BG3Loc should verify that the effective translation input has not changed.

Per-record input may bind:

~~~text
ContentUid
SourceText
primaryCategory
protected syntax input
prompt/rule identity
~~~

A stable inputHash can represent this effective input.

If the hash still matches, the previous succeeded result can be reused.  
If it changes, the result must be explicitly invalidated or sent for review according to project policy.

---

## Output hash / 輸出指紋

Successful results should also store a hash of normalized translated output.

Purpose:

- detect accidental file edits;
- compare retries;
- support audit;
- detect duplicate provider responses without treating them as identity.

---

## Batch completion / Batch 完成

A batch is complete when every assigned ContentUid reaches an allowed terminal state.

A batch summary may report:

~~~text
pending
running
succeeded
failed-retryable
failed-final
skipped
invalidated
~~~

Batch completion must be derived from row state.  
不能只靠 batch job process 已結束就宣稱完成。

---

## Run completion / Run 完成

A run is complete only when no executable work remains.

Example:

~~~text
pending = 0
running = 0
failed-retryable = 0
~~~

failed-final may still exist and must be reported.

So run complete does not necessarily mean 100% translation success.  
摘要必須把「執行結束」和「全部成功」分開顯示。

---

## Canonical execution store / 正式執行狀態儲存

For v1, the canonical mutable execution state should use SQLite.  
v1 的正式 mutable execution state 使用 SQLite。

Python already includes SQLite support, so this does not require a new runtime dependency.

Why / 原因：

- 218,272 current-state rows should not require rewriting one giant JSONL file after every completed translation;
- one-row checkpoints should be cheap;
- claim / lease updates need atomic compare-and-update behavior;
- attempts should be append-only without risking partial JSON lines;
- crash recovery needs transactions;
- multiple workers need single-writer coordination at the database boundary.

JSON / JSONL remain useful as exports, reports, and debugging surfaces.  
JSON / JSONL 仍可作匯出、報告與除錯格式，但不是 v1 canonical mutable store。

Suggested workspace:

~~~text
workspace/
└─ translation-execution/
   ├─ execution.sqlite3
   └─ exports/
      ├─ run-summary.json
      ├─ translation-state.jsonl
      └─ attempts.jsonl
~~~

### Current state table / 目前狀態

One durable row per ContentUid.

Suggested fields:

~~~text
ContentUid PRIMARY KEY
status
translatedText
inputHash
outputHash
lastSuccessfulRunId
lastAttemptId
attemptCount
leaseOwner
leaseExpiresAt
updatedAt
~~~

### Attempts table / 嘗試紀錄

Append-only logical history.

Suggested fields:

~~~text
attemptId PRIMARY KEY
runId
ContentUid
batchId
attemptNumber
provider
model
startedAt
finishedAt
outcome
errorCode
errorMessage
providerRequestId
inputHash
outputHash
~~~

### Runs table / Run 紀錄

Suggested fields:

~~~text
runId PRIMARY KEY
batchPlanFingerprint
provider
model
promptVersion
executionConfigHash
startedAt
finishedAt
status
~~~

Exact SQL names and indexes may be finalized during implementation, but the identity and transaction boundaries above are part of the v1 design.

---

## Transactions / 交易與安全寫入

A terminal attempt should be committed atomically.

Conceptually:

~~~text
BEGIN
write attempt history
update current ContentUid state
release claim / lease
COMMIT
~~~

If the process dies before commit, none of that terminal state is considered complete.  
If commit succeeds, restart must see the completed result.

如果程式在 COMMIT 前中斷，該次 terminal result 不算完成；如果 COMMIT 已成功，重開後就必須看得到成果。

SQLite WAL mode may be used when appropriate, but implementation must not rely on filesystem modification time as transaction truth.

---

## Restart safety / 重開機安全性

After an unexpected stop, BG3Loc should distinguish:

~~~text
completed result
known failed attempt
stale running claim
never started
~~~

A stale running state must not remain permanently locked.

Recovery should use an explicit lease/heartbeat or run boundary, not guess only from file modification time.

---

## Provider switching / 更換 Provider

A project may continue with a different provider or model.

~~~text
run 1 → provider A
run 2 → provider B
~~~

Previously successful rows remain valid unless their effective input or policy is invalidated.

Pending or failed rows may be picked up by the new run.

Provider switching must not create duplicate translation identity.

---

## Re-translation / 主動重翻

Sometimes a successful translation should intentionally be regenerated.

This must be explicit.

~~~text
invalidate selected ContentUid
→ reason = prompt-v2
→ next run translates only those rows
~~~

Do not silently overwrite a prior success.  
Old attempt/result provenance must remain auditable.

---

## What LSTP-01C does not decide / 01C 不決定的事

This milestone does not decide:

- which AI provider is best;
- which model should translate each category;
- the actual category prompts;
- linguistic QA pass/fail;
- terminology correctness;
- human reviewer workflow;
- final merge precedence.

Those belong to later milestones or project configuration.

01C only defines a safe execution substrate.

---

## OpenAI-compatible worker / OpenAI 相容 worker

The first provider adapter uses the widely supported Chat Completions shape:

~~~text
POST <base-url>/v1/chat/completions
~~~

The adapter name describes the API shape, not a required cloud vendor.  
第一個 adapter 採用的是 OpenAI-compatible API 格式，不代表一定要使用特定雲端服務。

It can be used with a compatible local server when that server implements the same endpoint.

### Ruleset file / 規則檔

Translation rules are supplied explicitly as JSON. BG3Loc does not hide production rules inside the provider adapter.

Example structure:

~~~json
{
  "version": "project-rules-v1",
  "sourceLocale": "English",
  "targetLocale": "ChineseTraditional",
  "commonRules": [
    "Preserve meaning.",
    "Preserve protected runtime tokens exactly."
  ],
  "categoryRules": {
    "bark": [
      "Keep short reactive lines concise."
    ],
    "item": [
      "Use consistent item terminology."
    ]
  },
  "glossary": [
    {
      "source": "Example source term",
      "target": "Example target term"
    }
  ]
}
~~~

The example above demonstrates file shape only.  
Those sentences are not BG3Loc's mandatory translation policy.

上面的內容只是格式範例，不是 BG3Loc 強制採用的正式翻譯規範。

### Initialize state with the ruleset / 用規則檔初始化 state

For real provider execution, initialize or reconcile the execution database with the same ruleset that will be used by the worker:

~~~text
bg3loc translation-state init \
  --batch-plan workspace/batching/batch-plan.json \
  --db workspace/translation-execution/execution.sqlite3 \
  --ruleset project-rules.json
~~~

This binds the current-state input hash to:

~~~text
ruleset fingerprint
source locale
target locale
source text
primary category
protected syntax
~~~

If the target locale changes later, existing successful rows are explicitly invalidated on re-init instead of being silently reused.

真實 provider workflow 應用同一份 ruleset 初始化 DB。這樣如果之後把目標語言從繁中改成日文，先前的成功譯文會明確變成 invalidated，不會被錯誤沿用。

### Start a provider-specific run / 建立對應 run

Use the provider-specific start command so the run records the complete non-secret execution configuration:

~~~text
bg3loc translation-state run-start-openai-compatible \
  --db workspace/translation-execution/execution.sqlite3 \
  --batch-plan workspace/batching/batch-plan.json \
  --ruleset project-rules.json \
  --base-url http://localhost:8080 \
  --model local-model \
  --run-id production-run-001
~~~

The execution config hash binds:

~~~text
provider type
base URL
model
timeout
max output tokens
temperature
ruleset version + fingerprint
~~~

### Run the worker / 執行 worker

~~~text
bg3loc translation-state worker-openai-compatible \
  --db workspace/translation-execution/execution.sqlite3 \
  --batch-plan workspace/batching/batch-plan.json \
  --ruleset project-rules.json \
  --base-url http://localhost:8080 \
  --model local-model \
  --run-id production-run-001 \
  --worker-id worker-1 \
  --max-items 10
~~~

Before making any HTTP request, the worker verifies that:

- the run exists and is still active;
- provider type matches;
- model matches;
- ruleset version matches;
- batch-plan fingerprint matches;
- full non-secret execution config hash matches.

If these do not match, the worker fails before claiming or sending translation work.

### API keys / API 金鑰

Secrets are read from an environment variable.

Default:

~~~text
BG3LOC_API_KEY
~~~

A different environment variable name can be selected with:

~~~text
--api-key-env NAME
~~~

The API key is used only to build the Authorization header.

It is intentionally excluded from:

~~~text
batch material
prompt
ruleset fingerprint
execution config hash
SQLite run metadata
attempt history
~~~

Local endpoints that do not require authentication can run without setting the environment variable.

---

## Real-corpus acceptance / 真實資料驗收

Synthetic unit tests are not enough.

LSTP-01C must later prove at least these scenarios:

1. start a run;
2. complete some records;
3. stop unexpectedly;
4. resume without retranslating completed records;
5. inject retryable failures;
6. retry only failed records;
7. hit retry limit for selected records;
8. switch provider/model for unfinished work;
9. keep prior successful results;
10. produce a correct final state summary.

The accepted LSTP-01B plan currently contains:

~~~text
218,272 classified records
291 batches
14,606 unresolved records outside normal execution
~~~

LSTP-01C should manage this scale without requiring one monolithic in-memory transaction.

---

## Accepted real-corpus evidence / 已接受的真實資料驗收

LSTP-01C was accepted against the real LSTP-01B v2 production plan:

~~~text
batchPlanFingerprint:
8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326

classified execution rows:
218,272

batches:
291

unresolved rows outside normal execution:
14,606
~~~

Verified behaviors / 已驗證行為：

- durable SQLite initialization for all 218,272 executable ContentUid rows;
- identical re-initialization is idempotent;
- stop/resume preserves completed translations;
- succeeded ContentUid rows are not reclaimed;
- retryable failures retry only unfinished work;
- retry limit is enforced: the same real ContentUid reached attempt 3 with maxAttempts=3 and then transitioned to failed-final;
- stale leases recover into auditable abandoned attempts and retryable current state;
- provider/model switching preserves prior successes and continues unfinished work;
- material resolution is fail-closed;
- ruleset, source locale, target locale, prompt/category rules, glossary, and protected syntax participate in deterministic translation identity/fingerprints;
- target-locale changes explicitly invalidate prior successful rows instead of silently reusing them;
- OpenAI-compatible provider execution is covered by offline contract and CLI end-to-end tests;
- provider-specific live-network compatibility testing is intentionally separate from this milestone and is not required for 01C acceptance;
- ContentUid ownership remained unique and SQLite integrity checks passed.

The final real-corpus retry-limit probe used:

~~~text
ContentUid:
h001e8d1eg28dag410dga211g29094e8e866f

attempt 1 → failed-retryable
attempt 2 → failed-retryable
attempt 3 → failed-final

maxAttempts:
3
~~~

Latest full regression evidence at acceptance:

~~~text
349 passed
44 subtests passed
0 failures
~~~

The remaining pytest cache warning on Windows is non-blocking and does not affect translation execution behavior.

---

## Acceptance question / 驗收問題

Can BG3Loc stop, resume, retry, switch execution providers, and preserve every completed translation by ContentUid without duplicating or silently overwriting work?

BG3Loc 能不能在大量翻譯途中停止、續跑、重試、換 provider，同時仍以 ContentUid 安全保存每一筆已完成成果，不重複工作，也不偷偷覆蓋？

If yes / 若可以：

~~~text
LSTP-01C Translation Execution and State = ACCEPTED
~~~
