# BG3Loc Mainline M2-B2 — Basic Workflow State & Dry-run Integrity

日期：2026-10-11。範圍只限 Windows Basic current workflow eligibility、validated snapshot、fresh dry-run、失敗產物隔離。A7、Production SQLite、Provider、B1-03 不實作；M2-B1 的 receipt／source reproof 保留。

## 1. Root cause 與修正前證據

原 `run_validate` 的 `_update_blocked_state` 只把 validation 改成 blocked，沒有撤銷已 completed 的 rebuild/install；失敗 validation 又會寫進原 accepted 路徑。`run_workflow_install` 只驗 rebuild completed／manifest SHA；cached dry-run 相符就直接回傳舊 evidence，不檢查目前 returns、accepted snapshot、artifact 或 destination。Rebuild 固定寫到同一個 output directory，因此第二次 repack 失敗可能覆寫舊 LOCA，同時留下舊 successful manifest／PAK。

正式新增 [test_basic_workflow_state_integrity.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_basic_workflow_state_integrity.py)，修正前 **6 failed、2 passed，9.53 秒**。六項 RED 分別為：validation FAIL 後 install 未拒絕、cached artifact tamper 未拒絕、edited returns 未 validate 仍 install/rebuild、failed rebuild 改動 prior successful bytes、current validation running 仍 reuse dry-run PASS。Target PAK freshness rejection 已由 B1 生效，unchanged validation reuse 也原本正常；沒有把這兩項捏造為 RED。

原 `workspace/mainline-m2-b2/red.txt`／`red.xml` 保留，沒有 xfail/skip；第一輪 GREEN **8 passed**。最終新增 23 個完整 synthetic tests，全部 current source／eligibility gates 實跑；只用 ZIP/XML backend 模擬封裝，沒有 mock source／current eligibility。

## 2. State／cache 綁定設計：沿用既有契約

沒有修改 state/manifest schema、版本或新增必要持久化欄位。沿用既有：

- `stages.translate.artifact` 保存實際被 Validate 使用的 input file 或 directory。預設仍為 returns；明確 `--input` 保存該輸入位置，不悄悄改回 default returns。
- `stages.translate.fingerprint` 仍為原本 `fingerprint_data({packageSha256, returns:[{path,sha256}]})`；後續重新枚舉該位置的當前檔案與 SHA，新增／移除／改動都不會取得 current eligibility。
- `stages.validate` status／artifact／SHA／原 fingerprint 與 `bindings.validationManifestSha256`／`validationAcceptedSha256`，認證 strict PASS 與 exact accepted bytes；validation fingerprint 保留原 formula（returns/package、reviewGate、review integration）。
- `stages.rebuild.fingerprint` formula 不變：validation manifest SHA、accepted SHA、Extract SHA。它必須等於 current validation 的 tuple，stage/alias/manifest SHA 必須一致，manifest 必須指向該 exact validation snapshot，所有 artifacts 再驗原 SHA。
- `state.artifacts`／`bindings` 保留 last-success references，可代表歷史成果；它們自己不授予資格。只有 current completed stage + 全綁定／current source + actual artifact + fresh destination preflight 才能安裝。

這是在已有「artifact location」欄位記錄實際使用的翻譯素材，不增加 list/sidecar、fingerprint version 或重解讀 SHA；因此沒有另行修改公開契約。舊 state 缺位置／指向非實際已驗證 inputs 而無法重建 fingerprint 時明確拒絕，要求重新 Validate，沒有猜測補值。

## 3. 狀態轉移與歷史成果

| 觸發 | Current eligibility | 歷史檔案 |
| --- | --- | --- |
| 同一未變動 input 的合法 Validate cache hit | recheck current validation tuple，重用既有 snapshot／rebuild 資格 | 不重寫 snapshot |
| 新 validation 開始 | validation running；rebuild/dry-run/install invalidated | last-success aliases／files 保留 |
| Validation FAIL／parser error／中斷／B1 input failure | blocked/failed；下游不能 install | prior valid manifest/accepted/LOCA/PAK 不變 |
| 新合法 Validation PASS | 指向新 validation snapshot；rebuild ready；舊 rebuild 不是 current | 先前 snapshots 留存 |
| Rebuild cache hit | exact current validation + manifest/artifact SHA 重驗才重用 | 不重新執行 backend |
| 新 Rebuild 開始／失敗／中斷 | running→failed；dry-run/install 撤銷 | candidate 隔離，舊 success bytes 不改 |
| 新 Rebuild 成功 | 驗 source/validation 後发布獨立 history output，completed 綁定新 SHA/fingerprint | prior success 仍保留 |
| 每次 dry-run | current validation/rebuild/artifacts/B1 source gate + 真正 installer destination preflight | 不用 fingerprint 命中直接回報舊 PASS |
| current inputs/state/artifacts 變動 | 拒絕當前 install；failed preflight 不授予資格 | historical reference 不等於本次成功 |

Basic validation outputs 位於 `validation/snapshots/<operation>/`，新的 FAIL diagnostics 不覆寫舊 accepted snapshot。Basic rebuild 用非 hidden 的 `rebuild/pending-<operation>/`，成功搬到 `rebuild/history/<operation>/`；失敗留在 `rebuild/failed/<operation>/`。stage pointer 只在成功後綁定 published manifest；不覆寫 prior artifact，沒有自動刪除歷史。所有搬移先驗 owned resolved paths 在該 rebuild root，拒絕 link／已有 destination。

Manifest references 在 publication 前轉成最終位置并重算 manifest SHA，artifacts bytes 不改。原 validation／rebuild JSON 格式、LOCA／PAK／UID/version／QA/譯文規則不變。CLI 與 state 回報真實 output path，不能依賴舊固定 `rebuild/rebuild-manifest.json` 猜位置。

只對 Basic 啟用此 current/history boundary；context/full 維持原 advanced 行為。這不是 A7 SQLite writer barrier、portable D7、全面 multi-process transaction 或 crash/power-loss durability 保證；第一版仍 single operator。孤立 pending/failed 目錄不能當 current successful output，沒有 current stage binding 時 high-level install 拒絕。

## 4. 修改位置

| 路徑／function | 改動 |
| --- | --- |
| [eligibility.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/eligibility.py), `validation_binding`／`rebuild_binding`／`EligibilitySession`／`revoke_downstream` | 新 Basic current binding helpers；用既有 fingerprint/SHA；operation pins 保護 inputs/accepted/manifest/artifacts，operation 後重讀 current validation state |
| [validate.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/validate.py), `run_validate`／`_run_validate`／`_validation_failure`／`_update_blocked_state` | validation start/failure 撤銷下游；fresh immutable snapshots；記錄 exact actual input location；unchanged successful snapshot 可重用 |
| [rebuild.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/rebuild.py), `run_workflow_rebuild`／`_run_workflow_rebuild`／`_move_owned_output`／`_relocate_paths` | exact accepted tuple gate；cache artifact recheck；pending/history/failed 隔離；完整 paths publication；failure revoke current資格 |
| [install.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/install.py), `run_workflow_install`／`_run_workflow_install` | current eligibility pins；每次 Basic dry-run 真實 preflight；失敗更新資格；仍沿用 B1 apply pin handoff、原 installer/rollback |
| [prepare.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/prepare.py), `run_prepare` | package reuse 時不覆寫 completed translation 的 actual explicit input location |
| B1／E2E tests | B1 原保留的 B2 defect assertions 改為拒絕；兩個 fake incomplete-manifest unit fixtures 明確 mock eligibility（只驗 CLI/orchestration）。新 23-case integration module／Native evidence 不 mock gate |

`state.py`、所有既有 schema、`baseline.py`、A1/A6/A8、rebuilder/installer 核心、Production/SQLite、Prompt/identity/provider、B1-03 guards 都不改。沒有新增 necessary persistent fields 或 silently migrated decisions。

## 5. 自動驗收範圍

新增 23 tests 包含：

- 六個原 RED 正確拒絕、B1 已有 target update 正確拒絕、unchanged Validate reuse 保留資格。
- JSONL／XLSX 的 Validation PASS→FAIL→PASS、Rebuild PASS→FAIL→PASS、重新合法 Rebuild 後恢復 dry-run；prior successful LOCA／PAK／manifest bytes 相同。
- changed accepted／validation manifest/fingerprint／rebuild manifest/fingerprint、return file 新增/遺失、edited returns 未重新 Validate。
- unchanged Rebuild backend 不重跑；unchanged dry-run 每次真正 run_install preflight，兩次結果可相同但檢查不是 cached假 PASS。
- explicit external input 位置被保存/檢查，unused default returns edit 不會冒充那份已驗證輸入；explicit檔案變動拒絕。
- validation start／parser exception 後立即撤銷 old資格；dry-run 中注入 validation running 後拒絕發布 PASS。
- failed operation 保留 prior successful files，獨立 failed candidates；舊 validation manifest/accepted bytes 不因 FAIL 改動。
- low-level standalone dry-run 可以檢查 historical artifact，但不使 high-level current workflow 合格；沒有自動 fallback。

B1 35-case source/receipt/snapshot reproof、blank／source-only／target-only／runtime tokens、A1 canonical locale、A6 same-size freshness、A8 all-entry SHA 與 H0/HSE/HD/guards 都在 targeted/full suite 中回歸。沒有把付費 Provider 或真實遊戲用作測試。

## 6. Native Windows CLI

Native Divine（目錄標示 LSLib v1.20.4）executable SHA：`65c47a5050e55f686b55484a901a01d0f1a1d5ba0e776f65fec71d3e1b2a16b7`。全部是自行建立的 `SYNTHETIC-game`，無真實 PAK／語料。JSONL、XLSX 各完成 scoped 3 source UID、source-only、blank、target-only、runtime token／markup、版本 7/2/4；LOCA semantic reread、entry set、3 個 non-LOCA entry SHA 相同，正常 dry-run 不改 source/target package。

Native failure/recovery 每種格式實測：cached artifact tamper → CLI **77**；new validation missing token → **75**；當前 workflow install → **77**；合法 Validate → **0**；injected native create-package failure → **76**，prior success bytes 相同；install 拒絕；正常 native rebuild／兩次 fresh dry-run 恢復 **0**。

首輪 Native 測試揭露 `.staging-*` 父路徑會使此 Divine 封裝產生 48-byte 空 PAK，A8 拒絕非法候選；trace 記錄 list/create/file sizes。換成非 hidden `pending-*` 後 PAK 493 bytes、Native readback 與所有 SHA checks 通過；沒有改 backend、A8 或把首輪錯誤當 PASS。

本機：`workspace/mainline-m2-b2/native-trace2/result.json`、`native-cycles-result.json`、`native-trace{,2}.txt`、`native-cycles.txt`、scripts `native_basic.py`／`native_trace2.py`／`native_cycles.py`。只做 dry-run，Native apply／rollback 為 0；public regression 的 apply/rollback tests 僅使用可丟棄的 fake install root。真實 BG3 修改 0、付費 Provider 0。

## 7. Targeted／Full Regression

| 執行 | 結果 |
| --- | --- |
| 修正前 RED | 6 failed／2 passed，9.53 秒；log/JUnit 保留 |
| 初輪 GREEN | 8 passed，9.55 秒 |
| 完整 state/source/E2E integration | 80 passed，60.29 秒（之後另補 validation-fingerprint case） |
| 最終 B2 module | 23 passed，30.51 秒 |
| 最終 targeted | **320 passed，103.30 秒**；包含 B2/B1/E2E/A1/A6/A8、H0/HSE prompt/input/actual message parity、HD/Stage2/transport guards；intentional duplicate ZIP warning 1 |
| Full available，無 exclude/deselect | **1556 passed、75 subtests passed、1 skipped、1 failed、1 warning，370.47 秒**；exit 1，不能宣稱 FULL PASS |
| 唯一 failure | `test_public_demo.py::test_demo_accepts_relative_output_from_external_cwd`，3 個 attempts 均 `PROVIDER_TRANSPORT_ERROR / WinError 10013` → **ENVIRONMENT-BLOCKED**，不算 PASS |
| Skip | 原有 `test_d7_corruption_rejected[link]` 的 host symlink 權限限制，未新增 B2 skip |
| compileall／git diff --check | PASS |

Source/QA/translation policy 不變；technical failures 的舊譯文不是自動刪除，而是不再具有 current install eligibility。從未執行真正 BG3 apply／rollback。Hosted CI、native Linux/macOS、power-loss／多操作者 state transaction 不是本次驗收；HTTP demo 如果 WinError 10013 仍為 environment-blocked。

## 8. 相容性與 low-level 邊界

既有 schema/version/hash formula 不改；舊正常 Basic state 若能從 recorded actual returns location 與 fingerprints 認證，可重用。位置 unknown／已變動或 tuple 不一致必須 fresh Validate，不猜、補或悄悄沿用。新增的是版本化 output **路徑**，不是檔案內容格式；external consumers 應使用 CLI/state 的 manifest path。

High-level `workflow install` 必須是當前 eligible snapshot；low-level `install` 只知道指定 rebuild/scan，不能判定目前 workflow validation 是否已失敗。它仍可能對合法 historical package 給 standalone preflight PASS，必須是操作者另行明確選擇；沒有自動改用低階命令繞過失敗。低階 install 原預設 apply 不改；此階段沒有借故修改 installer/API政策。

歷史資料不自動 GC、不覆寫；failed/pending 需保留供診斷，空間會增加。Baseline 原路徑、B1 reproof backend、single-operator 範圍維持；A7／portable Legacy／Production Activation 不宣稱已解決。

## 9. Git 與結案建議

HEAD `896b4870b3a24d8506e6d751db3d4602925fb8fb`，branch `feat/b1-03-dialogue-context`。起始 45 modified／61 untracked entries，405 份 public files 保存 SHA。

本次只改 7 個既有檔：e2e install/prepare/rebuild/validate、B1 tests、E2E flow/CLI unit tests；其他 **398 個 existing public files bytes 不變**。新增 eligibility helper、23-case public tests、此報告。所有既有 dirty work 保留，正式 schema／frozen contract／production code preserved；logs／Native artifacts／private inputs 只在 ignored `workspace/mainline-m2-b2/`。

最終 Git status **45 modified／64 untracked entries**（含全部先前 dirty work）；HEAD／branch 相同。既有正式 schema、frozen contracts、A1/A6/A8/B1、H0/HSE/HD、Provider／Production／SQLite／B1-03 stop guards 的檔案 bytes 未變；B1 test module 只把先前 B2 defect observations 改為正確拒絕。沒有清理、staging、commit／push／merge、transport activation 或真正遊戲修改。

本機證據：`workspace/mainline-m2-b2/{starting-state,ending-state,scope-audit,http-classification}.json`；`red.{txt,xml}`、`green.{txt,xml}`、`formal.{txt,xml}`、`fp.{txt,xml}`、`targeted.{txt,xml}`、`full.{txt,xml}`；Native scripts、traces、result files 亦維持 ignored。唯一 full-suite failure 已核對 DB attempts 的 WinError 10013，沒有改 demo／CI 或 fake PASS。

**M2-B2 建議：可提交實作審查並建議結案；正式 ACCEPTED/CLOSED 由使用者決定。** Current eligibility、fresh preflight 與歷史／失敗 isolation 的必要 gates 已驗證；HTTP environment-blocked、hosted CI、真實 Windows 安裝／game load、single-operator／crash recovery 等發布限制仍保留。本次不是 Stable Release／A7／Production Activation 核准。

**BG3Loc MAINLINE M2-B2 — READY FOR IMPLEMENTATION REVIEW**
