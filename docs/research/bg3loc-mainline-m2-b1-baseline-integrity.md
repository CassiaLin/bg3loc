# BG3Loc Mainline M2-B1 — Basic Source & Baseline Integrity

日期：2026-10-11。範圍：Windows Basic source/baseline binding；M2-B2、A7、Production SQLite、Provider、B1-03 不實作。

## 1. 結果與核准的契約

M2-B1 已實作：Basic Prepare 建立可信 baseline receipt；Validate／Rebuild／Install 驗原始 bytes bindings，並以 Scan SHA 相符的完整私有 PAK 重新認證 UID/version/text／LOCA origin。Rebuild 實際讀取私有完整素材，不重新開未保護的 external Extract references。來源變動／缺失／receipt 不完整均 fail closed，提示 fresh Scan／Extract／Prepare／Validate，保留 edited returns。

本次先依使用者限制提出 **CCR-B1-01**，使用者明確回覆：**「核准 CCR-B1-01，依提案繼續實作」**。因此新增必要 sidecar 是已批准的相容性變更，而不是利用 generic schema 靜默新增要求。

核准並實作的 `basic-source-baseline/1`：package `internal.bindings` 包含唯一的 `internal/bindings/basic-source-baseline.json` 及實際 file SHA；package container 仍為 1.0，既有 `sourceBinding.extractManifestSha256` 含義不變。新 payload 有獨立 strict schema。舊 Basic package 缺 receipt 明確拒絕，没有 backfill、edited-return 遷移或對變動檔案重新封印。

原始契約審查提案保留 local-only `workspace/mainline-m2-b1/contract-review-proposal.md`。Stage 0 registry／frozen schemas、H0/HSE/HD、manifest／DB 1.3／transport guards 均未變。

## 2. Root cause 與修正位置

原流程保存 Scan／Extract manifest SHA 與 selected immutable rows；但 Extract manifest 只有 material paths，沒有完整 external XML／LOCA／normalized byte binding。`run_workflow_rebuild` 用 recorded extract SHA 作 cache fingerprint，沒有驗 current extract bytes；semantic roundtrip 只保護當次讀到的 baseline。A6 的 PAK snapshot 在 Extract 後 close，A8 只保護當次 repack 的完整 PAK entries，不能補上 Prepare-time origin。

| 檔案／function | 本次改動 |
| --- | --- |
| [baseline.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/baseline.py), `BasicSourceSnapshot`／`prepare_baseline`／`validated_baseline` | 新增 Basic 專用 strict receipt／trusted capture／origin reproof／operation pins＋完整私有 files；沒有 SQLite、execution identity 或 global cache |
| [basic-source-baseline-v1.schema.json](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/schemas/basic-source-baseline-v1.schema.json) | 核准的獨立 Mainline payload schema；拒絕 unknown fields／版本／invalid SHA／bool size；不是 D7／Stage 0 schema |
| [prepare.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/prepare.py), `run_prepare` | Basic fresh package 在可信 capture session 中產生 receipt；reused package 必須具备 receipt 且 current inputs 一致，不自动補 historical evidence |
| [package.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/package.py), `prepare_translation_package` | 新 optional keyword `baseline_binding`，封存於 existing package staging／internal.bindings；direct old calls 的 material projection 不變；不把 paths／receipt 放入 delivery |
| [validate.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/validate.py), `run_validate`／`_run_validate` | 公開 Basic 入口加完整 source gate；原 row／technical QA 核心保持；profile context/full 維持原行為 |
| [rebuild.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/rebuild.py), `run_workflow_rebuild`／`_run_workflow_rebuild` | 先核對材料，含 cache 路徑；actual rebuild 使用 private extract projection；成功 manifest 路徑恢復原始 provenance，沒有 dangling temp references；source failure 标為 failed |
| [install.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/install.py), `run_workflow_install`／`_run_workflow_install` | dry-run/cache/apply 前都加 B1 input closure gate；apply 交接 source pins，讓既有 installer 能替換 target PAK；不改 installer／rollback 演算法或 B2 current decision/cache policies |
| 三份既有 E2E tests | 僅明確區分原有 incomplete/mock archive 的 orchestration／row-QA／CLI-dispatch unit tests；它們不再充當 source-integrity acceptance。新 complete synthetic test module 沒有 mock source gate |

共享 `scanner.py`、`extractor.py`、`source_packages.py`、`rebuilder.py`／A8、`installer.py`、Production modules 沒有修改。沿用現有 scanner canonical resolution、A6 `_ReadPins`／`ScanPackageSnapshot`、normalizer／roundtrip 及 A8 全 entry SHA。

## 3. 可信 baseline 與驗證細節

信任鏈：**state 已記錄 Scan SHA → Scan 的原 source/target/reference PAK SHA／path → 同 SHA 私有 PAK → 完整 original LOCA／XML／normalized／aligned origin proof → prepare-time receipt → package bytes SHA → 消費端 original file SHA／role／origin 重驗。**

Receipt 保存 Scan／Extract manifest SHA、canonical source/target/reference roles，以及完整 `files`：`role`、`localeId`、original path、sizeBytes、raw SHA256。兩語無 reference 時 11 筆（scan/extract/aligned + 每語 pak/normalized/xml/loca）；有 reference 同樣完整綁定。不是只封存被選取的 UID，untouched／target-only／blank baseline 也有來源證據。

拒絕重複 JSON keys、nonfinite values、unknown payload fields／version、wrong/missing/duplicate role、非 deterministic ordering、size/type mismatch、path substitution、wrong source/target/project roles、LOCA entry／package identity mismatch。Payload 的具體檔案集合與 metadata 必須與讀取的 complete universe 相同，不能只靠 `minItems` 或 `semanticMatch=true`。

每次 consumption 同時驗保存的 raw SHA 和 origin。即使模擬把變動 XML 的新 SHA 寫回 receipt、重算 package/state SHA，仍因不符合原 Scan PAK 的 XML／normalized／LOCA 完整內容而拒絕。沒有將 current files 重新 hash 後當作原 baseline，也不從 historical absence 推定 evidence。

語意比較保留 JSON primitive types（例如 version `true` 不能當 `1`），full UID/version/text／provenance／presence 一致；XML full nodeCount、source LOCA exact bytes、normalized full records、aligned complete projection 均核對。既有 UTF-8 text、markup、whitespace、blank、ContentUID、source-only／target-only、target-existing version 優先規則不改。

Windows originals／private copies／projection 都沿用 deny-write/delete pins；Rebuild 的 XML／normalized／PAK 是同一 session 的私有副本。結束前再驗 originals／copies hashes，close 後不能繼續使用。非 Windows 使用同一私有副本与 path/hash recheck；模擬無 Windows handles 的 mutation tests 不等於 native Linux/macOS 驗收。

Apply 時先完整驗證，再保留 source／reference／material pins，交回 target PAK replacement 給既有 installer，避免「保護 baseline」導致合法 atomic replace 永遠被鎖住。Installer 自己的 current target／artifact preflight、verified backup、post-check、rollback 保留；僅對 test-owned synthetic install root 測試 apply/rollback，沒有修改真實 BG3。

**限制**：此改動不是遊戲全域更新鎖，也不是 A7 writer barrier／整體 atomic output publication。來源在操作中變動會讓 B1 failure gate 拒絕；既有 rebuild failure 仍可能留下 work／artifact files，不能使用低階 overrides 誤當當前成功成果。Basic 維持 single-operator／保留原 Extract 路徑；沒有宣稱 detached portability。

## 4. Before／After 與正式回歸

修正前 local-only [test_b1_red.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/workspace/mainline-m2-b1/test_b1_red.py)：6 failed，均為 **DID NOT RAISE**。原 `red.txt`／`red.xml` 保留，不改 xfail/skip。

| 原始攻擊 | 修正後 |
| --- | --- |
| Source PAK 同大小有效替換 | Rebuild 拒絕 Scan SHA mismatch |
| Target PAK 獨立同大小有效更新 | Rebuild 拒絕，無須等 install target check |
| 改 Target XML target-only 文字 | original receipt SHA／完整 origin 拒絕 |
| Extract manifest 指向另一份 XML | manifest SHA 拒絕（相同 XML bytes 換 path 亦拒絕） |
| Source normalized version 1/2/3→99 | receipt／original PAK version proof 拒絕 |
| Target original LOCA 改動 | receipt／original entry bytes 拒絕 |

修正後六項 local probes **6 passed**；正式回歸已納入 [test_basic_baseline_integrity.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_basic_baseline_integrity.py)，不依賴 ignored M2 workspace。最終 35 個 public tests 包含：

- 原六項 + Scan／aligned mutation、missing normalized；初次 rejection 前不建立 rebuild output。
- JSONL/XLSX × 有／無 reference、subset／blank／source-only／target-only、version 7/2/4、full entry hash parity、dry-run 不寫來源。
- unknown receipt version/fields、missing/reordered/duplicate files、bool size／wrong SHA／relative substitution，即使 outer hashes rebound 仍拒絕。
- missing historical receipt 不自動補值、不覆寫 edited returns；source changed 時已有 rebuild artifacts bytes 原封不動。
- gate-to-read 私有 paths、Windows original write denial、close-after-use、模擬無 handles 的 pak/private XML/projection mutation。
- Extract 結束後、Prepare 前的 XML mutation 不會被封為合法 baseline；重算 receipt/package/state 也不能認證變動 XML。
- install 包含 cached path 的 source check、synthetic target pin handoff／原 installer rollback。
- **B2 已知缺陷仍可重現**：cached artifact tampering、new validation FAIL 後舊 rebuild eligibility；這些 assertions 表示限制保留，不是 B2 safety PASS。

既有 incomplete archive unit tests 明確 mock source session，保留 QA／reconciliation／CLI state 原測試目的；只有新 complete integration tests、Native CLI 與上述 RED/GREEN 當 B1 source-gate evidence。沒有大量 exclude／skip 或把 source-integrity 測試改成 mock PASS。

## 5. Native Windows LSLib

使用本機既有 Divine.exe，目錄標示 LSLib v1.20.4，executable SHA `65c47a5050e55f686b55484a901a01d0f1a1d5ba0e776f65fec71d3e1b2a16b7`；probe 未提供 version negotiation，不據此宣稱任意 LSLib version 相容。

修正前、後及最終 origin-reproof 版本各完成真正 Native **synthetic** JSONL／XLSX Basic prepare→回填→validate→LOCA/PAK rebuild→dry-run。每條 scoped 3 source UID；version 7（target-existing）、2（source-only）、4（blank）；scope 外 target-only 保留。原／重建 PAK entry set 一致，三個 non-LOCA payload SHA 相同；game packages 在正常鏈路中前後相同，沒有 real apply／real game／Provider。

另兩項 Native 負向 probes：有效 native Source PAK 更新、外部 target XML 改動，均 CLI exit **76／WORKFLOW_REBUILD_FAILED**；先前 rebuild artifacts SHA 完全不變。这些都在 `SYNTHETIC-game` 隔離目錄，不是玩家的實際安裝。

本機證據：`workspace/mainline-m2-b1/native{,-after,-final}/result.json`、`native*.txt`、`native-negative-result.json`；scripts `native_baseline.py`、`native_final.py`、`native_negative.py`。Native negative 針對 after 版本；最終版本保留原拒絕 gate，且增加 origin reproof，完整最終正常 Native鏈路已重跑。

## 6. 測試結果

| 最終執行 | 結果 |
| --- | --- |
| Source-gate + 原六項 local probes | **41 passed，48.96 秒**（35 public + 6 local） |
| Final targeted：B1、E2E、A1/A6/A8、H0/HSE golden prompt/input/actual messages、HD／Stage2 guards | **297 passed，77.65 秒**；一個 intentional duplicate ZIP warning |
| 完整 public suite，包含 HTTP demo，沒有 exclude／deselect | **1533 passed、75 subtests passed、1 skipped、1 failed、1 warning，468.52 秒**；exit 1，不是 FULL PASS |
| HTTP demo | 唯一 failure 為 `test_public_demo.py::test_demo_accepts_relative_output_from_external_cwd`；3 個 `PROVIDER_TRANSPORT_ERROR` attempts，真實 loopback diagnostic `URLError / WinError 10013` → **ENVIRONMENT-BLOCKED**，未算 PASS |
| Skip | 既有 host symlink 權限限制；未新增 skip 以避開 B1 |

修正前完整 public suite：1498 passed、75 subtests passed、1 skipped、同一 HTTP demo failure，406.20 秒。新增 35 個 public B1 tests 全部通過；沒有額外 regression failure。baseline 與 final logs／JUnit 分開保存，不能將 environment-blocked 計為 PASS。

Windows／JSONL/XLSX Native evidence 已完成；compileall／diff check 通過。HTTP demo 若仍 WinError 10013，分類 **environment-blocked**，不列 PASS。所有測試 Provider 是 mock／本機 fictional demo，不呼叫付費 Provider；真實 BG3 apply／rollback 為 0。

## 7. 相容性、效能與剩餘發布門檻

新 Basic receipt 是使用者已批准的必要契約；舊 package 1.0 未具备 receipt 時，不能直接進安全的 Validate／Rebuild／Install。要求 fresh workspace，而不是讀現在的舊資料自動補 hashes；edited returns 需明確人工保留／rebase，沒有改譯文內容。

原 PAK／Extract 必須仍存在，且 Native backend 在消费階段亦須可用，因現在重新驗 origin。每次操作都有完整 PAK capture／file SHA／origin re-extraction/roundtrip，成本隨完整語言 package 大小增加，而非只隨 UID subset 大小；此階段沒有量測全量真实 Basic 效能，也未為提速降低 fingerprint coverage。不得把 synthetic timings 推論為 full-game throughput。

H0/HSE prompt/input/provenance bytes、HD identity、B1-03 OFF／production stop guards、Stage 0 contracts 與 Production schemas/DB untouched。Context/full evidence profile 的行為不變；Basic receipt 没有套入 Production 或 Legacy D7。

M2-B2 的 cached artifact preflight／failed validation downstream gate **未修復**；B1 會拒絕 cached path 的 Source/Target PAK/material 更新，這只是重疊的 input freshness 保護。A7 implementation **仍 DEFERRED**。文件入口、hosted CI、native 真實小 scope／game load／授權 install/rollback、整體 release/recovery gates 仍待獨立完成；本次不是 Stable Release／Production Activation 核准。

## 8. Git 與工作保存

HEAD／branch：`896b4870b3a24d8506e6d751db3d4602925fb8fb`／`feat/b1-03-dialogue-context`，未變。起始 40 modified／57 untracked，401 份 nonignored public files 保存 SHA seals。

只改 8 個既有檔：e2e 的 package/prepare/validate/rebuild/install + 三份 E2E unit tests；另外 **393 份既有 files bytes 完全相同**。新增 module、獨立 schema、正式 synthetic test module、此報告 4 個 public files；Git **45 modified／61 untracked entries**，包括所有既有 dirty work。沒有清理、staging、commit、push、merge。

原與新所有真實素材／PAK／LOCA／receipt／returns／logs 只在 ignored workspace；Git 只新增程式、規格、synthetic test source／報告。起始 seals、scope audit、before/after logs/JUnit、Native evidence 保留 `workspace/mainline-m2-b1/`。

本機完整證據：`red.{txt,xml}`、`green.{txt,xml}`、`origin.{txt,xml}`、`targeted-final.{txt,xml}`、`full-after.{txt,xml}`、`loopback-after.txt`、`http-classification.json`、`scope-audit.json`；最後兩者與 ending-state 一起保留本機。

**BG3Loc MAINLINE M2-B1 — READY FOR IMPLEMENTATION REVIEW**。B1 可交付實作審查；不宣稱 B2／A7／Stable Release／Production Activation 已通過。
