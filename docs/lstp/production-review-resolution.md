# LSTP-02B | Production Human Review Resolution / 大型翻譯人工審核決議

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 02B
State: ACCEPTED
Depends on:
  LSTP-01C Translation Execution and State = ACCEPTED
  LSTP-01D Translation QA and Review Routing = ACCEPTED
  LSTP-01E Production Completion and Merge Readiness = ACCEPTED
Core reopening: no
~~~

## What this adds / 這次補上什麼

01D can route suspicious translations to REVIEW, and 01E can hold them in WAITING_REVIEW.

02B adds the missing operator step:

~~~text
REVIEW
→ human reads the candidate
→ ACCEPT current text
   or
→ REVISE text and re-run QA
~~~

The original automatic QA evidence is preserved. Human review does not rewrite an automatic REVIEW result into a fake automatic PASS.

原本的 QA route、issue 與 checked evidence 都保留；人工決議是另一層 provenance。

## Public CLI / 公開命令

~~~text
bg3loc qa review-export
bg3loc qa review-resolve
~~~

`review-export` writes current REVIEW candidates with source text, candidate translation, output hash, QA identity, and issues.

`review-resolve --decision accept` approves the exact current candidate.

`review-resolve --decision revise --text ...` writes a human revision. The changed output hash makes the previous QA stale, so the row must pass QA again before it can become merge-ready.

## Approval binding / 人工批准綁定

A human ACCEPT is valid only for the exact combination of:

~~~text
ContentUid
QA ruleset version
QA input hash
current output hash
~~~

If the output changes, the QA input identity changes, or the QA ruleset changes, the old approval does not follow the new candidate.

This is fail-closed by design.

## Production completion behavior / 完成度判定

A current automatic REVIEW normally remains:

~~~text
WAITING_REVIEW
~~~

When a matching current human ACCEPT exists:

~~~text
succeeded execution
+ current checked REVIEW
+ same QA ruleset
+ same QA input hash
+ same output hash
+ human ACCEPT
→ MERGE_READY
~~~

A manual REVISE does not bypass QA:

~~~text
REVISE
→ translated_text changes
→ output_hash changes
→ previous QA becomes stale
→ not MERGE_READY
→ run QA again
~~~

## Test evidence / 測試證據

Targeted tests cover:

~~~text
REVIEW + ACCEPT -> MERGE_READY
changed output invalidates old approval
changed QA input identity invalidates old approval
REVISE changes output and makes old QA stale
review-export CLI
review-resolve CLI
~~~

Final targeted result:

~~~text
5 passed
0 failed
~~~

Final repository regression after the provenance-binding fix:

~~~text
403 passed
68 subtests passed
0 failed
~~~

The recurring Windows `.pytest_cache` WinError 5 warning is environment/cache related and did not cause a failure.

## Acceptance decision / 驗收判定

Can an operator resolve only flagged REVIEW rows, preserve the automatic QA history, safely approve the exact current candidate, or revise it without bypassing re-QA?

答案是 **yes**。

~~~text
LSTP-02B Production Human Review Resolution = ACCEPTED
~~~
