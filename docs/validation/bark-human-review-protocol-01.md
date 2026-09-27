# Bark Character Dialogue Test Results

[繁體中文（台灣）](bark-human-review-protocol-01.zh-TW.md)

This page shows the results of our test on "barks" (the short phrases characters say out loud as they walk around). We made sure our tool can properly find and organize them for you to translate.

Before starting the test, we saved the code state:

```text
base main HEAD: 2f8bec2561c006b082b8dac1690999220c68fc57
branch: feat/bark-human-review-protocol
initial HEAD: 2f8bec2561c006b082b8dac1690999220c68fc57
```

We ran this test on September 13, 2026, using a legal, installed copy of Baldur's Gate 3. We used a third-party unpacking tool with game version `4.1.1.7398727`.

💡 **Tip:** We didn't use any old translations or private files for this test. We read everything directly from the game itself.

## The Results

Here is what our tool found when looking at the game files:

```text
research mappings: 51606
Bark review candidates: 289
SingleSpeaker: 277
SharedSpeaker: 12
SharedSpeaker member count: 8
Pass 1 validation findings: 0
Pass 2 validation findings: 0
OfficialTarget available: 0 / 289
```

Our tool successfully separated the spreadsheet files so they are easy to read. It correctly grouped together phrases that can be spoken by multiple characters at once, so you don't have to translate the exact same phrase over and over.

⚠️ **Warning:** Any game text or ID numbers found during this test are saved in a hidden `workspace/` folder on your own PC. They are never uploaded to the internet to protect the game's copyrights.

In this specific test, we didn't find any official translation for the 289 bark phrases we tested. This is just because of the specific game files we looked at, and it doesn't mean the tool is broken. The tool left the target text blank for you to fill in!

All 196 automated tests passed perfectly. There was one small warning about how text displays in the Windows console, but it did not break anything.
