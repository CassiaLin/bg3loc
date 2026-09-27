# Localization Records

[繁體中文（台灣）](localization-records.zh-TW.md)

Before doing any translation work, bg3loc converts game text into standardized "index cards" called **records**. 

Each record card contains:
* **ContentUid**: A permanent ID for each line of game text.
* **Language**: The language of the text.
* **Text**: The actual game text.
* **Version**: The version number of the text.
* **Source File**: Where the text came from.

💡 **Full Outer Join**
When comparing languages, we keep everything. If English has a line that Chinese doesn't, or vice versa, both are kept. Nothing is ever thrown away!

⚠️ **Round-Trip Check**
To make sure nothing is lost, bg3loc converts the text back and forth between formats. If the final result matches the start exactly, we know our translations are safe.
