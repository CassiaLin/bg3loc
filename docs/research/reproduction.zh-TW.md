# 逐步操作教學

[English](reproduction.md)

## 如何使用命令列操作

### 1. 掃描遊戲檔案
首先，我們需要找出你《柏德之門 3》遊戲資料夾裡所有有用的檔案。只要輸入這個：

```powershell
bg3loc research scan `
  --game-dir "...\Baldurs Gate 3" `
  --output research-scan-manifest.json
```

這會告訴工具去查看遊戲的壓縮包裝檔（像是 `Gustav.pak` 或 `Shared.pak`），並記錄下所有東西的位置、大小和格式。

### 2. 連結遊戲資料
現在，我們要讓工具找出這些檔案彼此之間的關聯：

```powershell
bg3loc research map `
  --scan research-scan-manifest.json `
  --output-dir research-output
```

這會產生一個資料夾，裡面整理了關於遊戲屬性、更新檔、環境語音 (Bark)、任務和對話語境的詳細資訊！
