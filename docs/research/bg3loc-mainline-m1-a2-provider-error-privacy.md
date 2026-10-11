# BG3Loc Mainline M1-A2 — Provider Error Privacy

日期：2026-10-11。範圍僅 A2；A1/A6 既有成果保留。所有攻擊字串、金鑰、Authorization、Prompt、來源與候選譯文均為虛構資料。沒有付費 Provider calls。

## 結論

A2 實作完成，建議經 Implementation Review 後結案。錯誤診斷改為固定白名單訊息；HTTP status、既有內建 error codes、retryable、Retry-After 與 worker attempt/backoff 規則保留。未變更 schema、版本、Prompt、翻譯 input identity 或 activation guards。

狀態：**BG3Loc MAINLINE M1-A2 — READY FOR IMPLEMENTATION REVIEW**。

## Root cause 與實際資料流

1. `src/bg3loc/providers/openai_compatible.py::UrllibJsonTransport.post_json` 原先把 HTTPError 的任意 JSON/non-JSON body、全部 headers 傳回 Provider。
2. `OpenAICompatibleChatProvider.translate_with_provenance` 原先直接取 `error.message`，或使用 exception type + `str(exc)`；protected-syntax failure 也回傳 token/details。任意 `id` 可成為 failure request ID。
3. `src/bg3loc/execution_runner.py::run_worker` 的 resolver/provider exception handler 同樣使用原始 exception 文字；failure DTO 沒有邊界防護。
4. `src/bg3loc/execution_state.py::TranslationExecutionStore.complete_failure` 原樣存入 attempts 的 error_code/error_message/provider_request_id。Retry/resume 保留 attempts，因而把洩漏長期保留。
5. CLI execution 主要顯示 counts，而非 body；仍不能阻止 SQLite 洩漏。`production_reporting.py::_attempt_and_usage_report` 還把 historical error_code 原樣作為 JSON/CLI key，可讓不受信任自訂 code 洩漏。

## 修正前／後證據

`tests/test_provider_error_privacy.py` 最初的 22 個負向 probes，在原始 Provider/worker/store 實作全部 FAIL：HTTP 400/401/403/429/500 的 message/custom/id echo、超長 body、timeout/connection/URL/OSError/ValueError、實際 CLI retry/resume 的 SQLite，以及直接 failure DTO/store 邊界。

隔離證據：`workspace/mainline-m1-a2/before-negative.txt`。此檔只包含虛構資料；不屬於發布內容。

擴充後涵蓋 partial prompt/source/translation、未知 echo、原生 urllib HTTPError、malformed/non-JSON/oversized body、Unicode decode failure、DNS、exception traceback serialization、provenance callback、protected syntax、歷史資料讀取與 JSON report。

## 修改位置與設計

| 檔案／function | 防護 |
| --- | --- |
| `src/bg3loc/provider_diagnostics.py::safe_error_code` | 已知內建 code／HTTP 100–599 白名單；未知自由文字 code → `PROVIDER_ERROR`。不嘗試以 secret regex 推測敏感內容。 |
| `safe_error_message` | 固定訊息，目前最長 90 字元（測試上限 160）；不讀 body、payload、任意 message 或 exception repr。 |
| `transport_error_message` | 僅已知 timeout/DNS/connection 類別及 WinError 10013；不 stringify args、reason、URL 或自訂 exception 類名。 |
| `safe_attempt_diagnostics` | 歷史 failure 的讀取時遮蔽；保留 NULL，禁止從 history 推測內容；不改 DB history。 |
| `execution_runner.py::TranslationFailure.__post_init__` | immutable DTO 一建立就規範化 code/message，移除 failure request ID，repr/asdict/JSON 不攜帶原始錯誤。 |
| `execution_runner.py::run_worker` | resolver/provider exception 不再 stringify；retry 分類不變。 |
| `execution_state.py::complete_failure` | 直接呼叫 store 亦必須套用同一防護；原有 writer transaction、claim/owner guards 不變。 |
| `execution_state.py::get_attempts` | 歷史錯誤的安全讀取邊界。 |
| `providers/openai_compatible.py::UrllibJsonTransport.post_json/_post_json` | HTTP error body 最多讀 65,537 bytes；超過 65,536 不解析。只回傳 allowlisted numeric usage、Retry-After；丟棄 body 自訂欄位／ID／其他 headers。直接 transport exception 使用安全文字與 suppressed exception chain。 |
| `OpenAICompatibleChatProvider.translate_with_provenance/_provider_error_message` | 不回傳 raw body、prompt/token details 或 exception 字串；保持 send provenance 的單次 render／before-send 時序。 |
| `production_reporting.py::_attempt_and_usage_report` | 歷史未知 code 先正規化再合計，避免 CLI/JSON report 洩漏。 |
| `tests/test_openai_compatible_provider.py` | 一個 failure ID assertion 改為 NULL；正常成功 ID 的原有測試保留。 |
| `tests/test_provider_error_privacy.py` | 本次新增自動回歸。 |

HTTP error body 超過解析限制時 usage 為 UNKNOWN；不影響 HTTP retry classification 或 Retry-After。成功翻譯仍保存正常 translated_text；privacy gate 限定錯誤診斷通道，沒有把翻譯內容當錯誤文字回傳，也沒有新增 raw-error debug channel。

## 錯誤格式與相容性評估

公開函式 signatures、DTO 欄位、SQLite columns、manifest/schema versions 不變。自由文字 error_message 不再保留 Provider 原文；failure provider_request_id 為 NULL；未知外掛 code 使用穩定 fallback。這是 A2 的診斷安全性變更，依賴原始 body/message/失敗 ID 的外部診斷程式需調整。所有既有內建 code 與 HTTP status code 保持；不把 Provider 自訂錯誤內容視為版本化身分契約。

Retryable：HTTP 429/5xx 與 transport exception 保持 True；其他非 2xx 保持 False；prompt/provenance/worker exception 原有 final 行為保留。原生 malformed JSON 仍走 `PROVIDER_TRANSPORT_ERROR` + retry；JSON object 缺少合法 choices 仍為 `PROVIDER_RESPONSE_INVALID` + retry。違反 transport protocol 的非-object payload 轉為安全的 invalid-response route。

`RetryPacingPolicy.retry_delay`、attempt limits、lease/owner/input identity、success text、H0/HSE prompt/input bytes 都未修改。歷史 NULL 仍表示 UNKNOWN。既有歷史 SQLite 實體檔不做清洗/backfill；有過 raw error 的舊 DB 及其備份仍應視為原有敏感本機資料，安全讀取不等於刪除已存在的 bytes。

## SQLite／CLI／Log privacy audit

- 實際 production CLI 使用 patched transport（非網路）：HTTP 500 → resume timeout，兩筆 attempts 為 failed-retryable／failed-final。SQLite 全部 attempts、原始 DB bytes、stdout、logging capture、輸出 JSON report 都無虛構敏感 markers。
- 直接 `complete_failure` 傳入未知 code、echo message 與 ID 仍無法穿透；DTO repr/asdict 也無原始內容。
- HTTP headers 僅 Retry-After 供現有 parsing；不持久化 headers/body。未知 Provider 欄位與 partial echo 被整體忽略，毋須預先知道 secret。
- 歷史 raw-code/message/ID fixture：safe API/report 不顯示，raw DB rows 前後相同；NULL fixture 沒有補值。
- 未增加 logging、debug dumps、payload archive 或 raw-error 檔。

## 回歸證據

最終驗收使用目前工作樹 `src`（PYTHONPATH）；pytest/TemporaryDirectory 使用隔離 ignored workspace，避免 Windows sandbox 的預設 TEMP 權限錯誤。

| 項目 | 結果／證據 |
| --- | --- |
| A2 privacy cases | 62 PASS，包含於 targeted JUnit |
| Targeted | 230 passed、6 subtests，44.75 s；`workspace/mainline-m1-a2/targeted.txt`／`targeted.xml` |
| Full current-tree | **1391 passed、1 skipped、75 subtests**，358.40 s；`workspace/mainline-m1-a2/full-current.txt`／`full-current.xml`。無 failure/error。 |
| HTTP demo | **ENVIRONMENT-BLOCKED**；`workspace/mainline-m1-a2/demo.txt`／`demo.xml`。目前工作樹 attempts 三筆為 `PROVIDER_TRANSPORT_ERROR`，安全訊息 `Provider transport failed (WinError 10013)`，兩筆 retryable、一筆 final。不是 PASS。 |
| Diff whitespace check | PASS；`git diff --check` |
| Config identity | `openai_compatible_execution_config_hash` before/after AST 相同 |

第一輪完整回歸為 1383 passed／1 skipped／75 subtests（371.78 s），但未指定 subprocess 的 PYTHONPATH，且尚未包含最後新增的 8 項 privacy probes；不能代替 current-tree 最終回歸。Windows TEMP 與測試 scaffolding 修正過程的失敗 logs 留於 ignored workspace，不列為 PASS。

Targeted 範圍：privacy、OpenAI provider、execution policy/state、worker CLI、production execution/report、B1-03 Stage 2/3。包括 frozen H0/HSE input/effective-prompt/actual-message byte parity、HD identity/provenance、semantic REVIEW、B1-03 transport stop guards。

完整 available regression 排除獨立 `tests/test_public_demo.py`，demo 單獨記錄結果。Native Windows symlink creation 的一項測試因 OS 權限不足維持 SKIP；不宣稱已驗證 native symlink creation。其他 tamper/path/reparse guards 依既有回歸執行。

## Git／範圍保護

開始 HEAD：`896b4870b3a24d8506e6d751db3d4602925fb8fb`；branch：`feat/b1-03-dialogue-context`。開始時 28 modified／42 untracked；384 個既有 nonignored files 作 SHA256 seals。

本階段只改既有 5 檔（runner/state/provider/reporting/provider tests），新增 diagnostics module、privacy tests、本報告；其餘 379／384 files byte-identical。execution config hash function AST 相同；frozen contracts、H0/HSE identity modules、B1-03 default/transport guards、A1/A6、Review、CI、PAK closure 均未變更。所有測試證據位於 ignored workspace。

最終 Git status：30 modified／45 untracked（含所有先前 dirty work），HEAD／branch 不變。不 stage/commit/push/merge，沒有 Production Activation。

Task delta／範圍 seals：`workspace/mainline-m1-a2/*-task.diff`、`starting-seals.json`、`scope-audit.json`、`git-status-final.txt`。六份 Stage 0 frozen 文件均保持 SHA256；無公開 schema/version contract 變更。
