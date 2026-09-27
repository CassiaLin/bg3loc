# Translation Test Results

[繁體中文（台灣）](human-review-protocol-closeout.zh-TW.md)

## Status

```text
Bark (Short Phrases)  ACCEPTED
Quest                 ACCEPTED
UI / Skill            ACCEPTED
Multilingual          ACCEPTED
Taiwan Usage          ACCEPTED

Translation Test = COMPLETE
```

This milestone proves our tool successfully organizes everything you need to translate the game. It does this by reading your game directly, without using old translations or private files. 

## General Rules

- A permanent ID number for each line of game text (`ContentUid`) is what keeps everything organized.
- We trust the files in your actual game more than any old translation files.
- The official translation is there to help you, but it's not strictly enforced. 
- You are not allowed to accidentally delete important game codes while translating. 
- The tool will stop if it detects something is missing or broken.

## What Was Tested

### Bark (Short Phrases)

Our tool perfectly extracts character barks and organizes who is speaking. 

Test results:

```text
289 phrases found
277 said by one character
12 shared by multiple characters
```

### Quest

The tool successfully grabs the names and details of quests.

Test results:

```text
94 unique ID numbers
96 places they appear in game
7 Quest Titles
87 Quest Descriptions
```

### UI / Skill

The tool pulls the game's menu buttons, items, and skill descriptions perfectly.

Test results:

```text
20,874 pieces of text found
0 duplicates!
```

### Multilingual 

You can translate between any source language and target language. You can also view other languages as a reference!

Our test from English to Traditional Chinese found:

```text
14,194 unique ID numbers

EXACT_SINGLE              445
EXACT_CONSENSUS           261
EXACT_CONFLICT          1,069
NO_EXACT_CANDIDATE     12,419
```

💡 **Tip:** Looking at other languages is just for help. You don't have to follow what they say!

### Taiwan Usage

We test for common Taiwanese wording, but it is ultimately up to a human to decide what sounds best. 

The tool will point out words that you might want to look at, but it won't force you to change them. A flag simply means "take a look at this," not "this is wrong."

## What We Do and Don't Do

Our tool **does**:
- Find the text you need to translate.
- Organize it neatly into spreadsheets.
- Give you context and references.
- Let you create rules to check your wording.

Our tool **does NOT**:
- Force you to use historical or old translations.
- Come bundled with private translation files.
- Include hidden rules about what words you must use.

## Wrapping Up

We have successfully integrated all of this into the main code! We did full test runs directly from the game files to ensure it's safe, reliable, and ready to go.
