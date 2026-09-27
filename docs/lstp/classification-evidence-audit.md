# LSTP-01A | Classification Evidence Audit

## Status

```text
Milestone: Large-Scale Translation Production 01A
Purpose: inventory existing BG3Loc evidence and record final real-corpus findings
Branch: feat/lstp-01a-functional-classification
Baseline: BG3Loc v1.1.0
```

## 1. Summary

The current BG3Loc research layer already provides strong deterministic evidence for several production categories, but not all twelve LSTP-01A categories are equally supported.

Initial implementation began from a narrow accepted evidence slice and was expanded only after real-corpus measurement.

Final real-corpus result:

```text
232,878 total ContentUid
218,272 classified
 14,606 other / unclassified
93.72804644491966% classified coverage
0 duplicate ownership
0 missing ContentUid
```

Deterministic production ownership is now supported for:

```text
bark
quest
skill_spell
item
ui
tutorial
system_message
dialogue_general
book_lore
character_world
other
```

`dialogue_story` remains intentionally unassigned. A dedicated audit of all 166,036 dialogue-lane UIDs found no retained structural field that can safely distinguish story-important from ordinary dialogue. The accepted interpretation of `dialogue_general` is therefore "default dialogue production lane", not "proven non-story dialogue".

No classifier should guess narrative importance from localized text, path naming, or model inference.

---

## 2. Evidence matrix

| Primary category | Existing evidence | Current readiness | Gap before classifier |
| --- | --- | --- | --- |
| `bark` | canonical Bark containers; bark speaker structure | **Strong** | wire accepted Bark mappings into ownership classifier |
| `quest` | Quest/Journal resources; QuestTitle / QuestDescription roles | **Strong** | wire accepted Quest mappings into ownership classifier |
| `skill_spell` | STAT references; UI/Skill provider domains; passive context | **Partial-strong** | define deterministic entity-family/role mapping |
| `item` | STAT references; UI/Skill provider domain `ItemsAndEquipment` | **Partial-strong** | define deterministic item entity-family/role mapping |
| `ui` | XAML/UI resource discovery; UI/Skill provider domain `UserInterface` | **Partial** | distinguish true UI ownership from strings merely displayed in UI |
| `tutorial` | UI/Skill provider domain `TutorialAndSystem`; path/resource discovery | **Partial** | separate tutorial from generic system text deterministically |
| `system_message` | `TutorialAndSystem`; resource/provider paths | **Partial** | define system-specific roles and precedence |
| `dialogue_general` | DialogsBinary/DialogResource; `dialog-context` mappings | **Partial-strong** | exclude bark/quest and establish ordinary-dialog ownership rule |
| `dialogue_story` | dialog graph, cinematics/resources, story/reachability evidence | **Insufficient** | no accepted deterministic rule yet for “story-significant” vs ordinary dialog |
| `book_lore` | scanner discovers `ReadableLocalizationRegistry` candidates | **Insufficient** | no accepted ContentUid-level readable/book ownership mapper yet |
| `character_world` | Tags/Characters and story resource discovery | **Insufficient** | no accepted ContentUid-level canonical world-entity classifier yet |
| `other` | fallback by contract | **Ready** | none |

---

## 3. Evidence already present in code

### Bark

Current evidence:
- canonical Bark container recognition;
- Bark speaker structure;
- deterministic Bark candidate mappings.

This is sufficient to classify Bark ownership without reading translated wording.

Expected classifier rule:

```text
accepted bark structural mapping
→ primaryCategory = bark
→ confidence = high
```

---

## 4. Quest

Current evidence:
- Quest/Journal source resources;
- structural parsing of quest localization handles;
- role classification such as `QuestTitle` and `QuestDescription`.

Expected classifier rule:

```text
accepted quest-journal mapping
→ primaryCategory = quest
→ confidence = high
```

Quest remains Quest even when displayed in the UI.

---

## 5. Skill / Spell

Current evidence:
- `stat-reference` mappings from generated Stats;
- stat property roles including `DisplayName`, `Description`, `ExtraDescription`, `Tooltip`;
- passive-specific structured evidence;
- UI/Skill domain classifier with `AbilityOrSkill`.

This is enough to build a useful classifier, but not by treating every stat reference as a skill.

Required additional rule table:

```text
entity family / stat type
+ property role
→ skill_spell
```

Examples expected to map here:
- SpellData
- PassiveData
- StatusData
- action/ability families when structurally proven

Unknown stat families must not be guessed.

---

## 6. Item

Current evidence:
- direct STAT references;
- UI/Skill domain classifier already recognizes:
  - item
  - armor
  - weapon
- these map to `ItemsAndEquipment`.

Required additional rule table:

```text
item/equipment entity family
+ localization property role
→ item
```

The current evidence is promising enough that this category should be implemented in the first classifier version.

---

## 7. UI

Current evidence:
- scanner recognizes XAML/UI resources;
- UI/Skill mapping recognizes `UserInterface`;
- provider path evidence exists.

Important limitation:

```text
shown in UI ≠ owned by UI
```

A spell, item, or quest string may also be shown in UI and must remain owned by its semantic category.

Therefore UI classification must run after more specific skill/item/quest rules.

---

## 8. Tutorial and System

Current UI/Skill path/domain logic currently groups both under:

```text
TutorialAndSystem
```

That is useful evidence but not yet enough to produce two authoritative production categories.

Required work:

```text
TutorialAndSystem
→ inspect structural provider/resource role
→ tutorial OR system_message
```

If that split cannot be established deterministically, affected records must remain `other` or carry a temporary unresolved tag rather than be guessed.

---

## 9. General Dialog

Current evidence:
- `Story/DialogsBinary/**/*.lsf` discovery;
- `DialogResource`;
- `dialog-context` mapping;
- speaker/node/timeline context.

After higher-priority Bark and Quest ownership is removed, this can support ordinary dialog classification.

Initial safe rule:

```text
dialog-context present
AND not owned by bark/quest/etc.
→ dialogue_general
```

This should be considered provisional until the story/general split is defined.

---

## 10. Story Dialog

Current research can prove that a string participates in story/dialog structure, but that is not the same as proving:

```text
major story / key narrative scene
```

Available signals include:
- dialog graph participation;
- cinematic resource discovery;
- story/reachability evidence;
- speaker/dialog/quest flags.

Missing piece:

A versioned deterministic rule defining when ordinary dialog becomes `dialogue_story`.

Until that rule is accepted:

```text
dialog records
→ dialogue_general
```

with optional story/cinematic tags where structurally justified.

This avoids inventing narrative importance.

---

## 11. Book / Lore

The scanner already recognizes a research family:

```text
ReadableLocalizationRegistry
```

using paths/names associated with:
- book
- letter
- gazette
- readable
- misc

However, discovery of a resource family is not yet equivalent to a deterministic ContentUid ownership mapping.

Required work:
- parse readable registries/resources;
- emit ContentUid-level mappings;
- preserve readable subtype as tags;
- prove that a handle belongs to an authored in-world readable.

Until then, `book_lore` is not implementation-ready.

---

## 12. Character / World

The scanner already discovers:
- `TagsCharacters`;
- RootTemplates;
- related story/world resource families.

Existing story logic also reasons about some DisplayName occurrences.

However, there is not yet an accepted rule that says a given localization handle is primarily:
- a character name;
- a place name;
- a faction;
- a deity;
- a race/species;
- another canonical world entity.

Required work:
- derive entity identity/type from structural resources;
- map localized fields to ContentUid;
- define precedence when the same name is referenced elsewhere.

Until then, this category is not implementation-ready.

---

## 13. Recommended implementation order

The first classifier implementation should not attempt all twelve categories at once.

Recommended order:

```text
Phase A
1. bark
2. quest
3. skill_spell
4. item
5. ui
6. dialogue_general
7. other

Phase B
8. tutorial
9. system_message

Phase C
10. book_lore
11. character_world
12. dialogue_story split
```

Reason:
- Phase A mostly reuses already accepted evidence;
- Phase B needs one domain split;
- Phase C requires genuinely new deterministic mapping work.

---

## 14. Safety rule

The classifier must prefer incomplete coverage over false certainty.

Therefore:

```text
no accepted structural rule
→ primaryCategory = other
→ classificationStatus = unclassified or ambiguous
```

A lower automatic coverage percentage is acceptable during development.

Incorrect production ownership is not.

---

## 15. Immediate next implementation target

The smallest useful classifier slice is:

```text
bark
quest
skill_spell
item
ui
dialogue_general
other
```

This slice should be implemented first and measured against a real game installation.

Only after observing real counts and overlap patterns should the remaining category rules be finalized.


## 16. Final unresolved boundary

After all accepted structural rules were connected, the remaining 14,606 `other` UIDs were fully accounted for:

```text
10,189  no UID-addressable structural evidence
 4,402  LevelResources / ContextSupportOnly
    11  QuestTimers ownership unresolved
     4  OsirisStrings structure insufficient
```

These are intentional fail-safe records.

The dialogue audit additionally established:

```text
166,036 dialogue-lane ContentUid
0 structurally proven dialogue_story
0 structurally proven non-story/general
166,036 structurally proven dialogue but story/general unresolved
```

Therefore no further deterministic split is justified in LSTP-01A.
