# Review Taiwan Usage

[繁體中文（台灣）](review-taiwan-usage.zh-TW.md)

The **Taiwan Usage** tool scans all translated game text to make sure the terminology matches common usage in Taiwan. 

It looks for non-standard terms and flags them so a human can double-check. If a single sentence breaks multiple rules, the tool nicely groups them all together into one review task.

## Your Private Rules

This tool does **not** include a built-in vocabulary list. Instead, you create your own custom rule file (in JSON format). 

💡 **Tip:** Just because the tool flags a word doesn't mean it's definitely wrong! It just means "hey, a human should look at this to be sure." 

## Review Decisions

When checking flagged terms, you will decide:
* **Pending:** You haven't decided yet.
* **AcceptAsIs:** The text is actually fine, leave it alone.
* **Revise:** The text needs to change. (You must provide the new text!)
* **NotApplicable:** The rule doesn't apply here.
* **NeedsContext:** You need to see this in the game to decide.

⚠️ **Warning:** Keep your custom terminology rules private. The bg3loc tools are public, but your specific translation rules should remain in your project folder!

## How to Use

To scan the text using your rules, just type this:
```powershell
bg3loc review taiwan-usage prepare --extract ... --rules project/taiwan-usage-rules.json --output workspace/taiwan-usage-review
```

After deciding what to fix, validate your changes by typing this:
```powershell
bg3loc review taiwan-usage validate --input ... --manifest ... --output workspace/taiwan-usage-review-validation
```
