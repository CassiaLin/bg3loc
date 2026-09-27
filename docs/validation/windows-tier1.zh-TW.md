# Windows 測試指南

[English](windows-tier1.md)

這份指南說明我們如何在真實的 Windows 電腦上測試我們的工具是否能修改《柏德之門 3》。在最後你明確下達安裝指令之前，我們絕對不會更動你的遊戲檔案，保證安全！

## 測試目標

我們的第一輪 Windows 測試必須證明以下幾點：

1. `scan` 指令能找到你的遊戲和語言檔。
2. 第三方解包工具能打開並讀取遊戲的語言檔。
3. 英文和繁體中文檔案能完美對齊（利用每筆遊戲文字的身分證號碼，即 **ContentUid**）。
4. 遊戲的語言檔可以完美轉換成可讀格式並轉換回來，不出任何差錯。
5. `build` 指令可以順利產生讓你翻譯的試算表。
6. `validate` 指令能成功檢查你翻譯好的檔案。
7. `rebuild` 能在不破壞原始遊戲資料的情況下，產生安全且可用的翻譯檔案。
8. `install --dry-run`（模擬安裝）能假裝安裝並檢查一切是否正常，且不會實際修改遊戲或建立備份。

實際安裝和還原遊戲檔案，我們會在另外的步驟測試。

## 已知的 Windows 測試位置

我們在初步測試時，使用的是這個資料夾：

```text
C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3
```

我們知道每個人的電腦不一樣，所以 `scan` 會自動支援並找到你的遊戲在哪裡！

## 前置需求

- Windows 11 或支援的 Windows 電腦
- Python 3.11 或更新版本
- Git
- 透過 Steam 安裝好的《柏德之門 3》
- 下載到電腦裡的第三方解包工具（例如 LSLib/Divine）

💡 **提示：** 我們使用 LSLib 1.20.4 版進行測試。其他版本也許可以用，但這個版本是保證沒問題的。請下載並解壓縮，找出裡面的 `Divine.exe`。

開始之前，先告訴你的電腦第三方解包工具在哪裡：

```powershell
$env:BG3LOC_DIVINE_EXE = "C:\path\to\LSLib\Packed\Tools\Divine.exe"
Test-Path $env:BG3LOC_DIVINE_EXE
```

## 階段 A：準備就緒

首先，下載我們的工具並設定好 Python：

```powershell
git clone https://github.com/CassiaLin/bg3loc.git
cd bg3loc
py -3.12 -m venv .venv
```

啟動它並安裝：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

輸入這行看看有沒有成功：

```powershell
bg3loc --help
```

應該會列出六個指令。接下來，跑一次掃描來確認你的解包工具準備好了！

## 階段 B：真實掃描

我們來找你的遊戲檔案。輸入這個：

```powershell
bg3loc scan `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --output workspace\scan-manifest.json
```

這會讓工具去檢查你的遊戲並做記錄。我們確保它能找到英文和繁體中文。請保留這份記錄檔。

## 階段 C：真實提取

現在我們把你要翻譯的文字抽出來：

```powershell
bg3loc extract `
  --scan workspace\scan-manifest.json `
  --source English `
  --target ChineseTraditional `
  --output workspace\extract
```

如果成功，代表我們安全地拿出文字，並且把每句話都對齊了！

## 階段 D：建立翻譯檔

讓我們產生你實際要編輯的翻譯檔案：

```powershell
bg3loc build `
  --extract workspace\extract\extract-manifest.json `
  --mode basic `
  --format csv `
  --max-rows 1500 `
  --output workspace\build
```

這會產生一個試算表 (CSV)，裡面有空格讓你填寫新的翻譯。

## 階段 E：測試翻譯

為了測試，我們複製一份試算表，隨便改幾行字。我們不會動到原始檔案。我們把測試檔存在 `workspace/returns/` 資料夾。

## 階段 F：驗證修改

我們檢查你的測試檔有沒有可能讓遊戲當機的錯誤：

```powershell
bg3loc validate `
  --build workspace\build\build-manifest.json `
  --input "workspace\returns\*.csv" `
  --output workspace\validate
```

這能確保你沒有不小心刪掉重要的遊戲代碼！

## 階段 G：重建檔案

現在我們把你的翻譯包裝回遊戲的格式，但還不會放進遊戲裡：

```powershell
bg3loc rebuild `
  --validate workspace\validate\validate-manifest.json `
  --extract workspace\extract\extract-manifest.json `
  --container auto `
  --output workspace\rebuild
```

## 階段 H：模擬安裝 (Dry Run)

我們假裝安裝一次，確保百分之百安全：

```powershell
bg3loc install `
  --rebuild workspace\rebuild\rebuild-manifest.json `
  --scan workspace\scan-manifest.json `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --backup-dir workspace\backups `
  --dry-run
```

⚠️ **警告：** 如果這一步通過，代表沒有任何遊戲檔案被修改。這完全安全。

## 階段 I：真實安裝與復原

只有在階段 H 通過後才能做這步！現在我們真的把檔案放進遊戲裡：

```powershell
bg3loc install `
  --rebuild workspace\rebuild\rebuild-manifest.json `
  --scan workspace\scan-manifest.json `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --backup-dir workspace\backups
```

打開《柏德之門 3》，去看看你的新翻譯吧！

想換回來嗎？只要輸入：

```powershell
bg3loc install --rollback <path-to-install-manifest.json>
```

你的遊戲就會完好如初！

## 測試證據

我們會儲存日誌檔案來證明測試成功，但**我們絕不會把你的私人遊戲文本上傳到網路上**。你的遊戲檔案永遠只會留在你的電腦裡。
