# bg3loc install

[繁體中文（台灣）](install.zh-TW.md)

**`bg3loc install`** is the ONLY command that actually writes files to your game folder.

💡 **Tip:** Always run `bg3loc install --dry-run` first! This lets you see what will happen without actually changing anything.

## What It Does

- **Preflight checks:** It double-checks your game identity, build version, and verifies the file hashes to make sure everything matches.
- **Mandatory backup:** It always creates a timestamped backup before it writes anything to your game.
- **Safe replacement:** It writes a temporary file first, checks that it's perfect, does a split-second swap, and checks it again.
- **Automatic rollback:** If the final check fails, it immediately restores your backup.

## How to Use It

Just open your command line and type this:

```bash
bg3loc install --rebuild output/rebuild/rebuild-manifest.json --scan scan/scan-manifest.json --dry-run
```

After reviewing the dry run, repeat that command without `--dry-run` for a real install. Save the install manifest path printed by the command. To undo it manually, use:

```bash
bg3loc install --rollback <manifest>
```

## Safety Guarantees

- **No `--force`:** If your game has updated since your last scan, the tool will stop immediately and force you to rescan.
- **File Locking:** Make sure to close the game before installing, especially on Windows!
- **Platform Support:** Safely handles file locations on Windows (Steam paths), Linux/Proton (case-sensitive paths), and macOS (native bundle paths).
