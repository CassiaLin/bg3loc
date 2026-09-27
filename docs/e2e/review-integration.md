# E2E-01D | Review Integration Contract

[繁體中文（台灣）](review-integration.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01D
State: ACCEPTED
Implementation: not started
Depends on: E2E-01A / 01B / 01C ACCEPTED
Core reopening: no
```

## 1. Goal

Take all of our different ways of checking a translation (like checking quests, checking menus, and checking your custom spelling rules) and make them work smoothly together. 

We need to make sure that these different checks don't start fighting each other over what the "final" translation should be.

---

## 2. Canonical text rule (The One True Translation)

For every `ContentUid` (the ID for a line of text), there is only **one** official translation.

When a review tool checks your work, it is allowed to:
- Approve it.
- Ask you to fix it.
- Suggest a better translation.
- Say it needs more context.
- Say it doesn't apply.

But the review tool **cannot** overwrite your translation directly. Any changes it suggests have to go through a careful "reconciliation" step before they are accepted. 

---

## 3. The two kinds of checks

### 3.1 Structural / semantic review
These check if your translation makes sense inside the actual game.
- **Bark:** Does it work as a short shout during combat?
- **Quest:** Does it make sense in the quest log?
- **UI-Skill:** Does it fit on a menu button or skill description?
- **Multilingual:** Does it match how this word was translated elsewhere?

### 3.2 Project-language QA
This checks if your translation follows your custom style rules (like Taiwan spelling rules). 

⚠️ **Important:** The QA check looks at your *new* translation, not the old one that came with the game. 

---

## 4. How the Review Lifecycle works

Here is the journey your translation takes:

```text
translation package prepared
        ↓
external translation (You do the work!)
        ↓
canonical ProposedTargetText snapshot (Tool saves your work)
        ↓
structural review preparation (Tool prepares the game-logic checks)
        ↓
human structural review (You look at the game-logic suggestions)
        ↓
normalized structural results (Tool gathers your decisions)
        ↓
reconciliation (Tool applies your game-logic fixes)
        ↓
canonical translated text updated if required
        ↓
project-language QA on reconciled text (Tool checks your spelling)
        ↓
QA reconciliation if required (Tool applies your spelling fixes)
        ↓
final translation validation (Final safety check)
```

The spelling check happens **after** the game-logic check, so it can catch any new typos you might have introduced while fixing a quest log!

---

## 5. What happens when the tool checks something?

No matter what kind of check it is, the tool always gives it a simple status:

- `pending` (Waiting for you to look at it)
- `clear` (Looks good!)
- `revision-required` (You need to fix this)
- `needs-context` (Too hard to tell, needs more info)
- `insufficient-evidence` (Not enough clues in the game files)
- `not-applicable` (Doesn't matter for this line)

---

## 6. The Gates (Stopping you from making mistakes)

### The Structural Gate (Game Logic)
If the tool flags a problem with a quest or menu, you **must** deal with it. If a check is marked `pending` or `needs-context`, the tool stops. You cannot move forward until you give it a clear answer. 

### The Language QA Gate (Spelling)
If you fix a quest, the tool realizes the text changed. If that text had a spelling check attached to it, the spelling check is now considered out-of-date! The tool will force you to run the spelling check again on the newest version of the text.

---

## 7. Reconciliation (Fixing conflicts)

What happens if you have to change a translation?

- **No change requested:** The translation stays exactly as you typed it.
- **Everyone agrees:** If a check suggests a new translation and there are no disagreements, the tool safely updates it.
- **A massive fight:** What if the Quest check says the word should be "Apple", but the Spelling check says the word should be "Orange"? 
  **The tool stops everything.** It refuses to guess which one is right. It creates a `conflict` error, and you have to manually tell the tool which one wins.

There is no "boss" check. A quest check isn't automatically more important than a spelling check. If they disagree, a human has to step in.

---

## 8. Blind-first rules

If you chose the `blind-first` strategy:
- You still do your first translation completely blind.
- The first structural checks are also done blind.
- Only in the final "Comparison Pass" are you finally allowed to see the old game translation to see how you did.

---

## 9. Security

The review tools lock the original game evidence so you can't accidentally edit it. If the tool catches you trying to sneak in a change to the evidence files, it invalidates your work.

---

## 10. Acceptance checklist

*(Technical checklist for developers ensuring all the rules above were met. All checked off!)*

```text
E2E-01D | Review Integration = ACCEPTED
```
