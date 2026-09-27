# Step-by-Step Guide

[繁體中文（台灣）](reproduction.zh-TW.md)

## How to use the Command-Line

### 1. Scan Game Files
First, we need to find all the useful files inside your Baldur's Gate 3 game folder. Just type this:

```powershell
bg3loc research scan `
  --game-dir "...\Baldurs Gate 3" `
  --output research-scan-manifest.json
```

This tells the tool to look at the game's compressed package files (like `Gustav.pak` or `Shared.pak`) and write down where everything is, how big it is, and what format it uses.

### 2. Connect the Dots
Now, we tell the tool to figure out how all those files connect to each other:

```powershell
bg3loc research map `
  --scan research-scan-manifest.json `
  --output-dir research-output
```

This creates a folder full of organized information about the game's stats, patch updates, Barks (short spoken phrases), quests, and dialogue context!