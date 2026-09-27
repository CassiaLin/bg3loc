# Review Quest

[繁體中文（台灣）](review-quest.zh-TW.md)

**Quest** text includes quest logs, journal entries, and task objectives. 

If the exact same quest text appears in multiple files, this tool is smart enough to combine them into **ONE** item for you to translate. This prevents you from doing duplicate work!

## Two-Pass Review System

Just like the short dialogue (bark), we review quest text in two steps:
* **Pass 1 (Blind):** You translate without seeing the official game translation.
* **Pass 2 (Comparison):** You compare your translation side-by-side with the official one.

## Validation Checks

When you validate your quest reviews, the tool will check for mistakes automatically. It looks for issues like duplicate IDs, missing entries, invalid quest roles, or changes that don't match the original meaning.

⚠️ **Warning:** Quest files contain heavy spoilers and actual game text. Keep these files private in your `workspace/` folder!

## How to Use

To prepare the quest files for review, just type this:
```powershell
bg3loc review quest prepare --mappings ... --extract ... --output workspace/quest-review
```

After reviewing, validate your changes by typing this:
```powershell
bg3loc review quest validate --input ... --output workspace/quest-review-validation
```
