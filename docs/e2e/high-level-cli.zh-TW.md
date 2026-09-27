# E2E-01E | 高階指令介面 (High-level CLI)

[English](high-level-cli.md)

## 狀態

```text
Milestone: End-to-End Translation Workflow 01E
State: ACCEPTED
Depends on: E2E-01A / 01B / 01C / 01D ACCEPTED
Core reopening: no
```

## 指令列 (您真正會用到的工具)

以下是您要在指令列（像是 PowerShell）中輸入的簡單指令清單，用來施展魔法：

```text
bg3loc project init
bg3loc project check
bg3loc workflow prepare
bg3loc workflow validate
bg3loc workflow review prepare      # 進階操作
bg3loc workflow review integrate    # 進階操作
bg3loc workflow review resolve      # 解決文字衝突
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

預設情況下，所有這些指令都會去找您的 `bg3loc-project.json` 設定檔。

---

## project init (初始化專案)

**它的作用：** 建立您的 `bg3loc-project.json` 設定檔。
您告訴它您的專案名稱、來源語言以及目標語言。為了防止您不小心刪除自己的設定，如果專案檔案已經存在，它會安全地拒絕覆蓋。

## project check (檢查專案)

**它的作用：** 讀取您的設定檔，確保所有內容都合乎邏輯（例如確保您沒有把來源和目標設定成一模一樣的語言）。它不會動到您的遊戲檔案。

---

## 範圍限定專案 (只翻譯一小部分)

如果您只想翻譯一句特定的台詞來測試看看，您可以在執行 `project init` 時加上 `--content-uid <uid>`。

工具依然會掃描整個遊戲來了解那句話和其他東西的關聯，但它只會給您那**唯一一句話**去翻譯，而且它只會驗證並安裝那唯一一句話。（目前，這只在您的情境深度是 `basic` 或 `context` 時才有作用）。

---

## workflow prepare (流程準備)

```text
config → scan → extract → evidence → translation package → external translation boundary
```

**它的作用：** 處理所有繁重的工作，把您的檔案準備好。
它會檢查您的設定、掃描遊戲、提取文字、收集背景情境，並建立您的 Excel 試算表。

**它超級無敵安全。** 如果您已經開始翻譯，然後又跑了一次這個指令，它**絕對不會**覆蓋掉您已經輸入翻譯的檔案。

---

## workflow validate (流程驗證)

```text
returned translation → structural review validation → reconciliation → language QA → reconciliation → final validation
```

**它的作用：** 檢查您的作業。
它會讀取您填寫完的試算表，並驗證您有沒有把任何東西搞壞。它會自動執行您要求的所有任務、介面或拼字檢查。

如果檢查發現有錯，驗證會停止並告訴您該修復什麼。

如果兩個不同的檢查對同一個翻譯意見不合（發生衝突），驗證就會失敗。您必須建立一個名為 `manual-resolutions.jsonl` 的小檔案，告訴工具哪一個翻譯才是對的，然後執行：
```powershell
bg3loc workflow review resolve --input manual-resolutions.jsonl
bg3loc workflow validate
```

一旦所有東西都修復了，它會對遊戲內部的程式碼進行最終的安全檢查。

---

## workflow rebuild (重建)

**它的作用：** 把您完成且通過驗證的文字，重新打包成遊戲引擎看得懂的 `.loca` 格式。
（如果您還沒通過 `workflow validate`，它會拒絕執行！）

---

## workflow install (安裝)

**它的作用：** 修改您的遊戲！

**安全第一：** 預設情況下，執行這個指令只會進行「演習 (dry-run)」，以確保安裝時不會當機。
如果您真的想把翻譯安裝進《柏德之門 3》裡，您**必須**輸入 `--apply`。

---

## workflow status (狀態)

**它的作用：** 告訴您現在狀況如何！它會印出您目前的步驟、您使用的情境深度，以及您是否被錯誤卡住了。任何時候執行它都很安全，因為它不會改變任何東西。

---

## 執行時狀態 (它如何記住事情)

工具會在一個祕密的 `e2e-workflow-state.schema.json` 檔案中追蹤進度。

如果遊戲更新了，工具會注意到檔案雜湊值改變了。它會將您目前的進度標記為「已失效 (invalidated)」，讓您知道必須重新執行 `workflow prepare` 才能與新版本的遊戲同步。它絕對不會默默地重複進行真實的安裝。

---

## 驗收清單

*(開發人員確保所有指令都能正確且安全運作的技術清單。已全數打勾！)*

```text
Synthetic public CLI E2E acceptance: PASS
Local full test suite: 288 passed
E2E-01E | High-level CLI = ACCEPTED
```
