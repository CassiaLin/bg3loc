# BG3Loc Mainline M1-A6 — Source Package Freshness

日期：2026-10-11（Asia/Taipei）。Repository：`CassiaLin/bg3loc`。
Branch：`feat/b1-03-dialogue-context`。
HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`，未變更。

## 1. 結論與範圍

**A6 技術修正已完成；建議在 Implementation Review 接受後結案。** Extract 不再直接讀取可變的 live PAK：先依 scan 的來源路徑與 SHA256 建立 verified private snapshots，所有選定 source／target／references 通過後才開始 backend 擷取，最後經完整 staged output 驗證才發布。

只處理 A6。A1 已接受成果保留；A2–A5、A7–A9未實作。B1-03 預設 OFF、frozen contracts、Prompt、identity、review policy與production transport guards不變。未commit、push或merge。

公開 scan／extract schema仍為1.0，無新欄位／版本要求。錯誤沿用既有 Extract exit15／`ARCHIVE_EXTRACTION_FAILED`，freshness訊息明確要求重新 `bg3loc scan`。不要求 Steam build ID，未知 build與明確指定的非Steam安裝仍可使用。

## 2. Root cause 與 pre-fix 證據

Scanner 已記錄 BG3 id/appId、dataPath、每個locale的packageFile與packageSha256。但 `run_extract` 原先只依path找PAK／LOCA entry，沒有比對scan SHA，並將部分產物直接寫入output。有效的新套件即使與原包同大小，仍會被當成舊scan的來源；後續失敗也可能留下先完成的locale產物。

在修正前建立正式 `tests/test_source_package_freshness.py`：**7 failed、1 passed**。English／French／German各自以另一份有效、同大小PAK替換或原地改寫時，六個「應拒絕」probes都沒有拒絕；已有output的第七個probe亦未保護既有內容。未變更的非Steam／unknown-build流程正常通過。

這是實際程式重現，不只引用Readiness Audit的A6結論；所有素材均為synthetic。

## 3. 修改位置與設計

| 位置／function/class | 修正 |
| --- | --- |
| [source_packages.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/source_packages.py:86), `ScanPackageSnapshot` | 依已選canonical locale建立短期私有PAK copies；package必須位於scan記錄的dataPath、為regular file，bytes SHA256必須等於scan；檔案身分／大小／mtime與內容再次驗證 |
| 同檔 `_ReadPins`（40） | Windows以OPEN_REPARSE_POINT讀取named object；original與snapshot files deny-write/delete，directories deny-delete但允許child writes以完成publication；持續核對ancestor與file identity／reparse狀態 |
| 同檔 `verify`／`_verify`／`close` | backend前後及publication前後核對original descriptor/path與snapshot hashes；after-close使用拒絕；無可變全域cache或activation flag |
| [extractor.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/extractor.py:37), `run_extract` | 保留A1canonical resolution；驗所有selected packages後才建立工作產物；保護scan/source與output重疊；existing output在stage內複製，正常output未提前覆寫 |
| 同檔 `_extract_verified`（126） | backend只讀private snapshot；normalization的sourcePackage、manifest的packageFile／sourceLoca／sourceXml／normalized／aligned等仍指向原來源或正式logical output，沒有temporary snapshot依賴流入manifest |
| 同檔 `_publish_extract`（88） | complete stage以directory rename發布；驗證失敗／rename失敗時restore舊output或移除新output；rollback本身失敗時，舊output留在獨立recovery folder，不被stage cleanup刪除 |
| [test_source_package_freshness.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_source_package_freshness.py) | 新增持續synthetic回歸：unchanged／stale／same-size／source/target/reference、timing、Windows sharing、nonlocking-copy算法、publication／rollback及close lifecycle |
| [test_extract.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_extract.py), `test_extract_normalizes_and_full_outer_aligns` fixture | 原先fake packages在recorded dataPath外，SHA是0/1 placeholders；補為真正位於synthetic Data/Localization內且SHA對應其bytes。原locale／alignment斷言維持 |

### TOCTOU保證與平台界線

不能只做 `SHA(live path) → backend(live path)`：這會讓backend讀到驗證後替換的另一份包。現在capture使用opened original descriptor，複製時逐塊SHA；SHA完全符合scan的private copy才可供backend使用。所有選定packages先驗完，避免source完成後才發現target早已更新。

Windows original／snapshot readonly sharing handles保持至publication檢查結束；existing write owner會造成preflight拒絕。Directory sharing允許合法stage child writes，但不允許刪除／替換受pin的directory。也保留full SHA檢查，而不是只相信handle或size。

非Windows依private owned copies隔離輸入，並重查original／snapshot SHA、path／descriptor identity、mtime與POSIX ctime。可觀察到的變更拒絕發布；live path短暫替換不能讓backend混入新PAK內容。這不是承諾跨平台阻止所有遊戲寫入，也不保證Extract返回後遊戲永不更新；產物綁定的是驗證期間scan-defined snapshot。

Windows Python3.12的path/descriptor `st_ctime`在新建檔上可不一致，因此不拿該deprecated Windows欄位做相等判斷；file ID、size、mtime、SHA及write/delete sharing檢查均保留。POSIX ctime仍核對。

沒有建立signed scan attestation：來源身分依現有可信scan的BG3 schema identity、recorded dataPath/package path與SHA綁定。主線原有buildID處理不改，也沒有把portable D7或B1-03契約套到本階段。

## 4. 修正後驗證與相容性

### 自動回歸

- Unchanged PAKs：Scan→Extract→Build通過；canonical／lowercase locale沿用A1解析。
- Source、target、selected reference分別換有效包或同大小不同bytes：拒絕且不發布output。
- 全部selected package preflight：target stale時，backend一次也未被呼叫。
- Unknown Steam build／非Steam explicit install：不新增build ID門檻。
- Missing package、偽造SHA、recorded dataPath以外的同bytes包、錯誤game identity：fail closed。
- Nonlocking算法的open／backend／conversion／publication時序變更：拒絕，fresh output不存在，existing output bytes不變。此類測試在Windows關閉test pin implementation以測copy/check邏輯；不是native Linux/macOS驗收。
- Windows original／snapshot寫入與替換：OS正確拒絕；合法擷取仍成功。預先存在write owner會阻止capture。
- Late conversion／atomic rename failure：舊output恢復；雙重publication/rollback failure：舊bytes保留於recovery folder並回報位置。
- Existing notes、unselected locale files、logical paths保留；snapshot使用完即清理，closed object不能再使用。
- Source與target更新後重新scan：新的合法scan恢復擷取。

原有正常success欄位、角色、UID、原文／譯文、版本及roundtrip語意不變。Private copies不進入prepared/extract schema的durable path；A7 legacy finalize依賴沒有在本次被重新設計。

### Native LSLib synthetic驗證

使用本機既有標記LSLib-v1.20.4目錄的Divine.exe，以synthetic English／French PAK實際執行7個CLI calls：

1. 非Steam、buildId=NULL的scan、extract及low-level JSONL Build成功。
2. English換成另一份有效native PAK，old scan Extract exit15，stderr提示rerun scan；existing output逐檔bytes完全相同。
3. French獨立換有效native PAK，同樣正確拒絕並保護output。
4. 恢復synthetic package後scan／extract成功；refresh output逐檔byte parity通過。

真實遊戲讀取／修改與provider calls均為0；不能把此fixture當成所有game builds或native Linux/macOS已驗收。

## 5. Targeted / full regression

| 驗證 | 結果 |
| --- | --- |
| Formal pre-fix reproducer | 7 failed／1 passed；負向拒絕未實現 |
| Fresh targeted | **219 passed，24.38s**；A6、A1、scan/extract/build、E2E prepare/CLI/flow、H0/HSE identity/prompt與B1-03stop guards |
| Full available | **1329 passed、1 skipped、75 subtests passed，374.59s**；33項A6自動回歸全數通過 |
| Native synthetic | English／French valid-package changes正確拒絕；unknown-build/nonSteam合法成功；existing/refresh output bytes parity |
| HTTP demo | 獨立重跑 **environment-blocked**；1 failed／7.96s，3 attempts皆PROVIDER_TRANSPORT_ERROR／WinError10013；不列PASS |

唯一skip是 `test_d7_corruption_rejected[link]`：host不允許建立symlink。沒有將此skip或HTTP環境限制當作PASS。Native Linux/macOS sharing與filesystem實測仍不在本階段驗收範圍。

開發期間曾發現Windows新建file ctime不一致及directory sharing阻擋合法stage rename；調整為相容stat欄位＋不降低SHA覆蓋的file/dir sharing後通過targeted。Nonlocking測試改用in-place writer，避免Windows Python read streams另行deny-delete而把模擬誤當POSIX能力；沒有削弱production guard以通過測試。

Local-only證據：`workspace/mainline-m1-a6/` 的starting seals／red、targeted、full、HTTP JUnit/log、native CLI log/summary、publication recovery fixtures與preservation audit。測試PAK與遊戲形狀資料全部synthetic。

## 6. Git／保留結果

Starting：27 modified／39 untracked status entries；381個既有tracked或non-ignored untracked files SHA封存。允許改動的既有檔案只含`extractor.py`及一個`test_extract.py` fixture；A1其餘檔案與所有Stage0–5／S5-R1成果不改。

Task新增`source_packages.py`、`test_source_package_freshness.py`與本報告。**最終：28 modified／42 untracked status entries；379／381既有檔案byte-identical**，其餘兩個即授權的extractor與test fixture。A1其餘程式／測試／報告、所有frozen/public schemas、Prompt、identity與transport guard檔案保持起始SHA。

HEAD／branch不變，`git diff --check`通過；完整status／preservation audit保持local-only。未commit、push、merge，未啟用B1-03／formal provider transport，沒有變更schema或版本。

## 7. A6結案建議

**YES — 建議Implementation Review接受後將A6結案。** Stale source/target/reference bytes不再被舊scan正常擷取，backend輸入已與scan-defined bytes綁定，失敗publication與recovery均有測試。此結論不批准A2–A5、A7–A9或public release／B1-03 activation。

**BG3Loc MAINLINE M1-A6 — READY FOR IMPLEMENTATION REVIEW**
