# BG3Loc Mainline M1-A5 — Legacy Review Decision Integrity Design

日期：2026-10-11。**本階段為缺陷分析／設計／獨立回歸準備，未修正 production。** Legacy 1.0–1.2、S5-R1 1.3 與 accepted legacy contracts 均依現有程式查核；不修改 frozen contracts，不啟用 transport。

## 結論

**VERIFIED：A5 仍存在。** 六個原始 negative probes 全部未拒絕 stale actual bytes；完整 sealed 1.0/1.1 H0 與 1.2 HSE 亦重現。ACCEPT 可以形成錯誤的 current approval／MERGE_READY；REVISE 會對無效 base 產生 history 並覆寫譯文。

原始「只改 bytes、不更新 declared hash」案例的 bridge/finalize 仍會拒絕。**不能據此宣布整個流程安全**：additional rebound-QA API probe 在 actual SHA 已更新一致、QA evidence 卻屬於另一份內容時，Legacy ACCEPT、bridge 與離線 finalize 全部通過；current actual technical QA 原應 RETRY，輸出缺失必要 runtime token。

**PROPOSED：最小完整修正應包含 actual-base SHA、base QA input 重算、同一 writer transaction 的 current snapshot 核對，以及 acceptance/completion 的 current-content 防護。僅移除一個 `modern` 條件不夠。** 保留 legacy REVISE 後重新 QA、H0/HSE routing／prompt／identity、歷史 NULL 與所有既有 valid translation bytes。

**Contract Review：** 純 byte-integrity hardening 可視為恢復 accepted legacy semantics，無須變更 Stage 0／版本演算法。完整 QA-binding 若要求原先 ACCEPT 不必提供的 material／plan，屬 legacy API compatibility change，**需要 Legacy Contract/Compatibility Review 先核准 availability／failure 行為**。本階段沒有自行修改任何契約。

狀態：**BG3Loc MAINLINE M1-A5 — DESIGN READY FOR REVIEW**。

## 1. 權威與程式進入點

`docs/lstp/production-review-resolution.md` 已接受的語意是 ACCEPT「exact current candidate」，approval 綁定 ContentUid、QA ruleset、QA input hash、current output hash；REVISE 不得把 automatic REVIEW 改寫為假 PASS，改變 output 後需再 QA。

| 程式位置（本次查核） | 實際作用 |
| --- | --- |
| `src/bg3loc/production_review.py:76` `ProductionReviewStore.resolve` | 共用 legacy/1.3 決策 API；preflight、BEGIN IMMEDIATE、state/QA/decision 寫入。 |
| `production_review.py:151` | actual current_text SHA 驗證受 `modern` 限制。 |
| `production_review.py:163` | 1.3 locked expected tuple／material refresh／base qa_input_hash recomputation；Legacy 沒有相同段落。 |
| `production_review.py:183` | 所有 REVISE 均 evaluate replacement technical QA；FAIL/RETRY 拒絕。 |
| `production_review.py:232` | 只有 modern REVISE 同 transaction persist 新 QA；Legacy 保留舊 QA。 |
| `production_review.py:263` `get_current_acceptance` | 比 current metadata、QA/decision tuple／input binding；未讀 current_text 做 actual SHA。 |
| `src/bg3loc/qa_state.py:125` `record_result` | 驗證 current declared input/output／status，但沒有重算 result.qa_input_hash 是否真的屬於該份 actual text。 |
| `qa_state.py:340` `get_result` | QA stale 基於 declared output、ruleset、input binding；未檢查 actual bytes。 |
| `src/bg3loc/commands/translation_qa.py:110` `run_qa` | checked metadata 視為 cache current，跳過重新 evaluate。 |
| `commands/translation_qa.py:321` `run_review_resolve` | 直接呼叫 review store；Legacy expected tokens 可省略。 |
| `src/bg3loc/production_qa_orchestration.py:162` `resolve_workspace_review` | 先 verify workspace，再將 batch plan 傳給低階 resolver；不會補齊 mandatory 1.3 expected tuple。 |
| `src/bg3loc/production_completion.py:249` `build_production_completion_view` | Legacy approvals/QA metadata tuple 決定 ready；actual bytes check 在 validated 1.3 path（約399行）。 |
| `src/bg3loc/final_merge_bridge.py:89` `build_final_merge_bridge` | MERGE_READY 譯文再次 actual SHA check（約180行）；與 declared SHA 不符則拒絕。 |
| `src/bg3loc/production_finalize.py:187` `finalize_production_workspace` | Legacy preflight completion → bridge → rebuild → artifact hashes／DB seal；不重新 evaluate technical QA input。 |

## 2. 原始六案例 fresh reproduction

全部由當前 code 執行。資料為 invented source／translations、UID，沒有 corpus、hidden assignments 或 Provider calls。

| Legacy DB version label | 決策 | stale bytes 拒絕 | History | 後續 QA / completion |
| --- | --- | --- | --- | --- |
| 1.0 | ACCEPT | **NO** | 新增決策 | checked／MERGE_READY；current acceptance 存在 |
| 1.0 | REVISE | **NO** | 新增決策、overwrite current candidate | stale／BLOCKED（新 hash 不同） |
| 1.1 | ACCEPT | **NO** | 同上 | checked／MERGE_READY |
| 1.1 | REVISE | **NO** | 同上 | stale／BLOCKED |
| 1.2 | ACCEPT | **NO** | 同上 | checked／MERGE_READY |
| 1.2 | REVISE | **NO** | 同上 | stale／BLOCKED |

**範圍：** 這六項刻意重現 Readiness Audit 的 isolated API 範圍：使用 latest initialized physical tables，再標記 legacy metadata version。不是所有歷史 DDL 的完整重播，也不是用這個 raw 1.2 label 假稱 sealed HSE。歷史 missing-column/NULL 相容性由現有獨立回歸另驗證。

## 3. 完整 sealed workspace tracing

另外建立合法 synthetic manifest 1.0/1.1 H0（使用目前初始化的legacy DB tables），以及透過現有 prepare/material adapter 產生的完整 1.2 HSE。workspace verification、input inventory／HSE material contract 保持有效。全部決策還傳入匹配的 optional expected input/output/QA/ruleset tuple，避免把問題歸因為 caller 沒有提供 token。

| Workspace／family | ACCEPT 影響 | REVISE 影響 |
| --- | --- | --- |
| 1.0 H0 | bytes != declared SHA 仍接受；QA cache 不變；MERGE_READY | 非法 base 未拒絕；valid revised bytes 寫入；舊QA stale |
| 1.1 H0 | 同上 | 同上 |
| 1.2 HSE | 同上；完整 HSE seals 與 current input binding 未能發現 output byte gap | 同上；HSE identity 沒有被修改 |

ACCEPT 後三個 sealed cases 的 bridge 均拒絕 `MERGE_READY output hash mismatch`；finalize 同樣停在 bridge，沒有 final artifact manifest。

REVISE 的 new candidate 保護 tokens、actual SHA 正確；先為 BLOCKED，既有 QA rerun 評為 PASS 後 MERGE_READY，offline finalize 正常通過。**這不是 corrupt base 被部署**：它顯示非法 base decision/history 仍可留下，但新 revision 的 current technical QA 可以合法通過；不能把此結果寫成 stale approval 被沿用。

## 4. Additional rebound-QA evidence case

這與六個 unchanged-hash probes 的前提不同，必須分開記錄。

1. Synthetic sealed 1.1 H0：base source 含 `{TARGET}`，原 source-copy QA route REVIEW。
2. current candidate 改成沒有 `{TARGET}` 的 invented text，**declared SHA 也正確更新**。
3. raw `TranslationQaStore.record_result` 接受舊 base 的 QaResult，但以 live current output hash 保存；甚至 expected input/output tokens 都匹配目前 metadata。
4. `resolve_workspace_review`（公開 production wrapper）ACCEPT 通過；current approval／completion 依 metadata 有效。
5. bridge actual SHA 正確，未拒絕。Fake/offline rebuild 與 finalize 回報 pass，roundtrip 中的譯文確實缺 `{TARGET}`。
6. 對 actual source/text 直接 evaluate，technical route 為 **RETRY**。

**VERIFIED：可形成 technically invalid final target 的程式流程證據。** 使用 fake XML/LOCA backend；未執行 real provider、真實 installation、native game deployment。不能將這份 fake `.loca` 稱為已部署的真實遊戲語言檔。

**Implication：** byte SHA 解決「bytes 與宣告不一致」，但不能單獨證明 QA evaluated 那份 bytes。QA input canonical hash 必須用可信 source/current text/category/tokens/ruleset 重算。這恢復 evidence binding，不代替人工語意審查，也不代表防範任意有權重造全部 DB facts 的攻擊者。

## 5. 與 S5-R1 1.3 的差異

| 防護 | Legacy 1.0–1.2 現況 | S5-R1 1.3 | 移植評估 |
| --- | --- | --- | --- |
| BEGIN IMMEDIATE + reread succeeded/state/QA | 已有 | 已有 | 沿用，不另建 state machine |
| actual UTF-8 SHA == declared output | **缺少** | writer內必驗 | 可直接沿用；拒絕invalid bytes不改合法data |
| current input/QA/output/ruleset/REVIEW | 已有 metadata checks；legacy NULL 可讀 | mandatory full expected tuple與locked comparison | 沿用existing checks；不能把mandatory tuple直接套到Legacy |
| source/material refresh與base QA hash | **缺少** | validated_stage3_material + canonical QaInput hash | 重用QaInput/hash概念；不可使用1.3/D7 validator驗Legacy |
| revised technical QA | 已有；FAIL/RETRY拒絕 | 已有 | 不放寬 |
| 新 revised QA persistence | Legacy不persist；oldQA hash不同時stale | writer內persist新QA | **不可直接移植**，會改Legacy REVISE重跑QA行為 |
| HD semantic REVIEW／七條prompt／D7 | 不適用 | frozen mandatory protection | 不引入Legacy |
| Input NULL | optional legacy UNKNOWN | mandatory current binding | 不補值、不冒稱known；HSE required-binding rules不放寬 |

S5-R1 加的是 write-time checks。`get_current_acceptance` 本身仍是 metadata-based；1.3 completion 的 actual-byte gate不能被誤寫成所有 read APIs 都有 same-byte 防護。

## 6. 最小完整修正設計（PROPOSED，尚未授權實作）

### Writer transaction

在任何 output、QA、decision/history 寫入前，同一 `BEGIN IMMEDIATE` 中依序：

1. reread current state：succeeded、text 必須 str，exact UTF-8 SHA 必須等於 current declared hash；不 normalize/strip/修復文字。
2. 重新讀 current QA；檢查 current ruleset、declared output、QA input hash、current REVIEW route、既有 input binding。caller 提供的 expected tuple 必須維持有效；不能與 transaction前 cache 混用。
3. 取得本 target 的可信 legacy prepared source material（UID/batch/category/source），依1.0/1.1已有bindings／1.2完整HSE seals處理，拒 duplicate UID、malformed／ambiguous material。讀取／驗證與source snapshot的範圍須能偵測 preflight後變更；不可直接信任 mutable research dictionaries 或可變全域cache。
4. 用**同一版本的既有 `QaInput`／`qa_input_hash`**、actual base bytes、source/category、`extract_protected_tokens` 重算，必須等於stored current QA input hash。不加context欄位進QA hash；HSE context由原execution input identity綁定。
5. REVISE仍先跑existing technical QA，FAIL/RETRY拒絕；approved correction只寫既有text/output/hash/history欄位。Legacy不套用1.3 revised-QA自動persist／HD semantic routing。
6. 任一拒絕／late SQL error，output、QA/issues、decision、attempt/retry/history全部不變。既有 additive initializer migration與decision transaction要明確區分；回歸在預先initialize後比較所有tables/sequence，另測真實historicalDDL migrations。

### Read／completion 防護

- `get_current_acceptance` 至少不得把 actual byte mismatch 的歷史decision稱作current。
- `qa_state` checked/cache 與 completion不能只比較declared SHA。最小共用 current-content check 應讓byte mismatch為stale／BLOCKED，避免 `run_qa`跳過壞state、status仍MERGE_READY。
- 對 matching SHA 但QA綁錯content，prepared completion/acceptance必須重算 base QA hash；這也是保護尚未重新做decision的舊rows所需。是否在QA store保存入口加同樣check，屬同一evidence-binding防護的候選範圍，**需另行核准實作範圍**，不順手改QA evaluator／routing policy。
- 保留bridge actual SHA、既有finalize handoff/DB seal，不把A5擴成A7 whole-workspace portability／writer-barrier remediation。

### 保留資料／身分

不得改H0/HSE prompt bytes、renderer、input hash、effective prompt/message fingerprints、B1-02 context algorithm／版本。不得改UID/version/source/current合法translation bytes、覆寫歷史decision、重寫QA route成PASS、補historicalNULL或替corrupt hash silently rehash。

有效既有decisions若actual bytes／current QA source/identity均一致，應保持原效力。既有history能讀不代表已證明當時有actual-byte驗證；無法從hash逆推出已被overwrite的舊譯文。沒有證據時不能backfill「已驗證」標記；全量強制re-review或新增history schema是另一個需核准的contract/policy變更。

## 7. 相容性與 Contract Change Review

| 項目 | 評估／決策 |
| --- | --- |
| reject bytes!=declared SHA | **PROPOSED compatible hardening**：符合accepted「exact current candidate」，無schema/identity版本變動 |
| reuse currentQA/input/ruleset checks | Compatible；保留NULL required/optional policy |
| base QA hash重算 | Needed by追加probe；須可信source，不能只採current text SHA |
| Legacy ACCEPT原本不需material；missing plan如何處理 | **Legacy Contract/Compatibility Review REQUIRED**：建議有prepared material時驗證，缺／malformed時fail closed且不改data；必須核准此新availability要求與低階API caller遷移方式 |
| mandatory caller expected tuple | **單獨CCR**；會破壞省略flags的Legacy CLI/API，不納入預設最小修正 |
| caller未給expected tuple是否等於reviewer看到current版本 | **UNKNOWN**；current bytes/QA gate不能證明人工先前看到哪份文字。若要求此保證，需新的export→resolve snapshot契約／使用流程核准 |
| Legacy REVISE自動persist新QA | 會改accepted流程與現有tests；不採用 |
| 新schema columns／input hash版本／D7／HD routing | 不必要，且未授權；如implementation發現必要，先Stage0/相關CCR |

**建議核准一個完整writer＋prepared read/completion binding修正範圍**，先就「Legacy ACCEPT material dependency」完成相容性決策，再授權production implementation。不要只做byte guard後宣告A5全數結案。Stage0 frozen contracts本設計不需要變更。

## 8. 獨立回歸準備與驗收矩陣

已準備 local-only acceptance module：

`workspace/mainline-m1-a5/regression/test_legacy_decision_guards.py`

直接呼叫現有production API；沒有複製一份假修正版、沒有monkeypatch implementation、沒有xfail/skip。**目前8項全部RED**：原six actual-byte probes＋兩個matching-SHA/wrong-base-QA probes（ACCEPT/REVISE）。每項未來應拒絕，並比較SQLite全tables/history/sequence不變。它們未加入正式`tests/`或CI，使未授權設計不改正式pipeline。

後續實作必須補齊：

| 必要tests | 驗證 |
| --- | --- |
| 原6 + sealed1.0/1.1H0/1.2HSE × accept/revise | 全部拒絕stale actual bytes，無data/history mutation |
| matchingSHA但QA屬不同text/source/category/tokens/ruleset | base QA hash拒絕；rebound-QA final target不能通過 |
| 正常ACCEPT／REVISE、identity不變 | 正常合法輸出仍可決策；LegacyREVISE保留新hash後stale→rerun QA流程；修正後REVIEW仍需新matching approval |
| expected tuple無／完整／不完整／過期 | approved Legacy compatibility unchanged；不是偷偷採1.3 mandatory tokens |
| historicalDDL缺binding columns／NULL | additive migration可重複、UNKNOWN不補值；H0 optional NULL可讀，HSE required NULL拒絕 |
| preflight到writer間的bytes/hash/QA/input變更 | transaction reread拒絕；同時測WAL/DELETE competing writer |
| source material/manifest/plan變更、duplicateUID、missing／ambiguousplan | 根據核准availability policy拒絕，rollback不留決策 |
| REVISE runtime syntax failure／late SQL INSERT ABORT | technicalFAIL/RETRY拒絕；all tables rollback |
| historicalstaleapproval、get_current_acceptance/status/cache | 不再false current／MERGE_READY；no-source案例按CCR處理 |
| bridge/finalize正常、stale、wrong-QA | 原bytes gate保留；不要由bridge SHA正確推論QA evidence正確 |
| H0/HSE原hash/prompt/messages、B1-03OFF/guards | frozen byte parity；no provider transport，S5-R1六probe繼續PASS |

## 9. 本次執行結果／範圍

- Fresh characterization：原6 probes＋sealed6 traces＋additional rebound-QA probe完成；`findings.json`／`probes-final.txt`。
- Future acceptance tests：**8 failed（預期RED）**，1.50 s；`future-red.xml`／`future-red.txt`。不是production fix PASS。
- 既有相關regression：**111 passed、4 subtests passed**，227.73 s；production review/bridge/finalize、S5-R1、context execution identity與H0/HSEfrozen byte parity。
- 沒有重跑無程式修改的full suite；HTTP demo本階段未執行，不列PASS。既有WinError10013限制沒有被解除。
- 不執行paid Provider或real-game/native installation；所有history/QA決策為explicit synthetic工程fixture，非人工語意品質審查。

## 10. Git／後續

HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch：`feat/b1-03-dialogue-context`。開始35 modified／51 untracked；395個原有nonignored files保存SHA256。

本次只新增此research design文件與ignored workspace probes／regression／證據。所有production source、frozen contracts、正式tests、CI、A1/A6/A2/A3/A4/A8工作保持原樣。最終Git status：35 modified／52 untracked（先前dirty work保留）；**395／395原檔byte-identical**。`workspace/mainline-m1-a5/scope-audit.json`／`git-status-final.txt`保存證據。不commit/push/merge，不解除B1-03 transport。

下一步僅建議：審查本design與legacymaterial/expected-token相容性，核准後再啟動A5 implementation；本階段缺陷**未修正／未結案**。
