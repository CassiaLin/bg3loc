# How the Tool Connects the Dots

[繁體中文（台灣）](deterministic-mappings.zh-TW.md)

This page explains the rules our tool uses to look at your game files and accurately figure out what text goes where. 

---

## 1. Character Stats and Items

- **Where it looks:** Text files dealing with game stats (`Public/*/Stats/Generated/Data/*.txt`).
- **How it connects:** It uses the permanent ID number for each line of game text (the `ContentUid`).
- **What it does:** It finds the names, descriptions, and tooltips of items and stats. 
- **The Rule:** The ID number always perfectly matches the item description in the game.

---

## 2. Reading Game Patches

- **Where it looks:** The game's compressed package files (`.pak`).
- **How it connects:** It reads them in a specific order: Patch > GustavX > Gustav > Shared > Game.
- **The Rule:** If an older file and a newer patch file have the same text, the newest patch file always wins!

---

## 3. Dialogue Context

- **Where it looks:** The dialogue story files (`Story/DialogsBinary/**/*.lsf`).
- **How it connects:** It uses the text ID number.
- **The Rule:** It carefully traces who is talking, what their choices are, and when they speak, so you know the context of the conversation.

---

## 4. Bark (Walking Around) Phrases

- **Where it looks:** The 11 main files for "ambient barks" (short phrases said out loud).
- **The Rule:**
  - If a phrase can be spoken by lots of different characters, it gets grouped together as `SharedSpeaker` so you only translate it once.
  - If a phrase belongs to one specific character, it gets labeled as `SingleSpeaker`.
- **Result:** It exactly finds 289 of these phrases for you.

---

## 5. Quest Journals

- **Where it looks:** The 555 quest files (`Quests.lsx`).
- **The Rule:** It figures out if a line of text is a `QuestTitle` (the name of the quest) or a `QuestDescription` (the details of the quest).
- **Result:** It finds 94 unique quest texts.

---

## 6. Comparing Languages

- **Where it looks:** The game's language files (`.loca`) for English, Traditional Chinese, Simplified Chinese, and Russian.
- **The Rule:** 
  - It finds English text that is used multiple times in the game to save you time.
  - It can look at how other languages translated the same ID number to give you hints!
- **Result:** It matches up 14,194 text IDs.

---

## 7. Leftover Story Text

- **Where it looks:** Other language packages and the game's story connections.
- **The Rule:** It double-checks if a line of text is actually used in the story. If it is, it's marked as ready to translate. If the game doesn't seem to use it anymore, it's set aside.
