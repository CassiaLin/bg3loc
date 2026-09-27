# Archive Backends

[繁體中文（台灣）](archive-backends.zh-TW.md)

Baldur's Gate 3's files are packed inside **.pak** files (the game's compressed package files) and encoded in **.loca** files (the game's language files). bg3loc uses external "backend" tools to open them. 

Currently, our validated setup uses Windows 11 with a third-party unpacking tool called LSLib (specifically `Divine.exe` v1.20.4 by Norbyte). Alternatively, we can use `Divine.dll` via .NET for cross-platform support.

⚠️ **Download Required**
bg3loc does NOT distribute `Divine.exe`. You must download it separately. To set it up, create an environment variable called `BG3LOC_DIVINE_EXE` and point it to your `Divine.exe` file.

## How the Backend Works
The backend tool performs several specific operations to handle your game files:

* **probe**: Checks if the unpacking tool is installed and working.
* **listArchive**: Looks inside the `.pak` files to see what is inside without unpacking them.
* **extractArchive**: Pulls the files out of the compressed `.pak` packages.
* **locaToXml**: Converts the unreadable `.loca` language files into a readable XML format we can edit.
* **xmlToLoca**: Converts the XML files back into `.loca` files after you finish translating.
* **packArchive**: Zips everything back up into `.pak` files so the game can read them.
