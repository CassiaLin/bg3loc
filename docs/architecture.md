# How It All Works (Architecture)

[繁體中文（台灣）](architecture.zh-TW.md)

The bg3loc tool has five different parts that work together to help you translate *Baldur's Gate 3*. Think of them as different layers of a cake!

## The Five Layers

1. **Portable Core:** This is the main brain. It handles the translation rules, keeps track of text IDs, and checks for mistakes. It does not talk to the game files directly.
2. **BG3 Game Adapter:** This part knows all the specific secrets about *Baldur's Gate 3*. It understands how the game organizes files, who is speaking in a dialogue, and which game patch is the newest.
3. **Version Discovery:** Whenever the game updates, this part looks at your installed game and recalculates what is new. It figures out what language files exist and what the current text IDs are.
4. **Platform Adapter:** This part knows where the game is installed on your computer. It works on Windows, Linux, and macOS automatically!
5. **Archive Backend:** This part interacts with the game's compressed package files (`.pak`) and language files (`.loca`). It uses a third-party unpacking tool (like `Divine.exe`) to open them up and pack them back together.

## The Most Important Rule

**ContentUid** is a permanent ID number for each line of game text. 

This ID number is the **only** thing that matters when we track text. Line numbers, file names, or batch numbers are not reliable. The ContentUid is the true identity of a sentence!
