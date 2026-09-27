# Review Multilingual

[繁體中文（台灣）](review-multilingual.zh-TW.md)

The **Multilingual** tool finds sentences in the game that have the original English text but are missing a translation. 

It acts like a smart search engine: it looks through the entire game to see if that exact English sentence was already translated somewhere else!

## Translation Match Types

When it finds missing translations, it categorizes them to help you:
* **EXACT_SINGLE:** The sentence appears once somewhere else, and it has one translation.
* **EXACT_CONSENSUS:** The sentence appears multiple times, and all previous translations agree.
* **EXACT_CONFLICT:** The sentence appears multiple times, but there are different translations for it.
* **NO_EXACT_CANDIDATE:** This sentence has never been translated anywhere in the game.

💡 **Tip:** Even if the tool finds a matching translation, it doesn't mean it's 100% correct for this context. A human must always review and approve it!

## How to Use

To find and prepare missing translations, just type this:
```powershell
bg3loc review multilingual prepare --mappings ... --extract ... --output workspace/multilingual-review
```

After reviewing the suggestions, validate your work by typing this:
```powershell
bg3loc review multilingual validate --input ... --manifest ... --output workspace/multilingual-review-validation
```
