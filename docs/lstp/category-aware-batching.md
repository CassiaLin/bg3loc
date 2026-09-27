# LSTP-01B | Category-Aware Batching / 分類後分批

## Status / 狀態

```text
Milestone: Large-Scale Translation Production 01B
State: ACCEPTED
Depends on: LSTP-01A Functional Classification = ACCEPTED
Core reopening: no
```

## Purpose / 用途

LSTP-01A 已經先決定每個 `ContentUid` 屬於哪一類。  
LSTP-01B 接著做的事很單純：**把同一類、而且彼此有關的內容盡量放在同一批，再交給後面的翻譯流程。**

LSTP-01A already decides which production category owns each `ContentUid`.  
LSTP-01B takes the next step: **keep related records together inside the same category, then split them into repeatable translation batches.**

這一階段不重新分類，也不翻譯文字。  
This stage does not reclassify or translate text.

---

## What goes in / 輸入

Required / 必要：

```text
functional-classification.jsonl
source normalized localization JSONL
```

Optional / 可選：

```text
story-occurrence-ledger.csv
ui-skill-universe.csv
research-mappings.jsonl
other structural ledgers used only for grouping context
```

Structural ledgers are allowed to help decide **which related records should stay together**.  
結構資料只能拿來決定「哪些相關內容應該放在一起」，不能拿來改掉 LSTP-01A 的分類結果。

Canonical identity remains / 唯一正式 identity 仍然是：

```text
ContentUid
```

---

## What gets batched / 哪些資料會進翻譯批次

Normal translation batches include only:

```text
classificationStatus = classified
primaryCategory != other
```

The following stay out of normal translation batches:

```text
classificationStatus = ambiguous
classificationStatus = unclassified
primaryCategory = other
```

它們會另外放進 unresolved queue，不和正常翻譯批次混在一起。  
They go to a separate unresolved queue.

目前真實 corpus 的 unresolved 數量是：

```text
14,606
```

---

## One UID only appears once / 同一筆只能翻一次

最重要的規則：

```text
one ContentUid
→ one primaryCategory
→ one batch
→ one editable translation row
```

同一個 UID 可能同時出現在幾個 dialog resource、provider 或 evidence source 裡。  
Those extra appearances are context only.

它們可以補上下文，但不能因此再建立第二份翻譯工作。  
They may add context, but they must never create a duplicate translation job.

---

## How batching works / 怎麼分批

分批順序固定如下：

```text
classified records
↓
split by primaryCategory
↓
find related structural groups
↓
choose one canonical group for each UID
↓
sort groups in a stable order
↓
pack groups into batches
↓
assign batch IDs
```

A batch never mixes primary categories.  
同一個 batch 不會混入不同 primary category。

Batch size is applied **after** related records are grouped.  
批次大小永遠最後才套，不會先每 500 筆硬切。

---

## Canonical group / 同一 UID 到底跟哪一組走

有些 UID 會同時出現在多個 structural group 裡，dialogue 特別常見。

When that happens, the batcher must choose exactly one canonical group.

規則是：

```text
1. collect every valid group key for the UID
2. normalize each key
3. sort keys lexicographically
4. choose the first normalized key as canonical
5. keep all other keys as read-only context references
```

這樣同一份輸入每次重跑，都會選到同一組。  
This keeps grouping reproducible and prevents the same UID from entering multiple batches.

如果某個 category 沒有可用 structural group：

```text
fallback group key = uid:<ContentUid>
```

Missing optional structural ledgers therefore do not reclassify records and do not create nondeterministic behavior.  
缺少可選的 structural ledger 時，不會改分類，也不會讓結果變成不穩定。

---

## Dialogue grouping / 對話怎麼分組

`dialogue_general` 是最大的 production lane，所以這裡最需要保留上下文。

Preferred grouping / 優先分組依據：

```text
logical dialog resource
InternalPath scope
Act / region / Camp / Companions path family
NodeId when useful
```

### Raw / Binary mirror handling / Raw 與 Binary 對應

同一份 dialog 常同時存在 raw 與 binary 版本。  
The same logical dialog often appears as both raw and binary resources.

For grouping only, the path is normalized as follows:

```text
replace "\" with "/"
case-fold path
remove known DialogsRaw / DialogsBinary container difference
remove final .lsj / .lsf extension
keep the remaining relative dialog path
```

Example / 範例：

```text
.../Story/Dialogs/Act1/Foo.lsj
.../Story/DialogsBinary/Act1/Foo.lsf
→ logical dialog key: act1/foo
```

If raw and binary paths cannot be matched by this normalization, they remain separate context groups.  
如果無法用這個規則安全對上，就保持分開，不猜它們是同一份 dialog。

Path families such as `Act1`, `Act2`, `Camp`, `Companions`, `Crimes`, or `GeneratedNarratorADs` only help grouping.  
這些 path family 只拿來分組，不會把 `dialogue_general` 改成其他分類。

---

## Other category grouping / 其他分類怎麼分組

### Bark

Keep records from the same bark container or speaker structure together when possible.  
同一 bark container、speaker structure 的內容盡量放一起。

### Quest

Keep structurally linked quest title and description records together.  
同一 quest 的 title / description 若有明確結構關聯，盡量放一起。

### Skill / Spell

Stats records use their structural `entryName` when available.  
Stats 類資料優先使用遊戲檔裡既有的 `entryName` 分組。

That keeps fields from the same spell, passive, or status together without treating the whole `Passive.txt`, `Spell_Target.txt`, or `Status_Boost.txt` file as one context.  
這樣同一技能、被動或狀態的名稱與說明可以放在一起，也不會把整份 stats 檔誤當成單一 context。

### Item

Group by the individual item/template entity whenever the LSX/LSF structure exposes one.  
LSX/LSF 結構有個別 item/template identity 時，就用該 entity 分組。

A container such as `GameObjects` or `RootTemplates/_merged.lsf` is not treated as one item.  
像 `GameObjects` 或整份 `RootTemplates/_merged.lsf` 只是容器，不代表單一物件。

### UI

Group by UI resource, screen/provider, or widget/entity identity.  
依 UI resource、screen/provider 或 widget/entity 分組。

UI grouping never changes LSTP-01A ownership.  
某文字就算出現在 UI 裡，也不會因此把原本的 quest、item、skill 分類改掉。

### Tutorial

Keep fields from the same individual `UnifiedTutorial` or `ModalTutorial` entity together.  
同一個別 tutorial entity 的 keyboard/controller、title、description 等欄位盡量放一起。

The whole tutorial registry is not one context group.  
整份 `UnifiedTutorials.lsx` 不是一個 context。

### System message

Group by the same system resource or registry identity.  
依同一 system resource 或 registry identity 分組。

### Book / Lore

Keep one readable/document node together when the registry exposes a stable node identity.  
Readable registry 有穩定 node identity 時，以單一書籍、信件或 readable node 分組。

If the evidence does not yet expose a node identity, the resource path remains a fallback only.  
如果舊 evidence 還沒有 node identity，整份 resource path 只當 fallback，不視為真正的單一文件。

### Character / World

Use the individual character/world node identity when available.  
有個別 character/world node identity 時，以該 node 分組。

A level-wide file such as `Characters/_merged.lsf` is only a container and should not become one giant context group.  
像 `Characters/_merged.lsf` 這種整個 level 的檔案只是容器，不應整份綁成一個大型 context。

---

## Exact packing rule / 批次怎麼裝

為了確保不同機器重跑會得到相同結果，v1 不使用 best-fit 或其他自由 bin-packing 方法。

v1 uses one simple sequential rule:

```text
1. sort canonical groups by normalized group key
2. start an empty batch
3. take the next whole group
4. if currentCount + groupCount <= maxRecords:
      append the group
   else:
      close current batch
      open a new batch with that group
5. continue until done
```

這代表只要輸入與設定相同，batch membership 就會相同。  
With the same inputs and config, batch membership is reproducible.

---

## Oversize groups / 單一 group 太大怎麼辦

If one structural group is already larger than `maxRecords`, it still has to be split.

規則固定如下：

```text
1. use category-specific stable subkeys when available
2. sort those subgroups by normalized key
3. pack them sequentially using the same rule
4. if any subgroup is still too large:
   stable-sort its records by category-specific structural keys
   then ContentUid
5. split into contiguous chunks of maxRecords
```

最後一定會退到 `ContentUid`，所以不會出現「這組太大但不知道怎麼切」的情況。  
The final `ContentUid` fallback guarantees deterministic termination.

---

## Initial batch sizes / 第一版批次大小

These are starting defaults for measurement, not permanent constants.  
這些數字只是第一版拿來實測，不代表永遠固定。

```text
dialogue_general   1000
bark                750
quest               500
skill_spell         500
item                500
ui                  500
tutorial            400
system_message      400
book_lore           250
character_world     500
```

`other` does not enter ordinary translation batches.  
`other` 不設定正常翻譯 batch size。

v1 uses `maxRecords` as the hard batching limit.  
第一版先只用筆數控制，不綁特定模型 tokenizer。

Later versions may also support:

```text
maxSourceChars
maxEstimatedTokens
```

---

## Stable ordering / 固定排序

All ordering must come from stable data.

Required final tie-breaker / 最後排序依據：

```text
ContentUid
```

The following must never affect batch membership:

```text
filesystem enumeration order
thread scheduling
dictionary insertion order
timestamps
random values
```

---

## Batch IDs / Batch ID

Batch IDs are human-readable execution labels:

```text
<category>-<ordinal>
```

Examples:

```text
dialogue_general-0001
item-0007
book_lore-0003
```

`batchId` is **not** localization identity.  
`batchId` 只是這次 production plan 的分組標籤，不是內容 identity。

Translation results must always be recoverable by `ContentUid`, even if a later config change produces different batch IDs.  
就算以後改 batch size 導致 batchId 改變，翻譯成果仍必須能靠 `ContentUid` 找回。

---

## Batch plan fingerprint / 分批計畫指紋

Each batching run should also produce a `batchPlanFingerprint`.

它用來辨識「這一版分批計畫」，不是拿來取代 `ContentUid`。

The fingerprint must bind at least:

```text
classification ledger hash
source localization input hash
effective batch config
batchingRuleVersion
structural grouping input hashes actually used
```

Changing one of these inputs creates a new batch plan.  
其中任一項改變，就視為新的 batch plan。

---

## Output / 輸出

Suggested layout / 建議輸出：

```text
workspace/
└─ batches/
   ├─ batch-summary.json
   ├─ batch-plan.json
   ├─ unresolved.jsonl
   └─ materials/
      ├─ dialogue_general-0001.jsonl
      ├─ dialogue_general-0002.jsonl
      ├─ item-0001.jsonl
      └─ ...
```

Each batch manifest should include at least:

```text
batchId
batchPlanFingerprint
primaryCategory
recordCount
contentUids[]
groupKeys[]
sourceLocale
batchingRuleVersion
```

Useful diagnostics may also include:

```text
sourceCharCount
groupCount
oversizeGroupSplit
firstContentUid
lastContentUid
```

---

## Translation rows / 翻譯資料列

Every editable row keeps:

```text
ContentUid
SourceText
TranslationText
PrimaryCategory
BatchId
```

Extra context fields are read-only.  
額外 context 欄位只供參考，不可取代 `ContentUid` identity。

Row number is never identity.  
列號永遠不是 identity。

---

## Resume and retry / 中斷續跑與重試

Batch generation itself is pure and repeatable.  
分批本身不應受到執行時間、API 狀態或前一次失敗影響。

A rerun with the same inputs must regenerate the same batch plan.  
同一組輸入重跑，應得到相同 batch plan。

Translation execution may retry:

```text
failed row
failed batch
```

It must not require rebuilding all 218k classified records after one failure.  
單一 API 失敗、斷線或重開機，不應要求整批 21 萬筆重來。

Runtime fields such as:

```text
attempt
provider/model
startedAt
finishedAt
error
```

belong to translation execution state and must not affect future batch membership.  
這些 runtime 欄位不能反過來改變分批結果。

---

## Unresolved queue / 未分類佇列

LSTP-01A currently leaves:

```text
14,606 other / unclassified
```

These records are written separately, for example:

```text
unresolved.jsonl
```

They are not silently mixed into translation batches.  
它們不會偷偷混進正常翻譯工作。

A later classifier version may move some of them into a normal category after new structural evidence is added.  
未來若找到新的可靠結構證據，再由新版 classifier 處理。

---

## Validation / 驗證

A valid batching run must satisfy:

```text
classified input UID count
= unique batched UID count

unresolved input UID count
= unresolved queue UID count

duplicate batched UID = 0
missing classified UID = 0
foreign UID = 0
mixed-category batch = 0
empty batch = 0
```

Every row inside a batch must match that batch's `primaryCategory`.  
每個 batch 裡的資料都必須和 manifest 的分類一致。

---

## Reporting / 報告

At minimum, report:

```text
total source ContentUid
classified input count
unresolved count
batch count
batch count per category
record count per category
min/max/mean records per batch
oversize group split count
duplicate batched UID count
missing classified UID count
foreign UID count
mixed-category batch count
batchPlanFingerprint
```

---

## Real-corpus acceptance / 真實資料驗收

Synthetic tests are not enough.  
只有測試資料通過還不算完成。

LSTP-01B must also run against the accepted real corpus:

```text
232,878 total ContentUid
218,272 classified
14,606 unresolved
```

Acceptance requires:

```text
all classified UID batched exactly once
all unresolved UID isolated
no duplicate UID
no missing classified UID
no foreign UID
no mixed-category batch
same inputs reproduce same batch plan
```

No target batch count is fixed in advance.  
不預設「應該剛好幾個 batch」，先以真實資料量測。

---

## Non-goals / 不處理事項

LSTP-01B does not:

- translate text / 不翻譯文字；
- choose an AI model or provider / 不選模型或 API；
- define category prompts / 不定義各分類提示詞；
- perform linguistic QA / 不做語言品質 QA；
- resolve LSTP-01A `other` / 不處理 01A 尚未分類資料；
- change `primaryCategory` / 不重新分類；
- infer story importance / 不判斷劇情重要性；
- rebuild or install game files / 不重建或安裝遊戲檔。

---

## Real-corpus result / 真實資料結果

LSTP-01B 已在完整 BG3 English source universe 上驗證。  
LSTP-01B has been validated against the full BG3 English source universe.

Latest accepted run:

```text
total source ContentUid      232,878
classified / batched        218,272
unresolved                  14,606
batch count                 291
duplicate batched UID       0
missing classified UID      0
foreign UID                 0
mixed-category batch        0
```

Default batch sizes were used. No category-specific limits were manually tuned for acceptance.  
驗收使用預設 batch size，沒有為了讓結果好看而人工調整各分類上限。

### Batch distribution / 分批結果

```text
dialogue_general   166,036 records / 178 batches
bark                 9,894 records /  19 batches
quest                5,458 records /  11 batches
skill_spell         14,558 records /  30 batches
item                13,615 records /  28 batches
ui                   1,262 records /   3 batches
tutorial               829 records /   3 batches
system_message           33 records /   1 batch
book_lore             2,201 records /   9 batches
character_world       4,386 records /   9 batches
```

The accepted batch plan fingerprint is:

```text
8529d7f30848f4c9e035527d6d3ef916d560b1b1cd03ddfafb2690050459d326
```

A second run with identical inputs reproduced:

- the same fingerprint;
- the same 291 batch IDs;
- the same ContentUid membership for every batch;
- the same row order inside every batch.

相同輸入第二次重跑後，fingerprint、291 個 batch、每個 batch 的 UID membership 與 batch 內順序都完全一致。

---

## Oversize-group acceptance / 大型 group 驗收

The first real batching run exposed 27 oversize groups:

```text
9  valid single-dialog contexts
18 overly broad registry / container / file groups
```

Those 18 broad groups were traced to missing entity-level grouping evidence in:

```text
book_lore
character_world
item
quest
skill_spell
tutorial
```

The grouping evidence was then refined without changing LSTP-01A ownership.

Final real-corpus result:

```text
oversize split batches      18
unique oversize groups       9
valid dialog contexts        9
overly broad groups          0
insufficient-evidence groups 0
```

All remaining oversize groups are Bark dialog resources.  
They are intentionally kept as one structural dialog context and are split only because they exceed the configured record limit.

最後剩下的 oversize group 全部是 Bark 的單一 dialog context；它們本身分組正確，只因筆數超過上限才被切開。

Previously broad groups now have these maximum canonical-group sizes:

```text
book_lore          1 UID
character_world    2 UID
item              56 UID
quest             14 UID
skill_spell       18 UID
tutorial           7 UID
```

A few tiny path fallbacks remain where finer structural identity is unavailable, but none recreates the earlier large aggregate-group problem.  
仍有少數很小的 path fallback，但不再形成整份 registry、container 或 stats file 被誤當成單一大型 context 的問題。

---

## Structural grouping evidence / 結構分組證據

The accepted implementation uses structural identity only.  
最終版本只使用結構證據分組，不依文字語意猜測。

Examples:

```text
dialogue / bark  → logical dialog resource
quest            → journal entity identity
skill_spell      → stats entryName
item             → individual GameObject / template entity
tutorial         → individual tutorial entity
book_lore        → readable node identity
character_world  → character/world node identity
```

On Windows LSF resources, some readable and character/world nodes do not expose UUID / MapKey / Name style identifiers through LSLib.  
For those resources BG3Loc uses a stable path-local `node#ordinal` identity.

This ordinal is used only for grouping fields that belong to the same parsed node.  
It is not localization identity and does not replace `ContentUid`.

Windows 的部分 LSF 無法從 LSLib 取得 UUID、MapKey、Name 等原生 ID，因此會使用穩定的 path-local `node#ordinal`。

這個 ordinal 只用來判斷哪些欄位屬於同一 parsed node，不是翻譯 identity，也不會取代 `ContentUid`。

Real-corpus validation showed:

```text
ReadableLocalizationRegistry NodeId coverage = 100%
TagsCharacters NodeId coverage               = 100%
story ledger row count unchanged             = yes
story ledger ContentUid universe unchanged   = yes
```

---

## Acceptance / 驗收

LSTP-01B is accepted because:

- every classified `ContentUid` is batched exactly once;
- unresolved records stay outside normal translation batches;
- no batch mixes primary categories;
- the same inputs reproduce the same plan;
- structural context is preserved where evidence exists;
- broad registry/container grouping discovered in the first real run was eliminated;
- `ContentUid` remains the only durable translation identity;
- batch IDs remain execution-plan labels only.

LSTP-01B 驗收成立，因為：

- 每個已分類 `ContentUid` 都只進一個 batch；
- unresolved 資料不會混入正常翻譯批次；
- batch 不會混 category；
- 相同輸入可重現完全相同的分批結果；
- 有結構證據時會保留 context；
- 第一次真實測試發現的粗粒度 registry/container grouping 已消除；
- `ContentUid` 仍是唯一持久翻譯 identity；
- `batchId` 只代表這一次 production plan。

```text
LSTP-01B Category-Aware Batching = ACCEPTED
```

---

## Next step / 下一步

After this accepted batching milestone:

```text
LSTP-01A classification
↓
LSTP-01B batching implementation
↓
real-corpus batching measurement
↓
LSTP-01C translation execution/state tracking
```

Acceptance question / 驗收問題：

> Can BG3Loc put every classified `ContentUid` into exactly one repeatable, category-pure translation batch while keeping useful structural context together?  
> BG3Loc 能否把每個已分類 `ContentUid` 放進唯一、可重現、同分類的翻譯批次，同時盡量保留有用的結構上下文？

If yes / 若可以：

```text
LSTP-01B Category-Aware Batching = ACCEPTED
```
