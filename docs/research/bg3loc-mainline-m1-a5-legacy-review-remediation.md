# BG3Loc Mainline M1-A5 — Legacy Review Integrity Remediation

日期：2026-10-11。M1-A5 Design 與 Legacy material dependency 已由使用者核准。僅 A5；未更動 A7、B1-03 policy/activation、frozen contracts 或版本化 identity。

## 結論

Legacy 1.0/1.1/1.2 decision 現在必須綁定 actual UTF-8 bytes、current declared hash、可信 prepared source、canonical QA input 與 writer transaction 的 current evidence。原八項 RED 已納入正式回歸並變成正確拒絕。

matching SHA 但 QA 屬於別份內容，不再取得 current acceptance／checked cache／MERGE_READY。Legacy REVISE 不自動persist新QA；變更輸出後仍須 rerun QA。A5建議經Implementation Review後結案；唯一HTTP demo環境失敗單列，不宣稱full suite零失敗。

## Before / After

正式 `tests/test_legacy_review_integrity.py` 最初八項於原code全部 FAIL（1.40 s），對應 design 的六項 stale bytes＋兩項 matching declared SHA/wrong QA evidence；`workspace/mainline-m1-a5-remediation/red.txt`／`red.xml`。目前這八項正確拒絕且SQLite全tables/sequence保持不變。

Design additional rebound-QA case：missing `{TARGET}` 的 actual text、正確 declared SHA、錯綁old source-copy QA原可 offline finalize PASS。新regression證明：QA STALE、acceptance None、completion BLOCKED、bridge無該UID accepted row、finalize拒絕，且`run_workspace_qa`不再跳過；重評 actual candidate 後為 RETRY。

## 修改位置

| 檔案／function | 實作 |
| --- | --- |
| `src/bg3loc/legacy_qa_material.py::LegacyQaMaterial` | 單次operation的source/material snapshot；自動解析manifest已記錄plan或唯一低階plan；strict rows/unique IDs/batch/category/count；current immutable input inventory；Windows deny-write/delete pins與其他平台重新hash；無跨operation全域cache。 |
| `LegacyQaSource.input`／`LegacyQaMaterial.current` | 使用既有`QaInput`、`qa_input_hash`、`extract_protected_tokens`；actual UTF-8 SHA一致後重算source/text/category/tokens/ruleset QA evidence。沒有新QA/input hash version或平行identity。 |
| `production_review.py::ProductionReviewStore.resolve` | 在BEGIN IMMEDIATE內reread bytes/hash/batch/input/QA，actual SHA檢查涵蓋Legacy；鎖內取得source snapshot/recomputeQA，最後commit前recheck；source pins保留到transaction完成。任何拒絕在decision/output/history寫入前。 |
| `production_review.py::get_current_acceptance` | 除existing metadata tuple，Legacy實際內容/source QA必須有效；不再沿用stale approval。 |
| `qa_state.py::get_result/list_by_route` | Legacy current內容、source、input binding不符→STALE；grouped reads在一致的SQLite read transaction中共用單次material snapshot。NULL/missing-binding column語意保留。 |
| `commands/translation_qa.py::run_qa` | 共用operation snapshot，避免每item重做whole workspace scan；stale evidence不能cache-skip。evaluator、routing、persist primitives不改。 |
| `production_completion.py::build_production_completion_view` | Legacy用同一次read transaction的state/QA/source snapshot重算evidence；無法驗證→QA stale/BLOCKED；不會產生假MERGE_READY。 |
| `production_qa_orchestration.py::_read_counts` | report的checked/stale counts使用同一content/source gate，不再只相信declared hashes。 |
| `final_merge_bridge.py::build_final_merge_bridge` | 原actual SHA gate保留；corrupt succeeded state即使已被completion排除，也明確拒絕bridge，避免成功空集合掩蓋corrupt bytes。沒有實作A7 writer barrier/portability。 |

`qa_state.record_result`的既有raw persist API沒有新增平行evaluator；若caller提供錯綁evidence，資料可保存為history/current record，但必須被read/cache/completion判為stale，不能批准或finalize。

## Material trust / Availability

- 正常Production Workspace：manifest指向的plan/database必須吻合；沿用`verify_production_workspace`的plan/ruleset/material/immutable inventory與1.2 HSE summary/context contract checks。source需要的files在operation期間固定，manifest malformed/downgrade/path misuse不會fallback。
- 既有低階caller：明確指定plan或唯一`batches/batch-plan.json`、`plan/batch-plan.json`、`batch-plan.json`。必須有完整source rows、唯一UID、正確category/batch/count且對應execution inventory。source與actual text還必須吻合existing QA canonical hash；無material不會被視為可審查。宣告context contract的DB缺manifest拒絕；HSE DTO仍沿用既有strict decoder。
- 缺失、歧義、duplicate JSON fields/UIDs、malformed rows、source/category變更、closed/foreign snapshot、link/reparse與檔案變動皆fail closed。正常source不做strip/normalize或infer/backfill。
- Windows使用已有`source_packages._ReadPins` deny-write/delete primitives；非Windows固定immutable source strings並重新驗證path identities/bytes。operation snapshot不新增persisted fingerprints或schema。

## Compatibility

| 項目 | 結果 |
| --- | --- |
| H0/HSE prompt/render/hash versions | 原functions／contracts未修改；既有golden input/effective/actual-chat parity驗證 |
| optional expected tuple | 無tuple正常接受；完整current tuple正常；stale/incomplete拒絕；未引入1.3 mandatory tokens |
| REVISE | before-write technical FAIL/RETRY仍拒絕；合法revision寫text/hash與history，舊QA不rewrite；新hash後STALE → rerun QA |
| historical NULL/DDL | missing input-binding columns additive/idempotent初始化；舊QA NULL保持NULL，不用current值補回；valid H0 approval可讀；HSE既有required binding規則不放寬 |
| existing valid translations/history | 不做migration/backfill/重新翻譯/rehash；existing合法bytes與matchingQA仍有效；拒絕時database dump不變 |
| B1-03 | modern material/semantic REVIEW/revised-QA branch保留；不套用HD policy到Legacy；transport guards保持封鎖 |
| schema/API | 無public schema/version/identity變更；source-material availability hardening依本次核准決策；internal optional read-snapshot參數不用於新parallel identity |

## Tests

48項新增cases涵蓋：

- 原六stale-base probes、兩matching-SHA/wrong-base-QA probes。
- absent/current/stale expected tuple × ACCEPT/REVISE。
- missing/ambiguous/changed/duplicate/wrong-category/malformed material × ACCEPT/REVISE。
- preflight後commit的bytes/source/QA/input變更 × ACCEPT/REVISE；rejection無API data/history變更。
- WAL/DELETE competing writer × ACCEPT/REVISE；review validation期間writer正確被SQLite阻擋。
- late REVISE decision INSERT ABORT全tables rollback；historical missing columns／NULL；closed snapshot不可重用。
- sealed 1.0/1.1 H0、1.2 HSE × ACCEPT/REVISE：stale state拒絕，正常流程與offline finalize可通過。
- rebound-QA missing-runtime-token：cache/acceptance/completion/bridge/finalize gates全部驗證；QA rerun變RETRY。

四個既有test fixtures的fake output hash改為actual SHA；QA-state fixture補可信source material，保持原routing/persistence/CLI/completion意義。沒有skip/xfail或降低negative assertions。初次fixture-root setup錯誤已修正，原logs保留不列PASS。

| 執行 | 結果 |
| --- | --- |
| 八RED修正前 | 8 FAIL，預期重現 |
| 48新增cases | **48 PASS**，11.85 s |
| Existing core correctness | **97 PASS、16 subtests**，13.56 s |
| Final targeted | **317 passed、16 subtests**，382.89 s；`targeted.xml`／`targeted.txt` |
| Full latest current-tree | **1498 passed、1 skipped、1 failed、1 warning**，509.85 s；exit 1。唯一failure為HTTP demo；existing native symlink permission SKIP；warning為A8故意duplicate ZIP entry fixture。 |
| HTTP demo | 最新full唯一failure為WinError10013，三筆安全diagnostics（retryable/retryable/final）；ENVIRONMENT-BLOCKED，不算PASS。 |

全Suite未exclude HTTP demo。所有Provider transport為mocked/fictional loopback；沒有paid Provider、真實遊戲修改或B1-03 activation。本次synthetic decision是工程state驗證，並非人工語意品質評估。

## Performance / scope

QA batch/read/report會共用per-operation material snapshot，沒有每個item的完整manifest/material掃描。source驗證增加immutable inventory與必要bytes檢查；沒有為效能削弱fingerprints，也沒有擴成Stage5 R2/R3/R4或A7。snapshot每次operation重新建立，resume/retry不信任舊全域cache。

## Git

開始HEAD `896b4870b3a24d8506e6d751db3d4602925fb8fb`，branch `feat/b1-03-dialogue-context`；35 modified／52 untracked；396個原有nonignored files保存SHA256。最終**40 modified／55 untracked**（含所有先前dirty work）；HEAD/branch不變。10個原有檔案必要變動，**386／396原檔byte-identical**，frozen specs/identity/prompts/transport guards均保留。新增helper/test/report三檔；`scope-audit.json`／`git-status-final.txt`有完整清單。

所有prior dirty work保留。不commit/push/merge；frozen spec與proprietary material未改。只新增Legacy source helper、正式synthetic tests及本報告，必要production檔與valid test fixtures作最小修正。

完成狀態：**BG3Loc MAINLINE M1-A5 — READY FOR IMPLEMENTATION REVIEW**。

證據：`workspace/mainline-m1-a5-remediation/{red.xml,new-final.xml,targeted.xml,full-current.xml,http-classification.json,scope-audit.json,*-task.diff}`。`git diff --check` PASS。第一輪full為1498 passed／1 skipped／1 environment-blocked failure（512.65 s）；最後增加report count gate後重新full驗證，以full-current結果為準。
