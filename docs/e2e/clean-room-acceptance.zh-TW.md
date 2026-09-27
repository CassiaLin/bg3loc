# E2E-01F | 無塵室驗收 (Clean-room Acceptance)

[English](clean-room-acceptance.md)

## 狀態

```text
Milestone: End-to-End Translation Workflow 01F
State: ACCEPTED
01F-BLOCKER-01 scoped project boundary: RESOLVED
Core reopening: no
Validation semantic reopening: no
```

## 目標

證明一個完全沒有內行知識的普通玩家，能只靠我們的公開指南和簡單的指令，就安全地翻譯《柏德之門 3》並安裝進遊戲中。

我們假設測試者只知道：
- 他們的《柏德之門 3》資料夾在哪裡。
- 他們想從英文開始翻譯。
- 他們想翻譯成繁體中文。
- 如何設定第三方解包工具（指南裡有教）。

## 實際遊戲測試

我們使用一個全新的空白專案，在真正的《柏德之門 3》遊戲上進行測試，設定如下：

```text
source: English
target: ChineseTraditional
profile: basic
strategy: standard
scope: 1 explicit ContentUid (只翻譯 1 行文字)
```

測試者輸入了這些指令：

```text
project init
→ project check
→ workflow prepare
→ edit returned XLSX (他們在檔案裡打上了翻譯)
→ workflow validate
→ workflow rebuild
→ workflow install   # 預設為演習 (dry-run)
```

然後這是發生的事：

```text
prepare = PASS
translation package scope = 1 row
validate = PASS
accepted records = 1
rebuild = PASS
changedUidCount = 1
install dry-run = PASS
game modified = no
```

完美運作！工具安全地更新了那 1 行文字，而龐大遊戲裡的其他所有東西都原封不動，非常安全。

## 「只翻一行」的難題 (為什麼我們發明了範圍限定專案)

遊戲有超過 230,000 行文字。我們的安全檢查器非常嚴格：只要您留了一行空白，它就會拒絕您的工作。

這代表我們的測試者不能只翻譯一行文字來看看工具會不會動！如果我們為此放寬了安全檢查器，這個工具對真正使用它的玩家來說就不安全了。

**解決方案：** 我們發明了「範圍限定專案 (Scoped Projects)」。您可以明確地告訴工具：「嘿，我現在只想翻譯這些特定的 `ContentUid` 台詞。」工具接受了這個要求，把您的翻譯素材包縮小到只有那幾行，安全地檢查它們，然後建立一個只會修改遊戲中那幾行文字的更新檔。

## 您如何自己嘗試範圍限定專案

您不需要一份神祕的 `ContentUid` 號碼清單才能做到這件事。您可以自己找到它們！

首先，建立一個普通的專案，並執行準備流程來取得所有檔案：

```powershell
bg3loc project init `
  --name "scope-bootstrap" `
  --game-dir "D:\SteamLibrary\steamapps\common\Baldurs Gate 3" `
  --source English `
  --target ChineseTraditional `
  --evidence-profile basic `
  --translation-strategy standard `
  --output bootstrap-project.json

bg3loc workflow prepare --project .\bootstrap-project.json
```

現在，打開 `workspace\e2e\returns\` 資料夾裡的任何一個 Excel 檔案。把您在第一直行看到的任何一個 `ContentUid` 複製起來！

接著，建立一個*全新*的專案，但這次加上 `--content-uid`，並貼上您剛剛複製的 ID：

```powershell
bg3loc project init `
  --name "my-scoped-project" `
  --game-dir "D:\SteamLibrary\steamapps\common\Baldurs Gate 3" `
  --source English `
  --target ChineseTraditional `
  --evidence-profile basic `
  --translation-strategy standard `
  --content-uid "<在這裡貼上您複製的 ContentUid>" `
  --workspace scoped-workspace `
  --output scoped-project.json
```

然後，只要在這個超小的新專案上執行剩下的步驟就可以了：

```powershell
bg3loc project check --project .\scoped-project.json
bg3loc workflow prepare --project .\scoped-project.json

# 現在，編輯位在這個資料夾裡的 Excel 檔案：
#   workspace\e2e\returns\

bg3loc workflow validate --project .\scoped-project.json
bg3loc workflow rebuild --project .\scoped-project.json

# 測試安裝，確保它是安全的：
bg3loc workflow install --project .\scoped-project.json
```

如果您真的想把它安裝進遊戲裡，請在 install 指令的最後面加上 `--apply`。

## 目前的限制

目前，範圍限定專案只有在您的情境深度設定為 `basic` 或 `context` 時才有作用。如果您試圖在範圍限定專案中使用 `full` 設定，工具會為了保護您的安全而停止運作（我們還在教那些進階的審查工具如何處理範圍限定專案）。

## 最終判定

測試者完美地遵照公開指示完成了操作，不需要任何秘密的幫助。

```text
E2E-01F = ACCEPTED
End-to-End Translation Workflow 01 = COMPLETE
```
