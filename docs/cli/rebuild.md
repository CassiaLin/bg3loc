# bg3loc rebuild

[繁體中文（台灣）](rebuild.zh-TW.md)

**`bg3loc rebuild`** puts your translations back together. It takes ONLY the approved records from the validation step and merges them with the original game text.

## What It Does

- **Safe merge:** It takes all 230,000+ lines of the complete game text, and ONLY replaces the lines you translated. Untouched lines stay completely safe.
- **Baseline-first:** It NEVER creates a language file from scratch using only your translated rows. It always uses the full game file as a base.
- **Double checking:** After rebuilding, it reads the new file back in to verify that everything matches perfectly (we call this a semantic round-trip).
- **Smart packaging:** It automatically decides whether to create just a game language file (`.loca`) or pack it into a compressed package (`.pak`), depending on how your game is set up.

## How to Use It

Just open your command line and type this:

```bash
bg3loc rebuild
```

## Missing Translation Policy

- If the English source has a line, but your target language originally didn't, and you provided a translation: it will create a new entry for it!
- If you didn't provide a translation: it leaves it missing (it never invents text).
- If your target language has an extra line that the English source doesn't: it safely preserves it.

⚠️ **Warning:** Rejected or unvalidated rows will NEVER be written. This command also does NOT install the text into your game yet.

## Output

It puts everything into the `workspace/rebuild/` folder, including the final `.loca` or `.pak` files and verification reports.
