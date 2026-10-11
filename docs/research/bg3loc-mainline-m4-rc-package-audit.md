# BG3Loc Mainline M4 — Windows Basic RC Source & Package Audit

日期：2026-10-11。**本機候選來源／封裝供審查，不是發布、Stable Acceptance 或 Production Activation。** 本次保留 Basic、既有 Production、B1-03、tests與歷史文件，不刪研究、不改程式／版本／frozen contracts。

## 1. 可追溯候選來源

HEAD：896b4870b3a24d8506e6d751db3d4602925fb8fb；branch：feat/b1-03-dialogue-context。起始 Git directory-level status為 **53 modified／68 untracked entries**；展開後為 **128 dirty files = 53 modified + 75 untracked**。snapshot共有 **413 個 nonignored public files**，包含必要的未修改程式。

逐檔 inventory：[bg3loc-mainline-m4-rc-source-inventory.json](bg3loc-mainline-m4-rc-source-inventory.json)。含每個 path、gitStatus、category、scopeTags、sizeBytes與完整 SHA256；附錄列出全部 dirty files。分類是審查歸屬，不代表共享檔案只含單一階段變更，也不是可直接刪檔的清單。

Source snapshot SHA256：**42f6a0421bf4ed64291f231b1aa717dce32e2478af24f15c76d7920a5f6763c9**。Canonicalization：按 path排序的413 entries，投影 path/sizeBytes/sha256，JSON sort_keys=true、separators逗號/冒號、UTF-8，最後 SHA256。這是 **M4 audit receipt**，不是 production manifest、translation identity或新 Basic runtime sidecar。

snapshot在新增本報告與inventory前建立；這兩個後產生的交付物不在已建archives內。正式整合／變更版本後須重建及更新 hashes。

| Dirty category | Files | 範圍 |
| --- | ---: | --- |
| packaging-ci | 6 | A3/A4 workflow、MANIFEST、dependencies及3個CI tools |
| public-docs-history-examples | 26 | M1/M2/M3公開文件、範例與歷史報告 |
| dialogue-research-contracts | 17 | B1-03研究／frozen contracts／Stage reports；非Basic Activation |
| basic-receipt-schema | 1 | 已核准 basic-source-baseline/1 |
| dialogue-disabled-retained-contracts | 2 | Manifest1.3／finalize assets schemas，保留 |
| basic-required-shared | 11 | A1/A6/A8、M2-B1/B2，Basic與共享helpers |
| existing-production-shared | 24 | A2/A5及H0/HSE/HD／Production共用能力 |
| dialogue-disabled-retained | 13 | Typed/offline/portable/sealed helpers，保留OFF／guards |
| synthetic-tests-fixtures | 28 | 修改／新增test modules；全部public tests/fixtures都入snapshot |

### 功能界線與實際 code paths

- A1：builder.py::run_build、extractor.py::run_extract/material_locale_roles及scanner canonical roles；A6：source_packages.py::ScanPackageSnapshot與extract late/publication checks。
- A8：rebuilder.py::repack_target_package/_archive_inventory/_extracted_entry_hashes，完整entry set與non-LOCA SHA。
- M2-B1：e2e/baseline.py::BasicSourceSnapshot/prepare_baseline/validated_baseline與Receipt schema，source/target/extract/normalized/XML/LOCA綁定。
- M2-B2：e2e/eligibility.py::validation_binding/rebuild_binding/EligibilitySession/current_eligibility，e2e validate/rebuild/install：accepted snapshot、current eligibility、historical/failed isolation及每次fresh dry-run。
- A2：provider_diagnostics.py、providers/openai_compatible.py；A5：legacy_qa_material.py、production_review.py與QA/completion binding。全部保留，未納入Basic自動Provider／Production Finalize驗收。
- A3/A4 CI/sdist、M3公開文件／虛構範例及既有accepted成果全部入snapshot。A7仍只有design，不宣稱implementation。

上列程式均在src/bg3loc/；function是此候選來源的既有入口，本次不修改。

**不建議刪掉B1-03來製作Basic-only wheel。** cli.py::build_parser unconditional imports/registers Production/research/translation commands；TranslationRequest、identity、workspace、QA/review共享程式引用dialogue DTO/contracts。粗略排除會漏guard或破壞import closure；若要物理分拆，必須單獨設計及授權。本次保留完整來源，以公開文件與release scope限定Windows Basic。

project init預設basic/standard；Basic prepare不建立dialogue material、HD items或Production SQLite，正常Basic不進HD semantic REVIEW。dialogue_execution_contract.py::reject_dialogue_execution及production_workspace.py::verify_production_workspace維持宣告1.3 fail closed；OFF、family互斥、H0/HSE identities與guards保留。既有非HD Provider CLI仍可見，是進階未納入首版能力；不能說所有Provider程式已移除或已驗收。

### 排除本機私有依賴

只複製git ls-files的tracked／untracked nonignored regular files；拒絕symlink/reparse，核對original before/after與snapshot bytes。沒有.git、ignored workspace、真實corpus、實際assignments/returns/SQLite或Divine。

Installed CLI從external cwd以-I、無editable／system-site packages執行；import位於venv site-packages，schemas來自venv share/bg3loc/schemas。Basic smoke只使用新解壓sdist的public fake transport helpers，不讀原repository或local research universe；Receipt/eligibility檢查沒有mock。玩家仍需自己的遊戲、LSLib及config指定的實際paths，這是explicit input，非硬編碼本機依賴。歷史文件中的local evidence paths屬文字，不被Basic runtime隱式讀取。

## 2. 候選版本與建置

**PROPOSED：1.4.0rc1。** Basic新公開邊界與accepted integrity fixes宜有新minor RC可辨識；舊receipt workspace的fail-closed compatibility要寫入Changelog。版本／tag待明確核准；本次沒有改pyproject.toml、__version__或建立tag。

目前archives仍是 **1.3.0 audit builds**，僅供SHA識別的本機審查，不覆蓋既有同名發行物，不可直接發布／改名冒充1.4.0rc1。Python3.12 Windows，Requires-Python >=3.11。

Direct build使用正常python -m build --sdist --wheel的PEP517 isolation。再沿用tools/ci/verify_distribution.py，安全解壓新sdist、從sdist重建wheel、fresh venv install/smoke/full pytest；後者ProjectBuilder使用既有build dependencies，不偽稱另一個isolated backend venv。Build isolation與clean install都使用18個普通dependency wheels，本機lock size/SHA核對通過，no-index/local find-links；無依賴下載、Provider或發布。

## 3. Artifacts / SHA256 / Contents

路徑相對repository，套件全部留在ignored workspace/mainline-m4/。下方表格由實際archive audit補入。

| Artifact | Bytes / regular files | SHA256 |
| --- | ---: | --- |
| workspace/mainline-m4/direct-dist/bg3loc-1.3.0-py3-none-any.whl | 446,538 / 174 | 786f428e0288c0780be408eaa8a2f82ed6bce523d9a8e841b4be26f16964581f |
| workspace/mainline-m4/direct-dist/bg3loc-1.3.0.tar.gz | 991,127 / 420 | fade43fc50ff46f934bb1d7b8772a1b57cc7aeea5493b5711383d36df3671208 |
| workspace/mainline-m4/distribution/dist/bg3loc-1.3.0-py3-none-any.whl | 446,538 / 174 | 9489bb1195b9bcf17e90cf2a928da84ff50a31527ca0ddefd15668288993c6d0 |
| workspace/mainline-m4/distribution/dist/bg3loc-1.3.0.tar.gz | 991,127 / 420 | 4256bf6694da1ae9784aef6cdf06faa0476b517570e2b73bbde56ef7cea4302b |


兩個wheel的 **174個member bytes完全一致**；兩份sdist的 **420個regular member bytes完全一致**。Archive SHA因container metadata/timestamps而不同；本次證明內容可重建，不宣稱bit-for-bit identical archives。每個archive有完整path/size/SHA inventory。

126個runtime .py/.ps1、42個schemas，source→sdist→兩個wheel bytes parity PASS；console entry、version metadata一致。必需docs/examples/tests/helpers及frozen synthetic contracts的sdist parity PASS。Basic Receipt schema在sdist、wheel及installed schema root中，亦由實際Basic smoke消費。

## 4. Privacy / Public fixtures

四個archives的unsafe/absolute/traversal path、duplicate/case collision、workspace/hidden assignments filenames、PAK/LOCA/SQLite/DB/EXE/DLL/KEY/PEM、tar non-regular members，以及SQLite/MZ magic檢查均PASS。高可信度API/GitHub/AWS/private-key credential patterns **0 findings**，不輸出matching values。

這不是證明所有未知secret形式不存在；來源範圍、fixture allowlist、內容檢查共同提供privacy evidence。五個fixtures的完整SHA見distribution/report.json：source_rows.jsonl、portable_source_rows.jsonl、ruleset.json、p3-baseline.json、p4-identity-baseline.json，全部位於tests/fixtures/b1_02/，內容為Fictional/f-*/portable-*測試資料。沒有任意新fixture被默認public。

M3 returned-row.example.jsonl是fictional UID／invented greeting，非遊戲素材。Test中的假credentials／虛構XML／生成disposable PAK是公開regression inputs，不是真實憑證或遊戲檔；archive內沒有actual PAK/LOCA、private research corpus或Divine binary。

## 5. Clean install / CLI / Schema / Basic

| Check | 結果與限度 |
| --- | --- |
| Fresh wheel[test] venv install / pip check | PASS，無editable/system-site；imports來自site-packages |
| CLI isolated/module/console | --version、--help、production --help、bg3loc.exe --version PASS，未執行Provider |
| 42 schemas | Bytes/JSON-schema有效；39 SchemaStore.load PASS，3 research BOM limitation；Basic Receipt load/usage PASS |
| Installed JSONL | init/check→prepare→allowed return edits→validate→rebuild→default install/status PASS |
| Installed XLSX | 同上PASS；各3 source UIDs、blank/source-only/tokens/markup，保留target-only |
| Source/A8 | 各3 non-LOCA SHA parity；所有fake original PAK before/after SHA相同，無backups/Apply |

三個既有BOM schemas：research/research-mapping.schema.json、research/research-scan.schema.json、research/research-summary.schema.json。Bytes/JSON Schema有效，但SchemaStore.load用utf-8無法直接讀BOM。既有verifier明確列出，本次不算load PASS、不改schema/fingerprint；Basic不消費這三份。若進階研究要加入release support，需另行授權修正／驗收。

Basic smoke使用public synthetic ZIP/XML backend，Receipt/eligibility/origin reproof未mock，**不是Native Divine或真實game-load acceptance**。Full pytest按既有tool測extracted sdist source（包含subprocess）；不能說所有tests僅import installed wheel。Installed Basic smoke另以-I核對import路徑及installed schemas。

## 6. Full available regression

Collection：**1558 tests**，沒有ignore/deselect/filter，HTTP demo包含。首輪deep workspace basetemp：**1494 passed、64 failed、1 warning、231.32 s，exit1**。JUnit的63 failures都是finalize-assets SHA object建立時FileNotFoundError，路徑 **268–269 characters**；另一個為HTTP demo。

同一D7 test改短root即 **1 passed / 0.79 s**。保留首輪FAIL/JUnit、failure classification及兩個probe。完整短root rerun使用新D:/workspace/codex/BG3/m4t1，無source/fixture/schema/assertion變更或排除；不能把原始verifier report改成PASS。

**最終short-root full suite：1556 passed、1 failed、1 skipped、1 warning、396.14 s，exit 1。** 唯一failure是test_public_demo.py::test_demo_accepts_relative_output_from_external_cwd；短root attempt DB再次確認3次WinError10013，分類ENVIRONMENT-BLOCKED，不算PASS。Skip為test_d7_corruption_rejected[link]，host無symlink權限。Warning為intentional duplicate ZIP entry。原63長path failures在此輪均無failure/error，其中link case進入正常host-permission skip；保留完整原始logs及JUnit。不宣稱ALL PASS、Native跨平台或hosted CI通過。

本機兩次full套件（含未改HTTPdemo）均完整執行。正常短root run約6分36秒，CI還需checkout與distribution兩次測試、建置與依賴安裝；40分鐘有本機参考但無hosted SLA。若runner path造成long-path failure，須保留實測並獨立修正環境配置，不能自動改PASS。

HTTP原始attempt DB已有3次PROVIDER_TRANSPORT_ERROR / Provider transport failed (WinError10013)。保留環境失敗，不fake PASS。深path已顯示Windows環境限制；短path test不代表任何長路徑皆安全，Basic仍要求短且穩定的original paths。CI若遇同類情況需獨立environment diagnosis或合法短temp配置，不能刪測試／降低完整性。

## 7. GitHub-hosted CI — NOT VERIFIED

| Runner | Python | 預期collection | Hosted |
| --- | --- | ---: | --- |
| windows-latest | 3.11 | 1558 | NOT VERIFIED |
| windows-latest | 3.12 | 1558 | NOT VERIFIED |
| ubuntu-latest | 3.11 | 1558 | NOT VERIFIED |
| ubuntu-latest | 3.12 | 1558 | NOT VERIFIED |

ci.yml：push/pull_request/workflow_dispatch，無path filters，2×2 matrix、fail-fast false、contents read、每job **40分鐘**。Install .[test]、compile、real loopback、collect/full pytest、sdist→wheel→clean install/full pytest、counts summary、JUnit/diagnostics upload；checkout與distribution各跑完整suite。本機耗時只作budget參考，不推論hosted速度／PASS。

HTTP probe失敗就是job failure，無continue-on-error；後續重要steps用!cancelled()以保留證據。Summary含failed/errors/skipped/missing，missing=NOT VERIFIED。Upload checkout XML及distribution JSON/TXT/XML，if-no-files-found: warn；不永久skip HTTP或假PASS。Timeout/cancel可能缺report，必須保留job log且不得標PASS。

Python3.11/Linux／新dependency resolution／Native LSLib未由本次單一Windows/Python3.12/offline lock驗證。平台skip須逐項解釋，code/tests變更後重記collection；此數量不是永久constant。本次不push、dispatch或改workflow。

## 8. 安全整合／發布順序

1. 審查source inventory、accepted Basic變更、shared/B1-03保留範圍及full regression例外，明確核准RC version／Changelog／release scope。
2. 另行授權後整合到可追溯branch/commits。共享檔跨stage，逐diff／dependency group審查；保留全部prior work，不reset/clean或粗略cherry-pick排除。可依A1/A6/A8、B1/B2、A2/A5、retained B1-03 OFF/guards、CI/fixtures/docs分組，維持import/test closure。
3. 核准後改package/runtime版本、雙語Changelog及notes；從exact committed source重建、重新privacy/fixture/full tests/clean install並記錄new SHA。不能直接發布本次同名1.3.0 audit builds。
4. 經另外授權push後跑四個hosted jobs及真正HTTPdemo；FAIL/SKIP/UNKNOWN逐項處理。若須修正temp path或BOM，另行授權，不在M4改程式。
5. Windows Native玩家安裝的唯讀小scope Scan→Extract→Prepare→Validate→Rebuild→Dry-run，記錄source/target before/after SHA及全entry parity；玩家自裝LSLib，不偷用私有固定path。
6. **另行明確授權**真實Apply／Rollback及small-scope game-load，先認證artifact/destination/backup SHA、停遊戲/updaters與recovery。Dry-run不授權write。之後才決定正式tag／GitHub Release／PyPI，均非本次授權。

Remaining gates：exact committed/versioned source、四個hosted jobs／HTTP可用環境、真實Windows Native唯讀、獨立授權的game-load/Apply/Rollback。A7 Legacy Finalize、Provider、B1-02/B1-03 Activation及general dialogue safety仍在首版範圍外。

## 9. Git / Preservation / Local evidence

**全部413個startup public files bytes保持相同，無遺失；HEAD／branch與所有原始dirty statuses不變。** 本次只新增此報告與machine-readable source inventory，git status最終為53 modified／70 untracked directory-level entries（展開130 dirty files），包含全部既有工作。沒有修改Production Code、tests、CI、schema、frozen contracts、package/runtime版本、H0/HSE/HD identities或B1-03 guards；沒有staging／commit／push／merge／tag／Release／PyPI、paid Provider、真實遊戲Apply／Rollback。

Build/test產物、venvs與copy source都留在隔離區；新增的報告／inventory不混入已建artifact。輪子同名但SHA不同，仍僅供本機audit，正式RC需核准版本與committed-source rebuild。

Local-only evidence：ignored workspace/mainline-m4/的source-inventory.json、source snapshot、direct-dist、direct-build.txt、package-audit.json及4份entry inventories、distribution/report.json／install/smoke/collection/tests logs/JUnit、installed-basic/result.json、first-run-failures.json、long-path-evidence.json、兩個probe、full-short.txt/xml、http-original-attempts.json、http-short-attempts.json、ending-state.json。Short-root synthetic測試位於D:/workspace/codex/BG3/m4t1；無real corpus，未加入repository。

## 附錄：全部128 startup dirty files

M=tracked modified，U=untracked file；full SHA/size/scopeTags見配套JSON。下面hash縮寫僅供人類比對。

| Status | Category | Path | SHA256 prefix |
| --- | --- | --- | --- |
| M | packaging-ci | .github/workflows/ci.yml | feca07379185a0c8 |
| M | packaging-ci | MANIFEST.in | 1c39103a85dfe58e |
| M | public-docs-history-examples | README.md | dd21b13de6d7d7ea |
| M | public-docs-history-examples | README.zh-TW.md | a1e3cbf3a9441a50 |
| M | public-docs-history-examples | docs/concepts/archive-backends.md | 1ac72c741e90fd20 |
| M | public-docs-history-examples | docs/concepts/archive-backends.zh-TW.md | b7df44d052110d09 |
| U | public-docs-history-examples | docs/development/testing.md | 49b77cfd551bb88f |
| M | public-docs-history-examples | docs/e2e/high-level-cli.md | d059d02d7bfa4c48 |
| M | public-docs-history-examples | docs/e2e/high-level-cli.zh-TW.md | 5af05a5cfc344081 |
| M | public-docs-history-examples | docs/getting-started.md | 00a2fadd5710e0c8 |
| U | public-docs-history-examples | docs/getting-started.zh-TW.md | a906c1950113affb |
| U | public-docs-history-examples | docs/production-getting-started.md | e0d143f3be2cdb3a |
| U | dialogue-research-contracts | docs/research/b1-03-production-contract-freeze.md | 25cb1ecfbeebc6bc |
| U | dialogue-research-contracts | docs/research/b1-03-production-integration-design.md | 7e747ed1c76d7db9 |
| U | dialogue-research-contracts | docs/research/b1-03-stage0-contracts/dialogue-context.schema.json | 452cd24666047806 |
| U | dialogue-research-contracts | docs/research/b1-03-stage0-contracts/finalize-assets.schema.json | ca4715811a6df8f8 |
| U | dialogue-research-contracts | docs/research/b1-03-stage0-contracts/production-manifest-1.3.schema.json | 32cc534e2245821f |
| U | dialogue-research-contracts | docs/research/b1-03-stage0-contracts/synthetic-existing-goldens.json | a059a5d142bf7585 |
| U | dialogue-research-contracts | docs/research/b1-03-stage0-contracts/version-registry.json | 2ac0d66f794d5491 |
| U | dialogue-research-contracts | docs/research/b1-03-stage1-implementation-review.md | ff5f640e019e89a1 |
| U | dialogue-research-contracts | docs/research/b1-03-stage2-implementation-review.md | 4c6d07ca4381c609 |
| U | dialogue-research-contracts | docs/research/b1-03-stage3-implementation-review.md | 89be2a84e288a55b |
| U | dialogue-research-contracts | docs/research/b1-03-stage4-implementation-review.md | 10ac16dee890185b |
| U | dialogue-research-contracts | docs/research/b1-03-stage4r-activation-blocker-remediation.md | 376efb7c4414b4e5 |
| U | dialogue-research-contracts | docs/research/b1-03-stage4r-case006-semantic-regression-adjudication.md | 3fe79cc663051940 |
| U | dialogue-research-contracts | docs/research/b1-03-stage4r-final-engineering-acceptance.md | 670dac9040d002b0 |
| U | dialogue-research-contracts | docs/research/b1-03-stage5-production-activation-review.md | 5ff9852ed40bf5cb |
| U | dialogue-research-contracts | docs/research/b1-03-stage5-r1-decision-integrity-remediation.md | e56dc6b01237ec99 |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a1-locale-integrity.md | d59315165bbb18ac |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a2-provider-error-privacy.md | f283d79309b3cebf |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a3-a4-ci-packaging.md | 785c2ee46ae5f95f |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a5-legacy-review-design.md | bf007c65c2cb590b |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a5-legacy-review-remediation.md | 2b43c54647a21497 |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a6-source-freshness.md | 06b3258432dc63ec |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a7-finalize-design.md | 75f5326a814e6cab |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m1-a8-pak-integrity.md | 3cef50e98cc6965f |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m2-b1-baseline-integrity.md | ec5ccbb20f25b596 |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m2-b2-workflow-state-integrity.md | 4d5dc86511bf45a4 |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m2-windows-basic-release-boundary.md | 5f41c68a1bb5f92f |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-m3-public-docs-rc-readiness.md | aadf357a4814234f |
| U | public-docs-history-examples | docs/research/bg3loc-mainline-readiness-audit.md | c4ee5b3b4b4ad63f |
| M | public-docs-history-examples | docs/troubleshooting.md | a4ffc8a24bd45f56 |
| U | public-docs-history-examples | examples/windows-basic/README.md | d5225f8bc1ff82ed |
| U | public-docs-history-examples | examples/windows-basic/returned-row.example.jsonl | 513c547e573e41e6 |
| M | packaging-ci | pyproject.toml | 9df1b5a104abf3c6 |
| U | basic-receipt-schema | schemas/basic-source-baseline-v1.schema.json | 0c970e32627bc846 |
| U | dialogue-disabled-retained-contracts | schemas/production-finalize-assets-v1.schema.json | ca4715811a6df8f8 |
| U | dialogue-disabled-retained-contracts | schemas/production-manifest-v1.3.schema.json | 32cc534e2245821f |
| M | basic-required-shared | src/bg3loc/builder.py | a8fa5a59964111c3 |
| M | existing-production-shared | src/bg3loc/chat_prompt.py | cc18a6af31c77818 |
| M | existing-production-shared | src/bg3loc/commands/production.py | e2d2cd2f4c86e483 |
| M | existing-production-shared | src/bg3loc/commands/research.py | 57f68e6819d9c04d |
| M | existing-production-shared | src/bg3loc/commands/translation_qa.py | dfc03c64900972f3 |
| M | existing-production-shared | src/bg3loc/commands/translation_state.py | 9486087520ae917e |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_context.py | 319e78d22818ab1d |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_execution_contract.py | 0a091454b09e163c |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_materialization.py | 5df9e914934ef83e |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_prompt.py | d2f336e0fcf00e01 |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_review.py | aae42d72393f0837 |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_semantic_replay.py | 369a1dc821b5d5dc |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_stage2_preview.py | 1189d13cc635b2dd |
| U | dialogue-disabled-retained | src/bg3loc/dialogue_stage_prepare.py | 496bf0f33b2fbf2a |
| U | basic-required-shared | src/bg3loc/e2e/baseline.py | 99d88bc96525b611 |
| U | basic-required-shared | src/bg3loc/e2e/eligibility.py | a2f9d895d79a61b9 |
| M | basic-required-shared | src/bg3loc/e2e/install.py | 49799ea1e2785f03 |
| M | basic-required-shared | src/bg3loc/e2e/package.py | 39a78d747eb36f25 |
| M | basic-required-shared | src/bg3loc/e2e/prepare.py | 57167ea323ba46eb |
| M | basic-required-shared | src/bg3loc/e2e/rebuild.py | d7d4d1833996edac |
| M | basic-required-shared | src/bg3loc/e2e/validate.py | ca32974782ba26de |
| M | existing-production-shared | src/bg3loc/execution_runner.py | 7b1ccd395a438848 |
| M | existing-production-shared | src/bg3loc/execution_state.py | 5eab2b72cb61ef49 |
| M | basic-required-shared | src/bg3loc/extractor.py | 2ed821fb77149bb6 |
| M | existing-production-shared | src/bg3loc/final_merge_bridge.py | 1364f1b6ce4cecc6 |
| U | existing-production-shared | src/bg3loc/legacy_qa_material.py | b81429b1ca07e828 |
| U | dialogue-disabled-retained | src/bg3loc/offline_integration.py | 84919c7a54e254d2 |
| U | dialogue-disabled-retained | src/bg3loc/portable_assets.py | 5668ff84869534ac |
| U | dialogue-disabled-retained | src/bg3loc/portable_finalize.py | f5a47b0d2779741e |
| M | existing-production-shared | src/bg3loc/production_completion.py | b720d5c6057a08e4 |
| U | dialogue-disabled-retained | src/bg3loc/production_dialogue_prepare.py | eebe7a04da08a705 |
| M | existing-production-shared | src/bg3loc/production_finalize.py | 48e34d2df8c83992 |
| M | existing-production-shared | src/bg3loc/production_orchestration.py | 92f4599f33d89770 |
| M | existing-production-shared | src/bg3loc/production_qa_orchestration.py | 60e836a89b9d4fe6 |
| M | existing-production-shared | src/bg3loc/production_reporting.py | b3aef0680acefc32 |
| M | existing-production-shared | src/bg3loc/production_review.py | 2d0c2e88fe143379 |
| M | existing-production-shared | src/bg3loc/production_workspace.py | b4bd6614576fd9cb |
| M | existing-production-shared | src/bg3loc/prompt_assembly.py | 144ece89d95588a8 |
| M | existing-production-shared | src/bg3loc/prompt_provenance.py | e2993ac6d1e4c1b0 |
| U | existing-production-shared | src/bg3loc/provider_diagnostics.py | e1ea8f38b674918c |
| M | existing-production-shared | src/bg3loc/providers/openai_compatible.py | f64dc6eb09955403 |
| M | existing-production-shared | src/bg3loc/qa_state.py | 290a80f42dcbf8d5 |
| M | basic-required-shared | src/bg3loc/rebuilder.py | 4d92aca9b19ce9f2 |
| M | dialogue-research-contracts | src/bg3loc/research/dialogue_pilot.py | 2fa4ca50af614152 |
| U | dialogue-disabled-retained | src/bg3loc/sealed_snapshot.py | f42e5f67fe5ab642 |
| U | basic-required-shared | src/bg3loc/source_packages.py | 88017e32ae408b00 |
| M | existing-production-shared | src/bg3loc/translation_identity.py | 625f314b874b74df |
| M | existing-production-shared | src/bg3loc/translation_request.py | bcf08d01860c26b6 |
| U | existing-production-shared | src/bg3loc/translation_send.py | 9ca44e89cc7fdc7b |
| U | synthetic-tests-fixtures | tests/test_b1_03_stage0_contracts.py | f8f4ad869589db06 |
| U | synthetic-tests-fixtures | tests/test_basic_baseline_integrity.py | 4a8142c3de2d3ebc |
| U | synthetic-tests-fixtures | tests/test_basic_workflow_state_integrity.py | 88d6643410345205 |
| U | synthetic-tests-fixtures | tests/test_ci_distribution.py | fa57ce64ec964983 |
| U | synthetic-tests-fixtures | tests/test_dialogue_engineering_acceptance.py | 7b77af7d385ae9bf |
| M | synthetic-tests-fixtures | tests/test_dialogue_policy_evaluation.py | 0b8d485d41f9f30c |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage1.py | 3489f106e712a5fc |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage2.py | 3a976e372940a93f |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage3.py | 48ce6d09d6db1687 |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage4.py | d733adc77b2c8eb2 |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage4r.py | 39f41965f3932769 |
| U | synthetic-tests-fixtures | tests/test_dialogue_stage5_r1.py | 71739378b64da408 |
| M | synthetic-tests-fixtures | tests/test_e2e_cli_acceptance.py | 04c59085ebf938ee |
| M | synthetic-tests-fixtures | tests/test_e2e_flow.py | fc1cc4daa2e59f63 |
| M | synthetic-tests-fixtures | tests/test_e2e_workflow.py | cbe7d544ce301411 |
| M | synthetic-tests-fixtures | tests/test_extract.py | 638e85163040c445 |
| U | synthetic-tests-fixtures | tests/test_legacy_pak_integrity.py | 5241498a6404d549 |
| U | synthetic-tests-fixtures | tests/test_legacy_review_integrity.py | f599c0c900b0234a |
| U | synthetic-tests-fixtures | tests/test_locale_material_integrity.py | ee7570e92ae7002a |
| M | synthetic-tests-fixtures | tests/test_openai_compatible_provider.py | e0fc6d486e23fc89 |
| M | synthetic-tests-fixtures | tests/test_production_cli.py | b82bdae0afb7adbf |
| M | synthetic-tests-fixtures | tests/test_production_completion.py | ddce04317f26c66e |
| U | synthetic-tests-fixtures | tests/test_provider_error_privacy.py | c00a0280993b20bf |
| M | synthetic-tests-fixtures | tests/test_qa_state.py | ad0aa2adfdb64873 |
| M | synthetic-tests-fixtures | tests/test_rebuild.py | cb8378e0dba93212 |
| U | synthetic-tests-fixtures | tests/test_source_package_freshness.py | 0923fa465aaf3f17 |
| M | synthetic-tests-fixtures | tests/test_translation_qa_cli.py | a5f8536f2eead788 |
| M | synthetic-tests-fixtures | tests/test_validate.py | 6d6d2bb981535eef |
| U | packaging-ci | tools/ci/check_loopback.py | a0ad90c972078d33 |
| U | packaging-ci | tools/ci/summarize_tests.py | 6d8861f36aef81dc |
| U | packaging-ci | tools/ci/verify_distribution.py | 2988d4d0decbd886 |


**BG3Loc MAINLINE M4 — RC PACKAGE READY FOR REVIEW**

