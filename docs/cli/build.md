# bg3loc build

[繁體中文（台灣）](build.zh-TW.md)

**`bg3loc build`** creates the actual spreadsheets that translators will work on. 

It splits the game's massive text (over 230,000 lines!) into smaller batches. The default is 1,500 lines per file, so it doesn't freeze Excel.

## What It Does

- Has three modes for translators: basic, context, or blind-first.
- Finds **ProtectedTokens**: these are special codes like `{SpeakerName}` or `%s` that the game uses. Translators MUST keep these in their translations.
- Creates an immutable baseline. This is a locked, secure record of all the original English text so no one can secretly tamper with it.

## How to Use It

Just open your command line and type this:

```bash
bg3loc build
```

⚠️ **Warning:** This command does NOT translate anything for you, and it does not call any AI. It only prepares the files.

## Output

It can output files in Excel (`.xlsx`), CSV (`.csv`), or JSON Lines (`.jsonl`) formats. Everything goes into the `workspace/build/` folder.
