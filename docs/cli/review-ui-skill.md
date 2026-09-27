# Review UI and Skills

[繁體中文（台灣）](review-ui-skill.zh-TW.md)

**UI/Skill** text includes interface buttons, spell descriptions, character abilities, item tooltips, and status effects.

This tool keeps track of how skills relate to each other. For example, if a specific spell inherits its description from a basic magic template, the tool knows this connection!

## Workstreams

To make reviewing easier, the tool separates different types of text into distinct groups called workstreams. For example, all text related to the character progression UI is grouped into a `UserInterface` workstream.

We use the same two-pass system and validation checks as the other review tools.

## How to Use

To prepare UI and skill text for review, just type this:
```powershell
bg3loc review ui-skill prepare --universe workspace/research/ui-skill-universe.csv --extract ... --output workspace/ui-skill-review
```

When you are done reviewing, validate your work by typing this:
```powershell
bg3loc review ui-skill validate --input ... --manifest ... --output workspace/ui-skill-review-validation
```
