# 審閱台灣慣用語 (Review Taiwan Usage)

[English](review-taiwan-usage.md)

**台灣慣用語 (Taiwan Usage)** 工具會掃描所有已翻譯的遊戲文字，確保用語符合台灣的常見習慣。

它會尋找非標準的詞彙並標記起來，讓真人可以再次確認。如果同一個句子違反了多項規則，工具會貼心地把它們全部整理成一項審閱任務。

## 專屬你的私人規則

這個工具**沒有**內建任何詞彙表。相反地，你需要自己建立專屬的規則檔案（JSON 格式）。

💡 **提示：** 工具標記了某個詞，並不代表它絕對是錯的！這只代表「嘿，這裡需要真人來看一眼確認」。

## 審閱決定

在檢查被標記的詞彙時，你需要決定：
* **Pending（待處理）：** 你還沒做出決定。
* **AcceptAsIs（維持現狀）：** 這段文字其實沒問題，不需要改。
* **Revise（需要修改）：** 這段文字必須修改。（你必須提供修改後的新文字！）
* **NotApplicable（不適用）：** 這個規則不適用於這裡。
* **NeedsContext（需要情境）：** 你需要回遊戲裡看看具體情況才能決定。

⚠️ **警告：** 請保護好你的自訂詞彙規則。bg3loc 掃描工具是公開的，但你專屬的翻譯規則應該保留在你的專案資料夾中！

## 如何使用

要使用你的規則來掃描文字，請直接輸入這行指令：
```powershell
bg3loc review taiwan-usage prepare --extract ... --rules project/taiwan-usage-rules.json --output workspace/taiwan-usage-review
```

決定好要修正哪些地方後，請輸入這行指令來檢查變更：
```powershell
bg3loc review taiwan-usage validate --input ... --manifest ... --output workspace/taiwan-usage-review-validation
```
