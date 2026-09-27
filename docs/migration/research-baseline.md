# Research baseline migration / 研究基準移植

## Purpose / 用途

Preserve recoverable BG3 localization research from translation-team workbooks before old research workspaces are deleted.  
在舊研究工作目錄被清除前，把翻譯團隊工作簿中仍可恢復的 BG3 研究成果正式抽出並保存。

## Confirmed source workbooks / 已確認來源

### `bg3-english-only-full-translation-review.xlsx`

Confirmed sheets include:

- `TranslationQueue`
- `ContextEvidence`

The workbook states that the formal English-only boundary is 14,194 unique `ContentUid` values and that `ContextEvidence` contains 679 evidence-backed targets.

`ContextEvidence` preserves:

- `ContentUid`
- `ConflictGroup`
- `ContextSource`
- `ContextType`
- `ContextSummary`
- `EvidenceStrength`
- `TranslationConstraint`
- `PakName`
- `InternalPath`
- `DialogUUID`
- `NodeUUID`

Observed context families include:

- `Dialog/Bark`
- `Dialog/Gameplay`
- `Quest/Journal`
- `StatsDataField:DisplayName`
- `StatsDataField:Description`

### `phase4w-bark-human-review.xlsx`

The workbook states a 289-item Bark review scope: 277 `SingleSpeaker` + 12 `SharedSpeaker`, with unresolved identity count 0 at package construction time.

Confirmed sheets preserve:

- `SingleSpeaker`
- `SharedSpeaker`
- `SharedSetMembers`
- `EvidenceReference`

`EvidenceReference` preserves a stronger evidence chain than the translation queue alone:

- package/internal path
- dialog/node UUID
- container-purpose evidence
- speaker evidence including SpeakerUUID → ParentTemplateUUID → named TemplateUUID chains
- context strength
- review readiness
- evidence notes
- source report provenance

The package also preserves shared-set membership, so `SharedSpeaker` constraints do not need to be reconstructed from prose alone when this workbook survives.

### `phase4ad-quest-human-review.xlsx`

The workbook states a 94-target Quest/Journal scope: 7 `QuestTitle` and 87 `QuestDescription`, all with `StrongQuestProgressContext` at package construction time.

Confirmed sheets include:

- `QuestReview`
- `LocalizationAvailability`

The package preserves target-level structural and localization evidence including:

- `ContentUid`
- `QuestJournalFieldRole`
- `EvidenceStrength`
- `PakName` / `InternalPath`
- module and record/node type
- record/node UUID or ID where present
- field name and `FieldPath`
- `StructuralOwner`
- physical occurrence count
- `OccurrenceClassification`
- Traditional Chinese availability
- localization action status
- translation constraint
- human review decision / proposal / note / reviewer / time

`LocalizationAvailability` separately preserves English and Traditional Chinese exact-hit counts plus addition/approval flags. This is important evidence for the historical conclusion that all 94 targets were missing from the Traditional Chinese XML and required separate addition-policy review rather than automatic writeback.

### `bg3-four-language-translator-table-filled.xlsx`

Confirmed to preserve the 14,194-row English-only boundary plus Traditional Chinese reuse/conflict references, exact Simplified Chinese / Russian same-UID references when available, review decisions, Taiwan-usage audit information, and copied context fields.

## What the workbooks can reconstruct / 可由工作簿恢復

The surviving translation/review workbooks are sufficient to reconstruct a substantial research baseline:

- `ContentUid`-keyed context assignments
- context type and human-readable summary
- translation constraints
- evidence-strength labels
- final selected package/internal path evidence
- DialogUUID / NodeUUID for context rows where recorded
- Bark speaker identity and evidence
- SharedSpeaker membership where `SharedSetMembers` is present
- Quest/Journal field role, structural owner, field path, occurrence classification, and localization availability evidence
- multilingual reference decisions
- human review decisions, translations, notes, reviewer identity, review time
- provenance back to research phase/source report names

## What they do not fully reconstruct / 仍無法完整恢復

These packages usually preserve conclusions and selected evidence, not the complete discovery graph. They are not sufficient by themselves to reconstruct all of the following with the same evidentiary strength:

1. Every candidate resource/provider inspected before the winning source was selected.
2. Negative evidence and rejected candidate paths.
3. The complete official patch/hotfix provider precedence graph used to prove overlay rules.
4. Full traversal traces from package/resource structures to translated-string handles when only the final path/UUID is retained.
5. Research intermediates that never entered a workbook because they were not part of the translation/review boundary.
6. The original raw reports referenced by `SourceReport`, unless those reports also survive.

Therefore referenced reports such as `reports/phase4u-target-context-evidence.csv` and `reports/phase4v-review-readiness.csv` should remain preserved until equivalent collectors and evidence reports are reproducible from a clean BG3 installation.

## Extractor / 抽取工具

Use:

```powershell
python scripts/extract-research-baseline.py `
  --full "bg3-english-only-full-translation-review.xlsx" `
  --bark "phase4w-bark-human-review.xlsx" `
  --quest "phase4ad-quest-human-review.xlsx" `
  --four-language "bg3-four-language-translator-table-filled.xlsx" `
  --output "workspace/research-baseline"
```

Outputs:

```text
workspace/research-baseline/
├─ research-baseline.jsonl
└─ research-baseline-summary.json
```

Every extracted evidence object includes workbook/sheet/row provenance. Source workbook SHA-256 values are stored in the summary.

Summary v1.1 includes dedicated coverage counters for Quest review rows and Quest localization-availability evidence in addition to context, Bark, human-review, multilingual-reference, and shared-set coverage.

## Deletion policy / 刪除政策

Until clean-install context reconstruction is verified:

- KEEP the four source workbooks above.
- KEEP referenced phase reports and any provider/overlay research evidence.
- KEEP any files containing rejected candidates or traversal evidence.
- Raw LOCA/XML/basic text-only intermediates may be considered reconstructible only after Windows Tier 1 clean reconstruction passes.

No old research workspace should be bulk-deleted based only on the existence of the current `bg3loc` localization core.
