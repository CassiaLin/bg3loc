# BG3Loc Mainline M5 — Git Integration & RC Version Plan

日期：2026-10-11。M4 Source & Package Audit：使用者 ACCEPTED / CLOSED。RC目標 **1.4.0rc1 版本計畫已核准，尚不修改檔案**。

**本次只有差異審查、整合設計及唯讀驗證。** 不stage、commit、push、merge、tag、release、reset、clean、discard或checkout既有工作；不修改程式、版本、frozen contracts、Prompt或transport guards。

## 1. M4來源完整性與新增文件

HEAD：896b4870b3a24d8506e6d751db3d4602925fb8fb；branch：feat/b1-03-dialogue-context。M4 snapshot SHA256：42f6a0421bf4ed64291f231b1aa717dce32e2478af24f15c76d7920a5f6763c9。

以 [M4完整source inventory](bg3loc-mainline-m4-rc-source-inventory.json) 的path、size、SHA、gitStatus逐檔核對：**413 / 413個M4原始公開檔案保持一致，無遺失、status drift或版本變更**。目前比M4 snapshot僅增加下列兩個M4交付物，並非M4後的程式變更：

| New M4 file | SHA256 |
| --- | --- |
| docs/research/bg3loc-mainline-m4-rc-package-audit.md | 6aaeefe04f2d9551ebdd2d511f5710b15571f0a1b0f56b00da7e93375864fd8e |
| docs/research/bg3loc-mainline-m4-rc-source-inventory.json | 993f32d92befea6cc49db01b1c85e731101f87a5141ab19f9be09b69059a7b96 |


起始公開來源415 files；Git directory-level為53 modified／70 untracked entries，展開為 **130 dirty files：53 modified + 77 untracked**。與M4結束status相同；128個M4 snapshot dirty files，加上上述2份報告。M4報告／inventory中的歷史SHA及1.3.0 audit-build紀錄不改寫。

本報告是M5唯一新增公開檔，歸C4文件組；其hash不做自我引用，另存local ending audit。附錄含全部130個起始dirty paths、proposed group及SHA prefix；完整SHA已在M4 inventory或上方兩個新增文件核對表。沒有未分類或默默排除的dirty檔案。

## 2. 實際diff／logical review groups

讀取全部53個tracked diff：**1862 insertions、618 deletions**；對全部49個modified/new runtime Python modules比較HEAD AST與目前source，列出新增／改動／移除symbol及新增imports。不是只依前階段PASS分類。完整diff、506條實際import edges（含function-local／conditional imports）及per-symbol mapping保留於local證據。

| Logical group | 實際diff/入口 | Proposed physical commit |
| --- | --- | --- |
| L1 Basic shared：A1/A6/A8 | builder.run_build新增role/projection checks；extractor新增canonical角色／material一致性及source snapshot extraction/publication；source_packages新增pins／private capture；rebuilder.repack_target_package新增全entry SHA與atomic candidate | C2 |
| L2 Basic Workflow：M2-B1/B2 | e2e.package增加optional baseline_binding／internal.bindings；prepare receipt與reuse檢查；baseline/eligibility新增；validate/rebuild/install exact-current binding／history-failure isolation | C2 |
| L3 Production safety：A2/A5 | provider/worker/execution-state safe diagnostics；ProductionReviewStore.resolve/get_current_acceptance、QaStore cache與completion/current material驗證，歷史NULL語意不補 | C3，同L4整檔整合 |
| L4 B1-03 retained OFF | DTO/materializer、grouped prompt/identity、provenance/SQL additive欄位、QA semantic REVIEW、portable/sealed helpers、1.3 stop guards；frozen authority與schemas保留 | C3，同L3整檔整合 |
| L5 CI/Packaging：A3/A4 | ci.yml pytest matrix、pyproject test extras、MANIFEST及CI tools/test；不改current版本 | C1 |
| L6 Public docs/tests/history | Public docs/history歸C4；tests跟所驗證code歸C1/C2/C3；現有5個public fixtures在HEAD已tracked，保留 | C1–C4 |
| L7 RC version/notes | 目前尚無版本diff；下節列最小future變更，歷史文件不替換 | C5，須下一階段檔案修改授權 |

檔案可屬多個logical groups。尤其e2e/package、prepare同含A1/B1/B2；execution_runner、provider、QA/review/completion同含A2/A5/Stage3/R1。**不建議用目前整檔做逐階段cherry-pick，或臨時hunk splitting重造舊stage state。** 下列sequence採完整目前檔案的已接受結果，配合相依模組/schema/tests同批納入。若堅持更多小commits，需另行設計hunk-level intermediate snapshots與完整行為驗證，不能從本計畫推定它們可用。

## 3. Proposed commit sequence

C1→C2→C3→C4→C5是建議順序，不是本次Git操作。C1–C4 path sets disjoint、聯集涵蓋全部130個起始dirty files；C5重訪部分已整合檔案，只修改version/notes。各commit仍須在下一階段實際stage前重新核對SHA及diff。

| Commit | Proposed title | 當前dirty files | Prerequisite / minimum gate |
| --- | --- | ---: | --- |
| C1 | test: run full pytest and preserve public sdist fixtures | 8 | HEAD；explicit test extras、CI/tools及CI tests一起；collection/import、CI/package targeted |
| C2 | fix: bind Basic source materials and current workflow eligibility | 23 | C1；A1/A6/A8與B1/B2一起，Receipt/schema/pins及11個test modules不可漏；Basic JSONL/XLSX、negative mutations、A8 entry parity |
| C3 | fix: retain guarded dialogue support and current Production decision evidence | 62 | C2；L3+L4整個相依群、Stage0書面authority+5個normative檔、2個runtime schemas、相關tests；H0/HSE、HD/guards、A2/A5/R1 regression |
| C4 | docs: define Windows Basic release scope and retain audit history | 37 + 本M5報告 | C3；雙語docs/examples、全部research/history與M4 inventory；link/privacy及full available/package gates |
| C5 | chore: prepare Windows Basic 1.4.0rc1 metadata and release notes | 尚未產生 | C4；下節8-path proposal，版本一致性、producer metadata、full tests／wheel/sdist rebuild及privacy |

C1包括CI/docs testing；C2包含所有11個Basic runtime/shared檔、Receipt schema及11個tests；C3包含其餘38個runtime檔、2個runtime schemas、Stage0目錄5個檔、freeze Markdown authority與16個tests。C4為其餘公開文件／範例／歷史 reports。對照附錄可逐檔追溯；新增模組不靠ignored workspace提供。

C3不是新的Activation：retained means編碼／研究保留，OFF／reject仍存在；同批整合是import／interface closure需要，不能省略guard來讓中間commit看似可用。

## 4. Dependency / import closure 實證

| Actual edge / shared interface | 分組含意 |
| --- | --- |
| builder / e2e.package → extractor.validate_material_locales / validate_material_projection → source_packages | A1、A6與Basic material consumers放C2 |
| e2e.prepare/package → baseline.BasicSourceSnapshot / RECEIPT_PATH → source_packages._ReadPins；Receipt schema | prepare與Receipt materializer不能分開或漏schema |
| eligibility → e2e.validate（local import）；validate/install/rebuild → eligibility/baseline | B1/B2互相依賴，whole-file C2；不能只升級dry-run入口 |
| providers.openai_compatible → translation_send → prompt_assembly/chat_prompt/dialogue_prompt/PromptProvenance | A2目前provider檔混入Stage3 actual-send，單獨套檔不完整 |
| execution_runner → provider_diagnostics + dialogue execution guard + PromptProvenance/ExecutionStore新欄位 | worker/privacy/provenance界面一起C3 |
| production_review → dialogue_review + dialogue_context + qa_state；qa_state/completion/review → legacy_qa_material | A5現有檔案已含HD gate及current material依據，不能只移植resolve |
| TranslationRequest / identity / prompt_assembly / chat_prompt → typed dialogue DTO/projection/contract | 保留HD branch及typed helpers；H0/HSE不走HD branches，不能刪DTO |
| production_orchestration/finalize/workspace → production_dialogue_prepare / portable_finalize / sealed_snapshot | 進階retained helpers與runtime schemas不可漏；不是A7 remediation |
| Stage0 tests → version-registry / synthetic goldens / frozen JSON schemas | Normative files與相關tests一起C3；不是可選私有workspace |
| public tests → existing sibling synthetic fixture helpers | tests跟code整合，不只收集新tests而漏共享helper；sdist graft保留 |

另在C2 prefix做兩個**故意不完整**的負向import probes：只載入目前production_review.py→缺bg3loc.dialogue_review；只載入目前OpenAI provider檔→缺bg3loc.translation_send。兩者預期ModuleNotFoundError確認上述whole-file coupling，不是新缺陷或真實工作樹修改。

### Prefix rehearsal（不是Git commits）

只讀git archive HEAD bytes，在ignored workspace/mainline-m5/建立普通prefix目錄，按計畫overlay已核對的public bytes。沒有.git、worktree註冊、staging／commit/object/ref建立，沒有checkout或hunk edits。正式freeze Markdown authority前移C3後，cumulative source仍一致。

| Cumulative prefix | Proposed new paths | Importable bg3loc submodules | pytest collect-only |
| --- | ---: | ---: | --- |
| C1 | 8 | 105 PASS | 897 PASS |
| C1+C2 | 23 | 108 PASS | 1070 PASS |
| C1+C2+C3 | 62 | 124 PASS | 1558 PASS |
| C1+C2+C3+C4 | 37 | 124 PASS | 1558 PASS |

每個prefix核對import root來自該copy/src，全部submodules可import、CLI parser可建立。**只證明import/collection closure，沒有宣稱各intermediate commit全部行為／full tests PASS。** C4資料累積與130-file map完整一致。本次不改版本，四個prefix都仍1.3.0；C5沒有提前模擬版本改寫。

HEAD archive與本機checkout有29個未修改檔案只差CRLF/LF；130個dirty overlays全部bytes一致，其餘未修改檔案相同。這是Git blob／checkout representation差異，不是把M4 source變更丟掉；本機原415個files完全未改。詳細清單在newline-differences.json。正式stage前記錄git attributes/core.autocrlf與index blob SHA，從resulting commit重新source inventory/build並驗H0/HSE parity；不得手動改newline設定、重寫frozen檔案或把M4工作檔SHA當新commit的同一hash。prefix驗證只接受此已核對的newline差異，不推定所有byte-level資料都能任意normalize。

M4已接受的完整回歸仍是1556 passed／1 failed（HTTP WinError10013）／1 skipped（symlink host權限），不是ALL PASS。M5沒有重跑full suite；下一階段每實際code commit仍要適當targeted checks，最終candidate完整available及packaging regression不可省。HTTP不得忽略、hosted四jobs仍NOT VERIFIED，Windows長路徑及research BOM限制保留。

## 5. 1.4.0rc1最小version proposal

已核對所有public source中的1.3.0、__version__、CREATED_WITH_VERSION references（25個startup matches）及M4實際wheel metadata。**Package release version與workspace/DTO/identity version是不同軸，不能全域取代1.3或/1。**

| Source | Current evidence | Future action |
| --- | --- | --- |
| pyproject.toml:7 | project.version=1.3.0；現有dirty diff只有test extras，沒有version bump | 在C5獨立改1.4.0rc1，保留C1 extras |
| src/bg3loc/__init__.py:5 | __version__=1.3.0 | 同C5改1.4.0rc1 |
| src/bg3loc/cli.py:6/22 | --version引用runtime，非第二個固定字串 | 不改CLI；用新wheel console/module實測1.4.0rc1 |
| Wheel dist-info / sdist PKG-INFO / filenames | M4 audit artifacts均1.3.0；setuptools由pyproject產生 | 從核准source fresh build，不手改METADATA、不重命名舊archive、不提交egg-info |
| src/bg3loc/research/portable_translation.py:29 | CREATED_WITH_VERSION=bg3loc-1.3.0，export_package當下生成createdWithVersion；safety_validation import它 | 建議C5只改producer stamp為bg3loc-1.4.0rc1，保持固定常數方式，不重構功能 |
| CHANGELOG.md／zh-TW | 頂端1.3.0 - 2026-09-28是已發生release記錄 | 新增1.4.0rc1未發布段落，不改舊1.3.0日期／tests／acceptance |
| docs/getting-started.md／zh-TW:19 | 「目前checkout reports 1.3.0」是current描述 | C5改為candidate1.4.0rc1／source+checksum提醒，不升格Stable或game-load accepted |
| docs/releases/ | 歷史v1.0–1.2 notes；目前沒有1.4.0rc1檔 | 新增雙語docs/releases/v1.4.0rc1.md，僅draft notes，無發行日期／tag宣告 |

**建議C5最多8個paths**：pyproject、runtime init、portable_translation producer stamp、雙語Changelog、雙語current入門、1份新雙語release notes。不是8個已授權修改；M5只核准version計畫，實際metadata/docs寫入需下一階段授權明列這份scope。

Producer stamp不是歷史檔：目前export_package與safety export會新生成它。兩個schemas對createdWithVersion只有nonempty string，沒有固定1.3.0 const；requestPackageFingerprint在兩個exporters都是digest(requests)，不含producer stamp。因此提案只更新新輸出的producer provenance，不修改sample salt/order、requestIds、requests/prompt bytes或fingerprints。**舊研究package、assignments、response及receipt完全不重寫／重新匯出。** 此改動仍需portable/safety metadata＋request-fingerprint regression，不以「只是版本」略過。若另有契約authority要求literal保持，停止該path並做CCR，不默默漏掉stale producer reference。

必須保留：M1–M4/B1-03 reports與M4 inventory的1.3.0/source SHA/artifact hashes，歷史Changelog／release notes／capturedFromHead goldens與驗收計數。Stage0 registry、Manifest/Execution DB1.3、dialogue-context/1、dialogue-prompt/1、translation-input/2與/3、basic-source-baseline/1、H0/HSE canonical algorithms不變。

Future notes需明確寫：Windows Basic外部回填→Validate→Rebuild→Dry-run；A1/A6/A8/B1/B2、A2/A5 shared safety、pytest/distribution closure；舊workspace缺Receipt需fresh prepare並保留returns。A7 implementation DEFERRED／未修復，Production Provider/Finalize、B1-02/B1-03 Activation未列首版驗收；OFF/guards不解除。四hosted jobs／HTTP、真實Windows Native唯讀及另行授權Apply/Rollback/game-load仍待驗收，不能寫成已發布Stable。

## 6. Include / exclude / integrity gates

**Include：** 附錄130 paths與本M5文件；所有新增runtime modules、normative/runtime schemas、public tests、CI helpers、docs/examples/history。HEAD既有5個synthetic fixtures已tracked，SHA比M4一致，不必假造duplicate diff，sdist必須繼續graft保留它們。Future C5另產生的8-path changes逐項審查。不得用git add .／-A作為無審查的實施捷徑。

**Exclude：** ignored workspace、copied prefix trees、logs、wheel/sdist/build/dist、venvs、egg-info、短-path temp dirs、真正PAK/LOCA、SQLite、API secrets、Divine EXE/DLL、local corpus／assignments／responses／unblind mappings。歷史docs中的路徑／filename說明不代表包含實際檔案。用explicit path allowlist，不靠排除後重新算SHA來認證被改的材料。

**VERIFIED：** 全部M4 code/schema/frozen bytes一致；Basic Receipt schema與baseline.py仍basic-source-baseline/1；現有git-visible資料只有public規格／程式／synthetic tests與文件。起始source path inventory、collision/forbidden-pattern/credential-pattern檢查通過；5個fixture維持M4 SHA。新2個M4docs只有報告及filename/hash inventory，無corpus。privacy pattern掃描不是未知secret的絕對證明；stage前仍須review exact paths/diff及實際artifact contents。

**H0/HSE：** 實際diff保留原payload／instructions，HD欄位及safety只在dialogue-present分支加入；兩family同時存在fail closed，absence不serialize null。原HEAD→整合diff本身新增guard／HD功能是已接受工作，不能說所有prompt檔跟HEAD bytes相同。正確保證是M5比M4 bytes未變、H0/HSE輸出parity需保留golden regression；C3不得改寫已接受分支或降低guard以解import。

**B1-03：** cli project default basic/standard；Basic不建立TranslationRequest/HD或SQLite；宣告1.3仍由verify_production_workspace/reject_dialogue_execution及worker拒絕。完整prepared/offline 1.3 technical helpers保留不等於Activation。Freeze authority／normative schemas／program fingerprints不變。

**A7：** 仍DEFERRED。M2 boundary表與目前README/教程已排除Legacy Production Finalize首版驗收；future RC notes須再次明寫A7未修復。不能把B1-03 portable assets/writer barrier當legacy A7解決方案，亦不新增Basic feature split或native跨平台支援。

## 7. Rollback / recovery 設計

- 操作前再保存nonignored source SHA、完整dirty statuses、explicit group allowlist與candidate copy；private workspace／遊戲資料不打包進公開backup或Git。
- 若下一階段獲准實施，優先在**另行核准的隔離integration checkout/branch**，以這次已核對的source bytes overlay分組，保留原dirty checkout。具體branch名/base SHA及建立方法要明確批准；不在本次創建，也不默認複製ignored research資料。
- 每組stage後核對staged paths、diff、dependency closure與指定tests，再commit。SHA drift／意外extra file／missing import／frozen mismatch立刻停止；只在授權的隔離區處理本次stage，不以reset/clean/force checkout丟棄共享工作樹。
- 尚未commit的失敗保留diagnostics與候選copy；重試前人工比對group，禁止從歷史artifact假裝當前成功。已commit後若需復原，另行授權新增revert commit或新candidate branch，不重寫已分享history、不force push；不得假設可git revert跨相依群而保留可用中間狀態。
- Commit/source差異變動會使M4 archive SHA不再適用；回到核准source重新build/verify，不restore舊1.3.0 wheel當新RC。遊戲Apply/Rollback不在Git recovery範圍內，永遠另行授權。

## 8. 下一階段需要的明確授權

1. 是否准許建立隔離integration checkout/branch、確切branch name/base HEAD、保留original dirty tree及source overlay方法。
2. 准許explicit C1–C4 path groups實際stage/commit（含本M5報告），採合併C3的L3/L4相依群；各驗證失敗的停止條件與HTTP/symlink環境例外必須記錄，不能偽造PASS。
3. 准許C5那8個paths的實際version/docs/producer-stamp修改與commit；不是授權改Prompt、identity、frozen schema、guards或其他bug remediation。
4. 准許從exact resulting commit本機build/clean install/privacy/full regression並保存new source/artifact hashes。這仍不准許tag或正式發布。
5. Push／hosted CI dispatch、merge、正式tag、GitHub/PyPI release、Native實際game Apply/Rollback及Production Activation全部分開授權。本M5及version計畫核准都不能替代它們。

建議先核准本計畫與局部stage/commit／metadata實施範圍，待candidate內容及tests可審查後，再決定push與hosted四jobs；沒有任何Git/network寫入已執行。

## 9. 驗證與Git status

本次static diff/AST/import審查、四個prefix import/collection及兩個故意不完整negative import probes已完成；沒有provider calls、game scans/writes、重新翻譯或full suite重跑。曾讀git show/diff/status/archive，全是只讀；未stage、建立commit/object/ref或worktree。

**415個起始公開檔案SHA全部保持一致**：含413個M4 snapshot files，以及2個M4報告／inventory，後者另與M4 final-audit原始SHA逐項比對一致。130個原始dirty statuses完全保留；唯一新增為本M5報告。最終Git為 **53 modified／71 untracked directory-level entries**，展開131 dirty files，staged files為0；HEAD／branch不變。版本仍1.3.0。沒有刪除／覆寫原檔、改Production Code或frozen contracts、Git staging／commit／push／merge／tag／release、paid Provider或遊戲修改。最終Git reads關閉optional locks；不修改Git config。

Local-only證據：ignored workspace/mainline-m5/的starting-state.json、tracked-diff.patch、dependency-map.json、version-references.json、commit-groups.json、prefix-validation.json、prefix checks/logs、partial-group-negative-probes.json、privacy-check.json與ending-state.json。普通prefix copies不是Git commits，不能當作已完成實際整合。

## 附錄A：完整130-file mapping

M=tracked modified，U=untracked。C1–C4合計130；hash prefix只供閱讀，fullSHA來源是M4 inventory與本報告section1的新M4 files表。

| Status | Proposed commit | Path | SHA256 prefix |
| --- | --- | --- | --- |
| M | C1 | .github/workflows/ci.yml | feca07379185a0c8 |
| M | C1 | MANIFEST.in | 1c39103a85dfe58e |
| M | C4 | README.md | dd21b13de6d7d7ea |
| M | C4 | README.zh-TW.md | a1e3cbf3a9441a50 |
| M | C4 | docs/concepts/archive-backends.md | 1ac72c741e90fd20 |
| M | C4 | docs/concepts/archive-backends.zh-TW.md | b7df44d052110d09 |
| U | C1 | docs/development/testing.md | 49b77cfd551bb88f |
| M | C4 | docs/e2e/high-level-cli.md | d059d02d7bfa4c48 |
| M | C4 | docs/e2e/high-level-cli.zh-TW.md | 5af05a5cfc344081 |
| M | C4 | docs/getting-started.md | 00a2fadd5710e0c8 |
| U | C4 | docs/getting-started.zh-TW.md | a906c1950113affb |
| U | C4 | docs/production-getting-started.md | e0d143f3be2cdb3a |
| U | C3 | docs/research/b1-03-production-contract-freeze.md | 25cb1ecfbeebc6bc |
| U | C4 | docs/research/b1-03-production-integration-design.md | 7e747ed1c76d7db9 |
| U | C3 | docs/research/b1-03-stage0-contracts/dialogue-context.schema.json | 452cd24666047806 |
| U | C3 | docs/research/b1-03-stage0-contracts/finalize-assets.schema.json | ca4715811a6df8f8 |
| U | C3 | docs/research/b1-03-stage0-contracts/production-manifest-1.3.schema.json | 32cc534e2245821f |
| U | C3 | docs/research/b1-03-stage0-contracts/synthetic-existing-goldens.json | a059a5d142bf7585 |
| U | C3 | docs/research/b1-03-stage0-contracts/version-registry.json | 2ac0d66f794d5491 |
| U | C4 | docs/research/b1-03-stage1-implementation-review.md | ff5f640e019e89a1 |
| U | C4 | docs/research/b1-03-stage2-implementation-review.md | 4c6d07ca4381c609 |
| U | C4 | docs/research/b1-03-stage3-implementation-review.md | 89be2a84e288a55b |
| U | C4 | docs/research/b1-03-stage4-implementation-review.md | 10ac16dee890185b |
| U | C4 | docs/research/b1-03-stage4r-activation-blocker-remediation.md | 376efb7c4414b4e5 |
| U | C4 | docs/research/b1-03-stage4r-case006-semantic-regression-adjudication.md | 3fe79cc663051940 |
| U | C4 | docs/research/b1-03-stage4r-final-engineering-acceptance.md | 670dac9040d002b0 |
| U | C4 | docs/research/b1-03-stage5-production-activation-review.md | 5ff9852ed40bf5cb |
| U | C4 | docs/research/b1-03-stage5-r1-decision-integrity-remediation.md | e56dc6b01237ec99 |
| U | C4 | docs/research/bg3loc-mainline-m1-a1-locale-integrity.md | d59315165bbb18ac |
| U | C4 | docs/research/bg3loc-mainline-m1-a2-provider-error-privacy.md | f283d79309b3cebf |
| U | C4 | docs/research/bg3loc-mainline-m1-a3-a4-ci-packaging.md | 785c2ee46ae5f95f |
| U | C4 | docs/research/bg3loc-mainline-m1-a5-legacy-review-design.md | bf007c65c2cb590b |
| U | C4 | docs/research/bg3loc-mainline-m1-a5-legacy-review-remediation.md | 2b43c54647a21497 |
| U | C4 | docs/research/bg3loc-mainline-m1-a6-source-freshness.md | 06b3258432dc63ec |
| U | C4 | docs/research/bg3loc-mainline-m1-a7-finalize-design.md | 75f5326a814e6cab |
| U | C4 | docs/research/bg3loc-mainline-m1-a8-pak-integrity.md | 3cef50e98cc6965f |
| U | C4 | docs/research/bg3loc-mainline-m2-b1-baseline-integrity.md | ec5ccbb20f25b596 |
| U | C4 | docs/research/bg3loc-mainline-m2-b2-workflow-state-integrity.md | 4d5dc86511bf45a4 |
| U | C4 | docs/research/bg3loc-mainline-m2-windows-basic-release-boundary.md | 5f41c68a1bb5f92f |
| U | C4 | docs/research/bg3loc-mainline-m3-public-docs-rc-readiness.md | aadf357a4814234f |
| U | C4 | docs/research/bg3loc-mainline-m4-rc-package-audit.md | 6aaeefe04f2d9551 |
| U | C4 | docs/research/bg3loc-mainline-m4-rc-source-inventory.json | 993f32d92befea6c |
| U | C4 | docs/research/bg3loc-mainline-readiness-audit.md | c4ee5b3b4b4ad63f |
| M | C4 | docs/troubleshooting.md | a4ffc8a24bd45f56 |
| U | C4 | examples/windows-basic/README.md | d5225f8bc1ff82ed |
| U | C4 | examples/windows-basic/returned-row.example.jsonl | 513c547e573e41e6 |
| M | C1 | pyproject.toml | 9df1b5a104abf3c6 |
| U | C2 | schemas/basic-source-baseline-v1.schema.json | 0c970e32627bc846 |
| U | C3 | schemas/production-finalize-assets-v1.schema.json | ca4715811a6df8f8 |
| U | C3 | schemas/production-manifest-v1.3.schema.json | 32cc534e2245821f |
| M | C2 | src/bg3loc/builder.py | a8fa5a59964111c3 |
| M | C3 | src/bg3loc/chat_prompt.py | cc18a6af31c77818 |
| M | C3 | src/bg3loc/commands/production.py | e2d2cd2f4c86e483 |
| M | C3 | src/bg3loc/commands/research.py | 57f68e6819d9c04d |
| M | C3 | src/bg3loc/commands/translation_qa.py | dfc03c64900972f3 |
| M | C3 | src/bg3loc/commands/translation_state.py | 9486087520ae917e |
| U | C3 | src/bg3loc/dialogue_context.py | 319e78d22818ab1d |
| U | C3 | src/bg3loc/dialogue_execution_contract.py | 0a091454b09e163c |
| U | C3 | src/bg3loc/dialogue_materialization.py | 5df9e914934ef83e |
| U | C3 | src/bg3loc/dialogue_prompt.py | d2f336e0fcf00e01 |
| U | C3 | src/bg3loc/dialogue_review.py | aae42d72393f0837 |
| U | C3 | src/bg3loc/dialogue_semantic_replay.py | 369a1dc821b5d5dc |
| U | C3 | src/bg3loc/dialogue_stage2_preview.py | 1189d13cc635b2dd |
| U | C3 | src/bg3loc/dialogue_stage_prepare.py | 496bf0f33b2fbf2a |
| U | C2 | src/bg3loc/e2e/baseline.py | 99d88bc96525b611 |
| U | C2 | src/bg3loc/e2e/eligibility.py | a2f9d895d79a61b9 |
| M | C2 | src/bg3loc/e2e/install.py | 49799ea1e2785f03 |
| M | C2 | src/bg3loc/e2e/package.py | 39a78d747eb36f25 |
| M | C2 | src/bg3loc/e2e/prepare.py | 57167ea323ba46eb |
| M | C2 | src/bg3loc/e2e/rebuild.py | d7d4d1833996edac |
| M | C2 | src/bg3loc/e2e/validate.py | ca32974782ba26de |
| M | C3 | src/bg3loc/execution_runner.py | 7b1ccd395a438848 |
| M | C3 | src/bg3loc/execution_state.py | 5eab2b72cb61ef49 |
| M | C2 | src/bg3loc/extractor.py | 2ed821fb77149bb6 |
| M | C3 | src/bg3loc/final_merge_bridge.py | 1364f1b6ce4cecc6 |
| U | C3 | src/bg3loc/legacy_qa_material.py | b81429b1ca07e828 |
| U | C3 | src/bg3loc/offline_integration.py | 84919c7a54e254d2 |
| U | C3 | src/bg3loc/portable_assets.py | 5668ff84869534ac |
| U | C3 | src/bg3loc/portable_finalize.py | f5a47b0d2779741e |
| M | C3 | src/bg3loc/production_completion.py | b720d5c6057a08e4 |
| U | C3 | src/bg3loc/production_dialogue_prepare.py | eebe7a04da08a705 |
| M | C3 | src/bg3loc/production_finalize.py | 48e34d2df8c83992 |
| M | C3 | src/bg3loc/production_orchestration.py | 92f4599f33d89770 |
| M | C3 | src/bg3loc/production_qa_orchestration.py | 60e836a89b9d4fe6 |
| M | C3 | src/bg3loc/production_reporting.py | b3aef0680acefc32 |
| M | C3 | src/bg3loc/production_review.py | 2d0c2e88fe143379 |
| M | C3 | src/bg3loc/production_workspace.py | b4bd6614576fd9cb |
| M | C3 | src/bg3loc/prompt_assembly.py | 144ece89d95588a8 |
| M | C3 | src/bg3loc/prompt_provenance.py | e2993ac6d1e4c1b0 |
| U | C3 | src/bg3loc/provider_diagnostics.py | e1ea8f38b674918c |
| M | C3 | src/bg3loc/providers/openai_compatible.py | f64dc6eb09955403 |
| M | C3 | src/bg3loc/qa_state.py | 290a80f42dcbf8d5 |
| M | C2 | src/bg3loc/rebuilder.py | 4d92aca9b19ce9f2 |
| M | C3 | src/bg3loc/research/dialogue_pilot.py | 2fa4ca50af614152 |
| U | C3 | src/bg3loc/sealed_snapshot.py | f42e5f67fe5ab642 |
| U | C2 | src/bg3loc/source_packages.py | 88017e32ae408b00 |
| M | C3 | src/bg3loc/translation_identity.py | 625f314b874b74df |
| M | C3 | src/bg3loc/translation_request.py | bcf08d01860c26b6 |
| U | C3 | src/bg3loc/translation_send.py | 9ca44e89cc7fdc7b |
| U | C3 | tests/test_b1_03_stage0_contracts.py | f8f4ad869589db06 |
| U | C2 | tests/test_basic_baseline_integrity.py | 4a8142c3de2d3ebc |
| U | C2 | tests/test_basic_workflow_state_integrity.py | 88d6643410345205 |
| U | C1 | tests/test_ci_distribution.py | fa57ce64ec964983 |
| U | C3 | tests/test_dialogue_engineering_acceptance.py | 7b77af7d385ae9bf |
| M | C3 | tests/test_dialogue_policy_evaluation.py | 0b8d485d41f9f30c |
| U | C3 | tests/test_dialogue_stage1.py | 3489f106e712a5fc |
| U | C3 | tests/test_dialogue_stage2.py | 3a976e372940a93f |
| U | C3 | tests/test_dialogue_stage3.py | 48ce6d09d6db1687 |
| U | C3 | tests/test_dialogue_stage4.py | d733adc77b2c8eb2 |
| U | C3 | tests/test_dialogue_stage4r.py | 39f41965f3932769 |
| U | C3 | tests/test_dialogue_stage5_r1.py | 71739378b64da408 |
| M | C2 | tests/test_e2e_cli_acceptance.py | 04c59085ebf938ee |
| M | C2 | tests/test_e2e_flow.py | fc1cc4daa2e59f63 |
| M | C2 | tests/test_e2e_workflow.py | cbe7d544ce301411 |
| M | C2 | tests/test_extract.py | 638e85163040c445 |
| U | C2 | tests/test_legacy_pak_integrity.py | 5241498a6404d549 |
| U | C3 | tests/test_legacy_review_integrity.py | f599c0c900b0234a |
| U | C2 | tests/test_locale_material_integrity.py | ee7570e92ae7002a |
| M | C3 | tests/test_openai_compatible_provider.py | e0fc6d486e23fc89 |
| M | C3 | tests/test_production_cli.py | b82bdae0afb7adbf |
| M | C3 | tests/test_production_completion.py | ddce04317f26c66e |
| U | C3 | tests/test_provider_error_privacy.py | c00a0280993b20bf |
| M | C3 | tests/test_qa_state.py | ad0aa2adfdb64873 |
| M | C2 | tests/test_rebuild.py | cb8378e0dba93212 |
| U | C2 | tests/test_source_package_freshness.py | 0923fa465aaf3f17 |
| M | C3 | tests/test_translation_qa_cli.py | a5f8536f2eead788 |
| M | C2 | tests/test_validate.py | 6d6d2bb981535eef |
| U | C1 | tools/ci/check_loopback.py | a0ad90c972078d33 |
| U | C1 | tools/ci/summarize_tests.py | 6d8861f36aef81dc |
| U | C1 | tools/ci/verify_distribution.py | 2988d4d0decbd886 |


另加本M5報告為C4文件；C5計畫paths尚未更改，勿在目前diff中假造它們。

## 附錄B：實際runtime diff / symbols

Top-level symbol新增／改動是HEAD AST與目前source直接比較；class列包含其method改動，不是只修改class名。完整method/import edges可於local dependency-map與tracked-diff查證。

| File | Added top-level symbols | Changed symbols |
| --- | --- | --- |
| src/bg3loc/builder.py | — | run_build |
| src/bg3loc/chat_prompt.py | — | render_chat_messages |
| src/bg3loc/commands/production.py | — | register, run_prepare |
| src/bg3loc/commands/research.py | run_dialogue_stage_prepare | register |
| src/bg3loc/commands/translation_qa.py | — | register, run_qa, run_retry_handoff, run_review_export, run_review_resolve |
| src/bg3loc/commands/translation_state.py | — | _sealed_execution_contract, load_execution_items, run_init |
| src/bg3loc/dialogue_context.py | DialogueAlternative, DialogueBudgetContract, DialogueContext, DialogueContextValidationError, DialogueSourceVariant, DialogueTargetBinding, DialogueTargetProof, NativeChildProof, _Wire, _arguments, _camel, _decode, canonical_bytes, collection, constant, decode_dialogue_context, dialogue_context_from_material, digest, evidence_projection, fail, fingerprint, ordered, source_complete, strict_json_loads, string, text_hash | — |
| src/bg3loc/dialogue_execution_contract.py | Stage2WorkspaceValidation, _frozen_schema, _strict_const, contained_file, dialogue_identity_descriptor, execution_context_contract_v2, guard_material_family, material_workspace_version, reject_dialogue_execution, validate_context_contract_v2, validate_manifest_1_3, validate_stage2_workspace | — |
| src/bg3loc/dialogue_materialization.py | DialogueEvidenceAdapter, MaterializationResult, _Node, _stats, jsonl_rows, load_english_sources, materialize_inventory, sealed_evidence_rows | — |
| src/bg3loc/dialogue_prompt.py | DialoguePromptAlternative, DialoguePromptContext, dialogue_prompt_policy_fingerprint, project_dialogue_context | — |
| src/bg3loc/dialogue_review.py | apply_dialogue_semantic_review, is_dialogue_workspace, semantic_gate_present, validated_stage3_material | — |
| src/bg3loc/dialogue_semantic_replay.py | _rows, import_semantic_replay_responses, prepare_semantic_replay, validate_semantic_replay_review | — |
| src/bg3loc/dialogue_stage2_preview.py | read_stage1_contexts_for_validation | — |
| src/bg3loc/dialogue_stage_prepare.py | _file_seal, load_prepared_inventory, prepare_dialogue_stage | — |
| src/bg3loc/e2e/baseline.py | BasicSourceSnapshot, _File, _constant, _file_sha, _json, _rows, _same, _sha, _unique, prepare_baseline, validated_baseline | — |
| src/bg3loc/e2e/eligibility.py | EligibilitySession, ValidationBinding, current_eligibility, input_bindings, is_basic, rebuild_binding, revoke_downstream, validation_binding | — |
| src/bg3loc/e2e/install.py | _run_workflow_install | run_workflow_install |
| src/bg3loc/e2e/package.py | — | prepare_translation_package |
| src/bg3loc/e2e/prepare.py | — | run_prepare |
| src/bg3loc/e2e/rebuild.py | _move_owned_output, _relocate_paths, _run_workflow_rebuild | run_workflow_rebuild |
| src/bg3loc/e2e/validate.py | _run_validate, _validation_failure | _update_blocked_state, run_validate |
| src/bg3loc/execution_runner.py | — | TranslationFailure, run_worker |
| src/bg3loc/execution_state.py | — | TranslationExecutionStore |
| src/bg3loc/extractor.py | _extract_verified, _publish_extract, material_locale_roles, resolve_locale_roles, validate_material_locales, validate_material_projection | run_extract |
| src/bg3loc/final_merge_bridge.py | — | build_final_merge_bridge |
| src/bg3loc/legacy_qa_material.py | LegacyQaMaterial, LegacyQaSource, _borrow, _unique_object, actual_output_current | — |
| src/bg3loc/offline_integration.py | OfflineOutcome, run_offline_integration | — |
| src/bg3loc/portable_assets.py | PortableAssetView, PortableAssetsError, _snapshot, _version_snapshot, active_backend, collision_free, create_finalize_assets, lexical_path, normalized_records, read_version_index, records_map, reject, safe_file, verify_finalize_assets | — |
| src/bg3loc/portable_finalize.py | _validate_output_bytes, finalize_portable_workspace, logical_snapshot | — |
| src/bg3loc/production_completion.py | _semantic_gate_present | _load_material_index, build_production_completion_view, derive_production_disposition |
| src/bg3loc/production_dialogue_prepare.py | attest, input_path, prepare_dialogue_workspace | — |
| src/bg3loc/production_finalize.py | — | finalize_production_workspace |
| src/bg3loc/production_orchestration.py | — | ProductionPrepareRequest, prepare_production_workspace |
| src/bg3loc/production_qa_orchestration.py | — | _read_counts, resolve_workspace_review |
| src/bg3loc/production_reporting.py | — | _attempt_and_usage_report |
| src/bg3loc/production_review.py | — | ProductionReviewStore |
| src/bg3loc/production_workspace.py | verify_portable_workspace | execution_inventory_fingerprint, verify_production_workspace |
| src/bg3loc/prompt_assembly.py | — | AssembledTranslationPrompt, assemble_translation_prompt |
| src/bg3loc/prompt_provenance.py | — | PromptProvenance |
| src/bg3loc/provider_diagnostics.py | safe_attempt_diagnostics, safe_error_code, safe_error_message, transport_error_message | — |
| src/bg3loc/providers/openai_compatible.py | — | OpenAICompatibleChatProvider, UrllibJsonTransport, _provider_error_message, openai_compatible_execution_config_hash |
| src/bg3loc/qa_state.py | — | TranslationQaStore |
| src/bg3loc/rebuilder.py | _archive_inventory, _extracted_entry_hashes, _unique_entry_paths | repack_target_package, safe_archive_relative_path |
| src/bg3loc/research/dialogue_pilot.py | _markup_lexemes, _pilot_rows, _strict_pairs | import_responses |
| src/bg3loc/sealed_snapshot.py | SealedMaterialItem, SealedRunSnapshot, _PinnedFiles | — |
| src/bg3loc/source_packages.py | ScanPackageSnapshot, SourcePackageError, _ReadPins, file_identity, mismatch, no_link, stream_hash | — |
| src/bg3loc/translation_identity.py | — | translation_input_hash |
| src/bg3loc/translation_request.py | — | BatchMaterialResolver, TranslationRequest |
| src/bg3loc/translation_send.py | PreparedTranslationSend, prepare_translation_send, provenance_for_prepared_send | — |


**BG3Loc MAINLINE M5 — GIT INTEGRATION PLAN READY FOR REVIEW**

