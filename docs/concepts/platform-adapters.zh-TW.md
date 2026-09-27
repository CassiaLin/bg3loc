# 平台轉接器 (Platform Adapters)

[English](platform-adapters.md)

《柏德之門 3》可以在 Windows、Linux 和 macOS 上執行。每個作業系統儲存檔案的方式都不同。**平台轉接器**就是用來處理這些差異的工具，讓我們的核心翻譯引擎在任何地方都能順利運作。

* **Windows**: 轉接器會讀取你的 Steam 收藏庫，並使用 appmanifest 檔案找到遊戲。
* **Linux/Proton**: 轉接器直接讀取 Steam。不需要 Proton 前綴就能讀取遊戲檔案。
* **macOS**: 這是原生的 Steam 安裝，所以我們不會假設檔案路徑是 Windows 的格式。

⚠️ **重要規則**
平台轉接器**只**處理檔案位置。它們絕對不會觸碰或更改你的翻譯內容！
