# BG3Loc Mainline M1-A3/A4 — CI & Source Distribution Reproducibility

日期：2026-10-11。僅 A3/A4；A1、A6、A2 已接受，全部既有 dirty work 保留。本報告針對目前工作樹，不是已發布 tag。

## 結論與結案建議

- **A3：實作 READY FOR REVIEW；GitHub-hosted Windows/Ubuntu CI = NOT VERIFIED。** 建議接受 CI 入口／設定修正，但正式 hosted matrix 驗收須在使用者另行允許發布這些變更後取得四個 jobs 的實際結果。YAML syntax／本機 PASS 不能當作 hosted CI PASS。
- **A4：fixtures／public test resource closure、sdist→wheel、乾淨安裝與 payload 一致性已驗證。** 建議接受 A4 fixture/resource remediation 並結案：clean-sdist 完整收集與 1413 個可執行 tests 通過。唯一 HTTP sandbox failure 另列 ENVIRONMENT-BLOCKED，不偽稱完整 suite PASS；hosted HTTP、Linux/Python 3.11 與既有 BOM parser 限制仍未解除。
- 不 commit/push/merge；未啟用 Provider Transport，未變更 runtime production code、A5/A7/A8、frozen contracts、H0/HSE/HD 或 B1-03 OFF/guards。

## 1. 原始問題與修改位置

原 `.github/workflows/ci.yml` 只有 Ubuntu + Python 3.12、5 分鐘 timeout、`pip install -e .`、`unittest discover`。test dependencies 沒有 pytest；PR paths 漏掉 schemas/docs/examples/MANIFEST 等。原 sdist 雖有 test modules，沒有 `tests/fixtures/`，也沒有 `scripts/extract-research-baseline.py`，造成 import-time collection failure。

| 修改位置 | 行為 |
| --- | --- |
| `.github/workflows/ci.yml::jobs.test` | Windows/Ubuntu × Python 3.11/3.12；正式 pytest collect/full-suite；包含 HTTP demo；clean-sdist pipeline；failure logs/JUnit/statistics；所有 PR/push/manual events，無 paths filter。 |
| `pyproject.toml::project.optional-dependencies.test` | `pytest>=9,<10`、`build>=1.4,<2`、`setuptools>=77.0.3`、`PyYAML>=6,<7`。pytest 9 提供現有 unittest subtests 支援；setuptools 為明確 standalone build dependency。一般 runtime dependencies／version 不變。 |
| `MANIFEST.in` | 納入 tests、scripts、tools/ci、CI workflow；既有 docs/examples/schemas 繼續保留；prune workspace/build/dist/.venv 與 game/DB/binary/cache files。 |
| `tools/ci/check_loopback.py::main` | 真實 loopback HTTP server/client；socket denial 回傳 1，不是假 PASS 或 skip。 |
| `tools/ci/verify_distribution.py::main` | fresh sdist build→安全解壓→從解壓來源 build wheel→資源比對→獨立 venv wheel[test] install→CLI/schema smoke→sdist collect→完整 pytest。失敗保留非零 exit。 |
| `verify_distribution::check_public_paths/unpack_sdist/verify_contents` | private/binary/unsafe archive path rejection；五個 reviewed synthetic fixtures 完整 inventory；test helpers／Stage 0 docs／runtime／schemas byte parity。 |
| `tools/ci/summarize_tests.py::summarize/main` | JUnit passed/failed/errors/skipped；缺報告 = NOT VERIFIED；GitHub step summary + stdout。JUnit 顯示 pytest 報告的 testcase 統計；`-q` terminal 另顯示 subtests 統計。實跑 intentional failing unittest subTest probe 確認會回傳 exit 1。 |
| `tests/test_ci_distribution.py` | 22 項 CI、fixture、archive privacy/traversal/link/device、failure-summary 與 loopback-denial regressions。 |
| `docs/development/testing.md` | Git/sdist test extra、完整測試、offline wheelhouse、native-backend 與平台／BOM 限制。 |

沒有移除 fixtures、增加測試排除或修改既有 skip 條件。

## 2. CI Test Matrix

| OS | Python | YAML/structure checks | 實際 GitHub-hosted execution |
| --- | --- | --- | --- |
| windows-latest | 3.11 | PASS | NOT VERIFIED |
| windows-latest | 3.12 | PASS | NOT VERIFIED |
| ubuntu-latest | 3.11 | PASS | NOT VERIFIED |
| ubuntu-latest | 3.12 | PASS | NOT VERIFIED |

`fail-fast: false`，每 job timeout 40 分鐘，permissions 僅 contents:read。取消中的 run 可停止；其他 step 失敗後仍執行完整測試與收集診斷，upload-artifact 保留 JUnit／command logs／report。CI 不排除 `test_public_demo.py`，完整 suite 的失敗會使 job 失敗。

CI hosted capabilities 由 `check_loopback.py` 加上真實 demo 驗證。此 dirty 工作樹沒有 commit/push，也沒有 dispatch 尚未發布的 workflow，因此四個 hosted jobs 的實際 socket、安裝、Linux/Windows 行為尚未查證。

## 3. Pytest Collection Before / After

| 來源 | 結果 |
| --- | --- |
| 原 CI 的 unittest discover | 454 cases；漏掉 378 個 top-level pytest test functions／26 modules（含參數化等） |
| 修改前 Git 工作樹 pytest | 1393 tests collected，無 errors |
| 修改前 fresh sdist pytest | **1273 tests collected、4 collection errors、exit 2**：fixtures 的 p3/p4 golden 與 baseline helper script 缺失 |
| 修改後 Git 工作樹 pytest | **1415 tests collected，exit 0** |
| 修改後 fresh sdist pytest | **1415 tests collected，exit 0**，與 Git 完全一致 |

22 個新增 cases 解釋 Git before/after 數量差異；未藉 exclude/deselect/新 skip 改善結果。證據：`workspace/mainline-m1-a3-a4/{before-test-discovery.json,collect-before.txt,sdist-collect-before.txt,collect-after.txt}`、`workspace/a34dist-final/collection.txt`。

## 4. Sdist Fixtures Before / After

原 fresh sdist：0 fixtures。修正後：以下五個原檔，SHA256 與本機來源一致；沒有修改其內容。

- `tests/fixtures/b1_02/source_rows.jsonl`
- `tests/fixtures/b1_02/portable_source_rows.jsonl`
- `tests/fixtures/b1_02/ruleset.json`
- `tests/fixtures/b1_02/p3-baseline.json`
- `tests/fixtures/b1_02/p4-identity-baseline.json`

直接檢視確認都是 invented identifiers、fictional spell/item/quest 文本、dummy model、synthetic prompt bytes 與其 goldens。不是 proprietary BG3 corpus／真正 API keys／hidden assignments。future fixtures 須經公開 synthetic review，更新 checker allowlist；不自動信任新增的資料檔。

同時補入 import-time 必要的 baseline extractor script、完整 public scripts、CI tools/workflow、既有 Stage 0 document schemas/goldens、fictional demo 與 runtime schemas，避免只修一個 missing file 後仍無法完整測試。

## 5. Fresh Environment Results

公開 PyPI dependency wheels 已下載到 ignored wheelhouse；18 個檔案的 names／sizes／SHA256 記錄於 `wheelhouse-lock.json`。乾淨環境未使用 system-site-packages。使用 pip 的正常 dependency resolver 從這些 wheels 安裝，不複製另一個 checkout 的 bg3loc，也不手工拷貝 site-packages。

- Developer test venv：Python 3.12.10、pytest 9.1.1、build 1.6.1、setuptools 84.0.0、PyYAML 6.0.3、jsonschema 4.26.0、openpyxl 3.1.5。
- 第二個 clean venv 安裝由 sdist 重建的 wheel[test]；`pip check` 通過。
- 無 source import 的 external-cwd／`python -I` smoke：module 實際位於 clean venv、sys.prefix != sys.base_prefix、SchemaStore root 指向 venv/share/bg3loc/schemas。
- 六個 smoke：pip check、installed module/schema load、module --version、--help、production --help、installed bg3loc console executable --version，全部 exit 0。
- 隨後 pytest 專門使用 unpacked sdist 的 src 與 test resources；subprocess 的 PYTHONPATH 同樣綁定 unpacked src，避免另一份已安裝 checkout 造成假證據。
- Full clean-sdist test result：1413 passed／1 skipped／1 failed，441.96 s；exit 1。唯一 HTTP demo failure 已核對為 WinError 10013（ENVIRONMENT-BLOCKED）；沒有 collection／其他 test errors。

此驗證支持公開 inputs 的 collection／執行／runtime payload 重建一致性；未承諾 tar/gzip/ZIP timestamp headers 的 bit-identical build。

## 6. Wheel / Sdist Privacy & Closure Audit

| 項目 | 結果 |
| --- | --- |
| Sdist | 897,448 bytes／399 files；五份 fixtures 齊全 |
| Wheel | 430,624 bytes／170 entries；123 Python/PowerShell runtime files、41 schemas，payload 與 source/sdist byte-identical |
| Sdist public inventory | 所有 payload 對應 nonignored public source inventory；其餘只有 setuptools 生成的 PKG-INFO／egg-info／setup.cfg；無 unexpected payload |
| Wheel public inventory | 除 runtime、41 schemas、dist-info metadata 外，無額外 payload |
| Console entry point | `bg3loc = bg3loc.cli:main` 存在；fresh console execution PASS |
| Private/game artifacts | 無 workspace、PAK、LOCA、SQLite、Divine/.dll/.exe、hidden assignments、responses、實際 credentials files；否定 probes 確認這些路徑不能穿透 checker |

fixture SHA、archive SHA/size、dependency-wheel hashes 及 inventory 證據分別為 `workspace/a34dist-final/report.json`、`workspace/mainline-m1-a3-a4/{archive-audit.json,wheelhouse-lock.json}`。public fixtures／test constants 中明確的虛構 key 或 prompt，不是使用者實際憑證或專有素材。

## 7. Platform-specific Limitations

- 本次實跑平台：Windows＋Python 3.12；Python 3.11 與 native Ubuntu/macOS 本次未實跑。不得宣告 hosted CI／跨平台正式驗收 PASS。
- 本機 real loopback probe：`URLError / WinError 10013`，exit 1。HTTP demo 的 pytest failure 保留，另記 environment-blocked；CI 中沒有永久排除或偽造成功。
- 既有 native symlink probe 若因 host 權限不足，保留原 SKIP 並揭露；Linux 的 Windows-only mapped-section/reparse/handle tests 依原平台 gate 跳過，沒有新增大量 skip。
- `tests/` 為 synthetic／mocked backend；未要求 CI 安裝 BG3、LSLib 或 proprietary assets。外部 Divine／真實安裝整合需另行平台驗收；`scripts/test_research_integration.py` 缺 backend 的 early-exit 不是 integration PASS，沒有把它當作 CI 正式入口。
- **既有 BOM 限制**：`research/research-{mapping,scan,summary}.schema.json` 保留 UTF-8 BOM。三檔已完整封裝、byte parity 與 BOM-aware JSON/schema check PASS；generic `SchemaStore.load` 不接受 BOM。其餘 38 schemas 的 installed SchemaStore load PASS。沒有以刪除檔案避開，也未擅自修改 schema/runtime parser；這是既有 API 限制，須在另行授權的修正範圍處理。

## 8. Targeted / Full Regression

| 執行 | 結果 |
| --- | --- |
| 新 CI/package tests | 22 PASS，0.48 s |
| CI + A1/A6/A2 + Provider + H0/HSE/HD + Stage 2/3 targeted | **288 passed、6 subtests passed**，56.22 s |
| Git checkout 完整 suite（含 HTTP demo） | **1413 passed、1 skipped、1 failed**，440.42 s；exit 1。唯一 failure 為 HTTP demo，已核對三筆安全 WinError 10013 attempts → ENVIRONMENT-BLOCKED。不是 full-suite PASS。 |
| Clean sdist 完整 suite（含 HTTP demo） | **1413 passed、1 skipped、1 failed**，441.96 s；exit 1。唯一 failure 為 HTTP demo，三筆安全 WinError 10013 attempts → ENVIRONMENT-BLOCKED；不是 full-suite PASS。 |
| HTTP loopback | ENVIRONMENT-BLOCKED；非 PASS |

targeted 明確覆蓋 locale/material、source freshness、Provider diagnostics、H0/HSE frozen input/effective/actual-message byte parity、HD identity/provenance、semantic REVIEW 與 transport stop guards。full command 不使用 ignore/deselect；不把 socket failure算入 PASS。命令／JUnit 留於 ignored task workspace。

## 9. Git / Scope

開始 HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch：`feat/b1-03-dialogue-context`；30 modified／45 untracked。387 個原有 nonignored files 保存 SHA256 seals。

只改三個既有檔：`.github/workflows/ci.yml`、`MANIFEST.in`、`pyproject.toml`。其餘 **384／387 byte-identical**，包括所有 production source、frozen contracts、A1/A6/A2、B1-03 defaults／guards、既有 test fixtures。新增三個 CI helpers、一個 test module、一份 developer testing doc 與本報告。

最終 Git status：33 modified／49 untracked（含先前 dirty work）；HEAD/branch 不變；不 stage/commit/push/merge，未 deployment，未付費 Provider call 或解除 Production Transport 防護。

## 10. Next review

接受設定／封裝 remediation 與本機證據後，另行授權發布／取得 hosted 四 jobs 實測。Hosted Linux/Windows、Python 3.11、HTTP socket 能力與 clean-sdist pipeline 都不能由 YAML 結構驗證推定。既有 BOM parser 限制獨立保留，不在此階段修改 A5/A7/A8 或 B1-03。

完成狀態：**BG3Loc MAINLINE M1-A3/A4 — READY FOR IMPLEMENTATION REVIEW**。

最終證據：`workspace/mainline-m1-a3-a4/{full.xml,full.txt,targeted.xml,targeted.txt,junit-summary.txt,scope-audit.json,git-status-final.txt}`；`workspace/a34dist-final/{collection.txt,tests.xml,tests.txt,report.json,smoke-*.txt}`。`git diff --check` PASS；所有原有 production source／frozen contracts 保持 bytes。
