# BG3Loc Mainline M1-A1 — Locale / Material Integrity

執行日期：2026-10-10–2026-10-11（Asia/Taipei）。
Repository：`CassiaLin/bg3loc`。Branch：`feat/b1-03-dialogue-context`。
HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`，未變更。

## 1. 結論與授權範圍

**A1 技術缺陷已修正，建議在本次 Implementation Review 接受後結案。** Scanner inventory 的 canonical locale ID 現在貫穿 Extract、manifest、Build、Workflow package，以及 full-profile research forwarding。無效／歧義角色、資料不一致或生成素材失去 source／required binding 時會拒絕正常發布。

僅處理 A1。未修改公開 schemas／版本、B1-03 frozen contracts、Prompt、H0/HSE/HD identity algorithms、人工 review policy 或 transport guards。A2–A9、B1-03 activation 與其他發布缺口沒有因此結案。

## 2. Root cause 與修正前重現

`run_extract` 原本透過既有 `_index_locales` 的 casefold key 找到 scanner entry，例如 `english` 解析為 `localeId="English"`，並以 English 寫 normalized／aligned data。但 manifest 的 `sourceLocale`／`targetLocale`／`referenceLocales` 卻直接使用 request 原始拼法。

`build_material_row` 與 `prepare_translation_package` 以 manifest role 字串對 aligned locale map 做精確 lookup。因此 `locales.get("english")` 找不到實際 `English` key，SourceText 變成空字串，TranslationRequired 變 false；程式仍發布成功。

修正前先建立正式 `tests/test_locale_material_integrity.py` 回歸。第一組八項測試在修正前得到 **6 failed、2 passed**：兩種 alias 的 low-level／workflow source-count 檢查失敗；Build／Package 對 malformed role manifest 也沒有正確拒絕。合法 canonical 兩條路徑通過。

本次另建立隔離 before-source snapshot：四個修正前的核心 module bytes 經 Git HEAD 與 task starting seals 核對，其餘既有 dirty source 保留。用同一組 native synthetic PAK 實際執行 before／after CLI，沒有依舊報告 PASS 推定结果。

## 3. 修改檔案與 functions

| 檔案／實際位置 | 修改 |
| --- | --- |
| [extractor.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/extractor.py:32), `run_extract` | 在 extraction 邊界解析 canonical IDs；manifest 三種 role 使用 resolved IDs，normalized／aligned 的 ID 與輸出一致 |
| 同檔 `resolve_locale_roles`（250） | **沿用 `_index_locales`／scanner inventory**，不新增硬編碼語言表或另一套 aliases；保留 case-insensitive 輸入，拒絕未知、重複角色、多 provider 與非 ready provider |
| 同檔 `material_locale_roles`（268） | 消费 extract manifest 時驗 canonical roles；舊版本 bug 產生的 lowercase role manifest 明確拒絕並要求 re-extract，不默默改寫已有資料 |
| 同檔 `validate_material_locales`（276） | 驗 aligned canonical keys／UID、locale text、完整 role count；normalized sidecars 可用時核對 locale identity、UID/text/version projection；explicit subset 驗選定的 projection |
| 同檔 `validate_material_projection`（340） | 在素材發布前核對 UID/count、SourceLocale／TargetLocale、SourceText、TranslationRequired，以及有輸出的 source/target version／existing text；blank source 仍保留原本 required 語意 |
| [builder.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/builder.py:43), `run_build` | 建材前驗 input；寫正常 output 前驗 material 與 immutable projections。使用既有 BuildFailure／exit code，不變更欄位或 candidate generation |
| [e2e/package.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/package.py:235), `prepare_translation_package` | scope 選取後驗 locale input，再驗 delivery／immutable material；錯誤不得發布正常 package |
| [e2e/prepare.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/e2e/prepare.py:43), `run_prepare` | 新建／reused extract 均驗 role；其 casefold semantics 必須符合 project。下游 research 使用 canonical roles；不重寫使用者 config 或改其 SHA canonicalization |
| [test_locale_material_integrity.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_locale_material_integrity.py) | 新增45項持續自動回歸，全部 synthetic |
| [test_e2e_workflow.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_e2e_workflow.py), `fake_extract` | 原本 `{}` 的 mocked extract 補上該 test 已宣告的 roles／inventory，讓 checkpoint 測試使用有效角色資料；原行為斷言維持 |
| [test_validate.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_validate.py), `_build_many_csv` | 原 fixture 擴增到100 rows 卻仍宣告 nodeCount=2；改為對應實際 fixture 的 row_count，原 partial-return／coverage 斷言維持 |

沒有更動 Scanner discovery、public manifest fields 或 schemaVersion。新的檢查落在既有資料的語意一致性，不是新增 locale registry 或翻譯政策。

## 4. Before / after 與資料完整性

Native synthetic fixture：English 3 records、French 3 records、German 2 records；union 5 UIDs。English 包含一筆真正的空字串，因此 non-empty SourceText 是2筆，但 required 必須是3筆。使用本機既有標記 `LSLib-v1.20.4` 目錄的 Divine.exe 進行實際 PAK／LOCA 轉換與 CLI，不是以 fake archive codec 代替這份 native 證據。

| 階段／輸入 | Extract roles | Low-level rows／required／non-empty SourceText | Workflow XLSX required |
| --- | --- | --- | ---: |
| Before：English／French／German | canonical | 5／3／2 | 3 |
| Before：english／french／german | lowercase | 5／0／0 | 0 |
| Before：eNgLiSh／FrEnCh／gErMaN | mixed case | 5／0／0 | 0 |
| After：canonical | English／French／German | 5／3／2 | 3 |
| After：lowercase | English／French／German | 5／3／2 | 3 |
| After：mixed case | English／French／German | 5／3／2 | 3 |

**VERIFIED：** canonical before／after 的 low-level JSONL material 與 immutable sidecars **byte-identical**；high-level XLSX cells／headers 相同。After 三種輸入拼法也產生相同的 JSONL／immutable bytes 和 XLSX cells。XLSX zip metadata/timestamps 沒有冒充 byte-parity 證據。

ContentUID、原文、現有 target text、source version、target version均保留。共享 UID 的 source version1／target version7、source-only version2、空 source version3／target version4都不因角色解析改變。未生成新翻譯，未呼叫 provider，未读取或修改真實遊戲文本。

自動回歸除正確拼法外，確認以下錯誤拒絕正常 output/package：未知 source／target／reference、歧義或 unsupported provider、同 locale 的不同大小寫 provider／role、非canonical aligned key／duplicate key、source cells 全部變None、aligned text／version與normalized不一致、nodeCount不一致、normalized locale錯誤，以及有宣告資料的空 aligned array。

Fault-injection 的 material producer 若抹除 required／source／target、修改 source/target version 或 UID，發布前會被拒絕。Cached broken role manifest 也不會回傳「成功」，已有 package bytes保持不變。

## 5. Legacy compatibility 與空範圍界線

- **合法 canonical 輸出保持**：native before／after parity與原有 CSV/XLSX/JSONL tests 支持；schema／欄位／immutable語意未變更。
- **保留 aligned-only v1 consumer**：沒有增加 mandatory normalized-file availability 相依性；舊 material workflow 可能只有 aligned data 與 inventory。full alignment 必須對應既有 nodeCount；sidecar一旦可用，就必須與其實際 projection一致，不可忽略 malformed data。
- **Explicit subset**：只核對選定 UID 的來源／目標 projection。source rows存在於完整corpus，不表示 target-only 或 reference-only subset 必須有 source；這兩種合法子集 required=0可通過。
- **Blank source**：source record存在但 text=""，仍如既有行為 required=true；不以 non-empty text數量代替來源record數量。
- **空 UID list**：現有 project schema 的 minItems=1及 direct package zero-row scope拒絕維持。未新增「空 scan／空source extract」支持，也未變更公開 schema來合法化與非零nodeCount矛盾的空 alignment。
- **舊 bug artifacts**：lowercase role manifest 不屬於一致的 canonical extract。Build／Workflow會明確拒絕，需由玩家重新 extract／prepare；不改其原文、UID、翻譯或既有返回檔，沒有自動 migration。
- **Project config**：保留使用者輸入拼法與原有 config identity；正式 extract／package及 runtime research roles使用 scanner-resolved IDs。已有schema與hash算法不變。

未發現需要改版公開 manifest 或 frozen compatibility contract 的情況，因此沒有進行 Contract Change。若要進一步支援新的 empty-source 格式、通用locale alias表或自動遷移，需另外評估及授權。

## 6. Targeted / full regression

| 測試 | 結果 |
| --- | --- |
| 正式 pre-fix reproducer | **6 failed、2 passed**，確認低／混合case失去source及malformed角色未拒絕 |
| Fresh targeted | **199 passed、7 subtests passed，18.41s**；包括A1、extract/build/validate/rebuild、E2E config/workflow/CLI、B1-02及H0/HSE parity／B1-03guards |
| 新增 full-profile forwarding | **1 passed，0.96s**；research scan/map收到English／French／German，raw project config不重寫 |
| Full available | **1296 passed、1 skipped、75 subtests passed，305.95s**；45項A1 regression全部通過 |
| Skip | `test_d7_corruption_rejected[link]`：host不允許建立symlink；不是PASS |
| HTTP demo獨立重跑 | **environment-blocked**；1 failed／7.65s，3 attempts皆PROVIDER_TRANSPORT_ERROR／WinError10013，不列PASS |
| Native corpus範圍 | native synthetic 6 cases，low-level JSONL及high-level XLSX，before/after parity；真實corpus／provider calls為0 |

Targeted涵蓋input大小寫、unknown/ambiguity、Scan→Extract→Build、Project→Workflow Prepare、完整與subset binding、source失去required、合法zero-required subset、legacy aligned-only、cached broken roles。Full回歸亦包含既有H0/HSE effective prompt／actual messages／input fingerprints、HD identity／provenance／semantic REVIEW／transport stop guards；本階段沒有放寬它們。

初次 expanded targeted 的四項失敗已釐清：三項是 `_build_many_csv` fixture 的 stale nodeCount，另一次是新 cache 測試誤以為CLI會raise，而實際正確返回73。只修正fixture metadata／test assertion，沒有降低production guard；後續targeted及full全部通過。Synthetic試驗不是人工語意review或general safety validation。

Local-only可重現證據：`workspace/mainline-m1-a1/` 的 starting seals、pre-fix JUnit/log、targeted/full JUnit/log、HTTP classification、native CLI log／before-source／summary、preservation audit。所有遊戲形狀素材均為 synthetic；真實corpus及先前sealed workspaces不使用。

## 7. Git／保留狀態

Starting：21 modified／37 untracked status entries；379個既有tracked或non-ignored untracked files SHA封存。

Task delta只包含上述四個production module、兩個既有test fixture helper、新A1 test module與本報告。373／379起始檔案byte-identical；其餘六個即上述授權範圍。既有Stage0–5、S5-R1與Mainline Audit成果保留，所有原本dirty的檔案仍維持起始bytes。

**最終確認：27 modified／39 untracked entries**（包括所有先前dirty work）；`git diff --check`及新檔whitespace檢查通過。完整status／preservation audit保持本機。HEAD與branch不變。未commit、push、merge或開啟provider transport；A2–A9未修改。

## 8. A1 結案建議

**YES — 建議 Implementation Review 接受後將 A1結案。** Canonical resolution、source/material binding、native重現與legacy合法輸出相容性都有直接證據；環境blocked的HTTP demo與A1資料解析無關，已獨立保留限制。

這不是公開release或B1-03 activation批准。主線其他已發現缺口仍需各自授權與验收。

**BG3Loc MAINLINE M1-A1 — READY FOR IMPLEMENTATION REVIEW**
