# The Processing Workflow (Pipeline)

[繁體中文（台灣）](pipeline.zh-TW.md)

The bg3loc tool processes game translation in six clear steps. Think of it like a factory assembly line!

## The 6-Stage Journey

1. **scan:** Looks at the game files to see what text exists.
2. **extract:** Pulls the game text out so you can read it.
3. **build:** Prepares your workspace for translation.
4. **[translation]:** This is where human translators do their magic!
5. **validate:** Checks your translated text for any mistakes.
6. **rebuild:** Prepares the final translation to go into the game.
7. **install:** Puts your new translation safely into the game folder.

## One Job, One Tool

Each step in this processing workflow has exactly **ONE** job. 

For example, the `extract` tool only extracts text; it never translates it. The `build` tool prepares files but never builds the final game package. This keeps everything safe and organized.

## The Safety Boundary

We have a very strict safety rule to protect your game:
* Stages 1 through 5 **ONLY** save files into your private `workspace/` folder. They will **never** touch or modify your real game files.
* Only the very last stage (`install`) is allowed to actually touch the game files.

⚠️ **Warning:** You cannot skip steps! Every step relies on the work done by the step right before it. 
