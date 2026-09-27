# 檔案後端工具 (Archive Backends)

[English](archive-backends.md)

《柏德之門 3》的檔案被打包在 **.pak**（遊戲的壓縮包裝檔）中，並編碼在 **.loca**（遊戲的語言檔）裡。bg3loc 使用外部的「後端工具」來打開它們。

目前，我們驗證過的環境是 Windows 11 搭配名為 LSLib 的第三方解包工具（具體來說是 Norbyte 製作的 `Divine.exe` v1.20.4）。或者，我們也可以透過 .NET 使用 `Divine.dll` 來支援跨平台操作。

⚠️ **需要自行下載**
bg3loc **不包含** `Divine.exe`。您必須自行下載。設定時，請建立一個名為 `BG3LOC_DIVINE_EXE` 的環境變數，並將其指向您的 `Divine.exe` 檔案。

## 後端工具如何運作
後端工具會執行幾個特定的操作來處理您的遊戲檔案：

* **probe**: 檢查解包工具是否已經安裝且能正常運作。
* **listArchive**: 查看 `.pak` 壓縮檔內部，不用解壓縮就能知道裡面有什麼。
* **extractArchive**: 將檔案從 `.pak` 壓縮包中取出來。
* **locaToXml**: 將無法閱讀的 `.loca` 語言檔轉換為我們可以編輯的易讀 XML 格式。
* **xmlToLoca**: 在你完成翻譯後，將 XML 檔案轉換回 `.loca` 檔案。
* **packArchive**: 將所有東西重新打包回 `.pak` 檔案，這樣遊戲才能讀取它們。
