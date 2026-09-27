# E2E-01A | Workflow Contract

[繁體中文（台灣）](workflow-contract.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01A
State: ACCEPTED
Implementation: not started
Core reopening: no
Accepted basis: documentation / current implementation conformance review
```

## 1. Design Rule

The way this tool works depends on two main choices you make. You can mix and match them however you like!

### Evidence Profile (How much game context do you want?)

```text
basic
context
full
```

This controls how much extra background information the tool gathers for you to look at while translating.

### Translation Strategy (Do you want to see the old translation?)

```text
standard
blind-first
```

This controls whether the existing game text is visible to you when you start translating. 

⚠️ **Remember:** These are two separate choices. For example:
- `basic` + `standard`: You get minimal context, but you can see the old translation.
- `context` + `blind-first`: You get some context, but you can't see the old translation at first.
- `full` + `blind-first`: You get max context, but you still translate without seeing the old text first.

Choosing `full` doesn't mean "Traditional Chinese Project", and choosing `blind-first` doesn't mean you automatically get "full" context!

---

## 2. Public Stage Graph

Here is the exact order of steps you will take to translate the game. 

```text
Project configuration
        ↓
Discovery
        ↓
Locale extraction
        ↓
Evidence preparation
        ↓
Translation package build
        ↓
External translation
        ↓
Review / QA
        ↓
Final translation validation
        ↓
Rebuild
        ↓
Install dry-run
        ↓
Install
```

The tool handles most of this automatically behind the scenes.

---

## 3. Stage Contracts

Here is what each step actually does.

### 3.1 Project configuration

**What it does:** Saves your choices! It remembers the languages you are using, your context and strategy choices, and where your files are kept.
**What it writes:** Only its own setting files.
**What it DOES NOT do:** It never touches the game files.

---

### 3.2 Discovery

Behind the scenes command:
```text
bg3loc scan
```

**What it does:** Uses a third-party unpacking tool (a backend tool) to look at your Baldur's Gate 3 folder and figure out exactly what version of the game you have installed. It finds the game's compressed package files (`.pak`).
**What it DOES NOT do:** It never modifies the game.

---

### 3.3 Locale extraction

Behind the scenes command:
```text
bg3loc extract
```

**What it does:** Pulls the game's language files (`.loca`) out of the game and organizes them. It sorts them by their `ContentUid` (a permanent ID number for each line of game text).
**What it DOES NOT do:** It never modifies the game. It also never forces you to use an extra reference language.

---

### 3.4 Evidence preparation

This changes depending on your **Evidence Profile** choice.

#### basic
Provides the bare minimum. You'll get the text to translate and essential safety rules, but no deep research files.

#### context
Gives you helpful background info, like who is speaking, what quest they are on, and the surrounding conversation. It keeps things simple.

#### full
Runs the heavy machinery. It pulls out every single piece of advanced research data we can find about the text.

**What it DOES NOT do:** None of these options touch your game files.

---

## 4. Translation package build

Behind the scenes command:
```text
bg3loc build
```

This step creates the actual spreadsheet files that you will open and edit. 

### Standard strategy
If you picked `standard`, your spreadsheet will show the current game translation right next to the English text.

### Blind-first strategy
If you picked `blind-first`, the tool actively hides the current translation from you. You won't see it until you've done your first pass. 

**What it DOES NOT do:** The tool prepares the files, but it does not translate the text for you.

---

## 5. Workflow command boundary

There is a hard stop built into the process:

```text
workflow prepare
→ produces translation package
→ external translation happens
→ workflow validate
→ review / QA validation as configured
→ rebuild
→ install
```

When you run `workflow prepare`, the tool gives you the files and stops. It patiently waits for you to actually do the translation. 
You only run `workflow validate` after you've finished typing your translations into the files.

---

## 6. External translation boundary

**You** get to decide how the translation actually happens.
You can type it yourself, use AI, or use a website to manage a team. This tool doesn't care! It just checks the final results using the `ContentUid`.

---

## 7. Review / QA

There are two completely different ways to check your work.

### 7.1 Structural / semantic evidence review
This checks if your translation makes sense in the game. For example, did you translate a UI button correctly? Did you mess up a quest description?

### 7.2 Project-language QA
This checks if you followed your own spelling rules (like specific Taiwan wording habits). You have to provide the rules yourself! If the tool spots a broken rule, it highlights it for you to look at. It doesn't mean you are wrong, it just wants you to double-check.

---

## 8. Final translation validation

Behind the scenes command:
```text
bg3loc validate
```

Before letting you put the text in the game, the tool checks:
- Did you accidentally duplicate a `ContentUid`?
- Did you accidentally break the game's internal code syntax?
- Did you actually finish translating everything you were supposed to?

If you pass, you move to the next step.

---

## 9. Rebuild

Behind the scenes command:
```text
bg3loc rebuild
```

The tool takes your finished spreadsheet and packs it back into a `.loca` (game language file) format that Baldur's Gate 3 understands.

---

## 10. Installation

Behind the scenes command:
```text
bg3loc install
```

This is the **ONLY** step that modifies your game files. 
You must do a practice run first:
```text
install --dry-run
→ install
```
It will backup your original game files before applying your new translation.

---

## 11. Evidence profile matrix

A quick summary of what you get with each profile:

| Capability | basic | context | full |
| --- | --- | --- | --- |
| Source/target normalized text | required | required | required |
| Optional reference locales | supported | supported | supported |
| Basic localization metadata | required | required | required |
| General game-use context | no | yes | yes |
| Research reproduction | no | partial/as-needed | complete accepted layer |
| Bark evidence | no | optional if surfaced by context | yes |
| Quest evidence | no | optional if surfaced by context | yes |
| UI / Skill evidence | no | optional | yes |
| Multilingual exact-reuse evidence | no | optional | yes |
| Project language QA rules | separate QA stage | separate QA stage | separate QA stage |

---

## 12. Translation strategy matrix

A quick summary of what you see:

| Strategy | Existing target visible in independent translation pass | Reference locale text visible in independent translation pass |
| --- | --- | --- |
| standard | allowed by package policy | allowed by package policy |
| blind-first | no | no |

---

## 13. State and invalidation

The tool remembers what step you are on:
```text
not-started
ready
running
completed
invalidated
failed
```
If the game updates, or if you change a core file, the tool realizes things are out-of-date and marks them as "invalidated" so you know to run the preparation again.

---

## 14. Failure boundary

If a command fails, it will tell you exactly which step broke. It will not silently try to fix it and give you a broken file. It will stop immediately if files are missing or if a safety check fails.

---

## 15. Workspace ownership

All the text you generate stays in your own folder on your computer. 
The official copyrighted text from the game never gets uploaded to our public repository. 

---

## 16. Compatibility with current CLI

These new, easy commands don't replace the old, complex ones. Advanced users can still use the low-level commands if they need to do something highly specific!

---

## 17. 01A acceptance checklist

*(Technical checklist for developers ensuring all the rules above were met. All checked off!)*

```text
E2E-01A | Workflow Contract = ACCEPTED
```
