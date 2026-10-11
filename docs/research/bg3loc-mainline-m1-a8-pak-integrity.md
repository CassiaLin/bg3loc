# BG3Loc Mainline M1-A8 — Legacy PAK Integrity

日期：2026-10-11。僅修正 A8；Windows Basic／low-level legacy rebuild。所有測試資料為 synthetic，未修改真正 BG3 installation，未呼叫 Provider。A3 hosted CI 仍 PENDING，沒有擴大處理 A5/A7/B1-03。

## 結論

**A8 建議經 Implementation Review 後結案。** Legacy repack 現在以完整 original inventory 與逐一 entry SHA256 為基準，候選 PAK 重讀通過後才 atomic publish。Native LSLib 及 Basic workflow、備份／rollback 均通過。

狀態：**BG3Loc MAINLINE M1-A8 — READY FOR IMPLEMENTATION REVIEW**。

## Root cause／實際資料流

- Low-level CLI：`src/bg3loc/commands/rebuild.py::run` → `rebuilder.run_rebuild` → `repack_target_package` → `ArchiveBackend`（Windows `LSLibWindowsExeBackend` 的 list/extract/create/convert commands）。
- Basic：`src/bg3loc/e2e/rebuild.py::run_workflow_rebuild` 使用同一個 `run_rebuild`，container=`auto`。只有 rebuild 成功才記錄 completed stage／manifest binding；`e2e/install.py` 使用既有 installer preflight／backup／rollback。
- 舊 helper 只把 entry names 正規化、casefold 後放入 set；duplicate/case aliases 被消去。封裝後比較同樣的 set，並單獨讀目標 LOCA 比較 rebuilt artifact SHA。其餘 entries 的內容沒有 hashes。
- 舊 create-package 直接寫正式 destination，再驗證。即使 entry set 或 LOCA 檢查發現錯誤，損壞／partial PAK 已存在；先前有效 artifact 也可能已被覆寫。

## Before / After reproduction

`tests/test_legacy_pak_integrity.py` 使用 self-contained ZIP-backed synthetic PAK（不是 LSLib 或 BG3 資料）：目標 LOCA + binary、nested text、JSON metadata、empty file、另一個未替換 LOCA。

第一版 14 probes 在原實作：**13 failed、1 passed**（`workspace/mainline-m1-a8/before.txt`／`before.xml`）。這些是修正前的負向重現，不算測試通過。

| Probe | Before | After |
| --- | --- | --- |
| 五個未替換 payload 分別損壞 | 名稱不變即可被接受；nonempty 亦涵蓋同大小不同 bytes | SHA mismatch，無發布 |
| 重複／case aliases／case rename | set 會掩蓋部分衝突／變名 | 明確拒絕 |
| 缺少／額外／file-directory collision／錯誤 LOCA | 部分已有檢查，但在 destination 寫入之後；既有 bytes 不保留 | 檢查候選檔，既有 destination 保留 |
| create failure | partial candidate 直接覆寫 destination | partial 只留於待清理的 candidate temp，原 destination 保留 |
| 正常全 entry parity | PASS | PASS |

37 個新增 A8 cases 全部包含於 targeted/full 回歸，另外涵蓋 unsafe original names、semantic mismatch、source/replacement/candidate mutation、extraction/list disagreement、original single-read disagreement、publish failure、low-level failure 不發布 manifest／PAK。

## 修改位置／最小實作

| 檔案／function | 修改 |
| --- | --- |
| `src/bg3loc/rebuilder.py::repack_target_package` | private source PAK／replacement LOCA copies，各自 bind capture SHA；所有 SDK reads 使用 source snapshot。original inventory 完整保存於本次 run 記憶體，不加入新 manifest/schema。 |
| `repack_target_package` | 原始 full extraction hashes 與逐一 original entry reads 比對；封裝後重新 list + full extract；所有未替換 entries SHA 相同，含其他 LOCA、空檔與 binary。 |
| `repack_target_package` | 目標 LOCA bind capture SHA，並用既有 `parse_loca_xml`／`validate_rebuilt_records` 比 UID set/count/version/text。不是只相信 pre-pack roundtrip。 |
| `repack_target_package` | source／replacement／candidate／verified payload final recheck；candidate 位於 destination 同 filesystem 的 temp directory，所有 gates 通過後 `.replace(destination)`。source PAK 不可為 destination。 |
| `_archive_inventory/_unique_entry_paths` | canonical names + casefold collision key；拒 duplicate、aliases、file/directory collision；output normalized names 與 input 完整一致。 |
| `_extracted_entry_hashes` | extracted tree 必須與 listing 一致；拒 links/reparse/non-regular files，逐一 SHA256。 |
| `safe_archive_relative_path` | 在 PurePosixPath 自動折疊之前拒 empty／dot／dotdot segments；拒 Windows ADS、reserved devices、trailing dot/space、invalid characters。合法 backslash 路徑仍 normalize。 |
| `tests/test_rebuild.py::FakeRebuildBackend` | fake 改為 self-contained ZIP，支援 private PAK copies／atomic rename；不再依賴與 filename 綁定的 `.contents` sidecar。既有 LOCA-only／merge／target-only assertions 保留。 |
| `tests/test_legacy_pak_integrity.py` | 37 個新增自動回歸。 |

CLI signatures、manifest 1.0、error code 48 `CONTAINER_REPACK_FAILED`、UID/version/text merge 演算法、installer／backup／rollback 均未修改。沒有採用 D7 DTO/asset contract 或變更 execution identity。

## 完整 entry SHA256 結果（Native synthetic PAK）

Native executable：既有 LSLib directory label `1.20.4`，SHA256 `65c47a5050e55f686b55484a901a01d0f1a1d5ba0e776f65fec71d3e1b2a16b7`。此為本機 binary binding，不推論其他版本／平台。

| Entry | Original SHA256 | Repacked SHA256 | 結果 |
| --- | --- | --- | --- |
| `Localization/French/french.loca` | `13d9ff1e14b8ec6086a1a201ed3be6400c1ce52f5a6556ffa6d7cc3809a513ef` | `755d82d784ddb5972ab3dcbb09046c4f9ac1331c139225b8020a5da46261675c` | 替換 SHA match rebuilt LOCA；UID/version/text roundtrip PASS |
| `Metadata/invented.json` | `a8198524f58e72b56283ab71ebddada22840f108b46ef7165bb3fca9919c5558` | `a8198524f58e72b56283ab71ebddada22840f108b46ef7165bb3fca9919c5558` | PASS（原 SHA = repack SHA） |
| `Public/Fixture/a.bin` | `6509423fd9da5c225d2f8619ffae394b40f9f7686fee55a38c54b1424ac65f46` | `6509423fd9da5c225d2f8619ffae394b40f9f7686fee55a38c54b1424ac65f46` | PASS（原 SHA = repack SHA） |
| `Public/Fixture/empty.bin` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | PASS（原 SHA = repack SHA） |
| `Public/Fixture/nested/b.txt` | `622677ad0ebbf63c0de3e01d3a4c35ea19d88ce498fcfadc0a6ee4f5c2c4d1a1` | `622677ad0ebbf63c0de3e01d3a4c35ea19d88ce498fcfadc0a6ee4f5c2c4d1a1` | PASS（原 SHA = repack SHA） |

五個 entries 的完整 entry set／names 一致。目標 LOCA 為預期替換；四個 untouched entries 完全 hash parity。Basic workflow 的第二份 PAK 同樣驗證全部 untouched hashes。沒有要求整份 PAK bit-identical：本次整份 PAK SHA 確實改變，但 payload gates 通過。

## Native LSLib／Basic／備份與 rollback

`workspace/mainline-m1-a8/native-complete/summary.json`、`cli.txt`：14 個 CLI steps 完成，其中 13 exit 0，一個故意注入 native create corruption 的 rebuild 正確回傳 48。

1. Native 產生 English/French synthetic PAK，含四個不同 non-LOCA payloads；source English 2 records，target French 3 records。
2. Scan → lowercase english/french Extract → JSONL Build → 只填合法 editable translation fields → Validate → repack。
3. LOCA 4 records：更新原 target、加入 source-only UID/version 2、保留 target-only/version 3 與 blank/version 4。runtime token／markup 保留。
4. 用真正 native create-package 封裝被改成同大小 bytes 的 opaque text；驗證拒絕、既有有效 PAK bytes 保留、fresh failed rebuild 無成功 manifest；真正遊戲資料未修改。
5. synthetic game 的 Install dry-run → Install（backup）→ Rollback：backup SHA／restore SHA 回到原 baseline。
6. Project basic/standard → Workflow Prepare → 複製 delivery workbook 為 return 檔，只填 ProposedTargetText／TranslationStatus → Validate → Rebuild → Install dry-run。全部 exit 0；所有 untouched entry hashes 再度匹配。

初次 smoke harness 使用錯誤 editable 欄位／修改 prepared delivery 原檔，分別被 immutable／baseline hash guards 正確拒絕。只修正 ignored harness、改用 fresh synthetic directories；沒有放寬 validator 或改 production code，原失敗 logs 保留。

測量僅代表五-entry synthetic fixture：low-level native rebuild **2.5432 s**；Basic workflow rebuild **2.6337 s**。source snapshot + full extraction + original per-entry reads + output reread 會增加 I/O／SDK invocation 成本；未宣稱完整大型原始遊戲 PAK 的 throughput 已驗證。

## 回歸／平台限制

| 執行 | 結果 |
| --- | --- |
| Initial repack/rebuild/install/backend/Basic targeted | 57 passed、4 subtests（當時 36 個 A8 cases） |
| Final targeted：A8、rebuild/install/Basic/backend、A1/A6/A2、Stage 2/3 | **312 passed、4 subtests passed**，53.78 s（37 個 A8 cases） |
| Full pytest collection | **1452 tests**，無 collection errors |
| Full suite（沒有排除 HTTP demo） | **1450 passed、1 skipped、1 failed、1 warning**，394.76 s；exit 1 |
| HTTP demo | 唯一 failure；三筆 attempts 為安全 `PROVIDER_TRANSPORT_ERROR` + WinError 10013（retryable/retryable/final），**ENVIRONMENT-BLOCKED**；不算 PASS |
| Skip | 既有 D7 native symlink probe：host 不允許建立 symlink；沒有新增 skips |
| Warning | ZIP duplicate entry 負向 fixture 的預期 duplicate-name warning；production reader 正確拒絕 |
| Native LSLib Windows | PASS，含正常與同大小 corruption 負向測試 |

H0/HSE frozen input/effective prompt/actual-message bytes、HD identity/provenance、B1-03 OFF/stop guards 均包含於 regression。未作 Linux/macOS native PAK 驗收，未呼叫 Provider。

## Git／範圍與限制

開始 HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch：`feat/b1-03-dialogue-context`。開始 33 modified／49 untracked，393 個 public files 保存 SHA256 seals。

只有兩個既有檔案變動：`src/bg3loc/rebuilder.py`、`tests/test_rebuild.py`；**391／393 原檔 byte-identical**。新增 A8 tests 與本報告；其他所有 dirty work、CI／packaging、frozen contracts、identity／Prompt／review／transport guards 保留。

PAK gate 不發布未通過的候選檔；rebuild 仍可能留下先完成的 valid LOCA／work files。此處沒有改成 legacy whole-workspace finalize transaction，也沒有宣稱 A7 remediation 完成；installer 的既有 artifact-hash／baseline／backup／rollback gates 保留。

最終 Git status：35 modified／51 untracked，包含所有先前 dirty work；HEAD/branch 不變。不 stage／commit／push／merge，沒有 production activation。所有 native package fixtures、data inventories／hashes 與 temporary copies 維持 ignored workspace。

證據：`workspace/mainline-m1-a8/{before.txt,before.xml,targeted.txt,targeted.xml,full.txt,full.xml,http-classification.json,*-task.diff,starting-seals.json}`；native per-entry hashes、timings 與 CLI transcript：`native-complete/summary.json`／`cli.txt`。
