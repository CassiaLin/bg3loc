# 更新紀錄

[English](CHANGELOG.md)

## 1.3.0 - 2026-09-28

### 新增功能
- 為較大型的在地化專案提供 production 流程：功能分類、依類別分批，以及可續跑的 OpenAI-compatible provider 執行。
- QA 路由（PASS / RETRY / REVIEW / FAIL）、人工審核決議，以及完成度 gate 後的 finalize/rebuild。

### 可靠性與安全
- 暫時性 provider 失敗時的有界重試、`Retry-After` 與指數退避。
- 未分類項目須明確決議，不會默認為已翻譯。

### 報表
- 唯讀進度與錯誤報表、provider 回報的 token 用量，以及依使用者提供價格計算的可選估算。

### 文件與公開發布
- 新手、ruleset 與疑難排解指南，以及不產生可安裝遊戲內容的虛構端到端 smoke demo。
- 公開 Git 歷史從淨化後的產品樹重新開始，不含私人研發 ancestry 或遊戲衍生 corpus。

### 驗證
- 公開 repository 通過 464 個測試與 75 個 subtests；wheel 與 sdist 隔離 demo 通過。


## 1.2.0 - 2026-09-27

### 新增功能
- 新增大規模翻譯 production 流程，可處理數萬到數十萬筆 `ContentUid`。
- 新增 deterministic functional classification 與 category-aware batching。
- 新增可續跑的翻譯執行狀態、provider attempt history、retry/lease/recovery。
- 新增自動 QA 路由：PASS / RETRY / REVIEW / FAIL。
- 新增 production completion 與 merge-ready bridge，只允許安全資料進入 rebuild。
- 新增人工 REVIEW 決議：可接受目前譯文或人工修訂；修訂後必須重新 QA。
- 新增 `other / unclassified` 決議流程，可 `assign`、`exclude` 或 `pending`，並保留人工 provenance。

### 安全與可重現性
- 每個 `ContentUid` 維持唯一 production ownership，不因 batch、provider request 或 review queue 產生第二份翻譯工作。
- 人工 REVIEW approval 綁定 QA ruleset、QA input hash 與 output hash；任一變更都會使舊 approval 失效。
- resolved classification ledger 會被 batch fingerprint 的 SHA-256 綁定。
- `excluded` 與尚未處理的 `unresolved` 分開輸出。

### 驗收
- LSTP-01A～01F：已驗收。
- Public Large-Scale Workflow Integration 02A：完成。
- Production Human Review Resolution 02B：已驗收。
- Unclassified Resolution Policy 02C：已驗收。
- 最終整合 regression：`408 passed`、`68 subtests passed`、`0 failed`。
## 1.1.0 - 2026-09-20

### 新增功能
- 新增公開端到端翻譯 workflow 與高階 project/workflow CLI。
- 新增 schema-backed 專案設定與 workflow state。
- 新增 `basic`、`context`、`full` evidence profile 與 `standard`、`blind-first` translation strategy。
- 新增 ContentUid scope，可做小範圍翻譯專案。
- 新增 Bark、Quest、UI/Skill、多語與臺灣用語審查流程。
- 新增可從使用者自己的 BG3 安裝重建 research mapping 的流程。
- 強化 release packaging，source distribution 會包含公開 docs 與 schemas。

### 驗收
- E2E-01A～01F 全部完成。
- Windows clean-room 真實遊戲流程通過 scan / extract / prepare / validate / rebuild / install dry-run。
- 當時 release regression 基準：`294 passed`。

## 1.0.0 - 2026-09-11

### 新增功能
- 完整的 `scan` → `extract` → `build` → `validate` → `rebuild` → `install` 處理流程。
- 支援任意你在遊戲中找到的語言配對，不強制規定語言。
- 提供不同的翻譯方式：基本模式、附帶語境模式，以及不看原譯本盲翻的模式。
- 支援 Excel (XLSX) 和試算表 (CSV) 翻譯檔案，保護原文不被修改，並確保遊戲內的代碼不會損壞。
- 加入檢查機制，確保遊戲的壓縮包裝檔在重建時沒有問題。
- 安全的測試模式（`install --dry-run`）、自動備份、安全檢查以及復原修改的功能。
- 通過 Windows 實機測試，並確認能完美復原所有變更。
- 成功測試將英文翻譯成法文，證明工具可正常運作。
- 採用標準的 MIT 授權條款。

### 平台與測試狀態
- Windows 11 是我們主要測試通過的作業系統。
- 需要安裝 Python 3.11 或更新版本（在 3.12 測試通過）。
- 在 Windows 上需要 `Divine.exe`（來自 LSLib 1.20.4 的第三方解包工具）。
- Linux/Proton 與 macOS 尚未完成實機完整測試。
- 我們不保證能在所有系統上運作。

### 資料邊界
- 我們不提供《柏德之門 3》的官方文本或翻譯檔案。
- 你必須從你自己安裝的遊戲中提取遊戲的語言檔。
- 你必須自行下載第三方解包工具。

## 1.0.0-rc1 - 2026-09-10

### 新增功能
- 完整的 `scan` → `extract` → `build` → `validate` → `rebuild` → `install` 處理流程。
- 基本、語境與盲翻模式。
- 支援任何你已安裝的遊戲語言。
- 能自動找到 Steam 上的《柏德之門 3》安裝位置。
- 支援第三方解包工具 (LSLib)。
- 新增 CSV 與 XLSX 試算表格式供翻譯使用。
- 新增保護遊戲代碼與格式的檢查功能。
- 安全測試、備份與復原功能。

### 測試與安全性
- 在真實的 Steam 遊戲上測試了 Windows 11 的處理流程。
- 測試了從 `scan` 到 `install` 的完整流程，包含復原變更。
- 增強安全檢查，後端工具出錯時會直接停止，而不是假裝成功。
- 改善了只翻譯部分文本時出現的一大堆警告訊息。

### 目前已測試的環境
- Windows 11 是主要測試平台。
- 測試於 Python 3.12；支援 Python 3.11+。
- LSLib 1.20.4 是測試使用的第三方解包工具。
- 測試於 Steam 版的《柏德之門 3》。

### 目前的限制
- Linux/Proton 與 macOS 尚未完成完整測試。
- 此測試版本不代表所有平台都能完美運作。

### 資料邊界
- 我們不散佈官方遊戲文本。
- 你必須從自己的遊戲中提取檔案。
- 第三方解包工具需另外下載。
