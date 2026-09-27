# LSTP-02C | Unclassified Resolution Policy / 未分類資料處理政策

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 02C
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

01A deliberately leaves insufficient-evidence rows as `other / unclassified` instead of guessing.

02C adds an auditable operator layer for deciding what to do with those rows without rewriting the original automatic classification ledger.

01A 原始分類結果仍保持可重現；人工決議只形成新的 resolution overlay 與 resolved ledger。

## Decisions / 決議種類

~~~text
assign
exclude
pending
~~~

`assign` moves one unresolved ContentUid into one normal batchable production category.

`exclude` records an explicit decision that the row does not enter translation production.

`pending` keeps the row unresolved.

## Safety rules / 安全規則

The resolver fails closed when:

~~~text
decision ContentUid is foreign
decision ContentUid is already classified
decision file contains duplicate ContentUid
assign category is not a supported batchable category
assign/exclude has no reviewer
assign/exclude has no decidedAt
non-assign decision contains a category
~~~

The operator cannot use 02C to override an already accepted automatic classification.

## Provenance / 來源追蹤

Each resolved row keeps the original automatic classification fields and adds a `resolution` object containing:

~~~text
action
reviewer
note
decidedAt
sourceClassificationStatus
sourcePrimaryCategory
~~~

The resolved classification JSONL is a derived artifact. The original 01A ledger remains unchanged.

## Batching behavior / 分批行為

After resolution:

~~~text
assigned -> classified -> ordinary category batch
excluded -> excluded.jsonl
pending / no decision -> unresolved.jsonl
~~~

The batch plan fingerprint already binds the SHA256 of the classification ledger passed to batching. Therefore changing a resolution changes the resolved ledger hash and produces a different batch-plan fingerprint.

人工決議一旦改變，resolved classification SHA256 與後續 batchPlanFingerprint 也會跟著改變。

## Public CLI / 公開命令

~~~text
bg3loc research resolve-unclassified
~~~

The command reports:

~~~text
original unresolved rows
assigned
excluded
pending decisions
no decision yet
output SHA256
~~~

## Test evidence / 測試證據

Targeted tests cover:

~~~text
assign enters normal batching
exclude is separated from unresolved
pending remains unresolved
already-classified UID cannot be overridden
invalid category fails closed
duplicate decision fails closed
foreign UID fails closed
CLI output generation
~~~

Targeted result:

~~~text
5 passed
0 failed
~~~

Final repository regression:

~~~text
408 passed
68 subtests passed
0 failed
~~~

The recurring Windows `.pytest_cache` WinError 5 warning is environment/cache related and did not cause a failure.

## Acceptance decision / 驗收判定

Can BG3Loc keep automatic classification reproducible while giving operators an auditable, fail-closed way to assign, exclude, or defer unresolved rows before batching?

答案是 **yes**。

~~~text
LSTP-02C Unclassified Resolution Policy = ACCEPTED
~~~
