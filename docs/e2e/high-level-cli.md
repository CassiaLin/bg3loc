# E2E-01E | High-level CLI Contract

[繁體中文（台灣）](high-level-cli.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01E
State: ACCEPTED
Depends on: E2E-01A / 01B / 01C / 01D ACCEPTED
Core reopening: no
```

## Commands (The Tools You'll Actually Use)

Here is a list of the simple commands you type into your command line (like PowerShell) to make the magic happen:

```text
bg3loc project init
bg3loc project check
bg3loc workflow prepare
bg3loc workflow validate
bg3loc workflow review prepare      # Advanced
bg3loc workflow review integrate    # Advanced
bg3loc workflow review resolve      # Fixing text fights
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

By default, all these commands look for your `bg3loc-project.json` settings file.

---

## project init

**What it does:** Creates your `bg3loc-project.json` settings file. 
You tell it your project name, the language you are translating from, and the language you are translating to. It safely refuses to overwrite an existing project file so you don't accidentally delete your settings.

## project check

**What it does:** Reads your settings file and makes sure everything makes sense (like making sure you didn't set your source and target to the exact same language). It does not touch your game files.

---

## Scoped clean-room / subset projects (Translating just a tiny bit)

If you only want to translate one specific line of text to test things out, you can run `project init` and add `--content-uid <uid>`. 

The tool will still scan the whole game to understand how that line connects to everything else, but it will only give you that **one specific line** to translate, and it will only validate and install that one specific line. (Right now, this only works if your profile is `basic` or `context`).

---

## workflow prepare

```text
config → scan → extract → evidence → translation package → external translation boundary
```

**What it does:** Does all the heavy lifting to get your files ready. 
It checks your settings, scans the game, extracts the text, gathers background context, and builds your Excel spreadsheets. 

**It is incredibly safe.** If you already started translating and run this command again, it will **never** overwrite the files you've already typed translations into.

---

## workflow validate

```text
returned translation → structural review validation → reconciliation → language QA → reconciliation → final validation
```

**What it does:** Checks your homework. 
It reads your filled-out spreadsheets and verifies that you didn't break anything. It automatically runs any Quest, UI, or Spelling checks you asked for.

If a check finds something wrong, validation stops and tells you what to fix.

If two different checks disagree on a translation (a conflict), validation fails. You have to create a tiny file called `manual-resolutions.jsonl` to tell the tool which translation is correct, and then run:
```powershell
bg3loc workflow review resolve --input manual-resolutions.jsonl
bg3loc workflow validate
```

Once everything is fixed, it does a final safety check on the internal game code.

---

## workflow rebuild

**What it does:** Packs your finished, validated text back into the `.loca` format that the game engine can read. 
(It will refuse to run if you haven't passed `workflow validate` yet!)

---

## workflow install

**What it does:** Modifies your game! 

**Safety first:** By default, running this command just does a "dry run" (a practice run) to make sure it won't crash. 
If you actually want to install your translation into Baldur's Gate 3, you **must** type `--apply`. 

---

## workflow status

**What it does:** Tells you what's going on! It prints out your current step, what profile you are using, and if you are blocked by an error. It's safe to run anytime because it doesn't change anything.

---

## Runtime state (How it remembers things)

The tool keeps track of its progress in a secret `e2e-workflow-state.schema.json` file. 

If the game gets an update, the tool notices that the file hashes changed. It marks your current progress as "invalidated", letting you know you need to run `workflow prepare` again to sync up with the new game version. It will never silently repeat a real installation.

---

## Acceptance

*(Technical checklist for developers ensuring all the commands work correctly and safely. All checked off!)*

```text
Synthetic public CLI E2E acceptance: PASS
Local full test suite: 288 passed
E2E-01E | High-level CLI = ACCEPTED
```
