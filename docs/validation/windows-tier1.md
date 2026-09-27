# Windows Testing Guide

[繁體中文（台灣）](windows-tier1.zh-TW.md)

This guide shows how we test our tool on a real Windows installation of Baldur's Gate 3. We make sure it's safe to use and won't mess up your game until you explicitly tell it to install!

## Testing Goals

Our first round of Windows testing needs to prove that:

1. `scan` can find your real BG3 game and its language files.
2. A third-party unpacking tool can open and read the game's language files.
3. English and Traditional Chinese files line up perfectly using a permanent ID number for each line of game text (called a **ContentUid**).
4. Converting game language files to a readable format and back works flawlessly.
5. `build` creates the translation spreadsheets you can edit.
6. `validate` successfully checks a test file we send back.
7. `rebuild` makes a safe, working translated file without breaking the original game data.
8. `install --dry-run` pretends to install and checks if everything is okay, without actually changing your game or making backups.

Actual installation and reverting changes are tested in a separate step.

## Known Windows Test Location

When we first tested this, we used this folder:

```text
C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3
```

We know everyone's computer is different, so `scan` is built to find your game wherever it is!

## What You Need

- Windows 11 or a supported Windows PC
- Python 3.11 or newer
- Git
- Baldur's Gate 3 installed via Steam
- A third-party unpacking tool (like LSLib/Divine) downloaded to your PC

💡 **Tip:** We tested this with LSLib version 1.20.4. Other versions might work, but this one is guaranteed. Download it, extract it, and find `Divine.exe`.

Before starting, tell your PC where to find the unpacking tool:

```powershell
$env:BG3LOC_DIVINE_EXE = "C:\path\to\LSLib\Packed\Tools\Divine.exe"
Test-Path $env:BG3LOC_DIVINE_EXE
```

## Stage A: Getting Ready

First, download our tool and set up Python:

```powershell
git clone https://github.com/CassiaLin/bg3loc.git
cd bg3loc
py -3.12 -m venv .venv
```

Activate it and install:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Check if it works by typing this:

```powershell
bg3loc --help
```

It should list six commands. Next, run a scan to make sure your unpacking tool is ready!

## Stage B: Real Scan

Let's find your game files. Type this:

```powershell
bg3loc scan `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --output workspace\scan-manifest.json
```

This tells the tool to look at your game and take notes. We make sure it finds both English and Traditional Chinese files. Keep this notes file for later.

## Stage C: Real Extract

Now we pull out the text you want to translate:

```powershell
bg3loc extract `
  --scan workspace\scan-manifest.json `
  --source English `
  --target ChineseTraditional `
  --output workspace\extract
```

If it succeeds, it means we safely got the text out and lined everything up!

## Stage D: Build Translation Files

Let's create the file you would actually translate:

```powershell
bg3loc build `
  --extract workspace\extract\extract-manifest.json `
  --mode basic `
  --format csv `
  --max-rows 1500 `
  --output workspace\build
```

This makes a spreadsheet (CSV) with blank spots for your new translation. 

## Stage E: Test Translation

For testing, we take a copy of the spreadsheet and change a few lines. We don't touch the original. We save our test copy in a `workspace/returns/` folder.

## Stage F: Validate Changes

We check if your test file has any errors that might crash the game:

```powershell
bg3loc validate `
  --build workspace\build\build-manifest.json `
  --input "workspace\returns\*.csv" `
  --output workspace\validate
```

It ensures you didn't accidentally delete important game codes!

## Stage G: Rebuild the Files

Now we package your translations back into the game's format, but we don't put them in the game yet:

```powershell
bg3loc rebuild `
  --validate workspace\validate\validate-manifest.json `
  --extract workspace\extract\extract-manifest.json `
  --container auto `
  --output workspace\rebuild
```

## Stage H: Dry Run (Test Install)

We pretend to install to make sure it's 100% safe:

```powershell
bg3loc install `
  --rebuild workspace\rebuild\rebuild-manifest.json `
  --scan workspace\scan-manifest.json `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --backup-dir workspace\backups `
  --dry-run
```

⚠️ **Warning:** If this passes, it means no game files were changed. It's totally safe.

## Stage I: Real Install & Rollback

Only do this after Stage H passes! Now we actually put it in the game:

```powershell
bg3loc install `
  --rebuild workspace\rebuild\rebuild-manifest.json `
  --scan workspace\scan-manifest.json `
  --game-dir "C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3" `
  --backup-dir workspace\backups
```

Open Baldur's Gate 3 and check your new translation! 

Want to undo it? Just type this:

```powershell
bg3loc install --rollback <path-to-install-manifest.json>
```

Your game is exactly as it was before!

## Evidence

We save log files to prove the test worked, but **we never upload your personal game text to the internet**. Your game files stay on your PC.
