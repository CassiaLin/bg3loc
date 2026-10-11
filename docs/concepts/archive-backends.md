# Archive Backends

[繁體中文（台灣）](archive-backends.zh-TW.md)

Baldur's Gate 3's files are packed inside **.pak** files (the game's compressed package files) and encoded in **.loca** files (the game's language files). bg3loc uses external "backend" tools to open them. 

Historical native evidence used Windows 11 with LSLib (`Divine.exe` v1.20.4 by Norbyte). A .NET `Divine.dll` backend is implemented, but native Linux/macOS release acceptance is not established. The first Basic RC targets Windows; its real-installation and game-load acceptance remain pending.

⚠️ **Download Required**
bg3loc does NOT distribute LSLib. Obtain it from the [Norbyte project](https://github.com/Norbyte/lslib), retain the entire distribution and runtime files, and set `BG3LOC_DIVINE_EXE` to the actual `Divine.exe` path (not the GUI converter). Basic also needs this backend for later source/baseline re-verification. See the [Windows Basic setup](../getting-started.md#1-install-the-tools); the example path is illustrative and other backend versions are not automatically certified.

## How the Backend Works
The backend tool performs several specific operations to handle your game files:

* **probe**: Checks if the unpacking tool is installed and working.
* **listArchive**: Looks inside the `.pak` files to see what is inside without unpacking them.
* **extractArchive**: Pulls the files out of the compressed `.pak` packages.
* **locaToXml**: Converts the unreadable `.loca` language files into a readable XML format we can edit.
* **xmlToLoca**: Converts the XML files back into `.loca` files after you finish translating.
* **packArchive**: Zips everything back up into `.pak` files so the game can read them.
