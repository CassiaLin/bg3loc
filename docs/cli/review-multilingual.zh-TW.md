# 審閱多語系 (Review Multilingual)

[English](review-multilingual.md)

**多語系 (Multilingual)** 工具專門用來找出遊戲中只有英文原文，卻缺少翻譯的句子。

它就像一個聰明的搜尋引擎：它會尋遍整個遊戲，看看這句完全相同的英文句子是否已經在其他地方被翻譯過了！

## 翻譯匹配類型

當它找到缺少的翻譯時，會把它們分類來幫助你處理：
* **EXACT_SINGLE：** 這個句子在其他地方出現過一次，且有一個翻譯版本。
* **EXACT_CONSENSUS：** 這個句子出現過多次，且所有先前的翻譯都一致。
* **EXACT_CONFLICT：** 這個句子出現過多次，但存在著不同的翻譯版本。
* **NO_EXACT_CANDIDATE：** 這個句子從來沒有在遊戲的任何地方被翻譯過。

💡 **提示：** 即使工具找到了一致的翻譯，也不代表它絕對適合當下的情境。一定要經過真人的審閱和核准！

## 如何使用

要尋找並準備缺少的翻譯，請直接輸入這行指令：
```powershell
bg3loc review multilingual prepare --mappings ... --extract ... --output workspace/multilingual-review
```

審閱完建議內容後，請輸入這行指令來檢查你的工作：
```powershell
bg3loc review multilingual validate --input ... --manifest ... --output workspace/multilingual-review-validation
```
