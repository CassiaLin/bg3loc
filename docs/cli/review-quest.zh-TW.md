# 審閱任務 (Review Quest)

[English](review-quest.md)

**任務 (Quest)** 文字包含了任務日誌、手札紀錄以及任務目標。

如果完全相同的任務文字出現在多個檔案中，這個工具會聰明地將它們合併成**一個**項目讓你翻譯。這樣可以避免你做重複的工作！

## 兩階段審閱系統

就像短對話一樣，我們會分成兩個步驟來審閱任務文字：
* **第一階段（盲測）：** 你在不看官方翻譯的情況下進行翻譯。
* **第二階段（對照）：** 你可以將你的翻譯與官方版本並列比較。

## 驗證檢查

當你驗證任務審閱結果時，工具會自動檢查是否有錯誤。它會尋找像是重複的身分證號碼、遺漏的條目、無效的任務角色，或是與原文意思不符的修改。

⚠️ **警告：** 任務檔案包含了大量的劇透和真實遊戲文字。請務必將這些檔案保存在你的 `workspace/` 私人資料夾中！

## 如何使用

要準備任務檔案以供審閱，請直接輸入這行指令：
```powershell
bg3loc review quest prepare --mappings ... --extract ... --output workspace/quest-review
```

審閱完成後，請輸入這行指令來檢查你的變更：
```powershell
bg3loc review quest validate --input ... --output workspace/quest-review-validation
```
