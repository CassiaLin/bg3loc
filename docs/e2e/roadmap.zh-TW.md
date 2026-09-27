# 端到端翻譯處理流程藍圖

[English](roadmap.md)

## 里程碑

```text
End-to-End Translation Workflow 01
```

**目標：** 讓任何擁有《柏德之門 3》的玩家，都能輕鬆建立、檢查並安全安裝自己的翻譯。您不需要對這個專案過去的歷史有任何內行知識！只要跟著公開指南，輸入簡單的指令即可。

這個里程碑不會改變底層的技術核心（Core 架構）。相反地，它將我們已經打造的那些複雜、底層的工具組合起來，變成一個公開且容易使用的處理流程（pipeline）。

## 範圍

```text
01A Workflow Contract
01B Project Config
01C Material Package
01D Review Integration
01E High-level CLI
01F Clean-room Acceptance
```

這些是我們計畫中循序漸進的步驟。後面的步驟絕對不會破壞前面步驟定下的規則。這些里程碑目前**全部都已經完成**。

---

## 01A | 處理流程規則 (Workflow Contract)

**狀態：已接受 (ACCEPTED)**

### 目標

在寫任何程式碼之前，先弄清楚整體架構。我們需要定義所有步驟如何串連、您可以選擇哪些設定、檔案要存在哪裡，以及如何安全地處理錯誤。

### 我們的決定

- 將**您能看到多少遊戲情境**與**您是否能看到舊翻譯**這兩件事分開設定。
- 建立三種情境深度：`basic`（基本）、`context`（情境）與 `full`（完整）。
- 建立兩種翻譯策略：`standard`（標準，能看到舊翻譯）與 `blind-first`（盲翻優先，隱藏舊翻譯以免影響您）。
- 釐清這個全新且簡單的流程背後，到底是由哪些底層指令在運作。
- 決定您的工作檔案要存放在哪裡。
- 確保流程能在您中途停止時，記住進度並接續執行。
- 確保只有最後的 `install`（安裝）步驟才會碰到您真正的遊戲檔案。
- 允許加入選用的參考語言（例如日文或法文）以及自訂的拼字規則。
- 訂定明確的規則，讓工具在發生問題時自動停止並警告您。

### 成功證明

- 我們不需要寫出混亂的新程式碼。
- 這個計畫與我們現有且可靠的工具完美契合。
- 您不需要使用我們過去的舊檔案也能操作。
- 您可以把任何語言翻譯成任何語言。
- 額外的參考語言完全是選用的。
- 除非您明確下令安裝，否則您的遊戲檔案百分之百安全。

---

## 01B | 專案設定 (Project Config)

**狀態：已接受 (ACCEPTED)**

### 目標

建立一個簡單的設定檔，這樣您就不必每次執行指令時，都要輸入一大串像咒語般的文字。

以下是這個設定檔（`bg3loc-project.json`）在幕後的樣子：

```yaml
project:
  name: my-bg3-translation

game:
  sourceLocale: English
  targetLocale: ChineseTraditional

workflow:
  evidenceProfile: full
  translationStrategy: blind-first

references:
  - Japanese
  - French

reviews:
  bark: true
  quest: true
  uiSkill: true
  multilingual: true

qa:
  ruleSets:
    - rules/project-usage.json

workspace:
  root: workspace
```
*（註：我們最終選擇的格式是 JSON，但這個 YAML 範例能讓您更容易看出概念！）*

### 成功證明

- 設定檔使用嚴格且安全的格式。
- 它適用於任何語言，不限於繁體中文。
- 您不必非得選擇一個參考語言。
- 檔案路徑非常安全，無論您把資料夾放在哪裡都能運作。
- 所有的設定都符合我們在 01A 步驟定下的規則。
- 您可以匯入自己專屬的拼字規則，而不需要修改主工具。

---

## 01C | 翻譯素材包 (Material Package)

**狀態：已接受 (ACCEPTED)**

### 目標

把您需要的所有東西打包成一個整潔的包裹，讓翻譯變得更簡單。您不該為了搞清楚一句話是任務更新還是介面按鈕，而在五個不同的檔案裡翻找。

### 現在的運作方式

我們將您的工作區在實體上分成了兩個區域（詳見 [01C 翻譯素材包](material-package.zh-TW.md)）：
1. **交付區 (delivery)**：您實際打開並編輯的檔案。
2. **內部區 (internal)**：隱藏的軟體檔案，稍後用來驗證您的工作。

您的主要翻譯檔案會保持小巧乾淨。如果您需要某句台詞的超詳細情境，它會被存在另一個輔助檔案中，並透過 **ContentUid**（每筆遊戲文字的身分證號碼）連結起來。

### 成功證明

- 每行文字都有一個且唯一一個 `ContentUid`。
- 您絕對不會不小心把同一句話翻譯兩次。
- 您可以輕鬆地將任何背景資訊追溯回遊戲中。
- 特殊的遊戲程式碼（像是角色名字的變數）會受到安全保護。
- 如果您只想要 `basic`（基本）設定，您不會被多餘的檔案淹沒。
- 如果您想要 `full`（完整）設定，您就能獲得所有豐富的情境資訊。
- 我們不會把任何受版權保護的遊戲文字存入工具的程式碼資料庫中。

---

## 01D | 審查整合 (Review Integration)

**狀態：已接受 (ACCEPTED)**

### 目標

確切決定您的翻譯要在何時、以何種方式進行錯誤檢查。

以下是正常的流程：

```text
Prepare evidence
→ Build translation material
→ Translation
→ Structural / semantic review
   ├─ Bark
   ├─ Quest
   ├─ UI / Skill
   └─ Multilingual
→ Project-specific language QA
   └─ externally supplied rule sets
→ Final validation
```

### 成功證明

- 深度情境檢查（例如檢查某句話作為任務內容是否合理）運作完美。
- 自訂風格檢查（例如台灣用語習慣）能使用您自己的規則檔順暢執行。
- 如果規則標記了您的文字，那只是建議您檢查，而不是自動判定錯誤。
- 官方的遊戲文字只會用來當作參考，除非您明確核准使用它。
- 您的審查決定會直接送入最終的安全檢查環節。

---

## 01E | 高階指令介面 (High-level CLI)

**狀態：已接受 (ACCEPTED)**

### 目標

提供您超級簡單、容易輸入的指令，同時讓強大的引擎在背景安靜地運作。

只要輸入像這樣的東西：

```text
bg3loc project init
bg3loc workflow prepare
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
```

這些高階指令就像是按下微波爐上的一鍵啟動，而不是要您自己去重接電線。

### 成功證明

- 進階使用者如果想的話，仍然可以使用以前那些複雜的指令。
- 工具會記住您做過的事。如果什麼都沒改變，它就不會浪費時間重複工作。
- 如果遊戲更新了，工具會知道要更新您的背景檔案。
- 您可以進行一次演習（`--dry-run`）來確保安裝會成功，然後再真正去修改遊戲。
- 如果有東西壞了，工具會精確告訴您是哪個步驟失敗。

---

## 01F | 無塵室驗收 (Clean-room Acceptance)

**狀態：已接受 (ACCEPTED)**

### 目標

證明一個全新的使用者真的能做到這一切！我們找了一位測試者，他只知道三件事：
1. 他的遊戲安裝在哪裡。
2. 他想從什麼語言開始翻譯。
3. 他想翻譯成什麼語言。

### 試駕過程

```text
clone
→ install BG3Loc
→ configure archive backend
→ initialize project
→ workflow prepare
→ receive translation material
→ edit a small controlled subset
→ workflow validate
→ workflow rebuild
→ workflow install --dry-run
```

測試者不需要任何秘密密碼、舊檔案，也不需要深入了解我們的研究內容。

### 路上的一個小顛簸

我們在測試時遇到了一個問題。遊戲有超過 230,000 行文字。我們的安全檢查非常嚴格：除非**所有東西**都翻譯完了，否則它不准您安裝。這代表測試者不能只翻譯一行文字來看看有沒有用！

💡 **解決方案：** 我們透過建立「範圍限定專案 (scoped project)」解決了這個問題。您可以在設定檔裡告訴它，只關注幾個特定的 `ContentUid`。工具會讓您只翻譯那些台詞，安全地檢查它們，然後保持遊戲其他部分原封不動。問題解決！

更多詳細資訊請見 [E2E-01F 無塵室驗收](clean-room-acceptance.zh-TW.md)。

### 最終判定

一個普通的玩家社群，能只看我們的公開指南，就安全地翻譯《柏德之門 3》嗎？

**可以！**

```text
E2E-01F = ACCEPTED
End-to-End Translation Workflow 01 = COMPLETE
```

我們透過在真正的遊戲上進行小範圍翻譯測試，完全證明了它能運作。我們的自動化測試也執行了 294 項不同的檢查，並且全數通過。

---

## 這款工具「不」做什麼

為了避免誤會，這款工具不會：
- 自動幫您翻譯遊戲（沒有機器翻譯）。
- 強迫您使用特定的 AI 或翻譯公司。
- 內含 Larian 的官方翻譯檔（您必須從自己的遊戲中提取）。
- 內建字典或台灣拼字清單（您要自己製作）。
- 強迫您查看簡體中文、俄文或任何其他特定的語言。
- 刪除我們以前那些進階的工具。
- 保證目前在 Mac 或 Linux/Proton 上能完美運作。
