# BG3Loc Mainline M6-I1 — Isolated Git Integration C1–C4

日期：2026-10-12。M5 DESIGN ACCEPTED/CLOSED；本次僅四個本機Commit，未授權C5版本修改、push/merge/tag/Release/PyPI或Production Activation。

## 1. Original / integration

Original HEAD：896b4870b3a24d8506e6d751db3d4602925fb8fb，branch feat/b1-03-dialogue-context。原始工作樹：D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus。

隔離checkout：D:/workspace/codex/BG3/bg3loc-m6-i1-integration；branch integration/windows-basic-1.4.0rc1。採獨立local clone --no-hardlinks --no-checkout，再從指定HEAD建立branch，沒有在原倉庫建立worktree metadata，沒有shared objects／alternates。Clone origin目前為原本機repository path，**不是GitHub發布目的地，不得誤push到原倉庫**；遠端操作仍需另行授權。

首次clone遭sandbox MSYS named-object權限拒絕且未留半成品；以所需權限、精確per-command safe.directory處理不同owner後完成。沒有改global Git config、原始files／index或refs。

M5 415個原始public files與M5報告SHA全部重新核對，原Git status與M5 ending evidence相同。131-file explicit allowlist與M5報告表相符：C1=8、C2=23、C3=62、C4=37+M5報告=38。每組在copy/stage前核對全部416個original source hashes，不selectively取另一版本、不stash/reset/clean/discard。來源與evidence receipts在checkout外獨立目錄。

## 2. Four local commits

| Group | Commit SHA | Title / files |
| --- | --- | --- |
| C1 | 0c0dcf0dd89ea34743e6988b61c2595232f6091d | test: run full pytest and preserve public sdist fixtures / 8 |
| C2 | 53727b164f1cd3815508e5cf4bfa7a7fde4e4336 | fix: bind Basic source materials and current workflow eligibility / 23 |
| C3 | 91b1898791b86e7b8c5181013ed37021f6b626db | fix: retain guarded dialogue support and current Production decision evidence / 62 |
| C4 | 96b7c88c7ca12f465c1120c722efb3fc07bd9d6b | docs: define Windows Basic release scope and retain audit history / 38 |

逐組使用exact path allowlist，沒有git add .／-A。檢查staged set、original raw SHA256、checkout raw SHA256、Git clean-filter canonical blob SHA1、staged blob SHA256及diff。允許既有Git CRLF/LF representation，沒有其他filter差異；commit之後再次核對parent diff paths與所有committed blobs，全部對應核准來源。

各組詳細paths/hash列於local C1/C2/C3-staged.json、C4-postcommit-diff-audit.json及commits.json；M5完整path分組文件已在C4 tracked。不是只引用前stage PASS。

### C4 preserved whitespace / audit sequencing exception

Default staged whitespace check exit2：只有docs/research/bg3loc-mainline-m4-rc-package-audit.md與bg3loc-mainline-m5-git-integration-plan.md各1個new blank line at EOF；兩份原始SHA即M5核准值，沒有source drift。保留歷史內容、不trim改SHA，default warning原文存檔，不能標為default lint PASS。

補充稽核runner將CRLF文件末尾誤當必須LF-LF，assertion失敗後下一個已授權commit call仍執行，C4已建立。這是程序瑕疵，明確披露：C4 raw source/index canonical SHA checks與33 targeted tests先前已通過； supplementary evidence completion在commit後唯讀重做，確認exact 38 paths／committed blobs及canonical EOF。沒有reset/amend/rebase/force或第五個Commit。原始失敗與補充audit timing保留，不假造全程precommit audit PASS。此項需納入implementation review。

C3 runner另有一次誤填不存在的optional extra test_prompt_provenance.py，targeted未開始就停止；修正runner為repository實際存在的context_execution_identity與B1-02 activation coverage後才跑C3/commit。沒有改production source／allowlist或排除真正tests。

## 3. Per-commit regression

| Group | Imports / collection | Targeted result |
| --- | --- | --- |
| C1 | PASS / 897 tests collected in 1.02s | 22 passed in 0.47s |
| C2 | PASS / 1070 tests collected in 1.12s | 222 passed, 1 warning, 7 subtests passed in 62.36s (0:01:02) |
| C3 | PASS / 1558 tests collected in 1.36s | 626 passed, 1 skipped, 18 subtests passed in 305.88s (0:05:05) |
| C4 | PASS / 1558 tests collected in 1.33s | 33 passed in 1.18s |

C1：CI/packaging；C2：11個Basic/E2E/locale/freshness/PAK tests，JSONL/XLSX、receipt、current eligibility、source/target變更、whole-entry parity；C3：全部16個組內tests及H0/HSE/actual-send/activation golden modules，共627 cases，含A2/A5/R1、HD identity、frozen contracts、semantic REVIEW、retry/QA/completion/portable/sealed guards；C4：CI/documentation-adjacent/project/version tests。

C3的symlink skip是既知host權限限制；沒有新增skip/ignore/deselect以湊PASS。H0/HSE golden tests與frozen/1.3 stop guards通過，Basic不建立HD、Provider transport沒有解除。A7 Legacy Finalize仍DEFERRED，不將D7 portable/offline implementation當legacy A7修復。

## 4. Final full available / HTTP

| Environment | Actual result | Classification |
| --- | --- | --- |
| Integration checkout | ====== 1 failed, 1556 passed, 1 skipped, 1 warning in 502.60s (0:08:22) ======= | exit1；HTTP ENVIRONMENT-BLOCKED，不算PASS |
| Clean extracted sdist / fresh venv | ====== 1 failed, 1556 passed, 1 skipped, 1 warning in 357.89s (0:05:57) ======= | exit1；HTTP ENVIRONMENT-BLOCKED，不算PASS |

兩個full runs均收集1558 tests，無ignore/deselect。各只有public demo一個failure；各3個attempt DB rows均為PROVIDER_TRANSPORT_ERROR / Provider transport failed (WinError10013)，不是翻譯／QA內容failure。Symlink skip為test_d7_corruption_rejected[link]；warning為intentional duplicate ZIP entry。沒有未知regression failure，沒有將HTTP轉PASS。


Full command無ignore/deselect/filter，HTTP demo包含；TEMP/basetemp採短而隔離的D:/workspace/codex/BG3/m6full。Windows長路徑限制仍維持獨立風險，短root PASS不證明任意長path安全，不改程式或完整性coverage。

## 5. Package / clean install / privacy

Direct build使用正常PEP517隔離，sdist→wheel沿用已提交distribution verifier；fresh venv無editable/system-site imports，console/module CLI與pip check均PASS。建置／安裝以18個checksum核對的普通dependency wheels offline完成，沒有網路下載或發布。

| Artifact | Bytes / regular members | SHA256 |
| --- | ---: | --- |
| D:\workspace\codex\BG3\m6-i1-evidence\direct-dist\bg3loc-1.3.0-py3-none-any.whl | 446,816 / 174 | 199fae0878558d720879e61681ee8b28f5b3c2a2e08a8ccce19f9d64ac4b570a |
| D:\workspace\codex\BG3\m6-i1-evidence\direct-dist\bg3loc-1.3.0.tar.gz | 1,042,414 / 423 | 78bcd2de527165daeb14d0c3e83ae22e5a9682be547600be8c28c15c5bd636bb |
| D:\workspace\codex\BG3\m6-i1-evidence\distribution\dist\bg3loc-1.3.0-py3-none-any.whl | 446,816 / 174 | 796cb3c445c98b14d60c5e79ce49c1c75c2e6b780f0aefd8cf1bcf7f5843b88d |
| D:\workspace\codex\BG3\m6-i1-evidence\distribution\dist\bg3loc-1.3.0.tar.gz | 1,042,449 / 423 | 5cea1801fc53f8b072f97bdba64160ab507ff34e5de7b095c8aac696ad4724d6 |

兩個wheel的174個entries bytes相同；兩份sdist的423個regular members bytes相同。整個archive SHA因container metadata不同，不宣稱bit-for-bit reproducible archive。完整4份path/size/SHA inventories保留。126 runtime files、42 schemas與415必要公開source/resources之sdist/wheel byte parity PASS；5 fixtures明確public/synthetic、Receipt schema完整。

四archives的path/private-artifact/suffix、case-collision、SQLite/MZ magic與高可信度credentials patterns檢查PASS，0 credential findings；pattern audit不是所有未知secrets的絕對證明。沒有real PAK/LOCA/DB/Divine binary、local assignments/corpus/test outputs；pending M6 report不在archives內，建置於寫報告之前。

Installed JSONL與XLSX各完成3 source UID scope，包含blank/source-only/runtime token/markup，保留target-only及原UID/version；各3個non-LOCA SHA相同，所有fake original PAK before/after SHA不變，無backup/game write。首輪smoke parent未設writable TEMP，WinError5阻擋，未改來源；保留failed synthetic folder，改隔離TEMP/TMP及fresh output後兩格式PASS。


Version仍1.3.0；branch name 1.4.0rc1只是核准計畫，不代表已bump。Pyproject/runtime／research producer stamp／Changelog／release notes未作C5修改；新archives是C4-source audit builds，不發布、不重命名成1.4.0rc1。

Basic installed-wheel smoke使用public fictional ZIP/XML backend，真實receipt/eligibility/reproof與全entry SHA檢查不mock；不是Native Divine、真實game load或human semantic review。沒有paid provider或真實BG3 apply/rollback。

三個Research BOM schemas：research/research-mapping.schema.json、research-scan.schema.json、research-summary.schema.json；全部packaged bytes/JSON schema有效，但SchemaStore.load(utf-8)既有BOM limitation，39/42 load PASS、3明列限制，不能把skip當PASS。Basic Receipt不受影響。Hosted四jobs仍NOT VERIFIED，不push/dispatch。

## 6. Source / privacy / Git preservation

**Original416個files SHA全部不變**（415個M5原files加M5報告），HEAD/branch/status不變；原Git仍53 modified／71 untracked entries，展開131 dirty files。原始info/exclude SHA仍6671fe83b7a07c8932ee89164d1f2793b2318058eb8b98dc5c06ee0a5a3b0ec1。

Integration C4 HEAD為96b7c88c7ca12f465c1120c722efb3fc07bd9d6b，只有指定4個commits，416 tracked files完整對應source set；C4後及寫報告前Git status clean。131個approved overlays raw SHA與來源一致；另外29個未修改HEAD檔只差M5已記錄CRLF/LF，無其他內容差異，詳細file/SHA列表見checkout-line-endings.json。沒有為hash一致改newline設定或正式schema，committed canonical blobs與核准內容一致。


131個approved changed/new files、全部runtime modules/schemas/tests/docs及既有5個public synthetic fixtures完整納入；無extra code modifications。私有workspace／corpus／PAK/LOCA／SQLite／keys／Divine／test outputs未commit。Staged and committed path sets與canonical hashes完整核對；package內容另作allowlist、collision、credentials/binary-signature audit。

## 7. User-approved pending report exclude exception

Git rev-parse --git-path info/exclude回傳.git/info/exclude，absolute path：D:/workspace/codex/BG3/bg3loc-m6-i1-integration/.git/info/exclude。原倉庫exclude位於D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/.git/info/exclude，兩者不是共用；原檔SHA保持不變。

只在獨立clone local exclude新增一條exact anchored rule：

    /docs/research/bg3loc-mainline-m6-i1-git-integration.md

沒有docs/research/*萬用規則，沒有改tracked .gitignore或原始working tree。報告實際位於此隔離checkout docs/research/，**尚未tracked／未commit**；SHA256記錄於checkout外D:/workspace/codex/BG3/m6-i1-evidence/report-receipt.json並在交付回覆列出。此SHA不自寫入報告，以免自含hash改變內容。

User正式核准的clean定義是：C1–C4全部committed、工作樹無其他差異，唯一pending report受到明確暫時排除；**不表示所有交付物都已commit**。正常git status clean必須同時交付git status --ignored／check-ignore證據，不能以clean掩蓋report。

**C5必做：** 移除local info/exclude上述exact一條規則，保留其餘原始exclude內容；確認報告變成可追蹤、實際納入正式Git，並檢查git ls-files包含此報告且exclude不再含暫時rule。不自动force-add或把該rule搬到.gitignore。不額外建立第五個Commit。

## 8. C5 readiness / remaining gates

**C5技術內容可提交下一階段審查，但尚未開始／未取得實施授權。** 建議先核准本M6-I1 implementation review（包含C4補充audit時序瑕疵之確認），再另行授權M5八個version/docs/producer paths及本報告tracking、移除exact exclude；不得因四commit完成或測試除環境項通過，就自動進C5／正式發布。

Remaining release gates：四hosted jobs NOT VERIFIED、可用socket環境HTTP demo、真正Windows Native安裝唯讀與小scope game-load，以及明確授權Apply/Rollback。長path／3個research BOM限制保留；A7／Production／Provider／B1-03 Activation未驗收且不擴大功能。


本次四commit及local engineering evidence供獨立review；version write／C5 commit仍未授權。不push/merge/tag/Release/PyPI、開Provider或更動遊戲。原始dirty checkout完整保留，future Push必須指定核准GitHub目的地，不能沿用local clone origin誤寫原倉庫。

Evidence：D:/workspace/codex/BG3/m6-i1-evidence/ 的source-receipt、checkout-isolation、commits、每group source/staged/diff/tests logs/JUnit、C3-harness-correction、C4-postcommit-diff-audit、full、package inventories/results、installed Basic smoke、final source/Git/exclude/report receipts；pytest shortroots亦為隔離synthetic資料。

**BG3Loc MAINLINE M6-I1 — GIT INTEGRATION READY FOR REVIEW**
