# Blind-First Retranslation Mode

[繁體中文（台灣）](blind-first.zh-TW.md)

This is a specialized mode for COMPLETE retranslation projects. 

**The problem**: When translators see the old official translation, they tend to just slightly tweak it instead of writing a completely new and natural translation. This is called the "anchoring effect." In documented testing with 200,000 lines, an AI given the old text only changed 20,000 lines!

## How It Works

### Pass 1: Blind Draft
In the first step, translators will see ONLY the English source text, the game context, a glossary of terms, and protected placeholders. 

The old translation is **COMPLETELY REMOVED** from the files (not just hidden in a column). Translators must fill in the `IndependentTargetText` completely from scratch. 100% coverage is required!

### Pass 2: QA Comparison
After Pass 1 is entirely complete, the old translation and reference languages are finally revealed. Translators can then compare their new work with the old version to polish and fix any mistakes.

## Technical Details

* **ProtectedTokens**: These are special game codes like `{SpeakerName}` or `%s`. They MUST be kept exactly as they are so the game does not break. bg3loc extracts and tracks these automatically for you.
* The existing original translation is treated as just reference data by default, NOT the final authority. It only becomes the authority if someone explicitly marks it with `ApprovedAuthority = true`.
