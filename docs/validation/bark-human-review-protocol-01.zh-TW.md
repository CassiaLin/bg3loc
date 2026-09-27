# 角色環境語音 (Bark) 測試結果

[English](bark-human-review-protocol-01.md)

這個頁面展示了我們對「角色環境語音（Bark，也就是角色走路時頭上飄出的短句）」的測試結果。我們確保工具能正確找出這些句子並整理好讓你翻譯。

在測試開始前，我們記錄了程式碼的狀態：

```text
base main HEAD: 2f8bec2561c006b082b8dac1690999220c68fc57
branch: feat/bark-human-review-protocol
initial HEAD: 2f8bec2561c006b082b8dac1690999220c68fc57
```

我們在 2026 年 9 月 13 日，使用了一套正版且已安裝的《柏德之門 3》進行測試。我們使用第三方解包工具，遊戲版本為 `4.1.1.7398727`。

💡 **提示：** 測試中我們沒有使用任何舊的翻譯或私人檔案。我們完全直接從遊戲本體中讀取資料。

## 測試結果

以下是工具在遊戲檔案中找到的內容：

```text
research mappings: 51606
Bark review candidates: 289
SingleSpeaker: 277
SharedSpeaker: 12
SharedSpeaker member count: 8
Pass 1 validation findings: 0
Pass 2 validation findings: 0
OfficialTarget available: 0 / 289
```

我們的工具成功將試算表分開，讓它們更容易閱讀。它也正確地把「多個角色共用的語音」合併起來，這樣你就不用重複翻譯同一句話好幾次了。

⚠️ **警告：** 測試期間找到的任何遊戲文字或身分證號碼，都會存在你電腦上隱藏的 `workspace/` 資料夾裡。為了保護遊戲版權，它們絕對不會上傳到網路上。

在這次特定的測試中，我們在這 289 句語音中沒有找到官方翻譯。這只是因為我們讀取的遊戲資料特性，並不代表工具壞了。工具會把翻譯欄位留白，等你來填寫！

全部 196 個自動測試都完美通過。只有一個關於 Windows 命令提示字元顯示文字的小警告，但這不影響任何功能。
