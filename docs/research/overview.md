# How the Tool Reproduces Game Data

[繁體中文（台灣）](overview.zh-TW.md)

This page explains how the `bg3loc` tool works under the hood to pull data straight from your own game.

---

## Goal

The purpose of our tool is to let any player who owns a valid copy of Baldur's Gate 3 do the following:
1. Scan and extract text and story context directly from their own game files on their PC.
2. Regenerate specific groups of text that need translating, such as Barks (short character phrases), Quests, Dialogues, and Interface text.
3. Import your translations safely, without us ever needing to host or share the official game text on the internet.

---

## How It's Built

Our tool acts like a bridge between you and the game. Here is how the processing workflow is structured:

```text
+------------------------------------+
|    Portable Core (bg3loc)          |
|  - Creates files, checks rules     |
+-----------------+------------------+
                  |
+-----------------v------------------+
|    BG3 Game Adapter                |
|  - Finds Steam, unpacks files      |
+-----------------+------------------+
                  |
+-----------------v------------------+
|    Research Reproduction Layer     |
|  - Connects stats and rules        |
|  - Figures out which patch is new  |
|  - Understands dialog context      |
|  - Groups quest information        |
|  - Compares different languages    |
|  - Maps UI and skill text          |
|  - Handles leftover story text     |
+------------------------------------+
```

The tool simply adds helpful context on top of the text. It never breaks or alters the basic rules of how the game loads its files!