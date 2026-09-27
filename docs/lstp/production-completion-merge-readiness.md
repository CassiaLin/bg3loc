# LSTP-01E | Production Completion and Merge Readiness / 生產完成度與合併就緒判定

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 01E
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
  LSTP-01C Translation Execution and State = ACCEPTED
  LSTP-01D Translation QA and Review Routing = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

到 01D 為止，BG3Loc 已經知道每筆文字屬於哪一類、在哪個 batch、翻譯是否成功，以及 QA 是 PASS、RETRY、REVIEW 還是 FAIL。

01E 接著回答一個更接近實際生產完成度的問題：

> 哪些 ContentUid 已經真的可以進入最終合併？哪些仍然卡在翻譯、重試、人工審核或錯誤狀態？

LSTP-01E does not translate text and does not judge translation quality again. It combines the accepted execution state from 01C and QA state from 01D into a deterministic production-completion view.

---

## Core output / 核心輸出

For every classified translation unit, 01E derives exactly one production disposition:

~~~text
MERGE_READY
WAITING_TRANSLATION
WAITING_RETRY
WAITING_REVIEW
BLOCKED
~~~

### MERGE_READY

The current translation output exists and its current QA result is PASS.

### WAITING_TRANSLATION

The row has not yet produced a usable completed translation candidate. Typical execution states include pending, running, and invalidated.

### WAITING_RETRY

The current row is expected to return to translation execution, such as failed-retryable or a QA RETRY awaiting handoff.

### WAITING_REVIEW

The current output exists, QA is current, and route is REVIEW.

### BLOCKED

Automatic progression is not safe, for example failed-final, QA FAIL, or inconsistent state required to determine readiness.

---

## Merge-ready rule / 可合併判定

A ContentUid is merge-ready only when all required conditions are true:

~~~text
execution.status == succeeded
translated_text exists
output_hash exists
current QA result exists
QA status == checked
QA route == PASS
QA output_hash == current execution output_hash
~~~

Anything else is not merge-ready. This rule is intentionally conservative and fail-closed.

---

## ContentUid remains the identity / ContentUid 仍是唯一身份

01E must not create a second ownership system. Production completion is always derived by ContentUid, never by batchId, attemptId, row number, review position, file order, or provider request id.

Each ContentUid appears exactly once in the completion view.

---

## Completion summary / 完成度摘要

01E should expose counts for the whole production corpus and by primary category.

At minimum:

~~~text
total
mergeReady
waitingTranslation
waitingRetry
waitingReview
blocked
~~~

The invariant must hold:

~~~text
total = mergeReady + waitingTranslation + waitingRetry + waitingReview + blocked
~~~

No row may disappear from the summary and no row may be counted twice.

---

## Unresolved inventory / 未完成清單

01E should provide a machine-readable unresolved inventory for everything that is not MERGE_READY.

Each unresolved row should explain why it cannot move forward, for example:

~~~text
ContentUid
primaryCategory
batchId
executionStatus
qaStatus
qaRoute
reasonCode
lastAttemptId
attemptCount
~~~

This is an operational view, not a new source of truth. Canonical mutable state remains in the 01C/01D SQLite database.

---

## Review and retry boundaries / 人工審核與重試邊界

01E does not decide whether a REVIEW candidate should be accepted or rewritten.

For v1:

~~~text
QA REVIEW -> WAITING_REVIEW
~~~

01E also does not execute retries. 01C remains responsible for execution attempts, while 01D remains responsible for QA RETRY decisions and handoff.

---

## Merge boundary / 合併邊界

01E defines the merge-ready set. It does not yet write the final game language file.

The intended progression is:

~~~text
01A classify
-> 01B batch
-> 01C translate
-> 01D QA/review routing
-> 01E completion + merge-ready set
-> later final merge/rebuild/release workflow
~~~

---

## CLI shape / 預計 CLI

The first implementation should provide a simple operator-facing surface such as:

~~~text
bg3loc production status
bg3loc production unresolved
bg3loc production merge-ready
~~~

Exact command names may change during implementation, but these semantics are the contract.

---

## Determinism / 可重現性

For unchanged execution state, QA state, and batch material:

~~~text
same input state
-> same disposition per ContentUid
-> same counts
-> same merge-ready ContentUid set
-> same unresolved ContentUid set
~~~

Ordering for exported lists must be deterministic.

---

## Fail-closed conditions / 無法安全判定時停止

These must never silently become MERGE_READY:

~~~text
succeeded execution row with no QA result
stale QA result
QA result bound to an older output_hash
unknown QA route
missing translated_text for succeeded state
duplicate ContentUid in completion input
ContentUid missing required batch/category material
~~~

These should become BLOCKED or raise a deterministic integrity error, depending on whether the problem is row-local or invalidates the whole completion input.

---

## First implementation boundary / 第一版實作邊界

01E v1 should cover:

1. deterministic disposition for every classified ContentUid;
2. exact merge-ready rule;
3. whole-corpus and per-category completion counts;
4. unresolved inventory with reason codes;
5. deterministic merge-ready export;
6. stale/missing QA fail-closed behavior;
7. no duplicate ContentUid ownership;
8. CLI for status and inventory inspection.

It should not yet implement:

~~~text
human review editing UI
review approval workflow
final language-file writing
game installation
release packaging
locale-specific QA
cross-row terminology correction
provider scheduling
translation cost accounting
~~~

---

## Real-corpus acceptance / 真實資料驗收

01E 已在完整的 LSTP-01B 真實素材上完成 controlled acceptance probe。

使用：

~~~text
workspace/lstp-01b-real-batching-v2
~~~

建立兩個彼此獨立的隔離 probe：

~~~text
workspace/lstp-01e-real-completion-smoke
workspace/lstp-01e-real-completion-smoke-repeat
~~~

兩次都從完整 01B material 建立 execution state，總數都是：

~~~text
218,272 ContentUid
~~~

### Full-corpus disposition coverage / 全量 disposition 覆蓋

兩次 probe 都得到完全相同的結果：

~~~text
Total:               218272
MERGE_READY:              1
WAITING_TRANSLATION: 218268
WAITING_RETRY:            1
WAITING_REVIEW:           1
BLOCKED:                  1
~~~

總數精確相等：

~~~text
1 + 218268 + 1 + 1 + 1 = 218272
~~~

受控真實 ContentUid 也在兩次 probe 中保持一致：

~~~text
MERGE_READY
h00243b47g7339g4c8dg80bag35a7cb006977

WAITING_REVIEW
h001e8d1eg28dag410dga211g29094e8e866f

WAITING_RETRY
h00491da0gd5acg4814gb518g7a71ac94b36c

BLOCKED
h00667e20gb8fbg42d8gb0f5g791715404996
~~~

其餘 218,268 筆維持正常的 WAITING_TRANSLATION。

這證明完整 classified corpus 中每個 ContentUid 都得到且只得到一個 production disposition。

### Merge-ready and unresolved partition / 可合併與未完成集合

第一個 probe：

~~~text
Merge-ready rows: 1
Unresolved rows: 218271
~~~

repeat probe：

~~~text
Merge-ready rows: 1
Unresolved rows: 218271
~~~

因此：

~~~text
merge-ready ∩ unresolved = empty
merge-ready ∪ unresolved = all 218272 ContentUid
~~~

CLI/unit integration tests另外直接驗證兩集合互斥且聯集完整覆蓋 corpus。

### Byte-for-byte determinism / 位元組級可重現性

兩個獨立 probe 的 unresolved export：

~~~text
SHA256
7EB427A37F3F1C44AEAECD77E7FF76ABF3E71EB45EFAF62C0AC2CF8BB79968A8
~~~

兩份完全相同。

兩個獨立 probe 的 merge-ready export：

~~~text
SHA256
916C266F469D26DBF65F9A09A9622BDE68891C3F3F1A8E8764477A716E28AB60
~~~

兩份也完全相同。

因此 unchanged material + state semantics 會得到 byte-for-byte identical exported sets。

probe manifest 不要求 byte-for-byte 相同，因為其中包含不同的 work-directory/database path；其 disposition counts 與受控 ContentUid roles 則完全一致。

### Fail-closed evidence / 安全失敗證據

Automated tests cover the cases that must never silently become MERGE_READY:

~~~text
missing QA
stale QA
QA output hash mismatch
QA FAIL
unknown QA route
missing succeeded output
failed-final
skipped
unknown execution status
execution UID missing from material coverage
foreign execution UID outside material coverage
batch/category mismatch
duplicate ContentUid in batch material
~~~

Pending, running and invalidated execution states remain WAITING_TRANSLATION.

failed-retryable and current QA RETRY remain WAITING_RETRY.

Current QA REVIEW remains WAITING_REVIEW.

Only succeeded + current PASS + matching output is MERGE_READY.

### Final regression / 最終回歸測試

After the full 01E implementation and real-corpus acceptance work:

~~~text
393 passed
68 subtests passed
0 failed
~~~

The recurring Windows pytest cache warning remains:

~~~text
.pytest_cache
WinError 5
~~~

It is environment/cache related and did not cause a test failure.

### Acceptance checklist / 驗收清單

The 01E acceptance conditions are satisfied:

1. every classified ContentUid receives exactly one disposition — PASS;
2. totals reconcile exactly — PASS;
3. current succeeded + PASS becomes MERGE_READY — PASS;
4. REVIEW becomes WAITING_REVIEW — PASS;
5. failed-retryable becomes WAITING_RETRY — PASS;
6. pending/running work is never merge-ready — PASS;
7. failed-final or QA FAIL becomes BLOCKED — PASS;
8. stale QA is never merge-ready — PASS;
9. unchanged state produces deterministic output — PASS, including byte-for-byte JSONL hashes;
10. merge-ready and unresolved sets are disjoint and together cover the complete classified corpus — PASS.

---

## Acceptance question / 驗收問題

Can BG3Loc look at the current large-scale translation state and answer, deterministically and completely:

> What is finished, what is still waiting, what is blocked, and exactly which ContentUid rows are safe to pass into the final merge stage?

BG3Loc 能不能從目前的大規模翻譯狀態中，完整而可重現地回答：

> 哪些已完成、哪些還在等待、哪些被阻擋，以及究竟哪些 ContentUid 已經安全到可以送進最終合併階段？

The answer is **yes**.

功能、完整真實素材驗收、fail-closed coverage、deterministic exports 與完整 regression 都已通過。

~~~text
LSTP-01E Production Completion and Merge Readiness = ACCEPTED
~~~