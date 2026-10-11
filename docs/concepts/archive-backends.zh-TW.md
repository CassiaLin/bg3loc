# 檔案後端工具 (Archive Backends)

[English](archive-backends.md)

《柏德之門 3》的檔案被打包在 **.pak**（遊戲的壓縮包裝檔）中，並編碼在 **.loca**（遊戲的語言檔）裡。bg3loc 使用外部的「後端工具」來打開它們。

既有 Native 證據使用 Windows 11 與 Norbyte LSLib（`Divine.exe` v1.20.4）。程式也有 .NET `Divine.dll` 後端，但尚未完成 Linux／macOS Native 發布驗收。第一版 Basic RC 以 Windows 為範圍，真實安裝及遊戲載入驗收仍待完成。

⚠️ **需要自行下載**
bg3loc **不包含** LSLib。請由 [Norbyte 專案](https://github.com/Norbyte/lslib) 取得，保留整份工具及 runtime 檔案，將 `BG3LOC_DIVINE_EXE` 指向實際的 `Divine.exe`，不是圖形介面轉換器。Basic 後續來源／baseline 重驗仍需要此後端。參閱 [Windows Basic 入門](../getting-started.zh-TW.md)；路徑僅為示例，其他後端版本不代表自動取得驗收。

## 後端工具如何運作
後端工具會執行幾個特定的操作來處理您的遊戲檔案：

* **probe**: 檢查解包工具是否已經安裝且能正常運作。
* **listArchive**: 查看 `.pak` 壓縮檔內部，不用解壓縮就能知道裡面有什麼。
* **extractArchive**: 將檔案從 `.pak` 壓縮包中取出來。
* **locaToXml**: 將無法閱讀的 `.loca` 語言檔轉換為我們可以編輯的易讀 XML 格式。
* **xmlToLoca**: 在你完成翻譯後，將 XML 檔案轉換回 `.loca` 檔案。
* **packArchive**: 將所有東西重新打包回 `.pak` 檔案，這樣遊戲才能讀取它們。
