# LSTP-03B | Provider Execution Orchestration / Provider 執行流程編排契約

## Status / 狀態

~~~text
Milestone: v1.3 Production Usability 03B
State: ACCEPTED
Depends on:
  LSTP-01C Translation Execution and State = ACCEPTED
  LSTP-03A Production Orchestration = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

03A 已把大型 production setup 收斂成單一 prepare 動作，並產生具 provenance 綁定的 production-manifest.json。

但 v1.2 的 provider 執行仍需要操作人員手動串接：

~~~text
translation-state run-start-openai-compatible
→ translation-state worker-openai-compatible
→ translation-state run-finish
~~~

03B 新增一個高階 provider 執行命令，直接讀取 03A workspace，重用既有 01C primitive，不改變 provider、retry、lease、attempt、resume 或 execution-state semantics。

---

## Proposed CLI / 預計 CLI

~~~powershell
bg3loc production execute-openai-compatible ^
  --workspace workspace/production ^
  --base-url "https://your-provider.example/v1" ^
  --model "your-model" ^
  --run-id "run-001" ^
  --worker-id "worker-01"
~~~

可選執行參數沿用既有 worker：

~~~text
--api-key-env BG3LOC_API_KEY
--timeout-seconds 120
--max-output-tokens N
--temperature N
--lease-seconds 300
--max-attempts 3
--max-items N
~~~

實作時可微調 CLI spelling，但下列 semantics 不得改變。

---

## Workspace is the execution entry point / Workspace 是執行入口

03B 應要求一個已由 03A prepare 的 production workspace，而不是讓操作人員再次手動配：

~~~text
--db
--batch-plan
--ruleset
~~~

命令讀取：

~~~text
workspace/production-manifest.json
~~~

並解析其中綁定的：

~~~text
execution database
batch plan
ruleset
source locale
target locale
batchPlanFingerprint
ruleset fingerprint
~~~

SQLite execution database 仍然是 canonical mutable translation state；production manifest 只是 immutable preparation snapshot。

---

## What execute owns / execute 負責什麼

一次正常 invocation 應依序：

~~~text
1. validate production workspace binding
2. validate provider execution configuration
3. start one accepted 01C run
4. execute one accepted material-aware worker loop
5. finish that run
6. print a concise execution summary
~~~

概念上：

~~~text
production-manifest
→ run-start-openai-compatible
→ worker-openai-compatible
→ run-finish
→ execution summary
~~~

03B 必須重用既有 01C implementation path，不得另寫第二套：

~~~text
claim logic
lease ownership
attempt numbering
retry limit
provider HTTP handling
protected-token validation
execution config hashing
run finalization
~~~

---

## What execute does not own / execute 不負責什麼

03B 不負責：

~~~text
classification / batching preparation
修改 03A production manifest
QA
human REVIEW resolution
QA retry handoff
MERGE_READY 判定
bridge
rebuild
install
provider quota policy
automatic concurrency
rate-limit backoff policy
provider fallback/routing
cost accounting
~~~

以上屬既有 accepted stage 或後續獨立 milestone。

---

## Workspace validation / Workspace 驗證

開始 provider run 前必須 fail closed 驗證：

~~~text
production-manifest.json exists
execution database exists
batch plan exists
ruleset exists
manifest source/target locale present
manifest batchPlanFingerprint == batch-plan fingerprint
execution DB batchPlanFingerprint == manifest
manifest ruleset fingerprint == actual ruleset
execution DB ruleset fingerprint == actual ruleset
execution DB source/target locale == ruleset
~~~

只確認檔案存在不夠；provenance binding 必須一致。

任何 preflight binding failure 都不得產生 provider HTTP request，也不得建立錯誤的 run。

---

## Provider configuration binding / Provider 設定綁定

現有 OpenAI-compatible execution config hash 保持 authoritative。

它綁定：

~~~text
provider identity
base URL
model
timeout
max output tokens
temperature
ruleset fingerprint
ruleset version
~~~

API key 明確排除。

worker configuration 必須與 started run 完全一致，否則在任何 HTTP request 前 fail closed。

---

## Secrets / Secret 邊界

API key 仍只從指定 environment variable 讀取。

不得寫入：

~~~text
production-manifest.json
execution config hash input
run record
execution summary
stdout
BG3Loc-created logs
~~~

missing API key 不一定是錯誤，因為 local OpenAI-compatible endpoint 可以合法地不需要 authentication。

---

## Run identity / Run identity

03B 第一版保留 explicit run-id。

不得自動重用既有 run ID。

duplicate run ID 應由既有 execution-state integrity boundary fail closed。

每次 invocation 最多建立一個 run record。

run 仍綁定：

~~~text
batchPlanFingerprint
provider
model
ruleset/prompt version
executionConfigHash
~~~

---

## Worker identity / Worker identity

03B 第一版保留 explicit worker-id。

每次 invocation 執行一個 worker loop，不自動啟動多 worker concurrency。

多 worker 仍屬 advanced low-level usage，沿用既有 lease semantics。

---

## Bounded execution / 有界執行

03B 必須保留 --max-items。

~~~text
--max-items 10
--max-items 1000
~~~

指定時，只限制這次 invocation 可 claim 的 item/attempt 數，完全沿用 01C worker semantics。

不得重新解釋成 batch count、ContentUid range、token quota 或 provider quota。

未指定時，worker 會持續 claim executable rows，直到目前沒有可執行項目。

---

## Retry and rate-limit boundary / Retry 與限流邊界

03B 保留目前 retry semantics。

目前 retryable outcome 包括例如：

~~~text
transport failure
HTTP 429
HTTP 5xx
invalid/empty provider response
protected-output validation failure
~~~

existing worker + execution store 決定 row 維持 failed-retryable 或在 max-attempts 後成為 failed-final。

03B 不新增：

~~~text
implicit sleep
exponential backoff
Retry-After handling
requests-per-second scheduling
quota window management
~~~

這些會改變 execution policy，必須留給後續獨立 milestone。

---

## Run finalization / Run 結束

worker loop 正常返回後，03B 必須呼叫 accepted run finalization。

既有 01C semantics：

~~~text
completed
  when no pending, running, or failed-retryable rows remain

incomplete
  when pending, running, or failed-retryable rows remain
~~~

因此 bounded --max-items invocation 很可能正常結束但 run status 為 incomplete。

這不是 command failure。

stdout 必須清楚區分：

~~~text
command execution = successful
run status = completed | incomplete
~~~

之後可用新的 run ID 再次執行同一 workspace；已 succeeded 且仍有效的 ContentUid 不應重翻。

---

## Exceptional interruption / 異常中斷

若 worker 發生未預期 exception 而沒有正常返回，03B 不得 falsely report completed/incomplete。

durable per-attempt state 仍是 authoritative。

第一版可以讓 run 保持 active，以便現有 recovery / inspection 工具處理。

不得為了表面上「收尾漂亮」而在 finally 無條件 finish run，除非 execution-state contract 未來明確新增這種 transition。

---

## Execution summary / 執行摘要

正常 invocation 後至少輸出：

~~~text
runId
run status
provider
model
claimed
succeeded
failed-retryable
failed-final
whole-database status counts
~~~

這只是 operator view，不是新的 canonical mutable state。

03B v1 不新增第二個 execution-report database。

---

## Resume semantics / 續跑語意

後續使用新 run ID 對相同 accepted workspace 執行時：

~~~text
succeeded + still valid → skip
pending                  → execute
failed-retryable         → continue within max-attempts
failed-final             → leave blocked
~~~

03B 不可因為新高階命令啟動，就 reset attempt count 或 invalidate 已成功譯文。

ruleset / batch material 的有效輸入變更仍屬 03A / 01C invalidation semantics。

---

## Low-level compatibility / 與低階命令相容

03B 執行前後，advanced operator 仍可直接使用：

~~~text
bg3loc translation-state summary
bg3loc translation-state recover
bg3loc translation-state run-start-openai-compatible
bg3loc translation-state worker-openai-compatible
bg3loc translation-state run-finish
bg3loc qa run
~~~

03B 必須只產生普通 01C run/attempt/content-state record，不得創造低階 command 看不懂的 private execution state。

---

## Fail-closed conditions / 安全失敗條件

至少以下情況必須在 provider request 前停止：

~~~text
missing production manifest
missing execution database
missing batch plan
missing ruleset
manifest/batch fingerprint mismatch
manifest/ruleset fingerprint mismatch
execution DB/manifest fingerprint mismatch
execution DB/ruleset mismatch
source locale mismatch
target locale mismatch
duplicate run ID
invalid lease/max-attempt/max-items
invalid provider execution configuration
worker configuration differs from started run
~~~

---

## First implementation acceptance / 第一版驗收條件

03B 只有在以下全部通過後才可 ACCEPTED：

1. 一個高階命令可從 accepted 03A workspace 解析 DB / batch / ruleset；
2. 每次 invocation 恰好建立一個 OpenAI-compatible run；
3. 實際執行 accepted material-aware worker；
4. 正常返回時完成 run finalization 並報告 run status；
5. provider/model/base URL/config identity 完整保留；
6. API key 不進 persisted provenance 或 stdout；
7. workspace provenance mismatch 在 HTTP 前 fail closed；
8. run configuration mismatch 在 HTTP 前 fail closed；
9. duplicate run ID fail closed；
10. bounded max-items 在仍有工作時產生 ordinary incomplete run；
11. 後續新 run 可續跑未完成工作且保存既有 success；
12. retry/final failure counts 沿用 worker semantics；
13. low-level commands 可直接 inspect/continue 同一 state；
14. targeted tests 與 full repository regression PASS；
15. controlled provider tests 覆蓋 success、retryable failure、final failure、configuration mismatch，不要求外部付費 API。

---

## Real-provider acceptance boundary / 真實 Provider 驗收邊界

03B core acceptance 不應要求付費 API，也不應把 secret 放進 CI。

deterministic core acceptance 可使用 controlled HTTP transport tests。

之後可以另做一個非常小的 max-items sample，對使用者選定的 local 或 remote OpenAI-compatible endpoint 做 operator smoke test；這不是 provider-neutral core acceptance 的必要條件。

---

## Implementation validation / 實作驗證

03B targeted execution tests passed against the orchestration layer and accepted 01C worker/state machinery.

~~~text
26 passed
0 failed
~~~

Covered in the focused gate:

~~~text
bounded execution -> incomplete run
new run -> resume unfinished work
succeeded rows are not retransmitted
API key is used only for HTTP authorization
API key is not written to stdout, production manifest, or run provenance
workspace fingerprint mismatch fails before HTTP and before run creation
duplicate run ID fails before a second HTTP request
retryable HTTP 429 follows existing retry semantics
max-attempts converts repeated retryable failure to failed-final
existing low-level worker/state tests remain green
~~~

The recurring Windows pytest cache warning remains:

~~~text
.pytest_cache
WinError 5
~~~

It is nonblocking and did not cause a test failure.

Full repository regression is still required before 03B can advance toward acceptance.

---

## Final acceptance / 最終驗收

03B has now passed both focused execution validation and the complete repository regression.

~~~text
targeted:
26 passed
0 failed

full repository regression:
417 passed
68 subtests passed
0 failed
~~~

Controlled provider tests cover the first implementation acceptance boundary without requiring a paid external API:

~~~text
success path
bounded incomplete run
resume with a new run ID
preservation of existing succeeded rows
API-key secrecy
workspace provenance mismatch before HTTP
duplicate run ID fail-closed behavior
retryable HTTP 429 behavior
max-attempts transition to failed-final
compatibility with existing low-level execution-state and worker tests
~~~

A real external provider smoke test remains optional. It is not required for provider-neutral core acceptance because the HTTP transport path is deterministically exercised by controlled transport tests.

### Acceptance decision / 驗收判定

The 03B acceptance conditions are satisfied:

1. high-level execution resolves DB / batch / ruleset from a prepared workspace — PASS;
2. one invocation creates one OpenAI-compatible run — PASS;
3. accepted material-aware worker is reused — PASS;
4. normal return finalizes and reports run status — PASS;
5. provider/model/base URL/config identity remains bound — PASS;
6. API key is excluded from persisted provenance and stdout — PASS;
7. workspace provenance mismatch stops before HTTP — PASS;
8. duplicate run ID fails closed — PASS;
9. bounded execution produces an ordinary incomplete run — PASS;
10. later run resumes unfinished work without retranslating valid success — PASS;
11. retry and failed-final behavior remains 01C semantics — PASS;
12. low-level execution tooling remains compatible — PASS;
13. targeted tests pass — PASS;
14. full repository regression passes — PASS;
15. deterministic controlled provider coverage is sufficient for core acceptance — PASS.

~~~text
LSTP-03B Provider Execution Orchestration = ACCEPTED
~~~

---

## Deferred / 後續階段

03B 明確延後：

~~~text
automatic rate limiting/backoff
Retry-After
provider quota accounting
automatic multi-worker concurrency
provider fallback/routing
token/cost accounting
QA orchestration
review orchestration
finalize/bridge/rebuild orchestration
~~~

---

## Contract question / 契約問題

BG3Loc 能不能從一個已 prepare 的 production workspace，以單一安全命令執行 provider，同時完整保留 01C 已驗收的 run、worker、retry、lease、provenance 與 resume semantics？

03B 的目標是在不 reopening translation execution core 的前提下，讓答案成為 yes。
