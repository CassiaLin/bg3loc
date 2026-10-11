# BG3Loc M7-P2 — Python 3.11 Compatibility Remediation

2026-10-12。狀態：**READY FOR REMEDIATION REVIEW**。本機修復與 targeted gates 通過；完整測試及 fresh-install 的環境限制如下，不能宣稱 Full PASS 或 hosted CI 修復已驗收。

## 1. 基準及授權範圍

- 隔離 checkout：`D:/workspace/codex/BG3/bg3loc-m6-i1-integration`。
- Branch：`integration/windows-basic-1.4.0rc1`；HEAD 不變：`f37987429b2a06edcdf5f05946c41fcdef955db1`；commit tree 不變：`bf86a019bc3f2395073abcca010bf71bbdf6fa31`。
- Version：`1.4.0rc1`，不修改版本、CI、frozen contracts、Prompt、identity 或 transport guards。
- [GitHub CI Run 38179398514](https://github.com/CassiaLin/bg3loc/actions/runs/38179398514) 僅 GET 讀取。Windows job 114588548223／Ubuntu job 114588548264 的 logs 均確認 Compile 在 research.py:1309 失敗：`SyntaxError: f-string expression part cannot include a backslash`。該位置是 multiline f-string 的結束 delimiter，問題運算實際位於原 1113、1114、1121 行。修復未提交、未推送，因此本次 hosted verification **NOT VERIFIED**；未 re-run／dispatch。

外部證據根目錄：`D:/workspace/codex/BG3/m7-p2-evidence`。`preflight.json` 逐位元組驗證 C5 419 個 tracked source files，以及原始 dirty tree 416 個公開檔案。所有測試素材為 synthetic；沒有真實遊戲／付費 Provider 操作。

## 2. 根因及最小 Diff

修改 `src/bg3loc/commands/research.py::extract_and_generate_story_ledger`（約 1092 行）：

```python
ps_ledger_path = str(ledger_path).replace("\\", "\\\\")
ps_oldtext_path = str(oldtext_path).replace("\\", "\\\\")
ps_game_dir = str(game_dir).replace("\\", "\\\\")
```

在 f-string 內改為插值以上三個字串。既有 `str(...).replace(...)` 的運算與轉換語意完全保留。Production diff 僅 **6 insertions / 3 deletions**；不修訂 PowerShell quoting、parser、fallback 或錯誤處理。`git diff --check` 通過。

修復前完整 `research.py` 封存於 `research-before.py`，SHA 對應 C5 snapshot；3.11.9 compile 重現 line 1309 SyntaxError，3.12.10 可編譯。修復後 actual 3.11 compiler 掃描全部 125 個 `src/**/*.py`，另加 tests、tools/ci 共 215 個 Python 檔案：無其他 Python 3.12-only 語法問題。此為實際語法／匯入與目前回歸範圍，不能推論所有未測 runtime 行為已認證。

## 3. 雙版本驗證

| 驗證 | Python 3.11.9 | Python 3.12.10 |
| --- | --- | --- |
| Compile：src + tests + tools/ci | 215 files PASS | 215 files PASS |
| Import：bg3loc 模組，排除有執行副作用的 __main__ | 124 modules PASS | 124 modules PASS |
| Full pytest collection | 1,563 collected PASS | 1,563 collected PASS |
| Targeted suite | 415 passed / 147.85 s | 415 passed / 148.37 s |
| PowerShell AST renderer／actual tempfile bytes | PASS | PASS |
| Full available pytest，HTTP demo 未排除 | 見下表 | 見下表 |

Targeted 路徑與完整 command 保存在 `311-targeted.json`、`312-targeted.json`；collection／compile-import 記錄為 `*-collection.json`、`*-probe.json`。執行 interpreter：

- 3.11：`m7-p2-evidence/venv311/Scripts/python.exe`，由 [python.org 官方 Python 3.11.9 Windows embeddable package](https://www.python.org/downloads/release/python-3119/) 建立隔離 uv venv。官方 python.exe Authenticode Valid。未安裝系統 Python；portable bundle 起初沒有 stdlib venv/ensurepip，因此 clean venv 由 uv 建立。完整測試首輪有 18 個 CI/package tests 在 import venv 時失敗：已保留原 19 failed / 1,543 passed / 1 skipped（含 HTTP failure）證據。從同版本官方 Python-3.11.9.tgz 補入 13 個 venv/ensurepip files，僅修改外部隔離 runtime，SHA/inventory 保存於 stdlib-supplement.json。補入後整份 CI/package test module **22 passed**，再完整重跑 3.11 suite；沒有修改 project code 或排除測試。不宣稱 stdlib venv installer runner 在此 portable 配置已完成完整驗收。
- 3.12：既有 `bg3loc-b1-02-real-corpus/workspace/a34venv/Scripts/python.exe`，source 指向隔離 checkout，禁寫 bytecode，TEMP/TMP 與短 basetemp 均在 evidence/測試專用目錄。

Full available regression：

| Python | 真實 pytest 統計 | Wall time |
| --- | --- | --- |
| 3.11.9 | ====== 1 failed, 1561 passed, 1 skipped, 1 warning in 488.60s (0:08:08) ======= | 489.43 s |
| 3.12.10 | ====== 1 failed, 1561 passed, 1 skipped, 1 warning in 595.99s (0:09:55) ======= | 596.88 s |

HTTP demo 保持原測試；WinError 10013 屬 **environment-blocked，不能算 PASS**。兩版唯一 failure 都是 `test_demo_accepts_relative_output_from_external_cwd`；實際 SQLite attempts 各三筆 `PROVIDER_TRANSPORT_ERROR / Provider transport failed (WinError 10013)`，保存於 `http-environment-evidence.json`。3.11 首輪結果保留於 `311-full.xml/.txt/.json`，補齊 stdlib 後完整重跑為 `311-full2.xml/.txt/.json`；3.12 為 `312-full.xml/.txt/.json`。本機結果不代替 Windows／Ubuntu hosted CI。symlink privilege skip 與 intentional duplicate ZIP warning 分別保留，不新增 skip/exclude。

## 4. PowerShell 位元組一致性

`actual_script_probe.py` 在 3.12 載入封存的 C5 原函式、在 3.11／3.12 執行修復後正式函式。backend probe 僅使用 synthetic DLL placeholder；攔截 subprocess.run 於 transport 前讀取真實 NamedTemporaryFile bytes，**沒有執行 PowerShell、LSLib 或遊戲擷取**。

同樣的 ASCII／中文含空格輸入路徑，各驗證 pwsh success 及 pwsh 非零後 powershell fallback。每份 before／after bytes 直接比較，不僅比較字串。所有 fallback invocation 的 script bytes 也一致，temporary script 刪除行為保持。

| 實際 script case | Bytes | 修復前 = 3.11 after = 3.12 after SHA256 |
| --- | --- | --- |
| ASCII 含空格（success / fallback） | 14,794 | `555b4e4d0e3af5309c39ff7d6826ebd771bcac61a55665cab97c61659ebb6fea` |
| 中文含空格（success / fallback） | 14,789 | `66793dc9edcbec24bc886a5d79d0ae940b26d035882cd5ea41952efe86cba6a0` |

證據：`actual-312-before.json`、`actual-311-after.json`、`actual-312-after.json` 及對應 `.ps1`。另有獨立 AST 全 renderer byte 比較（各 14,526 bytes），見 `311-probe.json`／`312-probe.json`。

新增正式 synthetic tests：`tests/test_research_python_compatibility.py` 共五個 cases，涵蓋 3.11 grammar、ASCII／Unicode 路徑、actual temporary script、primary/fallback 命令及清理。實際 Python 3.11 compile／import／collection 才是相容性驗證的主要依據；不以 3.12 AST feature_version 取代它。

## 5. 身分與安全門檻

Targeted regression 包含 Research CLI orchestration／scan／story／static audit／cross-domain、B1-02 portable/safety export、H0/HSE golden effective prompt／actual chat／request input hash、HD add/change/remove/proof identity、Stage 0 schema/frozen policies、Stage 2–3 fail-closed／semantic REVIEW／transport 不呼叫，以及 Basic baseline receipt／current workflow eligibility JSONL／XLSX。

`production_orchestration.py::ProductionPrepareRequest.dialogue_evidence` 仍為 None default；`commands/production.py` 仍只允許 explicit `--dialogue-evidence` opt-in。HD provider guard 的負向測試 `tests/test_dialogue_stage2.py`、`tests/test_dialogue_stage3.py` 使用 Mock transport 並驗證未呼叫。以上全部模組 bytes 與 C5 相同。418 個既有 tracked files 未變（唯一例外為 research.py 語法修復），包含所有 frozen contracts、B1-03 OFF 及 guards。未新增 HD activation、未修改 Prompt／Fingerprint canonicalization。

## 6. Wheel / sdist、clean install 與 privacy

只把 420 個核對過的公開來源（419 tracked + 新測試）複製至外部 `source/` 建置；不讀 ignored workspace。兩版 build 均成功；3.11／3.12 都從 unpacked sdist 重建 wheel。三份 wheel 的 entry set 與每個 entry bytes **完全一致**；archive SHA 不同源於封裝 timestamps，不聲稱整份 archive reproducible bytes。

| Artifact | Bytes | SHA256 |
| --- | --- | --- |
| `dist311/bg3loc-1.4.0rc1-py3-none-any.whl` | 447145 | `09c6b4c2c49b9e123754f994ac47a12eab052239e4e9b4635635568e54437b1e` |
| `dist311/bg3loc-1.4.0rc1.tar.gz` | 1054034 | `02370e733aae1c526cda53e3a9f382a62912f12195ad736257126f9f96bdbe82` |
| `sdist-wheel311/bg3loc-1.4.0rc1-py3-none-any.whl` | 447145 | `a631df944ef9e4c2412d8c3a5e518a3efbaa8ed2ca8f9db96a8773459b40b790` |
| `dist/bg3loc-1.4.0rc1-py3-none-any.whl` | 447145 | `6df4e025b1cc2ec1856203d55f12fe880aa9333b0319c5d256c648d79cfcf8f1` |
| `dist/bg3loc-1.4.0rc1.tar.gz` | 1053979 | `fc00677a532b648fbbc6365a436c24d1818dbcf0a08fdfdbd5dec0cfed20e420` |

各 inventory 存於外部 `*.inventory.json`；`package-audit.json` 確認：版本全部 1.4.0rc1、42 schemas、basic-source-baseline receipt schema、五份 synthetic fixtures、新測試、runtime `.py/.ps1` bytes；sdist 含必要公開程式／文件／fixtures。Path／duplicate/case collision／binary signature／credential-pattern audit PASS，無真實 PAK／LOCA／SQLite／API credentials／hidden assignments／Divine binaries。測試產生的私有快照与 `.ps1` evidence 沒有納入發行套件。

3.11 fresh `clean311` venv 安裝當次 wheel + `[test]`：package/producer version、CLI --version/help、research/workflow/production help、42 schema 格式均通過。39 SchemaStore loads 通過，三份 historical research schema BOM 限制保持原樣、另列，不修復本次範圍。Installed Basic JSONL／XLSX 均通過 project-init → check → prepare → 回填 → validate → rebuild → install **dry-run** → status；每組三個 fictional UID，三個 non-LOCA entry SHA parity；原 synthetic packages SHA 未變，沒有 apply/rollback/backups。Archive backend 為公開 synthetic ZIP/XML，不宣稱 Native LSLib 認證。證據 `311-installed-smoke.json`、`installed-basic311/result.json`。

Clean 3.11 在 unpacked sdist 另外 collection 1,563，renderer/H0/HSE parity targeted **68 passed**；見 `311-sdist-collection.txt`、`311-sdist-parity.txt/.xml`。

3.12 fresh venv 的依賴安裝與 package resource audit 完成，但在 smoke import `rpds.cp312-win_amd64.pyd` 時被 Windows Enterprise Code Integrity policy 阻擋：events **3033／3077**，保存 `code-integrity-events.json`。同一 DLL SHA `f2151350525864528ac0664f461ea49444b787834f05a0c96f34fb3ac2690046` 與可用舊 venv 相同；從 PyPI 重裝相同 dependency 亦被阻擋。**3.12 fresh CLI / Basic / fresh full-suite = ENVIRONMENT-BLOCKED，未執行完成，不能算 PASS**。原 `m7d12/report.json` 的 FAIL／traceback 完整保留。沒有降低安全政策、skip tests 或修改 packaging/production code以繞過問題。此前 uv standalone 3.11.16 的 DLL 同樣被 policy 阻擋，故改用官方簽章 3.11.9。此環境問題與 f-string 語法缺陷分開處理。

## 7. Git 保護與交付

預期唯一工作樹變更：

```text
 M src/bg3loc/commands/research.py
?? tests/test_research_python_compatibility.py
?? docs/research/bg3loc-mainline-m7-p2-python311-compatibility.md
```

無 staged changes。HEAD／tree／branch 保持 C5；原始 `bg3loc-b1-02-real-corpus` HEAD `896b4870b3a24d8506e6d751db3d4602925fb8fb`、branch 及 dirty status 不變，416 個公開 source files SHA 未變。兩 repo info/exclude bytes 未變。最終逐檔檢查及本報告 SHA 保存在外部 `final-protection.json`，不在報告自引用自己的 hash。

本報告與新測試仍 **untracked**，research.py **modified**，未 commit；沒有 push/merge/tag/rebase/amend/reset/clean、CI re-run、Release、PyPI、正式／外部 Provider calls 或真實遊戲修改。所有 build/test outputs 都在外部 evidence／專用 basetemp。

## 8. 下一步

最小修復可交付 remediation review。3.11/3.12 hosted matrix 與 fresh 3.12 Windows policy 阻擋仍需獨立環境驗收；既有 HTTP sandbox、symlink 與 research BOM 限制保留。未發現其他 production 3.12-only 語法需擴大修正。任何後續 commit/push/CI re-run 必須另行明確授權。

**BG3Loc M7-P2 — READY FOR REMEDIATION REVIEW**
