# 審閱短對話 (Review Bark)

[English](review-bark.md)

**短對話 (Bark)** 指的是角色在遊戲中說出的簡短台詞。這包含了戰鬥時的呼喊（例如：「去死吧！」），或是你走過去時路人 NPC 的閒言閒語。

這個工具會把同一個角色的短對話整理在一起，讓你在審閱時更容易掌握角色在不同情況下的說話語氣。

## 兩階段審閱系統

我們會分成兩個步驟來審閱這些台詞：
* **第一階段（盲測）：** 翻譯或審閱時，你不會看到遊戲的官方翻譯。這能幫助你專注在句子的真實含義和角色性格。
* **第二階段（對照）：** 你會看到官方翻譯與你的版本並列顯示。官方翻譯僅供參考，並不是唯一的標準答案！

## 審閱決定

在審閱每句台詞時，你需要選擇以下其中一種狀態：
* **Pending（待處理）：** 你還沒做出決定。
* **Approved（已核准）：** 翻譯沒問題，可以採用。
* **NeedsRevision（需要修改）：** 翻譯內容需要調整。
* **InsufficientEvidence（證據不足）：** 你需要回遊戲裡看看具體情況才能決定。
* **NotApplicable（不適用）：** 這句台詞不需要審閱。

⚠️ **警告：** 審閱用的檔案包含了遊戲內的真實文字。請將它們保留在你的 `workspace/` 私人資料夾中，千萬不要公開分享到網路上！

## 如何使用

要準備審閱檔案，請直接輸入這行指令：
```powershell
bg3loc review bark prepare --mappings research-output/research-mappings.jsonl --extract workspace/extract/extract-manifest.json --output workspace/bark-review
```

審閱完成後，請輸入這行指令來檢查你的工作：
```powershell
bg3loc review bark validate --input workspace/bark-review/bark-review-pass1.csv --output workspace/bark-review-validation
```
