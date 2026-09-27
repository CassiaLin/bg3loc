# End-to-End Translation Workflow Roadmap

[繁體中文（台灣）](roadmap.zh-TW.md)

## Milestone

```text
End-to-End Translation Workflow 01
```

**Goal:** Allow anyone with a copy of Baldur's Gate 3 to easily create, check, and safely install their own translations. You don't need any special insider knowledge about how the project used to work! Just follow the public guides and type simple commands.

This milestone doesn't change the underlying technical engine (the Core architecture). Instead, it takes all the complex, low-level tools we already built and combines them into an easy-to-use, public process.

## Scope

```text
01A Workflow Contract
01B Project Config
01C Material Package
01D Review Integration
01E High-level CLI
01F Clean-room Acceptance
```

These are sequential steps in our plan. A later step won't break the rules set by an earlier step. All of these milestones are **COMPLETE**.

---

## 01A | Workflow Contract

**Status: ACCEPTED**

### Goal

Figure out the big picture before writing any code. We needed to define how all the steps connect, what options you can choose, where files get saved, and how to handle errors safely. 

### What We Decided

- Keep **how much game context you see** separate from **whether you can see the old translation**.
- Create three levels of context: `basic`, `context`, and `full`.
- Create two translation styles: `standard` (can see the old translation) and `blind-first` (hide it so it doesn't influence you).
- Figure out exactly which behind-the-scenes commands power the new, simple workflow.
- Decide where your working files will be stored.
- Make sure the process can pick up where it left off if you stop halfway.
- Ensure only the final `install` step ever touches your actual game files.
- Allow optional reference languages (like Japanese or French) and custom spelling rules.
- Set clear rules for when a step should stop and warn you if something is wrong.

### Proof It Works

- We didn't need to write new messy code.
- The plan matches our existing reliable tools perfectly.
- You don't need old files from our past work to use it.
- You can translate from any language to any language.
- Extra reference languages are completely optional.
- Your game files are 100% safe until you explicitly tell the tool to install your work.

---

## 01B | Project Config

**Status: ACCEPTED**

### Goal

Create a simple settings file so you don't have to type a massive wall of text every time you run a command. 

Here is a quick look at what that config file (the `bg3loc-project.json`) looks like under the hood:

```yaml
project:
  name: my-bg3-translation

game:
  sourceLocale: English
  targetLocale: ChineseTraditional

workflow:
  evidenceProfile: full
  translationStrategy: blind-first

references:
  - Japanese
  - French

reviews:
  bark: true
  quest: true
  uiSkill: true
  multilingual: true

qa:
  ruleSets:
    - rules/project-usage.json

workspace:
  root: workspace
```
*(Note: The final format we picked is JSON, but this YAML example shows the idea!)*

### Proof It Works

- The settings file uses a strict, safe format.
- It works for any language, not just Traditional Chinese.
- You don't have to pick a reference language.
- File paths work safely, no matter where you put your folder.
- Everything matches the rules we set in step 01A.
- You can bring your own custom spelling rules without changing the main tool.

---

## 01C | Material Package

**Status: ACCEPTED**

### Goal

Make translating easy by putting everything you need into one neat package. You shouldn't have to dig through five different files just to figure out if a line of text is a quest update or a UI button.

### How It Looks Now

We physically split your workspace into two areas (defined in [01C Material Package](material-package.md)):
1. **Delivery zone**: The files you actually open and edit.
2. **Internal zone**: Hidden software files used to verify your work later.

Your main translation file stays small and clean. If you need super-detailed context for a specific line, it's saved in a separate helper file linked by its **ContentUid** (a permanent ID number for each line of game text).

### Proof It Works

- Every line of text has one, and only one, `ContentUid`.
- You won't accidentally translate the exact same line twice.
- You can easily trace any background info back to the game.
- Special game code (like variables for character names) is kept safe.
- If you just want a `basic` setup, you won't be flooded with extra files.
- If you want a `full` setup, you get all the rich context.
- We don't save any copyrighted game text inside the tool's own code repository.

---

## 01D | Review Integration

**Status: ACCEPTED**

### Goal

Figure out exactly when and how your translation gets checked for errors.

Here is the normal process:

```text
Prepare evidence
→ Build translation material
→ Translation
→ Structural / semantic review
   ├─ Bark
   ├─ Quest
   ├─ UI / Skill
   └─ Multilingual
→ Project-specific language QA
   └─ externally supplied rule sets
→ Final validation
```

### Proof It Works

- Deep context checks (like checking if a line makes sense as a Quest) work perfectly.
- Custom style checks (like Taiwan usage rules) run smoothly using your own rule files.
- If a rule flags your text, it's just a suggestion to review it, not an automatic error.
- The official game text is only used for reference, unless you explicitly approve it.
- Your review decisions feed directly into the final safety check.

---

## 01E | High-level CLI

**Status: ACCEPTED**

### Goal

Give you super easy, simple commands to type, while keeping the powerful engine running quietly in the background.

Just type things like this:

```text
bg3loc project init
bg3loc workflow prepare
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
```

These high-level commands are like pressing a single button on a microwave instead of rewiring the circuits.

### Proof It Works

- Advanced users can still use the old complex commands if they want to.
- The tool remembers what you've done. If nothing changed, it won't waste time repeating work.
- If the game updates, the tool knows to update your background files.
- You can do a practice run (`--dry-run`) to make sure your install will work before actually changing the game.
- If something breaks, the tool tells you exactly which step failed.

---

## 01F | Clean-room Acceptance

**Status: ACCEPTED**

### Goal

Prove that a brand new user can actually do all of this! We tested this on someone who only knew three things:
1. Where their game was installed.
2. What language they wanted to translate from.
3. What language they wanted to translate to.

### The Test Drive

```text
clone
→ install BG3Loc
→ configure archive backend
→ initialize project
→ workflow prepare
→ receive translation material
→ edit a small controlled subset
→ workflow validate
→ workflow rebuild
→ workflow install --dry-run
```

The tester didn't need any secret passwords, old files, or deep knowledge of our research.

### A Small Bump in the Road

We hit one issue during testing. The game has over 230,000 lines of text. Our safety checker is strict: it won't let you install unless **everything** is finished. That meant the tester couldn't just translate one line to see if it worked! 

💡 **The Fix:** We solved this by creating a "scoped project". You can tell the config file to only care about a few specific `ContentUid`s. The tool will let you translate just those lines, safely check them, and leave the rest of the game untouched. Problem solved!

See [E2E-01F Clean-room Acceptance](clean-room-acceptance.md) for more details.

### The Final Verdict

Can a regular gaming community use our public guide to safely translate Baldur's Gate 3?

**Yes!**

```text
E2E-01F = ACCEPTED
End-to-End Translation Workflow 01 = COMPLETE
```

We completely proved it works by testing a small scoped translation on a real copy of the game. Our automated testing also ran 294 different checks, and they all passed.

---

## What This Tool Does NOT Do

Just to be clear, this tool does not:
- Automatically translate the game for you (no Machine Translation).
- Force you to use a specific AI or translation company.
- Include Larian's official translation files (you must extract them from your own game).
- Come with built-in dictionaries or Taiwan spelling lists (you make those yourself).
- Require you to look at Simplified Chinese, Russian, or any other specific language.
- Delete our old, advanced tools.
- Guarantee that it works flawlessly on Mac or Linux/Proton yet.
