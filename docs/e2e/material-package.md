# E2E-01C | Translation Material Package Contract

[繁體中文（台灣）](material-package.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01C
State: ACCEPTED
Implementation: not started
Depends on: E2E-01A ACCEPTED, E2E-01B ACCEPTED
Core reopening: no
```

## 1. Goal

Create one easy-to-use package of files for you to translate. It should contain exactly what you need without confusing you with extra software files.

---

## 2. Core rule: Two separate zones

We physically separate the files into two folders:

```text
translation-package/
├─ translation-package-manifest.json
├─ delivery/
└─ internal/
```

### `delivery/` (The part you see)
This is what you (or your translators) actually look at and edit. It only contains the text you are allowed to see based on your strategy.

### `internal/` (The hidden part)
This is the tool's private workspace. It holds the original, untouched text to check your work against later. 

If you chose `blind-first` (which hides the old translation), the old text is safely locked away in this `internal/` folder where you won't see it while translating.

---

## 3. What's inside the folder?

Depending on your settings, it looks something like this:

```text
translation-package/
├─ translation-package-manifest.json
├─ delivery/
│  ├─ materials/
│  │  ├─ 001.xlsx  (<- You type your translations here!)
│  │  └─ ...
│  ├─ evidence/
│  │  ├─ context.jsonl  (<- Extra context)
│  │  └─ ...
└─ internal/
   └─ ... (Hidden files)
```

If you pick `basic`, the `evidence` folder might be completely empty!

---

## 4. Translation identity

Every line of game text has a **ContentUid** (a permanent ID number). 

- You will only ever see one row to translate for each `ContentUid`. 
- Even if we find a lot of background context for a single line, you still only have to translate it once.
- The `ContentUid` is the only thing the tool cares about.

---

## 5. What does the spreadsheet look like?

When you open `001.xlsx`, you will see these columns:

```text
ContentUid
SourceLocale (e.g., English)
SourceText
TargetLocale (e.g., ChineseTraditional)
PresenceStatus
TranslationRequired
ProtectedTokens
EvidenceFlags
ContextSummary
ProposedTargetText (<- You type here!)
TranslationStatus
TranslatorNotes
TranslatorName
```

### Strategy differences
If you chose the `standard` strategy, you will also see `ExistingTargetText` (the old translation).
If you chose `blind-first`, that column will completely vanish!

---

## 6. What can you actually edit?

You are **only** allowed to type in these columns:

```text
ProposedTargetText
TranslationStatus
TranslatorNotes
TranslatorName
```

Everything else is locked evidence. If you change a `ContentUid` or the original English text, the tool will stop you from installing it because you might break the game.

---

## 7. Evidence sidecars (Extra Context)

If you picked `full` context, you get a bunch of extra files (like `quest.jsonl`) that provide deep lore and details. They are kept in separate files so they don't clutter up your main Excel spreadsheet. They are all linked back to the text using the `ContentUid`.

---

## 8. Context summary

The spreadsheet has a `ContextSummary` column. This is just a quick, helpful hint (like "This is a quest description"). It's just for you to read.

---

## 9. Validating your work

Before the tool accepts your work, it checks your `delivery/` folder against its hidden `internal/` folder. It makes sure you didn't accidentally delete anything important or change the game's internal code words (`ProtectedTokens`).

---

## 10. Translation Scope (Translating a small piece)

If you configured the tool to only translate a specific `ContentUid` (a scoped project), then your Excel file will only have exactly 1 row in it. It's perfectly safe!

---

## 11. Security

These translation files contain copyrighted text from Baldur's Gate 3. They are for your personal use on your computer. They are never automatically uploaded to our public internet repository.

---

## 12. Acceptance checklist

*(Technical checklist for developers ensuring all the rules above were met. All checked off!)*

```text
E2E-01C | Material Package = ACCEPTED
```
