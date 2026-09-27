# E2E-01F | Clean-room Acceptance

[繁體中文（台灣）](clean-room-acceptance.zh-TW.md)

## Status

```text
Milestone: End-to-End Translation Workflow 01F
State: ACCEPTED
01F-BLOCKER-01 scoped project boundary: RESOLVED
Core reopening: no
Validation semantic reopening: no
```

## Goal

Prove that a regular gamer with zero insider knowledge can use our public guides and simple commands to safely translate Baldur's Gate 3 and put it in their game.

The tester was only assumed to know:
- Where their Baldur's Gate 3 folder was.
- They wanted to translate from English.
- They wanted to translate to Traditional Chinese.
- How to set up the third-party unpacking tool (which is in the docs).

## The Real-Game Test

We ran a brand new, empty project against a real copy of Baldur's Gate 3 with these settings:

```text
source: English
target: ChineseTraditional
profile: basic
strategy: standard
scope: 1 explicit ContentUid (Translating just 1 line of text)
```

The tester typed these commands:

```text
project init
→ project check
→ workflow prepare
→ edit returned XLSX (They typed in the translation)
→ workflow validate
→ workflow rebuild
→ workflow install   # dry-run default
```

And here is what happened:

```text
prepare = PASS
translation package scope = 1 row
validate = PASS
accepted records = 1
rebuild = PASS
changedUidCount = 1
install dry-run = PASS
game modified = no
```

It worked perfectly! The tool safely updated that 1 line of text and kept the rest of the massive game completely untouched. 

## The "One Line" Problem (Why we made Scoped Projects)

The game has over 230,000 lines of text. Our safety checker is very strict: it will reject your work if you leave a line blank. 

This meant our tester couldn't just translate one line to see if the tool worked! If we relaxed the safety checker just for the test, the tool would be unsafe for real users.

**The Fix:** We invented "Scoped Projects". You can explicitly tell the tool, "Hey, I only want to translate these specific `ContentUid` lines right now." The tool accepts this, shrinks your translation package down to just those lines, safely checks them, and builds a patch that only changes those specific lines in the game. 

## How you can try a Scoped Project yourself

You don't need a secret list of `ContentUid` numbers to do this. You can find them yourself!

First, create a normal project and prepare it to get all the files:

```powershell
bg3loc project init `
  --name "scope-bootstrap" `
  --game-dir "D:\SteamLibrary\steamapps\common\Baldurs Gate 3" `
  --source English `
  --target ChineseTraditional `
  --evidence-profile basic `
  --translation-strategy standard `
  --output bootstrap-project.json

bg3loc workflow prepare --project .\bootstrap-project.json
```

Now, open any Excel file in your `workspace\e2e\returns\` folder. Copy any `ContentUid` you see in the first column!

Now, make a *new* project, but this time use `--content-uid` and paste the ID you copied:

```powershell
bg3loc project init `
  --name "my-scoped-project" `
  --game-dir "D:\SteamLibrary\steamapps\common\Baldurs Gate 3" `
  --source English `
  --target ChineseTraditional `
  --evidence-profile basic `
  --translation-strategy standard `
  --content-uid "<Paste the ContentUid you copied here>" `
  --workspace scoped-workspace `
  --output scoped-project.json
```

Then just run the rest of the steps on your tiny new project:

```powershell
bg3loc project check --project .\scoped-project.json
bg3loc workflow prepare --project .\scoped-project.json

# Now edit the Excel file in:
#   workspace\e2e\returns\

bg3loc workflow validate --project .\scoped-project.json
bg3loc workflow rebuild --project .\scoped-project.json

# Test the installation to make sure it's safe:
bg3loc workflow install --project .\scoped-project.json
```

If you want to actually install it for real, add `--apply` to the end of the install command.

## Current Limitations

Right now, Scoped Projects only work if your evidence profile is set to `basic` or `context`. If you try to use `full` with a scoped project, the tool will stop you to keep you safe (we are still teaching the advanced review tools how to handle scoped projects).

## Final Verdict

The tester followed the public instructions perfectly without needing any secret help. 

```text
E2E-01F = ACCEPTED
End-to-End Translation Workflow 01 = COMPLETE
```
