# 審閱介面與技能 (Review UI and Skills)

[English](review-ui-skill.md)

**介面與技能 (UI/Skill)** 文字包含了介面按鈕、法術說明、角色能力、物品提示以及狀態效果。

這個工具會追蹤技能之間的關聯性。舉例來說，如果某個特定法術的說明是繼承自基礎魔法範本，工具會知道這層連結！

## 工作流

為了讓審閱更輕鬆，工具會將不同類型的文字分類到不同的群組中，這稱為工作流。例如，所有與角色升級介面相關的文字都會被歸類在 `UserInterface` 工作流裡。

我們使用與其他審閱工具相同的兩階段系統和驗證檢查。

## 如何使用

要準備介面與技能文字以供審閱，請直接輸入這行指令：
```powershell
bg3loc review ui-skill prepare --universe workspace/research/ui-skill-universe.csv --extract ... --output workspace/ui-skill-review
```

完成審閱後，請輸入這行指令來檢查你的工作：
```powershell
bg3loc review ui-skill validate --input ... --manifest ... --output workspace/ui-skill-review-validation
```
