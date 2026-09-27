# E2E-01B | 專案設定 (Project Config)

[English](project-config.md)

## 狀態

```text
Milestone: End-to-End Translation Workflow 01B
State: ACCEPTED
Implementation: complete
Depends on: E2E-01A ACCEPTED
Core reopening: no
```

## 1. 目的

專案設定檔（`bg3loc-project.json`）是您翻譯專案的總指揮中心。

它會記住您的選擇（例如您要翻譯成什麼語言），這樣您就不必每次執行指令時都重新輸入一遍。它的設計非常安全，您可以存檔並與他人分享。

它**不是**用來儲存您翻譯進度的存檔。它只會儲存您的規則與設定。

---

## 2. 標準格式

這個檔案的名稱永遠是：

```text
bg3loc-project.json
```

我們使用 JSON 是因為它是一種標準格式，在 Windows、Mac 和 Linux 上都能可靠地運作，不需要安裝額外的軟體。

---

## 3. 使用者設定 vs 執行時狀態

我們將「您的選擇」與「工具內部的進度追蹤」完全分開。

### 使用者設定 (由您控制)
這個檔案儲存您的永久選擇：
- 專案名稱
- 來源語言（通常是英文）與目標語言
- 任何額外的參考語言
- 您的情境深度 (`basic`、`context` 或 `full`)
- 您的翻譯策略 (`standard` 或 `blind-first`)
- 您的自訂拼字規則 (QA rules)
- 您的工作檔案要儲存在哪裡

### 執行時狀態 (由工具默默追蹤)
工具會用另一個隱藏的檔案來追蹤它自己的進度。它會記錄像是：
- 您安裝了哪個版本的《柏德之門 3》
- 祕密的檔案雜湊值 (用來確保沒有東西被意外刪除)
- 您是否已經通過了最終的驗證檢查

您永遠不需要去編輯這個狀態檔。

---

## 4. 檔案長什麼樣子

以下是檔案內部的確切樣貌：

```json
{
  "schemaVersion": "1.0",
  "project": {
    "name": "my-bg3-translation"
  },
  "game": {
    "installDir": null
  },
  "locales": {
    "source": "English",
    "target": "ChineseTraditional",
    "references": []
  },
  "workflow": {
    "evidenceProfile": "full",
    "translationStrategy": "blind-first"
  },
  "reviews": {
    "structural": "profile-default"
  },
  "qa": {
    "ruleSets": []
  },
  "inputs": {
    "glossary": null
  },
  "material": {
    "format": "xlsx",
    "maxRowsPerFile": 1500
  },
  "workspace": {
    "root": "workspace"
  }
}
```

---

## 5. 欄位意義 (這些設定代表什麼)

### 5.1 `schemaVersion`
永遠是 `1.0`。這告訴工具該使用哪一個版本的規則。

### 5.2 `project.name`
專案名稱！這只是給人看的標籤。

### 5.3 `game.installDir`
通常保持為 `null`（空白）。如果您使用 Steam，工具夠聰明，能自動找到您的遊戲。如果您把遊戲安裝在奇怪的地方，可以在這裡輸入資料夾路徑。

### 5.4 `locales.source`
您要翻譯**從**哪個語言開始（例如 `English`）。

### 5.5 `locales.target`
您要翻譯**成**哪個語言（例如 `ChineseTraditional`）。它不能和來源語言一模一樣。

### 5.6 `locales.references`
您想參考的額外語言（例如 `["Japanese", "French"]`）。您可以留空 `[]`。

### 5.7 `workflow.evidenceProfile`
您想要多少遊戲情境。必須是 `basic`、`context` 或 `full`。

### 5.8 `workflow.translationStrategy`
您是否想看到舊的翻譯。必須是 `standard` 或 `blind-first`。

---

## 6. 結構審查選擇

### `reviews.structural`

預設情況下，這會設定為 `"profile-default"`。工具會根據您的「情境深度」自動開啟正確的檢查：
- 如果您選了 `basic` 或 `context`，它會關閉進階的結構檢查。
- 如果您選了 `full`，它會開啟所有的進階檢查（例如 Bark、Quest、UI 和 Multilingual）。

您也可以手動輸入您確實想要的檢查項目，但前提是您的情境深度必須是 `full` 才能這麼做。

---

## 7. 專案語言 QA (自訂拼字規則)

### `qa.ruleSets`
您可以要求工具利用您自己寫的「禁用詞」或「標準拼法」清單來檢查最終翻譯。

範例：
```json
{
  "qa": {
    "ruleSets": [
      {
        "id": "project-usage",
        "type": "taiwan-usage",
        "path": "rules/project-usage.json"
      }
    ]
  }
}
```
如果工具發現相符的地方，它會標記出來請您重新檢查。它不會直接判定您失敗。

---

## 8. 專案詞彙表

### `inputs.glossary`
您可以指定一個字典檔案來幫助翻譯人員。

---

## 9. 翻譯素材設定

### `material.format`
您想要編輯哪種檔案。通常是 `xlsx`（Excel）。

### `material.maxRowsPerFile`
遊戲裡的文字非常多！工具會把工作切成較小的檔案。預設是每個檔案 1500 行，這樣您的電腦才不會因為試圖打開超大試算表而當機。

---

## 10. 工作區

### `workspace.root`
儲存所有翻譯檔案的資料夾。通常就叫 `workspace`。

### 翻譯範圍 (只翻譯一小部分)

正常情況下，工具預期您會翻譯整套遊戲。但如果您只想測試一行字呢？

您可以加上一個 "scope" 區塊，利用 `ContentUid` 告訴工具只需要在乎特定的台詞：

```json
{
  "scope": {
    "contentUids": [
      "h000006d4gcefbg4092gbb39gfeb27a3bb0a7"
    ]
  }
}
```
如果您這麼做，工具會只為那一行字建立一個超小的素材包。在安裝時，它會安全地跳過遊戲的其他部分。（目前，這只在您的情境深度是 `basic` 或 `context` 時才有作用）。

---

## 11. 安全性與可攜性

這個設定檔可以安全地與其他人分享。
它**絕對不會**儲存密碼、秘密的金鑰，或是 Larian 受版權保護的遊戲文字。

---

## 12. 驗收清單

*(開發人員確保有達成上述所有規則的技術清單。已全數打勾！)*

```text
E2E-01B | Project Config = ACCEPTED
```
