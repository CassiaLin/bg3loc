# bg3loc extract

[繁體中文（台灣）](extract.zh-TW.md)

**`bg3loc extract`** unpacks the game's language files so you can read them.

## What It Does

- Selects a source language (like English) and a target language (like ChineseTraditional).
- You can optionally include reference languages.
- Converts the unreadable binary game files (`.loca`) into readable text.
- Aligns sentences by their `ContentUid` (a permanent ID number for each line of game text). It keeps everything, even if one language is missing a line.

## How to Use It

Just open your command line and type this:

```bash
bg3loc extract --scan scan/scan-manifest.json --source English --target French --output extract
```

## Round-trip Validation

It converts the text back and forth to prove nothing is lost. This guarantees that your game files won't get corrupted.

## Provider Precedence

If there are game patches, it automatically uses the latest version of the text (base game → patch → hotfix). It picks exactly one language file (`.loca`) from inside the compressed package per language.

⚠️ **Warning:** This tool does NOT judge translation quality. It just extracts the text.

## Output

It creates the chosen `extract/` folder with `extract-manifest.json`, normalized source and target JSONL, and aligned data. Replace the example locale IDs with those reported by your scan.
