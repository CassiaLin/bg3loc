# Platform Adapters

[繁體中文（台灣）](platform-adapters.zh-TW.md)

Baldur's Gate 3 runs on Windows, Linux, and macOS. Each operating system stores its files differently. **Platform adapters** are tools that handle these differences so our core translation engine works the same everywhere.

* **Windows**: The adapter reads your Steam library and finds the game using the appmanifest file.
* **Linux/Proton**: The adapter reads Steam directly. No Proton prefix is needed just for reading the game files.
* **macOS**: This uses a native Steam installation, so we don't assume Windows-style file paths.

⚠️ **Important Rule**
Platform adapters ONLY handle file locations. They never touch or change your translation content!
