# Review Bark (Short Dialogue)

[繁體中文（台灣）](review-bark.zh-TW.md)

**Bark** refers to the short dialogue lines characters say in the game. These include combat shouts ("Die!"), or ambient remarks from NPCs as you walk by. 

This tool groups these short lines by the speaker, making it easier to review how a character sounds across different situations.

## Two-Pass Review System

We review these lines in two steps:
* **Pass 1 (Blind):** You translate or review the text without seeing the official game translation. This helps you focus on the actual meaning and character voice.
* **Pass 2 (Comparison):** You see the official translation side-by-side with your work. The official translation is just for comparison, not the final authority!

## Review Decisions

When reviewing a line, you will choose one of these statuses:
* **Pending:** You haven't decided yet.
* **Approved:** The translation is good to go.
* **NeedsRevision:** The translation needs changes.
* **InsufficientEvidence:** You need more context from the game to make a decision.
* **NotApplicable:** This line doesn't need to be reviewed.

⚠️ **Warning:** The review files contain actual game text. Please keep them in your private `workspace/` folder and do not share them publicly online!

## How to Use

To prepare the files for review, just type this:
```powershell
bg3loc review bark prepare --mappings research-output/research-mappings.jsonl --extract workspace/extract/extract-manifest.json --output workspace/bark-review
```

After you finish reviewing, validate your work by typing this:
```powershell
bg3loc review bark validate --input workspace/bark-review/bark-review-pass1.csv --output workspace/bark-review-validation
```
