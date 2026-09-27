# E2E-01C | 翻譯素材包 (Material Package)

[English](material-package.md)

## 狀態

```text
Milestone: End-to-End Translation Workflow 01C
State: ACCEPTED
Implementation: not started
Depends on: E2E-01A ACCEPTED, E2E-01B ACCEPTED
Core reopening: no
```

## 1. 目標

為您建立一個容易使用的翻譯檔案包。它應該確切包含您需要的東西，而不會用多餘的軟體檔案來擾亂您。

---

## 2. 核心規則：兩個獨立的區域

我們在實體上將檔案分成了兩個資料夾：

```text
translation-package/
├─ translation-package-manifest.json
├─ delivery/
└─ internal/
```

### `delivery/` (您會看到的交付區)
這是您（或您的翻譯人員）實際查看與編輯的地方。它只會根據您的策略，顯示您被允許看到的文字。

### `internal/` (隱藏的內部區)
這是工具私人的工作區。它存放著原始且未經更動的文字，以便稍後用來檢查您的工作。

如果您選擇了 `blind-first`（盲翻，隱藏舊翻譯），舊文字就會被安全地鎖在這個 `internal/` 資料夾中，讓您在翻譯時不會看到它。

---

## 3. 資料夾裡面有什麼？

根據您的設定，它看起來大概會像這樣：

```text
translation-package/
├─ translation-package-manifest.json
├─ delivery/
│  ├─ materials/
│  │  ├─ 001.xlsx  (<- 您在這裡打上翻譯！)
│  │  └─ ...
│  ├─ evidence/
│  │  ├─ context.jsonl  (<- 額外的情境資訊)
│  │  └─ ...
└─ internal/
   └─ ... (隱藏檔案)
```

如果您選擇了 `basic`（基本），`evidence`（情境）資料夾可能完全是空的！

---

## 4. 翻譯的身分證明

遊戲中的每一行文字都有一個 **ContentUid**（一個永久的身分證號碼）。

- 針對同一個 `ContentUid`，您永遠只需要翻譯一行。
- 即使我們為了一句話找到了超多背景情境，您還是只需要翻譯它一次。
- 工具唯一在乎的就只有 `ContentUid`。

---

## 5. 試算表長什麼樣子？

當您打開 `001.xlsx`，您會看到這些直行：

```text
ContentUid
SourceLocale (來源語言，例如 English)
SourceText (來源文字)
TargetLocale (目標語言，例如 ChineseTraditional)
PresenceStatus
TranslationRequired
ProtectedTokens (受保護的變數)
EvidenceFlags
ContextSummary (情境摘要)
ProposedTargetText (<- 您在這裡打字！)
TranslationStatus
TranslatorNotes
TranslatorName
```

### 策略的差異
如果您選擇了 `standard`（標準）策略，您還會看到 `ExistingTargetText`（舊的翻譯）。
如果您選擇了 `blind-first`（盲翻），那個欄位會完全消失！

---

## 6. 您實際上能編輯什麼？

您**只能**在這些欄位裡打字：

```text
ProposedTargetText (您提議的目標文字)
TranslationStatus (翻譯狀態)
TranslatorNotes (譯者筆記)
TranslatorName (譯者姓名)
```

其他所有東西都是被鎖定的證據。如果您更改了 `ContentUid` 或原始的英文文字，工具會阻止您安裝，因為您可能會把遊戲搞壞。

---

## 7. 情境輔助檔 (Evidence sidecars)

如果您選擇了 `full` 完整情境，您會獲得一堆額外的檔案（例如 `quest.jsonl`），提供深度的背景故事與細節。它們被保存在獨立的檔案中，這樣就不會把您的主 Excel 試算表弄得很亂。它們全都會透過 `ContentUid` 連結回您的翻譯文字。

---

## 8. 情境摘要 (Context summary)

試算表中有一個 `ContextSummary` 欄位。這只是一個快速且有用的提示（例如「這是一個任務描述」）。它只是給您看的。

---

## 9. 驗證您的工作

在工具接受您的工作之前，它會拿您的 `delivery/` 資料夾與它隱藏的 `internal/` 資料夾進行比對。它要確保您沒有不小心刪除任何重要東西，或是更改了遊戲內部的程式碼變數（`ProtectedTokens`）。

---

## 10. 翻譯範圍 (只翻譯一小部分)

如果您將工具設定為只翻譯特定的 `ContentUid`（範圍限定專案），那麼您的 Excel 檔案裡就會確實只有 1 行。這非常安全！

---

## 11. 安全性

這些翻譯檔案包含了《柏德之門 3》受版權保護的文字。它們僅供您在自己的電腦上個人使用。它們絕對不會被自動上傳到我們公開的網際網路原始碼庫中。

---

## 12. 驗收清單

*(開發人員確保有達成上述所有規則的技術清單。已全數打勾！)*

```text
E2E-01C | Material Package = ACCEPTED
```
