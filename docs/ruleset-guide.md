# Translation ruleset

A ruleset tells the provider what language pair and writing conventions to use. Copy [the example](lstp/ruleset-example.json) to your project and edit it before `production prepare`. It is ordinary UTF-8 JSON.

| Field | Meaning |
| --- | --- |
| `version` | Your own stable label for this revision of the rules. Change it when the rules change. |
| `sourceLocale` | Locale ID used by `extract --source`, such as `English`. |
| `targetLocale` | Locale ID used by `extract --target`, such as `French`. |
| `commonRules` | Instructions applied to all translations; preserve meaning and protected tokens. |
| `categoryRules` | Instructions for classified categories such as `bark`, `quest`, `item`, and `ui`. |
| `glossary` | Optional project terminology entries. Inspect the example format before adding entries. |

The locale IDs must match the extract manifest exactly. The example's English → Traditional Chinese pairing is only an example; choose the pair from your own installation. Keep category rules concise and review real outputs before large runs. The prepared workspace snapshots the ruleset, so use a new workspace when you change its translation policy. Never put an API key in a ruleset.

For deeper behavior and category definitions, see the [production guide](lstp/large-scale-production-guide.md). For common validation failures, see [troubleshooting](troubleshooting.md).
