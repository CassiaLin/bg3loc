# bg3loc validate

[繁體中文（台灣）](validate.zh-TW.md)

**`bg3loc validate`** acts as your quality control inspector. It checks the translated spreadsheets you return to make sure they won't break the game.

## What It Does

- **Identity checks:** Every row must match a real `ContentUid` (a permanent ID number for each line of game text). No duplicates are allowed.
- **Tamper protection:** It throws an error if someone edited the English source text or the language names.
- **Protected syntax checks:** Game codes (like `{SpeakerName}`) must be preserved exactly. If a code is missing, or if an unauthorized one is added, it triggers an error. Broken formatting like broken `<LSTag>` tags will also trigger an error.
- **Blind-first coverage:** If you use blind-first mode, every required line must be filled out.

## How to Use It

Just open your command line and type this:

```bash
bg3loc validate
```

## Strict Mode

By default, the tool runs in **Strict Mode**. This means any single error will completely block the next step.
If you turn off Strict Mode, it will accept the valid rows and put the rejected ones in a separate list.

💡 **Tip:** Missing rows are just counted as coverage info. They don't generate individual warning errors.

⚠️ **Warning:** This tool does NOT judge your literary style or grammar. It only cares if the files work technically.

## Output

It puts everything into the `workspace/validate/` folder, separating accepted records, rejected records, and error reports.
