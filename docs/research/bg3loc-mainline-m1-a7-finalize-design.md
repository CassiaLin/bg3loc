# BG3Loc Mainline M1-A7 — Legacy Finalize Readiness Design

日期：2026-10-11。狀態：**DESIGN READY FOR REVIEW**。本次為設計審查，沒有修改 production code、正式 tests、schema、Prompt、identity 或 transport guards。

## 1. 結論與範圍

**VERIFIED：Legacy 1.1／1.2 目前不能宣稱為可攜、併行安全的 Finalize。** A5 能拒絕在其讀取／決策 transaction 中已經 stale 的內容與 QA evidence，但 Finalize 在多個分離讀取之間及發布前仍存在競爭窗口。WAL 中已提交的寫入可能完全不改變主 SQLite 檔案 SHA。A8 的完整 entry SHA 與 atomic PAK replacement 保護單一 PAK，沒有把 completion、bridge、LOCA、manifest 變成同一個原子工作階段。

**PROPOSED：Windows Basic MVP 採方案 A 的限制範圍，加上可強制執行的最小完整性修正；不必先建置方案 B 的完整 Legacy portable bundle。** 只寫「停止所有 writers」的操作說明，不能當成此次可重現併行缺陷的修復。限制版仍需要 SQLite writer 排他保護、工作階段內 material／baseline 保護、完整輸出發布及失敗復原。以下均待獨立實作授權，不是已完成修正。

Prepared Workspace 本身在同磁碟與 D:→C: 搬移測試均成功，前提是原始 Extract 保留在原路徑。原始 Extract 消失會明確拒絕，沒有靜默 fallback 成功。這是可重現的功能限制，不是 fail-open。

## 2. 實際程式路徑與邊界

下表位置以本次 working tree 為準，不能視為 HEAD 已提交內容。

| 入口／function | 實際工作及已存在保護 | 仍缺少的邊界 |
| --- | --- | --- |
| [commands/production.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/production.py:360), `run_production_finalize` | CLI `production finalize` → `ProductionFinalizeRequest`；成功後印出結果 | CLI 沒有停止 Worker／QA／Review 的共同鎖 |
| [production_finalize.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_finalize.py:187), `finalize_production_workspace` | verify → completion → resolve extract → 主 DB SHA → bridge → rebuild → artifact SHA／bridge handoff → 主 DB SHA → final manifest rename | 沒有全程 writer barrier／一致 SQLite snapshot；實際輸出先建立，最後只原子發布 final manifest |
| [production_finalize.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_finalize.py:55), `_resolve_recorded_extract` | 要求原始 absolute Extract manifest 存在且 SHA 與 prepared 記錄一致；relative reference 拒絕 | 只核對 manifest bytes，沒有封閉其指向的 XML／normalized／PAK 全部內容 |
| [production_workspace.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_workspace.py:124), `verify_production_workspace` | prepared plan、materials、ruleset、inventory、1.2 HSE contract／input identity 等驗證；1.3 production stop guard 保留 | Legacy 驗證不封存 external finalize assets；`inputs.source.sha256` 並未在此自動驗證外部 normalized source |
| [production_orchestration.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_orchestration.py:93), `prepare_production_workspace` | source 必須對應 Extract reference；copy ruleset／生成 prepared material；記錄 absolute extract/source 及其 SHA | 未複製完整 rebuild baseline 與 PAK entries；記錄 source SHA 不等於 finalize 必定使用該來源 bytes |
| [production_completion.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_completion.py:249), `build_production_completion_view` | 自有 `BEGIN` read transaction；A5 的 `LegacyQaMaterial` 驗 current output／canonical QA input／material；current acceptance 才能 MERGE_READY | read connection 與 source pins 在回傳前結束；回傳的 completion 不是之後 bridge／rebuild 的全程 snapshot |
| [final_merge_bridge.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/final_merge_bridge.py:89), `build_final_merge_bridge` | 重做 completion；normalized source／target 決定 UID version；另一個 connection 讀取 state；actual text SHA 必須等於 declared output SHA；bridge handoff SHA | completion 與後續 state query 不在同一 snapshot；新 state 即使 SHA 正確，也不保證其 QA／Review 是剛才認證的那份 |
| [production_review.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_review.py:76), `ProductionReviewStore.resolve` | `BEGIN IMMEDIATE` 下 actual bytes、current tuple、可信 source 重算 QA hash；REVISE technical QA；失敗 rollback；Legacy REVISE 仍待 QA rerun | 僅保護此 decision transaction；Finalize 不持有排他鎖，因此合法 REVISE 可在 rebuild 中提交 |
| [legacy_qa_material.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/legacy_qa_material.py:46), `LegacyQaMaterial` | immutable source projection／existing canonical QA hash；prepared relative material；Windows `_ReadPins` deny-write/delete；close 後拒絕使用 | 未涵蓋外部 Extract 的 normalized、XML、LOCA／PAK，亦不跨 Finalize 各步驟持續存活 |
| [rebuilder.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/rebuilder.py:43), `run_rebuild`／`merge_records`／`validate_rebuilt_records` | target baseline XML + source normalized + accepted；保留讀取到的 untouched／target-only／blank；UID/version/text roundtrip | semantic PASS 是相對於此刻讀取的 baseline，並非自動證明 baseline 與 prepare 時一致；LOCA 寫到 visible output |
| [rebuilder.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/rebuilder.py:344), `repack_target_package` | A8 private input copy、完整 entry set、每個 untouched SHA、replacement bytes／語意、最後 input check、same-volume candidate replace | 不認證 QA／Review；不封存整個 Finalize output；不建立 prepare 時 baseline attestation |

**VERIFIED：Windows Basic 高階流程是另一條入口。** [e2e/rebuild.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/rebuild.py:19) `run_workflow_rebuild` 經 workflow validate／accepted SHA、state binding 呼叫共同 `run_rebuild`，不是 `production_finalize`；[e2e/install.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/install.py:19) `run_workflow_install` 再確認 rebuild manifest binding。Basic file-based workflow 不使用 Production SQLite decision tables，因此不應宣稱它已重現同一個 SQLite race，也不應把修復 Production race 擴大成 Basic 自動採用 1.3 D7。

共同 rebuild／external assets／artifact publication 的限制仍適用。A7 的 SQLite 修正目標是 `production finalize`；Basic 說明必須分清兩條操作路徑。

## 3. 隔離重現與負向 probes

所有 source、translation、Review decision、baseline 均為 **synthetic**。使用本機現有 test helpers；1.2 由真正 `prepare_production_workspace` 產生 HSE workspace。LOCA backend 使用 XML-copy fake，沒有呼叫 Provider、LSLib 或真實遊戲。持有長開 WAL connection、停用 auto-checkpoint，commit 在另一个 thread 完成。hook 只安排確定性的 interleaving，實際 production completion／review／bridge／rebuild 程式照常執行。

| Probe | 實際結果 | 分類 |
| --- | --- | --- |
| 1.1 正常完成 | MERGE_READY → final status pass | 已有正常行為 |
| 1.1／1.2 同 D: 搬移 prepared | 原 Extract 留在原處；成功 | 搬移支援，有條件 |
| 1.1／1.2 prepared 從 D: 搬到 C: | 原 D: Extract 保留；成功 | 跨磁碟實測，有條件；不是 self-contained |
| 1.1／1.2 Extract directory 改名 | A5 completion 仍全部 MERGE_READY；Finalize `recorded extract manifest not found`；output 未建立 | 正確 fail closed，限制需公開 |
| 1.1 baseline XML 改動、manifest unchanged | Finalize PASS，未修改的 baseline-only 記錄採用被改的新文字 | **缺陷：prepare→baseline binding 未閉合** |
| 1.1 source-only normalized version 1→99、manifest unchanged | Finalize PASS，新增 UID version 99 | **缺陷：外部 version authority 可改** |
| 真正 prepare 的 1.2 外部 XML／source normalized 改動 | Finalize 仍 PASS，即使 source normalized SHA 已與 `inputs.source` 不同 | **同一驗證缺口**；該 fixture 全部 target UID 存在，不宣稱 source-only version 99 被寫入此 1.2 artifact |
| WAL：bridge completion 回傳後，另一 thread 更新 translation + 正確 declared SHA | Finalize PASS，發布沒有 current QA 的新文字；其後 completion BLOCKED；主 DB SHA 不變 | **缺陷：stale completion + 分離 state query + WAL hash blind spot** |
| DELETE：相同 translation interleaving | bridge snapshot mismatch，拒絕；partial bridge 留下 | 主檔 SHA 的有限防護有效 |
| WAL：rebuild 後 QA route 改為 RETRY | Finalize PASS；其後 WAITING_RETRY；主 DB SHA 不變 | **缺陷：發布未綁定 current QA**；此 probe 是 raw SQL evidence mutation |
| DELETE：相同 QA mutation | `production execution database changed during finalize`；拒絕，但 artifact 已存在 | 有限防護，沒有 output rollback |
| 1.1／1.2 WAL：真正 Review API 在 rebuild 後執行合法 REVISE | Review transaction 正常提交；Finalize 仍 PASS，輸出舊 accepted bytes；其後 completion BLOCKED，等待新版 QA；主 DB SHA 不變 | **缺陷：不是只靠非法 raw SQL 才能觸發** |
| DELETE：最後 DB SHA check 後、final manifest rename 前更新 state | Finalize PASS；其後 BLOCKED | **缺陷：即使 DELETE 也有最後檢查到發布的 TOCTOU** |
| bridge 完成／A5 pins 已 close 後，rebuild 結束前改 prepared source material | Finalize PASS；其後 completion BLOCKED | **缺陷：operation-scoped A5 snapshot 未涵蓋全程** |
| backend 在 LOCA 已寫入後失敗 | 沒有 final success manifest；partial bridge／LOCA 留下；同 output retry 被 fresh-directory guard 拒絕 | fail closed manifest，但需明確 staging／recovery |
| final manifest rename 前注入 KeyboardInterrupt | artifacts、rebuild manifest、`.json.tmp` 可見；沒有 final success manifest | 原子 final-manifest marker 有效；整目錄不原子 |

最後一項為 Python 邊界中斷注入，**未實測 OS kill、斷電或 filesystem durability**。WAL probes 的長開 connection 是合法 SQLite lifecycle，不以正常「最後一個 connection 關閉就 checkpoint」推定安全。

Local-only 腳本：[test_a7_probes.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/workspace/mainline-m1-a7/test_a7_probes.py)。輸出：[probe-evidence.json](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/workspace/mainline-m1-a7/probe-evidence.json)、`probes.xml`、`probes.txt`。

**21 probes assertions 通過只代表上述行為可重現；其中 10 個負向 probe 實際為 UNEXPECTED ACCEPT，不是 10 個安全 gate PASS。** 尚未把已知失敗行為改成正式 CI 的 acceptance tests。實作階段應將這些 probes 轉成「必須拒絕、或 writer 在受保護區間不能提交」的正式回歸。

## 4. A5／A8 能保護及不能保護的範圍

**A5 — VERIFIED**：actual UTF-8 SHA、source-bound canonical QA、input binding、current acceptance、REVISE QA rerun、SQL rollback／歷史 NULL 語意保持。預先 stale 的譯文／QA 不會直接取得 MERGE_READY；直接 bridge 也拒絕 succeeded actual bytes 與 declared SHA 不一致。Prepared source／ruleset／HSE summary／batch materials 使用 workspace-relative paths，搬移成功證明 A5 沒有重新要求原始 Extract 才能判定 QA。

**A5 限制 — VERIFIED**：read transaction 和 pins 在 completion 回傳前關閉。較早的正確 MERGE_READY，不能認證之後另一 query／rebuild／發布時的內容。Prepared source snapshot 並不包含 target baseline XML、full UID-version indexes、original PAK entries。Finalization 的 external dependency 不是 A5 新引入，而是原流程未閉合的既有依賴。

**A8 — VERIFIED**：原 PAK 全 inventory + per-entry SHA，缺少／額外／duplicate／collision／corruption／錯誤 LOCA 拒絕；candidate 在目的地 filesystem 驗證後原子替換；既有 destination 在失敗時保留。A8 相關 37 regression tests 本次重新執行。

**A8 限制 — VERIFIED**：以 repack 當下捕獲的 package 為基準；不證明該 package 就是 prepared 時的來源。A8 不參與 SQLite read／writer transaction，也不保護提前寫出的 LOCA 或 bridge。LOCA-only 根本不走 PAK candidate gate。故不能只靠 A8 解決 A7。

[installer.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/installer.py:36) `run_install` 另有 scan baseline SHA、artifact SHA、備份 SHA、temporary write／replace、post-install check 與 rollback；這是安裝階段保護，不會自動重新驗證人工決策或補上 Finalize snapshot。低階 installer 接受 rebuild manifest，未要求 production-final-manifest。因此失敗後留下的 rebuild manifest／artifact 不能只靠「沒有 final success marker」就防止被人工誤用。

## 5. 方案 A：Windows Basic 最小限制版

**PROPOSED，未實作。** 使用單一 Windows 操作者、保留原始 Extract／baseline 路徑、不承諾 detached portable workspace；禁止 finalize 時 Worker／QA／Review／其他 finalize 寫入。此限制包含後續自動工具，不能只要求使用者關閉可见視窗。

最小必要工程保護：

1. **Writer quiescence 可強制檢查。** 原 DB 上取得 `BEGIN IMMEDIATE` reservation，持有至最終發布；遇 busy 明確拒絕或有限等待，提示停止 writers。對 WAL／DELETE 均測試另一 connection 的 QA、Review、Worker commit 不能穿過。不是改成 DELETE journal 或只 checkpoint。
2. **同一工作階段資料。** 在 barrier 已取得後用 SQLite consistent backup 捕獲 committed DB（包含 WAL）；completion、bridge state 與 QA／Review 必須用此一致資料，不再讀互不相干的 live snapshots。原 DB barrier 必須持續到成功／失敗結束。A5 material verifier 可沿用，但要支援檢查 snapshot 所屬的原 workspace，不可將 copied DB 隨意假装成另一個 prepared workspace。不要在持有 write transaction 的同一 connection 上盲目呼叫 backup，需測試 barrier connection + separate committed reader 的正確設計，避免 backup 忙等。
3. **全程 source／asset 保護。** 從 verify 前至發布持有原 prepared files、Extract manifest、必要 normalized indexes、XML／LOCA／target PAK 的 Windows read pins；讀取均從已核對的 immutable capture，不讓 backend 重新開未保護路徑。用既有 material／ruleset／source SHA；完整 target baseline 保護不能只算 finalize-start SHA 就宣稱 prepare 時已認證。
4. **保留可信 baseline／backup。** 保留原 scan、Extract、原 target package／LOCA／XML、normalized source／target、prepared files，以及包含 WAL committed data 的 SQLite backup；記錄每份備份 size／SHA、對應 locale／version 與時間。須有可驗證的歷史依據，不能把已被改動的 baseline 重新算 SHA 後稱為原備份。缺少初始 target baseline hashes 的舊 workspace，需用已可信的原始 package／先前備份重做 LOCA／XML／normalized 語意一致性驗證；缺失或歧義就拒絕並 fresh scan/extract/prepare，不自動「補 seal」使其可信。
5. **完整輸出 staging。** 在目的地同 filesystem 的私有 operation directory 產生 bridge／LOCA／PAK／manifests；完成全部 gate 才發布最終目录，destination 必須全新且不在遊戲安裝路徑；PAK 保留 A8。現有 manifests 有 absolute child references，不能只 rename staging folder：需以現有可接受的 relative references 或最終目的地 references 寫出並重算 handoff SHA，發布後驗證 references 全部可解；不得更改 hash 演算法。
6. **恢復與拒絕誤用。** failure 清除只屬於此次 operation 的 staging，或隔離為明確 failed／non-installable；原 DB／原 Extract／原 output 不修改。中斷遺留的 staging 不可當成功；重試採 fresh operation ID。驗證備份與 restore 步驟，在 rollback 前確認沒有 writers 且身份相符，不自行還原較新的合法決策。限制版可要求手動重試，不要求自動 resume finalize。

**相容性**：H0／HSE prompt、input hash、QA hash、NULL 意義與 Review 政策不變。檔案缺失／變動拒絕更嚴格，busy 時可能拒絕而不是繼續，發布時可见性改變；應公開這些操作層行為。Legacy manifest 1.1／1.2 與 B1-03 D7 不改版、不互套。若要新增正式、必需的 baseline receipt／bundle sidecar 或改变 `executionDatabaseSha256` 的對外含義，**須先做相容性／Contract Change Review**；不能以「sidecar 不在 manifest」規避契約審查。原 main-file SHA 可保留原語義，不能把它替換成 backup SHA 後沿用名稱。

**成本：中等，未知工時。** 需 legacy-specific session wiring、barrier／backup、input pins、publication reference correctness、fault tests。整個 rebuild/repack 的 writer lock 可能很長；本階段沒有量測大量 Legacy 完成資料，不引用 1.3 的鎖定數字作 Legacy 性能證明。長 barrier 只適合明確停機操作，非持續多人審查服務。

## 6. 方案 B：Legacy 完整可攜／併行安全版

**PROPOSED，未實作；成本高於 A。** 為 Legacy 設計獨立的 self-contained baseline/material closure：source／target UID version indexes、target XML／LOCA、repack 必要原 package 或完整 entry payloads、locale/build/source binding、per-file size／SHA／semantic attestations、safe workspace-relative paths。不得稱為或直接套用 `production-finalize-assets/1`／Manifest 1.3。

需處理 fresh prepare atomic capture、disk／storage 成本、missing/tampered assets、links／junctions／collision、雙磁碟搬移、wheel／sdist public resources、migration 與 recovery。Prepared workspace 拿掉原 Extract／遊戲原 package 後仍應 offline finalize。新的 Legacy bundle 正式格式及舊資料 migration 政策，應獨立 Contract Change Review。

SQLite／發布至少保留方案 A 的一致 snapshot 與 barrier，不能因 self-contained 而解除 DB gate。若希望 rebuild 時 writers 可繼續，可研究短 barrier 捕獲 snapshot → 長時間 rebuild → 最終短 barrier 重新核對完整 relevant inventory/input/output/QA/Review/material → 發布；任何 relevant mutation 應拒絕／重試。需要可靠 committed-generation／無 ABA 的變更證據，與最後一次檢查到發布的同一 barrier；不是比較主檔 SHA，也不是借用未驗證的 mutable global cache。此 concurrent variant 的工程／測試成本明顯更高，非本次推薦 MVP 範圍。

| 面向 | A：限制版 + 最小強制保護 | B：完整 portable/concurrent 版 |
| --- | --- | --- |
| 原 Extract 依賴 | 原路徑保留，缺失拒絕 | 完整 bundle，不依賴外部 Extract |
| Prepared 搬移 | relative prepared files 可搬；external original paths 不變 | 原 Extract 消失、跨磁碟仍可完成 |
| Writers | 明確停機，SQL barrier 阻止提交直到發布 | 基本版同 A；持續 writers 需新增短 snapshot／reconciliation 協議 |
| Baseline 信任 | 既有可信備份／package + 新操作 capture；不悄悄認證無來源舊資產 | prepare-time closure，正式 attestation 與 migration |
| 故障復原 | 私有 staging、驗證備份、fresh retry | 可設 operation journal／更完整 replay，但仍需驗證與明確 status |
| 相容性成本 | 有限 call-path 變更；保持 schemas/hash；receipt 若正式化另審 | 新 Legacy bundle contract／storage／migration；仍不得修改 H0/HSE identity |
| MVP 適用 | 單人 Windows、停機 finalize、原素材保留 | 離線交付給另一台電腦、detached assets、多人持續 writes |

## 7. MVP 決策與建議最小實作

**Windows Basic MVP 不必完整方案 B。** Basic workflow 是檔案 validate→共同 rebuild→install，並未承諾可移除 Extract 或由多個 SQLite writers 併行 finalize。應明示原 Extract／baseline／scan 保留、更新遊戲後 fresh scan/extract、在未完成／failed operation 上不得安裝。保留 A8 全 entry SHA 與 installer backups。

**Production Legacy finalize 若列入公開 MVP，則必須處理已重現的安全缺口。** 推薦先實作方案 A 的完整性核心：writer barrier／consistent read、跨全程 source/asset pins、baseline 信任驗證、staged publication／recovery。不能以「Basic 是單人」把 `production finalize` 的 WAL race 算作已關閉；也不能只增加警告而宣稱 A7 修復。

建議獨立授權順序：

1. A7-I1：Legacy session／SQLite barrier，completion 與 bridge 使用同一一致資料；10 个 UNEXPECTED ACCEPT probes 改為拒絕／寫入阻擋；Review／QA 行為保持。
2. A7-I2：外部 source/version/baseline 信任及全程 capture；明確缺少歷史 attestation 的限制／fresh-prepare 路徑；如需新 receipt 契約先審查。
3. A7-I3：整個 output staged publication、manifest reference 驗證、失敗隔離／重試／備份恢复；保留 A8。
4. 驗收 Windows restricted flow，量測真實 Legacy workload 的 barrier／backup／rebuild/repack 開銷，再决定是否另開 B。

必要正式回歸：1.1 H0／1.2 HSE normal flow、same/cross-volume relocation（retain extract／detach 分開）、missing／wrong baseline、raw state mutation+matching hash、QA evidence mutation、真實 ACCEPT/REVISE/QA/Worker interleaving、WAL／DELETE readers/writers、checkpoint、最後 gate-to-publish mutation、prepared asset replace／close 後 mutation、batch/source completeness、late SQL/file failure、LOCA/repack failure、final rename failure、process kill/restart/staging recovery、no installable partial result、original output/DB/extract SHA 不變、H0/HSE byte parity與 B1-03 OFF guards。

## 8. 測試、證據限制及 Git

| 本次新執行 | 結果／範圍 |
| --- | --- |
| Local-only A7 behavior probes | **21 passed，11.41 秒**；10 個缺陷接受案例被重現，並未修復 |
| Targeted existing regression | **256 passed、20 subtests passed，28.29 秒**；1 warning 是故意 duplicate ZIP entry fixture |
| Regression modules | production finalize／bridge／completion／review、A5 legacy review、A8 legacy PAK、rebuild／install、context execution identity、same-entity prompt integration、dialogue Stage 2、E2E workflow |
| H0/HSE／B1-03 | golden hash／prompt/message parity、identity、immutable material、Stage 2 version/transport guards 回歸包含於上述；程式 bytes 未變 |
| 全套 suite／HTTP demo | 本次 design-only 未重跑全套或 HTTP demo。前次 A5 full available 為 1498 passed、1 skipped、1 failed（HTTP WinError 10013）；這是歷史證據，不是本次 full PASS。HTTP demo 繼續 **environment-blocked**，沒有轉成 PASS／永久排除 |
| 真實 Legacy 大量 reviewed workload／性能 | **UNKNOWN**；沒用 proprietary translations，也沒量測完整大量 writers／lock duration |
| Native LSLib／OS 中斷／非 Windows | 本次 **NOT VERIFIED**；不以 fake XML backend、thread hooks 或 KeyboardInterrupt 當 native／斷電／Linux/macOS 驗收 |

可重現命令（repository root、既有本機 venv）：

```powershell
$env:TEMP=(Resolve-Path workspace/a7tmp).Path
$env:TMP=$env:TEMP
$env:PYTHONPATH=(Resolve-Path src).Path
workspace/a34venv/Scripts/python.exe -X utf8 -m pytest workspace/mainline-m1-a7/test_a7_probes.py -q -p no:cacheprovider --basetemp=workspace/a7pt-fresh
```

跨 C:／D: probe 的 C: test directory 位於本次已授權 writable root，僅含 synthetic fixture，結束已清除。不同環境重播應將其改成該環境自己的隔離 writable 第二磁碟；不得改為移動真實 workspace。

起始／結束 HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`，branch `feat/b1-03-dialogue-context`。起始 **40 modified／55 untracked Git status entries**。本次新增這份公開報告，結束 **40 modified／56 untracked entries**；既有 399 個 nonignored public files 的逐檔 SHA 均保持一致。全部既有 dirty work 保留，沒有 staging／commit／push／merge。

起始 seals、Git status、probe logs/JUnit、regression logs/JUnit 與結束核對保持 local-only：`workspace/mainline-m1-a7/`。Production／schema／既有 tests 修改數：**0**；Provider calls：**0**；真實遊戲修改：**0**。沒有 A7 implementation，也未核准 B1-03／Production Activation。

**BG3Loc MAINLINE M1-A7 — DESIGN READY FOR REVIEW**
