# BG3Loc Mainline M2 — Windows Basic MVP Release Boundary

日期：2026-10-11。**RELEASE BOUNDARY READY FOR REVIEW**。本次只有路徑審查、隔離 synthetic probes 與验收規劃，未修改 production code、schemas、既有文件或 tests。

## 1. 第一版決策

**Windows Basic 可以在架構與產品範圍上獨立交付；目前不能宣告 Stable Release READY。** Basic 不依賴 Production SQLite、Legacy Production Finalize、自動 Provider 或 B1-03，因此 A7 implementation 可正式延後。然而本次找到直接影響 Basic 的素材 freshness／baseline binding／workflow gate 缺口；縮小產品範圍不會自動修復這些問題。公開入口文件、GitHub-hosted CI 與 native Windows 實際安裝驗收也仍待完成。

第一版驗收範圍：Windows、使用者自己的安裝、安裝中既有 source／target locale、`evidenceProfile=basic`、`translationStrategy=standard`、明確少量 UID scope、手動／外部 AI 編輯回填檔、技術格式 QA、LOCA／PAK 重建、唯讀 dry-run，另經明確授權才 apply／rollback。JSONL 與預設 XLSX 都須在 release candidate 驗收。外部 AI 的帳號、費用與操作在使用者控制範圍，BG3Loc 不自動發送；回填仍須維持 immutable fields。

不列入首版「已驗收」功能：`production *`、`translation-state`／Production QA／SQLite Review、自動 OpenAI-compatible provider、Legacy Production Finalize、B1-02 production context、B1-03 Dialogue Context、context/full evidence profile、研究型 review pipelines、general dialogue safety、Linux/macOS native backend、全語料翻譯、mods／patch overlays 完整整合、新增遊戲不存在的 locale。程式與研究保留，不移除能力、不改 H0/HSE 或 transport guards。

## 2. 實際 Basic CLI 與程式路徑

下列路徑為目前 dirty working tree 實作；「有程式」不等於新版 release candidate 已驗收。

| 使用者動作／CLI | 進入點與呼叫路徑 | 寫入範圍與 gate |
| --- | --- | --- |
| `bg3loc --version`／`--help` | [cli.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/cli.py), `build_parser`／`main` | 唯讀；目前 help 仍引導 Production，須在發布文件界定範圍 |
| `project init` | [commands/project.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/project.py), `run_init` → `load_project_config` | 寫 project JSON；拒絕覆寫；預設 basic／standard／XLSX；`--content-uid` 可重複指定 |
| `project check` | 同檔 `run_check` → [e2e/config.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/config.py), `load_project_config` | schema／語言角色／scope validation，project-relative path resolution；不驗證遊戲內容 freshness |
| `workflow prepare` | [commands/workflow.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/workflow.py), `run_prepare_command` → [e2e/prepare.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/prepare.py), `run_prepare` | config → scan → extract → basic evidence checkpoint → package → returns；寫 project workspace，不修改來源 PAK |
| 內部 scan | [scanner.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/scanner.py), `build_manifest`／`inventory_locales` → backend list | prepare 每次重新建 scan evidence；package path／SHA、locale ambiguity、unknown build；不要求 Steam build ID |
| 內部 extract | [extractor.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/extractor.py), `run_extract` → `resolve_locale_roles`／`ScanPackageSnapshot`／`_extract_verified`／`_publish_extract` | A1 canonical roles；A6 目前 PAK SHA／identity、Windows pins、private capture、late verification、atomic extract publication |
| package／回填初始化 | [e2e/package.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/package.py), `prepare_translation_package`；`e2e.prepare._initialize_returns` | immutable rows、target/source version、protected tokens、scope；basic 不建立研究 context；edited old returns 不被覆寫，異版 package 拒絕自動刷新 |
| 手動／外部 AI 回填 | 編輯 `<workspace>/e2e/returns/*`，或 `workflow validate --input ...` | 不呼叫 Provider；UID／source／locale／version 等 immutable fields 保持；填 `ProposedTargetText`／`TranslationStatus` 等允許欄位 |
| `workflow validate` | `run_validate_command` → [e2e/validate.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/validate.py), `run_validate`／`_validate_immutable`／`_validate_final_target` → `validator.read_return_material`／protected syntax | package／immutable／prepared delivery SHA、returns package binding、UID coverage／duplicates／unknown、runtime tokens／markup；生成 accepted snapshot。Basic 無額外 structural review／language rules 時直接做 technical checks，不代表語意已自動驗收 |
| `workflow rebuild` | `run_rebuild_command` → [e2e/rebuild.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/rebuild.py), `run_workflow_rebuild` → [rebuilder.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/rebuilder.py), `run_rebuild` | 要求 validate completed、validate／accepted SHA；重新讀原 Extract reference、target XML／source normalized。High-level 固定 `container=auto`；target 為 PAK 時輸出 LOCA + PAK，而非 CLI 提供兩個 container flags |
| LOCA／PAK | `merge_records`／`validate_rebuilt_records`／`repack_target_package` → [backends.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/backends.py), `NativeWindowsBackend` 的 Divine list/extract/convert/create | LOCA UID/version/text roundtrip；A8 完整 entry set、non-replaced SHA、replacement bytes／semantics、candidate atomic replacement |
| `workflow install`（無 `--apply`） | `run_install_command` → [e2e/install.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/install.py), `run_workflow_install(apply=False)` → [installer.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/installer.py), `run_install(dry_run=True)` | 首次實際 preflight 檢查 target baseline／artifact SHA、build（若可得）；只寫 project 的 dry-run evidence。再次執行可能 reuse cache，並非必然重新 preflight |
| `workflow status` | `run_status` → `e2e.state.load_state` | 唯讀 JSON state；不是 current game SHA 全驗證 |
| `workflow install --apply` | 同入口 `apply=True` → `run_install(dry_run=False)` | **另需明確授權**；current preflight、驗證備份、temporary deployment／replace、post-check、失敗 rollback。本階段未執行 |
| `install --rollback <manifest>` | [commands/install.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/commands/install.py), `run` → `run_rollback`／`restore_backup` | **修改遊戲，也需授權**；backup SHA 必須正確、current destination 必須仍是當時 installed SHA，否則拒絕；本階段未執行 |

診斷用低階 `scan`／`extract` → 同 scanner/extractor；`build` → [builder.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/builder.py) `run_build`；低階 `validate`、`rebuild` 可操作獨立 manifests，但不能假定具有 Basic state gate。首版標準路徑應使用高階 workflow，不把任意低階 overrides 列為推薦復原方式。特別是低階 `install` **預設會 apply**，與高階預設 dry-run 不同；文件不得引導未加 `--dry-run` 的低階安裝。

`basic`／`standard` 的 resolved structural review set 為空、預設 QA ruleSets 為空，不會經 research adapters 或 HD semantic REVIEW。没有建立 TranslationRequest／execution.sqlite3；不存在因 B1-03 default OFF 而換成 HD 的情形。

## 3. 已生效防護與新重現的 Basic 邊界

本次 14 個 local-only probes 使用虛構 English／French package、兩個 scoped UID、runtime `{name}`、HTML `<b>`、source-only、target-only、blank 及三個不同 non-LOCA payload。使用真正 scanner／extract／package／validate／workflow rebuild／installer dry-run 路徑；僅 archive backend 是 ZIP/XML fake。沒有 apply／rollback、付費 API、真實 PAK 或 Production SQLite。

| 情境 | 實際結果／判讀 |
| --- | --- |
| lowercase `english`／`french` → Basic prepare | A1 解析成 English／French；素材 source／target roles 一致；scope 2，原文不遺失 |
| 正常 scoped validate→rebuild→dry-run | target version 7、source-only version 2；target-only／blank 保留；三個 untouched entry hash 相同；來源 package SHA 前後不變，沒有 backup、沒有 DB |
| English 或 French PAK 以另一份有效同大小 package 替換後，用舊 scan extract | A6 正確拒絕，無新 output |
| PAK 更新後重跑 prepare，returns 已有 edits | scan 改變；prepare 明確拒絕覆寫 old returns，提示 archive/move；編輯 bytes 保留；validate 拒絕 changed package binding。不是自動遷移譯文 |
| Extract manifest 消失 | Basic rebuild 正確拒絕 missing artifact；Basic 並不 self-contained |
| **validation 後只有 English PAK 更新，不重跑 prepare** | **Basic rebuild PASS，fresh dry-run PASS**。A6 只保護 extract 當下；installer 驗 target package，不能偵測 source-only 更新（此 fixture build ID unknown） |
| validation 後 French PAK 更新，不重跑 prepare | rebuild 仍可跑，但首次 fresh dry-run 正確拒絕 target baseline mismatch；不能宣稱 rebuild 自己已拒絕 stale package |
| **validation 後改 target baseline XML，或改 Extract manifest 指到另一份 XML** | **Basic rebuild 採用 altered untouched target-only text，fresh dry-run PASS**。`run_workflow_rebuild` 把 recorded extract SHA 放進 fingerprint，沒有核對目前實際 Extract SHA／完整 baseline closure；semantic roundtrip 只認證當次讀到的 baseline |
| **首次 dry-run 完成後 target PAK 更新，再次 workflow install dry-run** | **cached dry-run PASS**。`stage_reusable` 核對 project artifact；cache fingerprint 沒有 current target／artifact bytes。apply 程式仍會呼叫 current installer preflight，但未執行 apply，不能把 cached PASS 當即時 readiness |
| validation 後 returns 編輯，未 rerun validate | rebuild 使用先前 validated accepted snapshot，新 unvalidated bytes 未寫入 artifact。需要清楚標註 snapshot／要求重新 validate；不宣稱新 edit 已通過 QA |
| 第二次 rebuild 故意 repack failure（先前已有成功輸出） | A8 保留先前 valid PAK；舊 rebuild manifest／部分 LOCA 留在目录；高階 workflow install 因 rebuild failed 正確拒絕；低階 read-only install dry-run 可接受舊 PAK，因它不知 workflow failure |
| **成功 rebuild 後，新的 returns 缺 runtime token，rerun validation FAIL** | validate blocked，舊 rebuild 仍 completed，**fresh workflow dry-run 可接受舊 valid PAK**。新壞譯文沒有進入 PAK，但當前失敗 workflow 沒有完整撤銷 downstream eligibility |

**14 assertions 通過只表示上述行為成功重現，並非所有安全 gates PASS。** 五項 probe 記為 GAP：source-only freshness、XML binding、Extract manifest binding、cached dry-run、failed-validation downstream eligibility。正式修正另需授權，本次不改程式。

Local-only 可重播腳本：[test_basic_boundary.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/workspace/mainline-m2/test_basic_boundary.py)；證據：[basic-probe-evidence.json](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/workspace/mainline-m2/basic-probe-evidence.json)、`basic-probes.xml`／`.txt`。

### Installer／Rollback 保護強度

**VERIFIED（code + 本次 dry-run）**：fresh `run_install` 拒絕 target scan SHA mismatch／artifact SHA mismatch，unknown build 不被硬性要求為 Steam install；dry-run 不建立 backup／不修改 package。

**VERIFIED（code，非本次 live apply）**：真正 install 会重跑 preflight，copy backup 後核對 SHA、temporary artifact SHA、atomic replace、post-install SHA；late install-manifest failure 可 restore backup。Rollback 拒絕壞 backup 或被外部更新的 destination；不會強行覆蓋別人較新的 package。

**UNKNOWN／限制**：本次未重新實跑 apply／rollback；不能宣稱新 release artifact 的真實 game load／rollback 已通過。installer 未建立跨整个安裝期間的ゲーム更新排他 session，應限定單一操作者、遊戲關閉、沒有 Steam／mod manager／另一程序更新；backup-to-replace race、OS crash／斷電與恢復需後續獨立驗收。沒有授權前不得為測量而 apply。

## 4. 阻擋與可延後項目

| 項目 | Windows Basic Stable 決策 | 最小下一步 |
| --- | --- | --- |
| **M2-B1：source／Extract／baseline current binding** | **BLOCKS STABLE RELEASE**。A6 extract guard 不能涵蓋 later rebuild/install | 獨立 Basic 修正範圍：核對實際 recorded extract/source/material、建立可信 baseline origin 與 operation capture、核對 live source/target package freshness；missing／changed 明確拒絕或要求 fresh prepare。不能只把 finalize-start hash 當 prepare-time evidence |
| **M2-B2：current validation／rebuild／dry-run gate** | **BLOCKS STABLE RELEASE**。目前 failed validation 可沿用 old eligibility，cached dry-run 非 current | 清除／拒絕 stale downstream bindings；dry-run 必須檢查 live inputs，不以旧 cache 當 current PASS；明示 artifact 是哪個 validated snapshot。採用既有 hashes/state primitives，另行設計，不套用 SQLite A5 政策 |
| Failure residual output | 高階 rebuild failed gate 有效；但有誤用舊／部分輸出風險 | 初版限制：失敗立即停止、隔離 failed output、禁止低階 override／手動 copy install。前次 valid output 必須明確是獨立 historical artifact；受支援 recovery 至少能辨別 current/failed/previous。完整整目錄 atomic rebuild 可另規劃，不得稱已由 A8 完成 |
| Public docs boundary | **BLOCKS STABLE RELEASE** | 將第一入口改為 Basic；Production/provider/research 另標未納入首版驗收；修正 overly broad safety、更新偵測、scope／安裝敘述 |
| GitHub-hosted CI／候選 package gate | **PENDING／NOT VERIFIED，Stable gate 未滿足** | 在另行批准的 release candidate commit 上跑四個 jobs、全 pytest、sdist clean tests／wheel install／privacy audit，保存 logs/JUnit |
| HTTP demo | 本次仍 **environment-blocked**；Basic runtime 不依賴 HTTP | 不以它證明 Provider 支援，不永久排除。需 hosted／允許 sockets 的乾淨環境真正通過，才可宣稱整套 regression PASS |
| Native Windows small-scope game acceptance | **PENDING／NOT VERIFIED** | 唯讀 real scan/extract、native LOCA/PAK；fake ZIP 不足。真實 apply／rollback／game load 另須具體授權 |
| A7 Production SQLite finalize／writer barrier／portable Legacy | **DEFERRED，未修復**；不阻擋被排除的 Basic SQLite 能力 | 不列 `production finalize` 為首版驗收；共同 baseline／rebuild 問題由 M2-B1/B2 處理，不隨 A7 全部延後 |
| 自動 Provider／A2 live endpoint／多 worker 吞吐 | **DEFERRED** | 第一版只有外部手動回填，沒有 endpoint、token accounting、retry/resume 自動化承諾 |
| B1-03 production activation／general safety | **DEFERRED／NOT APPROVED** | OFF、stop guards 保留；不建立 HD。不改 frozen contracts，不以 case-006 單例當一般品質證明 |
| Detached Basic portable workspace／並行操作者／多平台 native | **DEFERRED** | 保留 Extract、baseline、project 路徑；single operator；Windows-only。不宣稱可任意搬資料後繼續工作 |

M2-B1／B2 是 **Basic-specific code-path remediation proposal**，不是開始 A7 implementation、修改人工審查政策或開啟 B1-03。本階段沒有修正授權，不處理它們。

## 5. 文件盤點與發布敘述

| 目前文件／入口 | 直接證據與需更正範圍（本次未修改） |
| --- | --- |
| [README.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/README.md)、[README.zh-TW.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/README.zh-TW.md) | 第一段強調 1.3 resumable Provider／Production；主要步驟依序 research、production prepare、execute、qa、finalize、install；Basic 只有後面的較小工作流連結。與本次 release decision 衝突 |
| [getting-started.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/docs/getting-started.md) | 標題與完整入門均以 Production、自動 endpoint、Review、Finalize 為主。必須給 Basic 入門，不能將付費 Provider 作第一版必要步驟 |
| [high-level-cli.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/docs/e2e/high-level-cli.md) 及 zh-TW | 「incredibly safe」「全部 checked off」無法描述今回缺口；game update 自動偵測只在 prepare re-scan、fresh install target check 等特定入口，非每個命令；`--content-uid` 仍 rebuild/replace 完整 localization PAK、保留其他 entry，並非只在 filesystem install 一條句子。state filename 為實際 workspace JSON，不是 `.schema.json` 定義檔 |
| [public-readiness-v1.3.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/docs/public-readiness-v1.3.md) | 記錄 2026-09-28 public main 的歷史驗證與「Public blockers: none」，不能作目前 dirty branch／Basic candidate 的 release gate；保留歷史，加上新的適用範圍／後續 gate reference |
| [archive-backends.md](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/docs/concepts/archive-backends.md) | 記錄 Windows 11／Divine v1.20.4 歷史 native setup；DLL/.NET 支援實作不等於 Ubuntu/macOS native 正式驗收。LSLib 需使用者自行提供，不能打包 proprietary binary |
| B1-03 root/default claims | 已查 README EN/zh-TW、getting-started、E2E docs，**未找到 B1-03 是預設已啟用的敘述**。research／stage reports 是各階段歷史；release feature matrix 必須明示未啟用，不刪除研究。`production prepare --dialogue-evidence` CLI help 已寫 explicit opt-in、transport disabled |

README／CLI 仍保留 Production commands 是現有實作事實，不要求本階段移除 CLI。發布說明必须分清「可找到的 advanced command」和「首版已驗收功能」；CLI help 入口修正若需改 code，另行授權。

## 6. 最少驗收計畫與可用 CLI

### R0 — Release candidate 與自動化

先另行核准 M2-B1／B2 與文件變更，保存每個 probe 的前後 evidence；所有負向案例須正確拒絕／撤銷 current gate，不能用大量 skip/exclude 顯示 PASS。候選來源需經 review、版本／changelog／artifact checksums 與 privacy audit；目前 dirty working tree 不等於可直接發布的 commit。

[ci.yml](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/.github/workflows/ci.yml) 已配置 Windows/Ubuntu × Python 3.11/3.12、無 path filters、pytest collection/full suite、真实 loopback diagnostic、sdist→wheel→clean install/full tests、統計/JUnit uploads。**Hosted 四個 jobs 本次未執行，NOT VERIFIED**。Ubuntu synthetic PASS 仍不代表 Linux Divine／實際 BG3 驗收。

在候選 archive 重做 clean sdist fixtures、runtime schemas、CLI、wheel payload parity、distribution privacy；保留 all tests，包括 HTTP demo。禁止公開 PAK／LOCA／真實 corpus、returns、SQLite、API keys、workspace、hidden assignments、Divine binaries。A4 的歷史驗證可參考，但不能代替新 candidate archive 驗收。

### R1 — Windows 使用者安裝的唯讀驗收

使用乾淨 venv 安裝候選 wheel；自行取得已驗證的 Divine，記錄實際 executable SHA／version、Windows／Python／遊戲 metadata。project/workspace 在遊戲與 repository 外。用 read-only scan inventory 選兩種已存在、非 ambiguous locale；unknown Steam build／非 Steam 不硬拒絕，仍須 PAK bytes 綁定。

以下為**待執行範本**，本次沒有對真實安裝執行。語言及 UID 應由使用者自己的 scan/extract 選定，不能用測試虛構 UID：

```powershell
bg3loc --version
bg3loc scan --game-dir '<BG3_INSTALL>' --output '<PROJECT>/scan-inspection'
bg3loc extract --scan '<PROJECT>/scan-inspection/scan-manifest.json' --source English --target French --output '<PROJECT>/extract-inspection'
bg3loc project init --name 'Windows Basic pilot' --game-dir '<BG3_INSTALL>' --source English --target French --evidence-profile basic --translation-strategy standard --content-uid '<UID_1>' --content-uid '<UID_2>' --format xlsx --workspace workspace --output '<PROJECT>/bg3loc-project.json'
bg3loc project check --project '<PROJECT>/bg3loc-project.json'
bg3loc workflow prepare --project '<PROJECT>/bg3loc-project.json'
bg3loc workflow status --project '<PROJECT>/bg3loc-project.json'
# 使用者／外部 AI 編輯 <PROJECT>/workspace/e2e/returns 的允許欄位
bg3loc workflow validate --project '<PROJECT>/bg3loc-project.json'
bg3loc workflow rebuild --project '<PROJECT>/bg3loc-project.json'
bg3loc workflow install --project '<PROJECT>/bg3loc-project.json'
```

第一組低階 scan/extract 用來檢視與選 UID；workflow prepare 會在自己的 workspace 再 scan/extract，不能宣稱它直接 reuse inspection workspace。已取得 UID 時可省略 inspection，或从先前合法唯讀 extract 選定；scope 小仍會讀完整 language baseline／封裝完整 package，不承諾快速或低磁碟成本。

每一步記錄 source／target PAK SHA 前後相同；驗 source/required/scoped/accepted counts、source bytes、target-existing version 與 source-only version、至少一個 runtime token／markup、untouched／target-only／blank semantics。避免選新 locale 或無來源 UID。只把必要小 scope 交給使用者選擇的外部 AI，不將遊戲全語料上傳。由人確認翻譯意思，technical QA PASS 不等於語意品質或 B1-03 safety verdict。

### R2 — Native rebuild／negative／dry-run

用候選 wheel + native Divine，驗 LOCA roundtrip、PAK full entry inventory／每個未替換 SHA、replacement LOCA byte/semantic identity。至少 JSONL、XLSX 各一條完整 Basic small-scope chain。干擾／mutation／故障測試只用隔離 package copies，不修改真實 PAK：舊 scan same-size replacement、source/target independent update、Extract／baseline tamper、缺檔、改回填 immutable field、unknown/duplicate/missing UID、runtime token／markup破壞、failed validation downstream、cached dry-run、backend failure／中斷、prior valid artifact／partial output誤用。

真實 dry-run 必須 current、記錄 target destination／artifact／baseline hashes、沒有 game writes 或 backups；要求接受「當前 candidate」而不是舊 cache。未知 build 不等於任意來源變動可接受。所有 failure 停止，不手動 copy、低階 install override 或當成功重試。

### R3 — 另行明確授權的 apply／game load／rollback

R0–R2 通過後，先提供具體可審查的 target path、locale、原 SHA、candidate SHA、UID scope、game build（可得時）、備份位置與復原方法。**只有使用者對這份具體產物／目的地明確授權後**，才可執行 `workflow install --apply`；先關閉遊戲及所有更新／寫入者。驗 backup SHA、installed SHA 與 untouched payload parity，再由使用者確認遊戲載入及少量翻譯顯示。

Rollback 也會寫入遊戲，須明確授權 `bg3loc install --rollback '<INSTALL_MANIFEST>'`，核對 destination 與 backup，完成後 SHA 必須恢復原始值。外部變動／壞 backup 的拒絕、temporary write／replace failure、自動恢復、failure metadata 等先在可丟棄的隔離 install-root 測試；不得對真實遊戲注入故障。本階段任何 apply／rollback 均未執行，也未取得其授權。

**Stable 最小 gate**：Basic binding/state 缺口關閉 + 正確 public docs + 四 hosted jobs/full HTTP regression + 新 candidate package/privacy + native Windows唯讀／small-scope rebuild/dry-run + 明確授權的 install/game-load/rollback evidence。未達成前可供工程預覽審查，不能標為穩定、完整遊戲安裝驗收。

## 7. 本次結果與 Git

| 驗證 | 結果與限制 |
| --- | --- |
| 新 Basic 行為 probes | **14 passed，8.09 秒**；五項 GAP 重現，未修復。先前兩項 probe 對 edited returns 的預期較晚拒絕，實際 prepare 已更早 fail closed；已按實際拒絕邊界驗證，沒有改 production 行為 |
| 相關既有 regression | **137 passed，16.29 秒**；A1／A6／A8、project/config、prepare、scoped package／validate、protected syntax、installer dry-run；一個 intentional duplicate ZIP warning |
| HTTP 能力 | 重跑 `tools/ci/check_loopback.py`：`URLError / WinError 10013`；**ENVIRONMENT-BLOCKED，非 PASS**。未呼叫 Provider；未實跑完整 HTTP demo，不能推定它已通過 |
| Full／hosted／packaging/native | 本次沒有重跑完整 suite、GitHub-hosted、build archives 或 native LSLib；都不是本次 PASS。本階段只是計畫，以上 R0–R3 仍待驗收 |
| Apply／Rollback | **0**（包含 synthetic apply）；Installer/rollback 的 write 路徑僅靜態審查／歷史 evidence，未以執行測試偷渡授權 |

本機 probes／regression 用既有 Python 3.12 venv `workspace/a34venv`，TEMP/TMP 指向隔離的 `workspace/m2tmp`。probes 紀錄、JUnit/logs、HTTP diagnostic 與逐檔 source seals 保留 ignored `workspace/mainline-m2/`，不把 proprietary 資料或失敗性質 probes 放入正式 CI。

HEAD 起始／結束：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch `feat/b1-03-dialogue-context`。起始 **40 modified／56 untracked entries**；本次只新增這份公開報告，結束 **40 modified／57 untracked entries**。原有 **400 個 nonignored public files SHA 全部不變**，全部 dirty work 保留；A1/A6/A8/A5、frozen contracts、H0/HSE、B1-03 OFF／transport guards 都未修改。

不 stage／commit／push／merge，不部署、不付費 Provider、不修改真實遊戲。A7 implementation 仍 DEFERRED。建議下一階段只針對 M2-B1／B2 的 Basic binding／gate 設計與修正另行授權，然後文件與 release candidate acceptance；不藉 M2 重新啟動 Production 或 B1-03。

**BG3Loc MAINLINE M2 — RELEASE BOUNDARY READY FOR REVIEW**
