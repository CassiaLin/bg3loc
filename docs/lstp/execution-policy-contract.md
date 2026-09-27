# LSTP-03E Execution Policy

Milestone: v1.3 Production Usability 03E
State: ACCEPTED
Depends on: LSTP-01C = ACCEPTED; LSTP-03B = ACCEPTED
Core reopening: no

## English

### Problem and boundary

HTTP 429, HTTP 5xx, transport failures, and selected invalid provider responses are already retryable. Without pacing, one worker can immediately reclaim the same ContentUid and exhaust its attempt budget during a short provider outage.

03E adds a single-worker execution policy. It does not change ContentUid identity, append-only attempt history, the rule that one HTTP request is one attempt, `max-attempts`, or `failed-retryable` / `failed-final` transitions. It does not add provider fallback, quota accounting, pricing, a distributed scheduler, or global multi-worker coordination.

### Compatibility model

The low-level `run_worker()` default remains no-delay for backward compatibility. The high-level `production execute-openai-compatible` command supplies a production pacing policy by default:

```text
--retry-backoff-base-seconds 2
--retry-backoff-max-seconds 60
--min-request-interval-seconds 0
```

All values are non-negative. A zero base disables fallback backoff. The maximum delay caps both fallback and provider-requested waits. The minimum request interval is a per-worker pacing floor, not a provider-wide quota manager.

### Retry-After signal

The HTTP transport exposes response headers to the provider adapter. For retryable HTTP responses, the adapter parses `Retry-After` as either non-negative delta-seconds or an HTTP-date and returns `retry_after_seconds` as a signal. Invalid or past values are ignored or treated as zero. The provider reports the signal; it does not sleep.

### Backoff policy

The worker maintains one consecutive retryable-failure streak. With no usable `Retry-After`, delay is deterministic exponential fallback:

```text
min(max_delay, base_delay * 2 ** (streak - 1))
```

A success or non-retryable failure resets the streak. A valid provider delay takes precedence over exponential fallback and is capped by `max_delay`. The effective wait is also no shorter than the remaining per-worker minimum request interval.

The failed attempt is durably completed before waiting. The worker sleeps before its next claim, so a crash during the wait leaves no attempt in `running`. `max-items` remains a claim/attempt budget: when the budget is exhausted, the worker does not sleep or claim another row.

Clock, monotonic timer, and sleeper behavior are injectable. Automated tests never use real sleep.

### Multi-worker limitation

Each worker applies its own pacing policy. Multiple workers do not share a global rate-limit clock or quota. Global provider quota coordination is explicitly deferred.

### Acceptance gates

03E advances through `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED`. Acceptance requires controlled 429 and 5xx behavior, delta-seconds and HTTP-date parsing, deterministic capped exponential backoff, success reset, bounded-run behavior, unchanged secret handling, full regression, and a clean repository audit.

Acceptance evidence (2026-09-28):

- 42 focused provider/execution/policy tests and 3 subtests passed; the combined 03D/03E production regression passed 73 tests and 11 subtests.
- A controlled high-level production run received HTTP 429 with `Retry-After: 10`, durably recorded attempt 1 as retryable, invoked the injected sleeper with 10 seconds, and then performed attempt 2 successfully.
- HTTP-date parsing, deterministic fallback delays `2 -> 4 -> 5` with a five-second cap, success reset, per-worker minimum request interval, `max-attempts`, and `max-items=1` were verified without real sleep.
- Existing low-level no-policy worker tests and API-key non-persistence/non-output tests remain passing.
- Final regression passed with 456 tests and 72 subtests, with no failures or warnings. No paid or external provider call was required.

## 繁體中文（台灣）

### 問題與邊界

HTTP 429、HTTP 5xx、transport failure 與部分無效 provider response 已經屬於 retryable。若沒有 pacing，單一 worker 可能立刻再次 claim 同一個 ContentUid，在短暫限流期間快速耗盡 attempt budget。

03E 新增 single-worker execution policy，但不改變 ContentUid identity、append-only attempt history、每次 HTTP request 等於一次 attempt、`max-attempts`，以及 `failed-retryable` / `failed-final` transition。它不處理 provider fallback、quota accounting、pricing、distributed scheduler 或全域 multi-worker coordination。

### 相容模式

低階 `run_worker()` 預設維持 no-delay。高階 `production execute-openai-compatible` 預設套用 production pacing policy：

```text
--retry-backoff-base-seconds 2
--retry-backoff-max-seconds 60
--min-request-interval-seconds 0
```

所有數值必須非負。Base 為零時停用 fallback backoff。Maximum delay 同時限制 fallback 與 provider 指定的等待。Minimum request interval 是 per-worker pacing floor，不是 provider-wide quota manager。

### Retry-After signal

HTTP transport 將 response headers 提供給 provider adapter。Retryable HTTP response 的 `Retry-After` 可為非負 delta-seconds 或 HTTP-date；adapter 解析後以 `retry_after_seconds` signal 回傳。無效或過期值會被忽略或視為零。Provider 只提供 signal，不負責 sleep。

### Backoff policy

Worker 維護一個連續 retryable-failure streak。沒有可用 `Retry-After` 時，使用 deterministic exponential fallback：

```text
min(max_delay, base_delay * 2 ** (streak - 1))
```

成功或 non-retryable failure 會重設 streak。有效 provider delay 優先於 exponential fallback，並受 `max_delay` 限制；實際等待也不得短於 per-worker minimum request interval 的剩餘時間。

Retryable attempt 會先完成 durable failure 記錄，再等待下一次 claim，因此等待期間 crash 不會留下 `running` attempt。`max-items` 仍是 claim/attempt budget；budget 用完後不會 sleep，也不會 claim 下一列。

Clock、monotonic timer 與 sleeper 都可注入，automated tests 不使用真實 sleep。

### Multi-worker 限制

每個 worker 各自套用 pacing policy。多 worker 不共用全域 rate-limit clock 或 quota；全域 provider quota coordination 明確 deferred。

### 驗收門檻

03E 依序經過 `CONTRACT DRAFT -> IMPLEMENTED -> TARGETED PASS -> FULL REGRESSION PASS -> ACCEPTED`。必須完成 controlled 429/5xx、delta-seconds 與 HTTP-date、deterministic capped exponential backoff、success reset、bounded run、secret handling 不變、完整 regression 與乾淨 repository audit，才能 ACCEPTED。

驗收證據（2026-09-28）：

- 42 個 provider/execution/policy focused tests 與 3 個 subtests 全部通過；03D/03E 聯合 production regression 為 73 tests、11 subtests。
- Controlled high-level production run 收到 HTTP 429 與 `Retry-After: 10` 後，先把 attempt 1 durable 記為 retryable，再以 injected sleeper 等待 10 秒，之後成功執行 attempt 2。
- HTTP-date、`2 -> 4 -> 5` 且上限五秒的 deterministic fallback、success reset、per-worker minimum interval、`max-attempts` 與 `max-items=1` 都已驗證，沒有使用 real sleep。
- 既有 low-level no-policy worker tests 與 API key 不持久化、不輸出測試仍通過。
- 最終 regression 為 456 tests、72 subtests，零失敗、零 warning；不需要付費或外部 provider call。
