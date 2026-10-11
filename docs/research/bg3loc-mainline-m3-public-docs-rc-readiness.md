# BG3Loc Mainline M3 — Windows Basic Public Documentation / RC Readiness

日期：2026-10-11。範圍：公開文件、虛構範例、CLI 核對及發布驗收規劃。

**結論：文件可提交審查；Stable Release 尚未通過。** 第一入口已改為 Windows Basic 手動／外部 AI 回填，操作路徑停在 Dry-run。本次沒有發布 RC、建立新發行套件、派送 hosted CI、執行真實遊戲 Apply／Rollback 或呼叫付費 Provider。M2-B1／B2 已由使用者 ACCEPTED／CLOSED；本次不重新修改其實作。

## 1. 文件修改與保留範圍

| 文件 | 本次結果 |
| --- | --- |
| [README.md](../../README.md)、[README.zh-TW.md](../../README.zh-TW.md) | 第一入口為 Windows Basic；先說明 prerelease、少量 UID、LSLib、外部回填與 Dry-run；標示 advanced／未納入首版的能力 |
| [getting-started.md](../getting-started.md)、[getting-started.zh-TW.md](../getting-started.zh-TW.md) | 雙語完整路徑：工具安裝、唯讀 inspection、真實 locale／UID 選擇、project、prepare、允許回填欄位、Validate／Rebuild／Dry-run、失敗復原 |
| [high-level-cli.md](../e2e/high-level-cli.md)、[繁體中文 CLI](../e2e/high-level-cli.zh-TW.md) | 真實參數、prepare-time receipt、exact validation snapshot、current eligibility、historical/pending/failed output、低階 install 邊界 |
| [archive-backends.md](../concepts/archive-backends.md)、[繁體中文 backend](../concepts/archive-backends.zh-TW.md) | LSLib 全套 runtime／實際 Divine 路徑；既有 Windows native 證據與未完成的跨平台發布驗收區分 |
| [troubleshooting.md](../troubleshooting.md) | 第一段為 Basic status／復原；原 Production 診斷內容保留於進階區，不再作為 Basic 預設操作 |
| [production-getting-started.md](../production-getting-started.md) | 原 Production 入門 body 保留於相同目錄層級，前置範圍警示；不當成 Basic RC 驗收 |
| [examples/windows-basic](../../examples/windows-basic/README.md) | 雙語說明及一筆虛構 JSONL 邏輯列；明確不是可匯入玩家套件的遊戲回填資料 |

Production／automatic Provider、Legacy Production Finalize、B1-02、context/full 及研究 review 協定仍保留，全部標示為第一版 Windows Basic 已驗收範圍之外。B1-03 預設 OFF、production transport guards 不變。既有 `docs/public-readiness-v1.3.md`、release notes、Changelog、研究／歷史報告不改寫；其日期、舊 source HEAD、驗收計數屬歷史證據，不能代替新 Basic RC gates。雙語 high-level 文件的 E2E-01E ACCEPTED／288 passed 歷史區塊完整保留並加上歷史標示。

## 2. 實際 CLI 與素材綁定核對

| 實際程式位置 / function | 文件對應及驗證範圍 |
| --- | --- |
| `src/bg3loc/cli.py::build_parser`；`commands/project.py::register/run_init/run_check` | `--name --source --target`、Basic/standard 預設、重複 `--content-uid`／`--reference`、`--format`、`--workspace`、`--output`；無 init `--force` |
| `commands/workflow.py::register` | prepare/validate/rebuild/install/status 的真正 flags。高階 rebuild 沒有 `--container/--output`；高階 install 無 `--dry-run`，無 `--apply` 即 Dry-run |
| `e2e/prepare.py::run_prepare`；`e2e/baseline.py::prepare_baseline/validated_baseline/BasicSourceSnapshot` | 自行 scan/extract、Basic receipt 綁定完整 source/target/reference materials；inspection extract 不會自動被 prepare 採用；缺 receipt 不補造 |
| `extractor.py::run_extract`；`source_packages.py::ScanPackageSnapshot` | A1 canonical locale 與 A6 source package freshness；來源 byte 變動須 fresh Scan／Extract／Prepare／Validate |
| `e2e/validate.py::run_validate/_validate_immutable/_validate_final_target/_expand_input` | 回填 UID／immutable fields／runtime syntax；explicit `--input` 為 file 或 directory，不宣稱 glob 或 AI response importer |
| `e2e/eligibility.py::validation_binding/rebuild_binding/EligibilitySession/current_eligibility/revoke_downstream` | B2 current accepted validation/input/artifact 綁定；歷史成功不賦予當前資格 |
| `e2e/rebuild.py::run_workflow_rebuild/_run_workflow_rebuild`；`rebuilder.py::merge_records/validate_rebuilt_records/repack_target_package` | current tuple、candidate/history/failed 分離；LOCA UID/version/text roundtrip、A8 完整 entry set 及 non-replaced SHA |
| `e2e/install.py::run_workflow_install/_run_workflow_install`；`installer.py::run_install/run_rollback` | Basic 每次 Dry-run fresh source/artifact/destination preflight；不寫遊戲／不備份。Apply／Rollback 寫入，另需授權 |
| `commands/install.py::register/run` | low-level install 預設 apply，只有 explicit `--dry-run` 才唯讀；不具 current workflow gate，不能自動 fallback |

**回填契約不變。** 編輯自己的 generated returns；只改 `ProposedTargetText`、`TranslationStatus` 與選填 notes/name，保留 source／UID／locale／型別／comparison 欄位。XLSX 保留欄名及列，JSONL 每行完整 UTF-8 object；外部 AI 的 prose 或 `{requestId, translationText}` 不是 Basic 回填格式。示例與 `translation-material-row.schema.json` 相符，但示例 UID 不屬玩家材料，不能取得 package acceptance。

UID scope 限制交付／必要翻譯列，**仍需完整 baseline 與完整語言檔／PAK rebuild**。不宣稱單句 patch、不讀完整素材或大語料低成本。合法 blank、source-only、target-only、版本及未修改內容保留，技術 QA 不代表語意審查。

遊戲更新、外部 Extract／normalized／XML／LOCA 修改、receipt 缺失皆須保留舊 returns 並 fresh prepare；只能人工比對新 UID/source/version 後 rebase。沒有自動回填遷移、receipt backfill、改 SHA 修補或降低驗證。Validate FAIL／新驗證或 changed returns 撤銷下游資格；unchanged eligible 操作可重用，但 Dry-run 仍重新 preflight。Rebuild 路徑從 CLI／state 讀取，不使用過去固定檔名；history 累積，不宣稱 GC。

## 3. 本次 CLI 範例及回歸結果

| 檢查 | 本次結果 | 限制 |
| --- | --- | --- |
| 文件 code blocks 中 `bg3loc` commands | **40 / 40 parser PASS** | substitution 使用虛構 game/UID；不執行玩家路徑或 writable instructions |
| PowerShell blocks | **16 / 16 syntax PASS** | `Parser.ParseInput`；不等於新機 pip／LSLib 安裝成功 |
| 最終文件 local links / anchors | **81 / 81 PASS** | 包含保留的 Production 指南與本報告；未把 external URL 可用性當成本機 link check |
| Fictional JSONL row | **schema PASS** | 不是玩家 package identity proof；不是自動 importer |
| JSONL 完整 CLI | **PASS** | project init/check → prepare → allowed edits → validate → rebuild → default install → status |
| XLSX 完整 CLI | **PASS** | 同上；各 3 scoped source UIDs，包含 blank、source-only、tokens/markup；保留 target-only baseline |
| 相關 pytest 回歸 | **244 passed，2 warnings，81.72 s** | 七個既有 modules，無新 skip；不是本次 full-suite PASS |
| `git diff --check` | **PASS** | 舊檔 CRLF 提示不構成 diff error；沒有修改設定 |
| HTTP capability probe | **ENVIRONMENT-BLOCKED** | 真實 loopback 呼叫 exit 1：`URLError / WinError 10013`，不可計為 PASS |

CLI E2E 使用現有 **synthetic ZIP/XML archive backend**，只替代外部 archive transport；receipt、package SHA、source origin reproof、Windows pins、current eligibility、LOCA/entry checks 沒有 mock。每個 fake source/target/reference PAK 的 before/after SHA 相同；沒有建立 backups。Native Divine、真實 BG3、Apply、Rollback、Provider 皆未在此流程執行。首輪 harness 的 TEMP 未設於 writable workspace，出現 WinError 5；改為 workspace-local TEMP/TMP 後完成兩種格式，不改程式或完整性檢查。

Targeted modules：`test_basic_baseline_integrity`、`test_basic_workflow_state_integrity`、`test_locale_material_integrity`、`test_source_package_freshness`、`test_legacy_pak_integrity`、`test_e2e_project`、`test_dialogue_stage2`。包含 A1/A6/A8/B1/B2、H0/HSE byte parity、HD identity／both-family／prompt及 1.3 stop guards。兩項 warning 分別為 intentional duplicate ZIP fixture 與 sandbox pytest cache 寫入拒絕；測試全數完成，未更改或忽略安全 gate。

本次是 docs/examples-only，**未重跑 full suite**。最近 M2-B2 完整回歸是 1556 passed、75 subtests passed、1 skipped、1 failed；唯一 failure 為 HTTP demo WinError 10013，skip 為 host symlink 權限。這是歷史結果，並非 M3／candidate full PASS；本次 loopback probe 確認環境限制仍存在。Release 必須在可用環境執行 candidate 全套 pytest 與真實 HTTP demo。

Local-only 證據位於 ignored `workspace/mainline-m3/`：`starting-state.json`、`verify_docs.py`、`doc-validation.json`、`powershell-{blocks,parse}.json`、`jsonl-cli.txt`、`xlsx-cli.txt`、`targeted.{txt,xml}`、`loopback.txt`、`scope-audit.json`、`ending-state.json`、`final-doc-audit.json`。虛構測試工作區亦只在該目錄；未放入公開 example。

## 4. Release Candidate Gates — 只盤點，尚未發布

| Gate | 當前分類 | 正式驗收需求 |
| --- | --- | --- |
| 新 candidate source／version／wheel／sdist | **NOT VERIFIED / PENDING** | 選定 source revision、version/tag、雙語 release notes；新建 wheel/sdist、記錄 SHA／source，不能沿用舊 artifact 的驗收 |
| Candidate privacy／fixtures | **NOT VERIFIED / PENDING** | 檢查實際壓縮包 inventory；排除 game PAK/LOCA、real text、local workspaces/receipts、SQLite、assignments、secrets、Divine binaries；必要 public synthetic fixtures及文件保留 |
| sdist → wheel → clean install | **NOT VERIFIED / PENDING** | clean extraction、fixture presence、pytest collection/full run、wheel console entry、runtime schemas（含 Basic receipt schema）、fresh venv CLI；不以 source tree PASS 代替 distribution PASS |
| 四個 GitHub-hosted jobs | **NOT VERIFIED / PENDING** | 見下表；每 job retained JUnit／distribution diagnostics。YAML 有 matrix 不等於 hosted PASS |
| HTTP demo | **ENVIRONMENT-BLOCKED locally** | 可用 socket 環境跑真實 loopback + existing demo；不得 permanent skip／fake PASS，hosted 結果未知 |
| Windows Native 真實安裝唯讀 | **PENDING** | 操作者自己的安裝、明確 locales、小 UID；真實 Divine Scan/Extract/Prepare/Validate/Rebuild/Dry-run；記錄 backend/工具 SHA、counts/versions、所有 non-LOCA SHA及 game PAK before/after；不得 apply |
| In-game 載入 / Apply / Rollback | **PENDING / EXPLICIT APPROVAL REQUIRED** | 另行授權精確安裝及 backup 路徑、original/candidate SHA、少量 UID、停 game/updaters、載入及還原計畫；驗證 backup、部署與 rollback 後 SHA／遊戲載入；Dry-run不能替代 |
| 首版範圍／限制公告 | **DRAFTED / REVIEW PENDING** | Windows Basic single-operator，原始 paths 保留；拒絕 stale source／returns；進階能力不納入。需操作者與文件審查確認 |

`.github/workflows/ci.yml` 實際矩陣：

| Hosted runner | Python | 本次 hosted 結果 |
| --- | --- | --- |
| windows-latest | 3.11 | **NOT VERIFIED** |
| windows-latest | 3.12 | **NOT VERIFIED** |
| ubuntu-latest | 3.11 | **NOT VERIFIED** |
| ubuntu-latest | 3.12 | **NOT VERIFIED** |

既有 jobs 安裝 `.[test]`，compile、loopback probe、collect all pytest、full tests、`tools/ci/verify_distribution.py` 的 clean sdist/wheel/install/full tests、summary 與 artifacts；無 docs/schema path filter。未 dispatch、push 或用既有 PASS 猜測 hosted 結果。Ubuntu synthetic CI 即使通過，也不代表 Linux Native／跨平台遊戲安裝通過。

`MANIFEST.in` 已 graft docs/examples/schemas/tests/tools/ci、prune workspace/build/dist/venv、排除 PAK/LOCA/DB/EXE/DLL。`pyproject.toml` 提供 console script、runtime schemas data-files與 explicit test dependencies。**VERIFIED：靜態設定存在；UNKNOWN：新 candidate 實際 contents／clean-install closure。** 不修改這些檔案，不重新跑發行建置或把 denylist 當內容 privacy proof。

LSLib 取得來源：[Norbyte 官方專案](https://github.com/Norbyte/lslib)。文件不假定最新版本或自行下載 backend；既有 v1.20.4 native synthetic 證據保留其原限度，不能代替 real-installation acceptance。

## 5. 最小驗收順序與版本／Changelog 準備

1. 本文件／雙語指令審查，確認首版 stop-at-Dry-run 與 advanced exclusions。選定 **未決的** RC version、可追溯 source revision／tag、支援 Python／Windows／LSLib 組合；本次不改 `1.3.0` 或歷史 Changelog 日期／版本。
2. 經另外授權的 release preparation 建立 candidate wheel/sdist，完成 privacy、fixture closure、fresh install與全套 regression。版本字串不能保證包含這個 dirty tree 的 accepted fixes。
3. 四個 hosted matrix job 保留實測 log／JUnit，包括真正 HTTP demo；失敗／skip 逐項決策，不把 UNKNOWN 當 PASS。
4. 經同意的 Windows 真實安裝唯讀小範圍測試，以 package before/after SHA 確認 zero game writes，記錄 original baseline paths、UID/version與 D7 無關的 A8 entry parity。B1/B2 failure/recovery coverage 與新候選版本一致。
5. **另行明確授權** Apply／Rollback 和 in-game acceptance。先記錄確切 artifact、destination、original/candidate SHA、verified backup、恢復條件；任何 preflight FAIL 都停止，無 low-level bypass。
6. 根據上述證據決定 RC／Stable release；實際發布需要另外授權，M3 不是發布核准。

建議 future Changelog / release notes 草稿內容：Windows Basic 第一入口；A1 canonical locale、A6 package freshness、A8 all-entry parity、B1 receipt與舊 workspace fresh prepare requirement、B2 current eligibility及歷史成果保留；dry-run/apply 差異及 deferred A7／Production／Provider／B1-03。將 known limitations、tested backend/runtime組合、平台範圍與驗收未完成項目寫入。不可將本次文件審查寫成 Stable Release、一般 semantic safety或 Provider activation。

## 6. 相容性、隱私與 Git

公開新增 JSONL 僅含 fictional UID、invented source/translation及示例 token，沒有遊戲 corpus／secret／hidden mapping。公開 example 沒有可執行 Apply／Rollback 指令區塊。文件說明對外分享時只提供自己選定的必要文字／syntax，不上傳整個 workspace 或 internal receipt。

沒有修改 production code、tests、schemas、CI、packaging、版本、Prompt、H0/HSE/HD identity、frozen contracts 或 B1-03 guards。檔案 SHA 稽核：開始時 **408** 個既有 nonignored public files；只有 **8** 個既有文件變更，其餘 **400** 個 bytes 相同、無遺失。舊 Production tutorial body 與 high-level historical acceptance blocks 經比對保留。既有所有 dirty work 未清理或覆蓋。

HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch：`feat/b1-03-dialogue-context`，兩者不變。起始 **45 modified／64 untracked entries**；最終 **53 modified／68 untracked entries**（Git 以新目錄單筆計，包含全部既有工作）。M3 新增 5 個檔案：中文入門、保留 Production 入門、example README／JSONL、此報告。8 個已追蹤文件變更加這 5 個新增檔即本次全部公開 diff；驗證 scripts/logs 為 ignored local-only。

不 staging／commit／push／merge／發布，不呼叫正式 Provider，不改真實遊戲，未解除任何 transport guard。剩餘 release gates 如上，不宣稱已完成 Apply／Rollback／game-load 或 hosted CI。

**BG3Loc MAINLINE M3 — READY FOR DOCUMENTATION REVIEW**
