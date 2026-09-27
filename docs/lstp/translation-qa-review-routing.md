# LSTP-01D | Translation QA and Review Routing / 翻譯 QA 與人工審核分流

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 01D
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
  LSTP-01C Translation Execution and State = ACCEPTED
Core reopening: no
~~~

01D 的功能、真實資料驗收與最後完整 regression 均已通過，本 milestone 正式接受。

The 01D functionality, real-material acceptance checks, and final full regression all pass. This milestone is accepted.

---

## What this milestone does / 這一階段做什麼

LSTP-01C 負責「把翻譯跑完並保存」。

LSTP-01D 負責下一個問題：

> 一筆模型輸出的譯文，現在應該直接接受、重新翻譯、交人工看，還是阻擋流程？

01D 不嘗試自動判斷文學品質，也不要求 AI Judge。第一版優先處理可重現、可解釋、可以安全自動化的 QA。

LSTP-01C answers how to execute and persist translation work.

LSTP-01D answers what should happen to a completed candidate: accept it, translate it again, send it to a human, or block automatic progression.

---

## Four routes / 四種分流

Every QA result has exactly one route:

~~~text
PASS
RETRY
REVIEW
FAIL
~~~

- **PASS** — 沒有發現目前規則能確認的阻擋問題。這不代表譯文已達文學終稿品質。
- **RETRY** — 發現明確、可重現，而且重新翻譯可能修好的輸出問題。
- **REVIEW** — 有可疑訊號，但機器不應直接裁決；只把這一筆送人工看。
- **FAIL** — 專案或 QA 設定不完整，不能安全繼續自動流程。

In English:

- **PASS** — no blocking configured QA problem was found;
- **RETRY** — deterministic output defects that another translation attempt may fix;
- **REVIEW** — suspicious output that needs human judgment;
- **FAIL** — project/configuration conditions where automatic continuation is unsafe.

Routing precedence is:

~~~text
FAIL > RETRY > REVIEW > PASS
~~~

---

## Implemented QA / 已實作的 QA

### Universal hard checks / 通用硬檢查

The current core checks are language-neutral.

目前 core 已實作：

~~~text
OUTPUT_EMPTY
PROTECTED_TOKEN_MISSING
PROTECTED_TOKEN_ADDED
LSTAG_MALFORMED
~~~

Default routing:

~~~text
empty output             -> RETRY
missing protected token  -> RETRY
added protected token    -> RETRY
malformed LSTag          -> RETRY
~~~

Protected syntax reuses the existing BG3Loc protected-syntax parser.

Examples include:

~~~text
{PLAYER}
%s
%1$d
LSTag markup
~~~

---

### Category-aware QA / 依內容類別分流

Every primary category accepted by LSTP-01A is registered explicitly.

目前 12 個正式 category 都有 policy：

~~~text
dialogue_general
dialogue_story
quest
bark
ui
skill_spell
item
book_lore
character_world
system_message
tutorial
other
~~~

Unknown category fails closed:

~~~text
CATEGORY_RULE_MISSING -> FAIL
~~~

The first category-specific specialization is intentionally conservative:

- `bark`, `ui`, and dialogue categories have their own length-ratio bounds;
- other known categories currently use shared conservative bounds;
- surprising length ratios route to `REVIEW`, not automatic rejection.

第一版的 category QA 先做安全、可解釋的規則，不假裝已經能自動判斷所有術語、文風與敘事品質。

---

### Heuristic review / 可疑項目人工審核

Implemented review signals include:

~~~text
SOURCE_EQUALS_TARGET
LENGTH_RATIO_SUSPICIOUS
~~~

Language-bearing source text that is returned unchanged can route to `REVIEW`.

A suspicious length ratio also routes to `REVIEW`.

These are warnings, not automatic hard failures.

---

## Locale-specific QA / 語言專屬 QA

Locale-specific QA is **not implemented in 01D v1**.

這是刻意的邊界，不是漏做。

Traditional Chinese-specific checks such as the following belong in a later locale profile:

~~~text
Simplified Chinese residue
Mainland-China-specific wording
Traditional Chinese punctuation conventions
project terminology / naming conventions
machine-conversion artifacts
language-specific untranslated-text checks
~~~

The core QA must stay reusable for other language communities. Therefore Traditional Chinese or CJK-specific heuristics are not hard-coded into universal QA.

其他語言（例如日文、韓文）未來也應能加入自己的 locale QA，而不用修改 universal core。

---

## QA identity and persistence / QA 身份與保存

QA identity remains:

~~~text
ContentUid
~~~

It is never replaced by:

~~~text
batchId
row number
attemptId
review queue position
~~~

Persisted QA data lives beside the 01C execution state in the same SQLite database, but in separate QA tables.

Current persisted surfaces include:

~~~text
qa_results
qa_issues
qa_rejected_candidates
~~~

Each stored result records the QA route, ruleset version, QA input hash, output hash, check time, and issue details.

`checkedAt` is a real UTC timestamp.

---

## checked and stale / 已檢查與失效

The current stored QA status is derived as:

~~~text
checked
stale
~~~

A QA result becomes stale when:

- the current translation output hash no longer matches the output that was checked; or
- the requested QA ruleset version is different.

So changing `translatedText` does not silently keep an old QA approval.

`bg3loc qa run` skips current checked rows and rechecks stale rows only.

---

## RETRY handoff back to 01C / RETRY 如何回到 01C

01D decides that a candidate should be retried.

01C still owns the actual execution attempt lifecycle.

The implemented handoff is:

~~~text
translation succeeds
-> QA = RETRY
-> archive rejected candidate
-> preserve QA issues and output hash
-> clear current accepted output
-> reopen the same ContentUid in 01C
-> next claim uses the next attemptNumber
~~~

If the 01C retry limit has already been reached:

~~~text
RETRY
-> rejected candidate still archived
-> execution becomes failed-final
-> no new claim
~~~

01D never silently replaces a rejected candidate before preserving its provenance.

---

## CLI / 命令列

The current public CLI surface is:

~~~text
bg3loc qa run
bg3loc qa summary
bg3loc qa review-list
bg3loc qa retry-handoff
bg3loc qa smoke-probe
~~~

### qa run

Runs QA only for execution rows currently in `succeeded` state.

It resolves the original source material and `primaryCategory` from the LSTP-01B batch material, evaluates QA, and persists the result.

### qa summary

Shows persisted QA totals, checked/stale counts, and route totals.

### qa review-list

Lists only rows routed to `REVIEW`.

### qa retry-handoff

Archives one current `RETRY` candidate and reopens that `ContentUid` through the 01C retry lifecycle.

### qa smoke-probe

Creates an isolated controlled QA database from real batch material without calling any translation provider or modifying the real execution database.

---

## Human review boundary / 人工審核邊界

The intended workflow is:

~~~text
automatic translation
-> automatic QA
-> PASS     continue
-> RETRY    translate again
-> REVIEW   human review queue
-> FAIL     stop automatic progression
~~~

The goal is explicitly **not** to ask humans to inspect all 218,272 classified rows.

The current CLI review queue lists flagged `REVIEW` rows only.

Advanced filtering by category, provider/model provenance, issue code, or a web review UI is deferred work and is not claimed as part of 01D v1.

---

## Deferred work / 明確延後

The following are useful future capabilities but are **not part of the accepted 01D v1 implementation**:

~~~text
locale-specific QA profiles
Traditional Chinese-specific QA rules
cross-row terminology consistency engine
glossary drift detection
AI / semantic judge
web review UI
advanced review-queue filters
per-issue ruleVersion field
QA_CONFIG_INVALID handling
final merge or release approval
~~~

These can be added later without reopening the 01D core routing model.

---

## Real-material acceptance evidence / 真實素材驗收證據

The acceptance probe used real material from:

~~~text
workspace/lstp-01b-real-batching-v2
~~~

and an isolated database:

~~~text
workspace/lstp-01d-real-qa-smoke/execution.sqlite3
~~~

No translation provider was called and the real production execution database was not modified.

### Routing probe

Three real `bark` rows were selected:

~~~text
PASS
h00243b47g7339g4c8dg80bag35a7cb006977

REVIEW
h001e8d1eg28dag410dga211g29094e8e866f

RETRY
h00491da0gd5acg4814gb518g7a71ac94b36c
~~~

Observed QA result:

~~~text
Succeeded execution rows: 3
Checked this run: 3
PASS: 1
REVIEW: 1
RETRY: 1
~~~

### Review queue

Observed:

~~~text
Review rows: 1
h001e8d1eg28dag410dga211g29094e8e866f
SOURCE_EQUALS_TARGET
~~~

Only the flagged row entered the human-review queue.

### Stale detection

After changing the output of the PASS row:

~~~text
Persisted QA rows: 3
checked: 2
stale: 1
~~~

Running QA again rechecked only that stale row:

~~~text
Checked this run: 1
Skipped current QA: 2
~~~

### RETRY handoff

For:

~~~text
h00491da0gd5acg4814gb518g7a71ac94b36c
~~~

the observed handoff was:

~~~text
Previous QA route: RETRY
Execution status: failed-retryable
Rejected candidates archived: 1
~~~

The next 01C claim returned:

~~~text
ContentUid: h00491da0gd5acg4814gb518g7a71ac94b36c
attemptNumber: 2
~~~

This proves the rejected candidate was preserved and the same translation unit re-entered execution through the normal 01C retry lifecycle.

---

## Test evidence / 測試證據

After the final locale-boundary cleanup and UTC `checkedAt` fix, targeted QA regression passed:

~~~text
21 passed
12 subtests passed
0 failed
~~~

The final full repository regression then passed on the accepted code state:

~~~text
378 passed
56 subtests passed
0 failed
~~~

The recurring `.pytest_cache` Windows `WinError 5` warning is environment/cache related and did not cause test failures.

---

## Acceptance decision / 驗收判定

The functional acceptance question is now satisfied:

> Can BG3Loc automatically reject structurally bad translations, isolate suspicious translations for human review, let clean translations continue, detect stale QA, and return rejected candidates to the normal retry lifecycle while preserving audit history?

目前答案是 **yes**。

功能、真實素材驗收與完整 regression 都已通過。

~~~text
LSTP-01D Translation QA and Review Routing = ACCEPTED
~~~
