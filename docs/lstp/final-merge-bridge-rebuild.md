# LSTP-01F | Final Merge Bridge and Rebuild / 最終合併橋接與重建

## Status / 狀態

~~~text
Milestone: Large-Scale Translation Production 01F
State: ACCEPTED
Depends on:
  LSTP-01A Functional Classification = ACCEPTED
  LSTP-01B Category-Aware Batching = ACCEPTED
  LSTP-01C Translation Execution and State = ACCEPTED
  LSTP-01D Translation QA and Review Routing = ACCEPTED
  LSTP-01E Production Completion and Merge Readiness = ACCEPTED
Core reopening: no
~~~

## Purpose / 用途

01E 已經能明確回答哪些 ContentUid 是 MERGE_READY。

01F 不再做翻譯，也不重新判斷 QA；它負責把這個已通過的 MERGE_READY 集合安全地交給 BG3Loc 既有 rebuild pipeline。

The key rule is simple:

> Only the exact current MERGE_READY set may cross the bridge into rebuild.

---

## Reuse existing rebuild safety / 沿用既有 rebuild 安全機制

01F does not implement a second rebuilder.

Existing BG3Loc rebuild already validates:

~~~text
accepted text/version match
semantic round-trip
ContentUid set integrity
untouched baseline integrity
repacked archive entry-set integrity
repacked LOCA payload identity
~~~

Existing install already supports dry-run, backup, and rollback.

01F only creates the validated bridge artifact and bindings needed to reuse those capabilities.

---

## Bridge input / 橋接輸入

The bridge consumes:

~~~text
01E execution.sqlite3
01B batch-plan.json + materials
current QA ruleset semantics
extract-manifest.json
~~~

The execution/QA database and batch material determine the current MERGE_READY ContentUid set.

The extract manifest supplies the authoritative target locale, source locale, version/baseline information, and rebuild inputs.

---

## Bridge output / 橋接輸出

01F should create a deterministic accepted target compatible with the existing rebuilder.

Each accepted row must contain at least:

~~~text
contentUid
localeId
text
version
~~~

The row text must come from the current execution state for that same ContentUid.

The output must never contain WAITING_TRANSLATION, WAITING_RETRY, WAITING_REVIEW, or BLOCKED rows.

---

## Exact binding / 精確綁定

The bridge must record enough provenance to prove what was merged.

At minimum:

~~~text
batch plan fingerprint
merge-ready ContentUid count
merge-ready export SHA256
accepted target SHA256
execution database identity/fingerprint where practical
target locale
extract manifest SHA256
QA ruleset version
~~~

The rebuilder must consume the exact accepted target named by the bridge manifest.

If any bound input changes, the bridge must be regenerated.

---

## Version source / version 從哪裡來

The large-scale execution state stores translated text, not BG3 LOCA version metadata.

Therefore 01F must derive each accepted row version from the authoritative extracted localization baseline/source data already used by the existing rebuild pipeline.

It must not invent a version number.

For a ContentUid already present in the target baseline, preserve the authoritative target version unless the existing extraction model defines another canonical version.

For source-only ContentUid rows that need a new target node, use the authoritative source version already represented in the extract data.

---

## Partial merge semantics / 部分合併語意

01F supports partial production safely.

If only a subset of the classified corpus is MERGE_READY:

~~~text
MERGE_READY rows -> accepted target -> rebuilt into target locale
all other target baseline rows -> remain untouched
~~~

This matches the existing rebuilder behavior: accepted rows are edits; rows not present in accepted are preserved from the target baseline.

Therefore 01F does not require all 218,272 rows to be complete before producing a technically valid partial rebuild.

Whether a partial rebuild is suitable for public release is a separate release-policy decision.

---

## Fail-closed conditions / 無法安全橋接時停止

01F must refuse to create a rebuild input when any of these apply:

~~~text
MERGE_READY row has no translated_text
MERGE_READY output_hash does not match current text
ContentUid cannot be resolved in authoritative extract data
target/source version cannot be determined
target locale cannot be determined
duplicate accepted ContentUid
accepted set differs from current 01E MERGE_READY set
batch/material coverage mismatch
stale QA or stale merge-ready state
extract manifest or referenced baseline is missing/invalid
~~~

No fallback guessing is allowed.

---

## Rebuild handoff / 交給 rebuild

01F should emit a minimal validate-compatible manifest pointing at its accepted target, then call or hand off to the existing rebuilder.

The intended flow is:

~~~text
01E completion view
-> exact MERGE_READY set
-> 01F accepted target bridge
-> existing run_rebuild()
-> semantic round-trip validation
-> rebuilt LOCA / PAK
-> install dry-run
-> optional explicit apply
~~~

Actual game modification remains opt-in.

---

## CLI shape / 預計 CLI

A small operator-facing surface is sufficient, for example:

~~~text
bg3loc production bridge
bg3loc production rebuild
bg3loc production install
~~~

Exact names may change during implementation, but the safety boundary does not:

> production rebuild must never bypass the current MERGE_READY calculation.

---

## Determinism / 可重現性

For unchanged batch material, execution/QA state, and extract baseline:

~~~text
same MERGE_READY ContentUid set
-> same accepted target bytes
-> same bridge manifest semantics
~~~

Rebuild artifacts themselves are validated semantically through the existing rebuild checks.

Where the backend produces deterministic binary output, artifact SHA256 may also be compared, but byte-identical PAK/LOCA output is not required unless the backend guarantees it.

---

## First implementation boundary / 第一版實作邊界

01F v1 should cover:

1. derive the current MERGE_READY set directly from 01E;
2. resolve authoritative locale/version metadata from extraction outputs;
3. create deterministic accepted-target JSONL;
4. create a validate-compatible bridge manifest;
5. bind bridge output to its inputs with hashes/fingerprints;
6. invoke the existing rebuild pipeline without duplicating it;
7. preserve untouched baseline rows;
8. expose install dry-run through the existing installer;
9. never modify the game unless the user explicitly requests apply.

It should not yet implement:

~~~text
release publishing
GitHub Release creation
automatic public-release policy
human review UI
new QA rules
new translation providers
a second LOCA/PAK rebuilder
~~~

---

## Real-corpus acceptance / 真實資料驗收

01F 已使用真實 BG3 extraction material、完整 01B batch material，以及 01E controlled real-corpus production state 完成驗收。

### Real bridge / 真實橋接

Input:

~~~text
execution DB:
workspace/lstp-01e-real-completion-smoke/execution.sqlite3

batch plan:
workspace/lstp-01b-real-batching-v2/batch-plan.json

extract manifest:
workspace/ui-skill-role-real-20260913/extract-absolute/extract-manifest.json
~~~

01E 當下只有一筆 MERGE_READY，因此 bridge 必須也只接受一筆。

Observed:

~~~text
Production bridge PASS
Merge-ready rows: 1
Target locale: ChineseTraditional
~~~

Accepted ContentUid:

~~~text
h00243b47g7339g4c8dg80bag35a7cb006977
~~~

Binding:

~~~text
versionSource: source
version: 3
outputHash:
3b92a00ad5a98af1aed25551343cb743a5731baea6adb327469242c930979381
~~~

The accepted text was verified by decoding the JSON as UTF-8 and hashing the actual Unicode text. The calculated SHA256 matched the bound outputHash exactly.

No WAITING_TRANSLATION, WAITING_RETRY, WAITING_REVIEW, or BLOCKED row crossed the bridge.

### Deterministic bridge output / 可重現 bridge 輸出

The same real inputs were bridged twice into separate output directories.

accepted-target.jsonl:

~~~text
SHA256
4ed14d951090daa8ce552dd4f5a7555cb5dd6936e4f989c8983eda0abba9c029
~~~

Both runs produced the same SHA256.

merge-ready-binding.jsonl:

~~~text
SHA256
363D356D7852AFE9EA744AFC96E623FB421515EF4CFA9001A1B5F5FDB945F011
~~~

Both runs produced the same SHA256.

The bridge manifest also records provenance including:

~~~text
batchPlanFingerprint
batchPlanSha256
executionDatabaseSha256
qaRuleSetVersion
extractManifestSha256
targetLocale
mergeReadyCount
acceptedTarget SHA256
mergeReadyBinding SHA256
validateManifest SHA256
~~~

Missing batchPlanFingerprint is tested as a fail-closed condition.

### Real LOCA rebuild / 真實 LOCA 重建

Using the bridge validate manifest:

~~~text
bg3loc rebuild
container = loca-only
~~~

produced:

~~~text
ChineseTraditional.loca
SHA256:
d2d0dc12d18108012904a2eb1080efa97dbc3712b3b2348df638744bd2467a73
~~~

Rebuild validation:

~~~text
acceptedRecordCount = 1
changedUidCount = 1
semanticRoundTrip = pass
acceptedTextMatch = pass
uidSetIntegrity = pass
untouchedRecordIntegrity = pass
~~~

This demonstrates that the one accepted ContentUid changed while untouched target-baseline records remained intact.

### Real PAK repack / 真實 PAK 重封裝

The same bridge input was rebuilt with:

~~~text
container = repack
~~~

Result:

~~~text
ChineseTraditional.pak
SHA256:
eb98f4d5aabee83ff3b3f901e76e7b261dd9ea7e73e18e1946c4356b3cf72155
~~~

Repack manifest:

~~~text
containerAction = repack
acceptedRecordCount = 1
changedUidCount = 1
semanticRoundTrip = pass
acceptedTextMatch = pass
uidSetIntegrity = pass
untouchedRecordIntegrity = pass
~~~

The existing rebuilder additionally verifies archive entry-set integrity and that the repacked LOCA payload matches the rebuilt LOCA artifact.

### Install dry-run / 安裝預演

The repacked PAK was passed to the existing installer with the real scan manifest.

Observed:

~~~text
Install dry-run PASS
Target:
D:\SteamLibrary\steamapps\common\Baldurs Gate 3\Data\Localization\ChineseTraditional\ChineseTraditional.pak

Backup: would be created on real install
Game modified: no
~~~

Therefore the full bridge -> rebuild -> repack -> install-preflight chain was exercised without modifying the game.

### Fail-closed evidence / 安全失敗證據

Automated tests cover the bridge-specific conditions including:

~~~text
only current MERGE_READY rows are exported
pending/unresolved rows are excluded
current translated_text must hash to current output_hash
target-present UID uses authoritative target version
source-only UID uses authoritative source version
missing batchPlanFingerprint fails closed
deterministic accepted-target output
deterministic merge-ready binding output
CLI artifact generation
~~~

01E remains responsible for stale QA, missing QA, coverage mismatch, foreign/missing execution rows, and all other production-completion fail-closed checks before a row can become MERGE_READY.

The existing rebuild layer remains responsible for accepted text/version match, semantic round-trip, UID-set integrity, untouched-record integrity, and repack integrity.

### Final regression / 最終回歸測試

After the final provenance-binding fixes:

~~~text
398 passed
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

1. bridge accepts exactly the current MERGE_READY set — PASS;
2. unresolved ContentUid does not cross the bridge — PASS;
3. accepted rows use current translated text and authoritative locale/version — PASS;
4. repeated bridge generation is deterministic — PASS;
5. current text/hash inconsistency fails closed and production readiness is recalculated from current state — PASS;
6. semanticRoundTrip=pass — PASS;
7. acceptedTextMatch=pass — PASS;
8. uidSetIntegrity=pass — PASS;
9. untouchedRecordIntegrity=pass — PASS;
10. install dry-run passes without modifying the game — PASS.

---

## Acceptance question / 驗收問題

Can BG3Loc take exactly the translations that 01E says are ready, convert them into the existing validated rebuild format, rebuild the target language safely, and prove that no unresolved translation or untouched baseline content was changed?

BG3Loc 能不能只拿 01E 明確認定可合併的譯文，轉成既有 rebuild 能安全使用的格式，重建目標語言檔，並證明沒有未完成譯文混入、也沒有誤改未碰的原始內容？

The answer is **yes**.

The bridge boundary, provenance bindings, real LOCA rebuild, real PAK repack, semantic safety checks, deterministic exports, install dry-run, and full regression have all passed.

~~~text
LSTP-01F Final Merge Bridge and Rebuild = ACCEPTED
~~~