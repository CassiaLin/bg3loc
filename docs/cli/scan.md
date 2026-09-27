# bg3loc scan

[繁體中文（台灣）](scan.zh-TW.md)

**`bg3loc scan`** is the starting point. It acts like a scout, looking through your computer to find where Baldur's Gate 3 is installed.

It is completely read-only, meaning it won't change or break your game files.

## What It Does

1. Finds your Steam installation.
2. Locates the Baldur's Gate 3 install path.
3. Finds the Data directory.
4. Locates language packages (the game's compressed package files, `.pak`).
5. Finds language files inside (`.loca`).
6. Lists all available languages.

When it finishes, it saves a summary file called `workspace/scan-manifest.json`.

## How to Use It

Just open your command line and type this:

```bash
bg3loc scan
```

💡 **Tip:** It automatically discovers languages. There is no hardcoded list! Whatever is installed gets found.

### Optional Flags

- `--game-dir`: Tell it exactly where the game is.
- `--steam-library`: Tell it where your Steam library is.
- `--platform`: Tell it your operating system.
- `--backend`: Choose the background tool.

## Special Features

- **Duplicate Handling:** If two packages claim to be the same language, it flags them as ambiguous.
- **Platform Support:** Works on Windows (Steam library), Linux/Proton (direct Steam path), and macOS (native Steam).
- **Security:** Ignores shortcuts (symlinks) to keep things safe.

⚠️ **Warning:** This step needs a third-party unpacking tool (LSLib or `Divine.exe`) to be configured using `BG3LOC_DIVINE_EXE`.

## Exit Codes

- `0`: Success
- `2`: Game not found
- `3`: Data directory is missing
- `4`: No game languages found
- `5`: Ambiguous languages (duplicates)
- `6`: Backend tool unavailable
- `7`: Discovery error
