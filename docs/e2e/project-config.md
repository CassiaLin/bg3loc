# E2E-01B | Project Config Contract

[繁體中文（台灣）](project-config.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01B
State: ACCEPTED
Implementation: complete
Depends on: E2E-01A ACCEPTED
Core reopening: no
```

## 1. Purpose

The project config file (`bg3loc-project.json`) is the master settings file for your translation project. 

It remembers your choices (like what languages you are translating) so you don't have to type them into the command line every single time. It is meant to be safely saved and shared. 

It is **NOT** a save file for your translation progress. It only stores your rules and settings.

---

## 2. Canonical format

The file is always named:

```text
bg3loc-project.json
```

We use JSON because it's a standard format that works reliably on Windows, Mac, and Linux without needing extra software.

---

## 3. User config vs runtime state

We separate your choices from the tool's internal progress tracking.

### User config (What you control)
This file holds your permanent choices:
- The project name
- The source language (usually English) and target language
- Any extra reference languages
- Your Evidence Profile (`basic`, `context`, or `full`)
- Your Translation Strategy (`standard` or `blind-first`)
- Your custom spelling rules (QA rules)
- Where to save your workspace files

### Runtime state (What the tool tracks silently)
The tool has a separate, hidden file to track its own progress. It records things like:
- What version of Baldur's Gate 3 you have installed
- Secret file hashes to make sure nothing was accidentally deleted
- Whether you've passed the validation check yet

You never need to edit the runtime state file.

---

## 4. Canonical shape

Here is exactly what the file looks like on the inside:

```json
{
  "schemaVersion": "1.0",
  "project": {
    "name": "my-bg3-translation"
  },
  "game": {
    "installDir": null
  },
  "locales": {
    "source": "English",
    "target": "ChineseTraditional",
    "references": []
  },
  "workflow": {
    "evidenceProfile": "full",
    "translationStrategy": "blind-first"
  },
  "reviews": {
    "structural": "profile-default"
  },
  "qa": {
    "ruleSets": []
  },
  "inputs": {
    "glossary": null
  },
  "material": {
    "format": "xlsx",
    "maxRowsPerFile": 1500
  },
  "workspace": {
    "root": "workspace"
  }
}
```

---

## 5. Field semantics (What the settings mean)

### 5.1 `schemaVersion`
Always `1.0`. It tells the tool what version of the rules to use.

### 5.2 `project.name`
The name of your project! Just a label for humans to read. 

### 5.3 `game.installDir`
Usually left as `null` (empty). The tool is smart enough to find your game automatically if you use Steam. If you installed it somewhere weird, you can type the folder path here. 

### 5.4 `locales.source`
The language you are translating **FROM** (e.g., `English`). 

### 5.5 `locales.target`
The language you are translating **TO** (e.g., `ChineseTraditional`). It cannot be the exact same as the source.

### 5.6 `locales.references`
Extra languages you want to look at for hints (like `["Japanese", "French"]`). You can leave it empty `[]`.

### 5.7 `workflow.evidenceProfile`
How much game context you want. Must be `basic`, `context`, or `full`.

### 5.8 `workflow.translationStrategy`
Whether you want to see the old translation. Must be `standard` or `blind-first`.

---

## 6. Structural review selection

### `reviews.structural`

By default, this is set to `"profile-default"`. The tool automatically turns on the right checks depending on your Evidence Profile:
- If you picked `basic` or `context`, it leaves advanced structural checks off.
- If you picked `full`, it turns on all advanced checks (like Bark, Quest, UI, and Multilingual).

You can also manually type exactly which checks you want, but you are only allowed to turn them on if you picked the `full` evidence profile.

---

## 7. Project-language QA (Custom Spelling Rules)

### `qa.ruleSets`
You can tell the tool to check your final translation against your own list of forbidden words or required spelling.

Example:
```json
{
  "qa": {
    "ruleSets": [
      {
        "id": "project-usage",
        "type": "taiwan-usage",
        "path": "rules/project-usage.json"
      }
    ]
  }
}
```
If the tool finds a match, it flags it for you to review. It doesn't automatically fail you.

---

## 8. Project glossary

### `inputs.glossary`
You can point to a dictionary file to help your translators. 

---

## 9. Translation material settings

### `material.format`
What kind of file you want to edit. Usually `xlsx` (Excel). 

### `material.maxRowsPerFile`
Games have a lot of text! The tool chops the work into smaller files. By default, it puts 1500 lines per file so your computer doesn't crash trying to open a giant spreadsheet.

---

## 10. Workspace

### `workspace.root`
The folder where all your translation files will be saved. Usually just called `workspace`.

### Translation scope (Translating just a tiny piece)

Normally, the tool expects you to translate the entire game. But what if you just want to test one line?

You can add a "scope" block to tell the tool to only care about specific lines, using their `ContentUid`:

```json
{
  "scope": {
    "contentUids": [
      "h000006d4gcefbg4092gbb39gfeb27a3bb0a7"
    ]
  }
}
```
If you do this, the tool creates a tiny package just for that one line. It will safely skip the rest of the game when installing. (Right now, this only works if your profile is `basic` or `context`).

---

## 11. Security and portability

The settings file is safe to share with others. 
It **NEVER** stores passwords, secret API keys, or Larian's copyrighted game text. 

---

## 12. Acceptance checklist

*(Technical checklist for developers ensuring all the rules above were met. All checked off!)*

```text
E2E-01B | Project Config = ACCEPTED
```
