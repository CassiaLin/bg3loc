# LSTP-01A | Functional Classification Contract

## Status

```text
Milestone: Large-Scale Translation Production 01A
State: ACCEPTED
Branch: feat/lstp-01a-functional-classification
Depends on: BG3Loc v1.1.0
Core reopening: no
```

## 1. Goal

Classify every localization `ContentUid` into exactly one primary translation-production category before large-scale batching.

This stage does not translate text and does not define batch sizes. It answers one question only:

> Which production lane owns this `ContentUid`?

Classification must prefer reproducible game-structure evidence over guessing from localized text.

## 2. Primary categories

Exactly one primary category is assigned to each `ContentUid`.

```text
dialogue_general
dialogue_story
quest
bark
ui
skill_spell
item
book_lore
character_world
system_message
tutorial
other
```

`dialogue_general`: the default dialogue production lane for structurally proven dialog that is not owned by a more specific category. The name does **not** assert that the line is narratively unimportant.

`dialogue_story`: reserved category for a future accepted rule that can deterministically prove story-significant ownership. LSTP-01A does not currently emit this category.

`quest`: quest journal/localization records such as QuestTitle and QuestDescription.

`bark`: short ambient/combat/reactive spoken lines identified by Bark structure.

`ui`: interface-owned strings such as labels, buttons, menus, interface tooltips, and interface-only status text.

`skill_spell`: skills, spells, passives, statuses, actions, gameplay effects, names, and related tooltips/descriptions.

`item`: weapons, armor, consumables, equipment, objects, item names, and item descriptions.

`book_lore`: books, letters, diaries, notes, plaques, inscriptions, and other authored in-world readable content.

`character_world`: names and terminology for characters, places, factions, organizations, deities, races/species, and named world entities.

`system_message`: game/system feedback, notices, errors, and operation/state messages not owned by tutorial or ordinary UI layout.

`tutorial`: instructional/onboarding text whose primary purpose is teaching mechanics or controls.

`other`: safe holding category for records that cannot yet be classified deterministically. It must never be silently guessed into another category.

## 3. Identity rule

Canonical identity remains:

```text
ContentUid
```

Classification adds metadata only.

Each result carries:

```text
ContentUid
primaryCategory
tags[]
classificationEvidence[]
classificationConfidence
classificationStatus
```

Changing batch files or production order never changes identity.

## 4. One owner, many tags

A `ContentUid` has exactly one `primaryCategory`, but may have multiple tags.

Example:

```json
{
  "contentUid": "h...",
  "primaryCategory": "dialogue_story",
  "tags": ["act2", "companion", "cinematic", "shadowheart"]
}
```

Primary category controls which translation-production lane owns the record.

Tags may later control batching, routing, prompts, QA, human-review assignment, and reporting.

Tags never create duplicate translation jobs.

## 5. Evidence-first classification

Classification must use structural evidence from the user's installed game whenever possible.

Existing accepted/reproducible BG3Loc evidence includes:

```text
stat-reference
dialog-context
bark structure
quest/journal evidence
ui-skill mapping
story/reachability evidence
resource/provider provenance
```

Text keywords, translated wording, punctuation, length, or model inference alone must not override stronger structural evidence.

## 6. Production-ownership precedence

When evidence overlaps, use this ownership order unless a later accepted rule explicitly overrides it:

```text
1. bark structural evidence
2. quest/journal structural evidence
3. explicit skill/spell/stat role evidence
4. explicit item/stat role evidence
5. explicit tutorial/system resource-role evidence
6. explicit UI ownership evidence
7. story/dialog structural evidence
8. general dialog structural evidence
9. world-readable/book resource evidence
10. character/world entity evidence
11. other
```

Examples:

- a Bark line that also exists in a dialog graph remains `bark`;
- a QuestTitle shown in UI remains `quest`;
- a spell tooltip remains `skill_spell`, not generic `ui`;
- an item description remains `item`, not generic `ui`.

This precedence is about translation-production ownership, not importance.

## 7. Role-aware STAT classification

A `stat-reference` alone is not enough. The entity family and property role must be considered.

```text
spell/passive/status/action entity
→ skill_spell

weapon/armor/consumable/item entity
→ item
```

Ambiguous stat entities remain unresolved until a deterministic entity-family rule exists.

They must not be classified from English wording alone.

## 8. Dialog ownership and story significance

A dialog-context or story-occurrence record can deterministically prove dialogue ownership.

The real-corpus structural audit found that currently retained metadata can prove:

```text
this ContentUid belongs to dialogue
```

but cannot prove:

```text
story-important dialogue
vs
ordinary/general dialogue
```

without introducing a semantic importance judgment that is not encoded in the current structural evidence.

Therefore the accepted LSTP-01A rule is:

```text
structurally proven dialog
AND not owned by bark/quest/etc.
→ dialogue_general
```

For LSTP-01A, `dialogue_general` means **default dialogue production lane**, not "proven non-story dialogue".

`dialogue_story` remains a reserved schema value and must not be emitted until a later accepted deterministic rule exists. Narrative importance may later be represented by tags, a semantic-review layer, or a separately versioned classifier without changing ContentUid ownership.

A line must never become `dialogue_story` merely because of wording, dramatic tone, path names such as Act/Camp/Companions, or model inference.

## 9. Book/lore boundary

`book_lore` requires structural resource-role evidence that the content is an authored in-world readable.

Length is not evidence.

Therefore:
- a long quest description remains `quest`;
- a long spell description remains `skill_spell`;
- a long dialog monologue remains dialog;
- only structurally identified readable-world content becomes `book_lore`.

## 10. UI boundary

`ui` is not a catch-all for every string displayed on screen.

Therefore:
- QuestTitle remains `quest`;
- spell name remains `skill_spell`;
- item name remains `item`;
- tutorial instruction remains `tutorial`;
- only interface-owned records become `ui`.

## 11. Classification statuses

Each result must carry one of:

```text
classified
ambiguous
unclassified
```

`classified`: an accepted deterministic rule selected one primary category.

`ambiguous`: two or more structurally plausible categories remain and precedence does not resolve them.

`unclassified`: current evidence is insufficient.

Both ambiguous and unclassified records use:

```text
primaryCategory = other
```

until resolved.

## 12. Confidence

Confidence is evidence-derived, not model sentiment.

```text
high
medium
low
```

- `high`: direct deterministic structural mapping;
- `medium`: deterministic derived rule using multiple structural signals;
- `low`: incomplete structural evidence; reviewable only.

Low-confidence classification must not silently become authoritative.

## 13. Human correction

Manual correction is allowed but must be explicit and auditable.

A correction records:

```text
ContentUid
previousCategory
newCategory
reason
reviewer
timestamp
classificationRuleVersion
```

Repeated manual corrections should be reviewed for a reusable deterministic rule.

## 14. No duplicate ownership

After classification:

```text
one ContentUid
→ one primary production category
→ one translation job
```

The same UID may appear in many evidence sources, but this never creates multiple editable translation rows.

## 15. Output ledger

LSTP-01A eventually produces a classification ledger such as:

```json
{
  "contentUid": "h...",
  "primaryCategory": "skill_spell",
  "tags": ["spell", "level3"],
  "classificationStatus": "classified",
  "classificationConfidence": "high",
  "classificationEvidence": [
    {
      "type": "stat-reference",
      "role": "Description",
      "entityFamily": "spell"
    }
  ]
}
```

The public repository contains rules, schema, code, docs, and synthetic fixtures only.

Real generated classification ledgers remain user-generated/private artifacts because they may bind to proprietary game data.

## 16. Required reporting

A complete classification run must report:

```text
total ContentUid count
count per primary category
classified count
ambiguous count
unclassified count
coverage percentage
high/medium/low confidence counts
duplicate ownership count
missing ContentUid count
```

Required invariants:

```text
duplicate ownership = 0
missing ContentUid = 0
classified + ambiguous + unclassified = total
```

No automatic-classification percentage target is set before real-game measurement.

## 17. Non-goals

LSTP-01A does not:
- translate text;
- choose translation models;
- define prompts;
- define batch sizes;
- perform linguistic QA;
- perform translation review;
- merge translated results;
- change Core localization semantics;
- guess categories solely from wording.

## 18. Next-stage boundary

Only after LSTP-01A measures real-game classification coverage do we define batching.

```text
~230k localization records
        ↓
LSTP-01A functional classification
        ↓
primary category + tags
        ↓
LSTP-01B category-aware batching
```

Batching consumes classification results; it must not redefine them.

## 19. Acceptance question

Can BG3Loc assign every localization `ContentUid` to exactly one production lane, using reproducible structural evidence where available, while safely isolating unresolved records instead of guessing?

If yes:

```text
LSTP-01A Functional Classification = ACCEPTED
```


## 20. Real-corpus acceptance evidence

The accepted classifier was measured against a real English source universe of:

```text
232,878 ContentUid
```

Final LSTP-01A measurement:

```text
classified                  218,272
unclassified                 14,606
classified coverage          93.72804644491966%
duplicate ownership               0
missing ContentUid                0
```

Final unresolved `other` boundary:

```text
10,189  no current UID-addressable structural evidence
 4,402  LevelResources / ContextSupportOnly
    11  QuestTimers ownership unresolved
     4  OsirisStrings structure insufficient
------
14,606
```

The remaining `other` records are intentional fail-safe outputs, not known classifier ingestion gaps.

Dialogue-specific structural audit:

```text
dialogue production-lane UIDs      166,036
deterministically dialogue_story         0
deterministically non-story/general      0
cannot safely split story/general   166,036
```

This audit established that current structure can prove dialogue ownership but not narrative importance. LSTP-01A therefore accepts one default dialogue production lane and leaves story significance to a later optional semantic/tagging layer.

Acceptance invariants are satisfied:

```text
one ContentUid → one primary category
duplicate ownership = 0
missing ContentUid = 0
unresolved evidence → other
no text-semantic guessing required
```

Therefore:

```text
LSTP-01A Functional Classification = ACCEPTED
```
