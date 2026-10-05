# B1-02｜Same-Entity Context Production Integration Design

日期：2026-10-02。Audit baseline：`feat/b1-02-same-entity-context`，HEAD `a9e0c2b68f6e57f6c8cee71d632f112343941841`。

本文件是設計提案；沒有修改 runtime、CLI、schema 或 prompt。正式狀態沿用使用者提供的 Framework READY、Real-Corpus Validation ACCEPTED、Safety Validation PASSED。這些研究決策不等於 production integration 已實作或通過驗收。B1-03 Dialogue Context 保持 NOT STARTED。

## 1. Audit：目前 context 在哪裡

Repo 沒有 `src/bg3loc/production/` 目錄；實際 production 模組是 `production_*.py` 及 `commands/production.py`。

| 層 | 目前行為 | 整合意義 |
|---|---|---|
| `research/batching.py`：`build_batch_plan` | `canonicalGroupKey` 選排序後第一個 candidate；`contextGroupKeys` 保存所有 normalized candidates。material 只有 target source、空 translation、category、batch/group keys | 分批 metadata，不是可靠 same-entity textual context；不能從 key 推導 related fields |
| `commands/research.py`：`_load_research_grouping` | stats 使用 resource path + entryName；quest 支援 entityId 也支援 element ordinal fallback；其他 grouping 還有 story/UI/classification evidence | batching 的可接受分組範圍比 B1-02 prompt evidence 寬 |
| `research/context_experiment.py` | `_clean` 驗證三類 structural identity；`build_packs` 產生 bounded related fields；`render_pair` 在 baseline render 完後另行加 safety、targetFieldRole、entityType、relatedFields | context material 與 prompt 都仍是離線研究；沒有 production hook |
| `research/real_context.py` | join English source；排除跨類、Hold、非 Eligible、多 identity/role、缺 identity、ordinal、無原文；item 取 Root Templates/GameObjects occurrence | 可沿用已驗證 evidence adapter 原則，不能直接把研究 CLI 當 production execution dependency |
| `research/safety_validation.py` | 固定 pilot 的 10/10/5 子集，匯出 50 A/B requests，建立盲審並彙總 contamination/degradation | 研究安全驗證工具；不是 production runtime output validator，也不自行裁定 PASSED |
| `translation_request.py` | `BatchMaterialResolver` 只讀 prepared JSONL；request 帶 `context_group_keys`，沒有 field role 或 related source text | consumption 邊界已合適，缺 typed context contract |
| `prompt_assembly.py` | group keys 進 assembled prompt 與 effective prompt hash | 尚無 textual context 或 safety policy |
| `chat_prompt.py` | user JSON 含 ContentUid、primaryCategory、contextGroupKeys、sourceText | provider 目前看得到群組鍵，看不到 B1-02 related fields |
| `providers/openai_compatible.py` | 在 `__call__` assemble/render，HTTP 發送，再檢查空輸出與 target protected tokens | 已無遊戲資料掃描；保持這個限制。protected-token 檢查不能證明無 semantic contamination |
| `production_orchestration.py` | classify → batch/material → `run_init` seed state → manifest | context 應在 material 完成與 state 初始化之間固定 |
| `production_workspace.py` / `production_execution.py` | preflight 驗證 plan SHA、全部 material bytes、ruleset、DB inventory，再 start/worker | 可延伸既有 integrity boundary，不能只新增未受 hash 保護的 sidecar |
| `production_qa_orchestration.py` / `production_review.py` | QA、retry handoff、review acceptance 與目前 output 綁定 | context 改變導致重譯後，舊 review/QA 不可沿用 |
| `production_completion.py` / `production_finalize.py` | 以 target UID inventory、QA/review/output 狀態判斷完成與 rebuild | related field 不能增加 execution item 或 rebuild record |
| `production_reporting.py` | 使用 provider usage 與 execution accounting | context 成本納入 prompt usage；另加 coverage/reason 分布，不計成翻譯目標 |

補充 hash audit：`commands/translation_state.py::load_execution_items` 的 input hash 包含 target source、category、protected syntax、promptVersion、ruleset fingerprint、locales；不含 contextGroupKeys，也不含 B1-02 textual context。`effective_prompt_hash` 與 `chat_messages_fingerprint` 是不同層的 hash；目前 provider 沒有把它们作為 attempt provenance 持久化。

## 2. 決策：prepare materialize，execution consume

```text
既有 research structural evidence + normalized source snapshot
    → source-only evidence adapter / reliability validation
    → deterministic same-entity packs（完整 universe，不做研究 sampling）
    → production prepare 將 pack inline 寫入 batches/materials/<batchId>.jsonl
    → 驗證 material、計算 fingerprints、初始化 execution state、封存 manifest
    → BatchMaterialResolver → immutable TranslationRequest
    → prompt assembly → chat render → provider HTTP
```

建議新增 production-owned pure material builder（例如 `same_entity_context.py`），由 prepare orchestration 呼叫。共用已驗證 normalization/selection 規則應透過明確 library contract；不要依賴研究 CLI、pilot、A/B transport wrapper 或研究私有函式。研究 pack schema 與 production schema 分別版本化。

inline material 是主方案：不需 execution-time source join、跨 batch lookup 或額外 context sidecar 讀取。先在全 source universe 建 pack，再附加至 eligible target rows，因此 oversize split、batch 大小、worker ordering 不改變 related fields。相關 UID 只作 provenance，不能產生新 claim。保持既有 batching、canonicalGroupKey 及分類行為。

provider 可繼續 deterministic assemble/render；它不得讀 archive、game installation、mapping、source universe 或 context builder。execution 必須在原始 research/source 輸入不可用時仍可執行 prepared workspace；finalize 所需 extract artifact 是另外的既有流程。

## 3. Structural reliability contract

只允許 `skill_spell`、`item`、`quest`。dialogue（含目前 `dialogue_general`）、bark、book_lore、character_world、tutorial、system_message、ui 與其他類別都不供應 B1-02 context。禁止 semantic similarity、embedding、LLM linkage、filename-only/node-name grouping、stats `using` parent expansion。

| Category | 必要 structural identity | Evidence |
|---|---|---|
| skill_spell | stats entryName，保留適用來源 scope 與 provenance | StatsDefinition；沿用已驗證 entryType 範圍 |
| item | GameObjects 的 explicit template UUID/stable identity | GameObjectTemplate 與來源 provenance；一般 EntityName 不能當 identity |
| quest | journal explicit entityId | QuestJournal；拒絕 node ordinal/element fallback |

scope 不是新增 entity 關聯訊號。現有 `build_packs` 用 `(category, entityKey)` grouping；`real_context.adapt` 對重複來源取最小 resource 字串，並未解決同 key 在不同來源有衝突 definition 的版本選擇。production adapter 必須保留所有證據，確認同 identity 的定義一致或有已驗證 deterministic override resolution；無法確認時不供 context。不可自創來源 precedence、單凭相同 ID 合併衝突定義，或用 lexicographic resource winner 解衝突。

每個 target UID 必須與 production category/source snapshot 一致、能唯一解析 entity/field role；每個 related UID 亦須通過 reliability gate 並有相同 proven entity、source locale。多 entity、role ambiguity、category mismatch、Hold、缺 source、無可靠 identity，都不生成 context並記錄 reason。對損壞的輸入檔/非法 schema 則 prepare error。

缺可靠 context 是正常 absence，沿用 baseline；宣告 present 但 fingerprint、shape、target binding 或 category 不合法是 material error，不能默默降級。

## 4. Proposed material 與 request

在現有 material row 新增 optional `sameEntityContext`，absent row 不新增 prompt 欄位。下列只是 proposed shape，不是目前可執行 schema：

```json
{
  "sameEntityContext": {
    "schemaVersion": "same-entity-context/1",
    "policyVersion": "b1-02-structural/1",
    "targetBinding": {
      "contentUid": "<target UID>",
      "category": "skill_spell",
      "sourceTextSha256": "<hash of exact target source>"
    },
    "targetFieldRole": "DisplayName",
    "entityType": "StatsEntry",
    "entityIdentity": "<proven scoped identity>",
    "evidenceFingerprint": "<canonical complete evidence digest>",
    "relatedFields": [
      {
        "contentUid": "<related UID>",
        "fieldRole": "Description",
        "sourceText": "<source-only text>",
        "truncated": false
      }
    ],
    "contextFingerprint": "<canonical digest excluding this field>"
  }
}
```

保留 source corpus hash、所有 structural input hashes、adapter/builder versions、limits 與 source locale 在 production manifest。raw absolute paths、target/reference translations、provider outputs 與任意 evidence properties 都不可投影到 prompt。material provenance 可用相對資源識別與 digest。

`TranslationRequest` 建議加 default `same_entity_context: SameEntityContext | None = None`，以 frozen dataclasses、tuple related fields 表示。resolver 只解析/驗證，不生成或補齊 context。只有 related source text 供 interpretation；source_text 始終是唯一翻譯目標，protected_tokens 始終只由 target 計算。

selection 沿用 B1-02：最多 4 fields / 4000 source characters；依 category field priority、role、UID、source deterministic ordering；排除 target UID、同 target role、重複 source text、空或純 runtime token fields。保留既有 overflow/truncation 規則：僅第一個大於總 budget 的 field 可截斷，其餘按既有規則 skip，並保留 truncated flag。這是字元限制，不能宣稱是 token budget。新增限制或排序必須 bump policy version。

## 5. Prompt contract

assembly 僅將 present、validated typed context 投影到 assembled prompt；chat render 沿用研究 variant B 的 `targetFieldRole`、`entityType`、`relatedFields[{fieldRole,sourceText,truncated}]`。完整 identity、related UID、resource provenance 不送 LLM。保持 baseline `contextGroupKeys` 原狀，並在 context policy 中明確說明它們不是 same-entity proof。

present context 時 system 加入已驗證的四條安全指令：

```text
The related fields are context only.
Translate only the target source text.
Do not add information that appears only in the context.
Do not translate or return the context fields.
```

並明確以 sourceText 為唯一輸出目標；related source 是資料，不能充當指令。安全規則不能由可變 ruleset 覆寫。輸出仍只有 target translated text，不新增 context response schema。沒有 context 時 chat messages 及 legacy hashes 必須逐 byte 符合原 baseline；不加入空 relatedFields、null context、field-role 標籤或 context-only safety 段。

## 6. Versioning、hash、resume 與 integrity

未來 implementation 必須同時完成下列 binding 才能啟用：

1. material fingerprint 繼續覆蓋全部 inline bytes；新 production manifest schema 明確宣告 context policy、artifact version、builder settings 與完整 input digests。context-enabled plan identity 必須包含 context input/policy/material digest，不能只沿用舊 batching fingerprint。
2. context-present item 的 `input_hash` 加入 canonical effective context projection、context policy/prompt renderer version（或其受驗證 digest）。context 改變即不同輸入。absent legacy 模式沿用原公式，不能無意重置既有 workspace。
3. `effective_prompt_hash` 納入真正使用的 context 與 safety instructions；render 後 messages hash另記錄 actual chat bytes。兩者不宣稱相同，attempt provenance 應同時記錄 input、context、effective prompt、messages hashes。
4. execution config hash 綁 context/prompt policy，使 start 與 worker 不可使用不同 policy；version 的來源只能是封存 workspace contract，不能 execute-time 開關。
5. preflight 驗證新 schema、context fingerprints、target/category/source binding、limits 與 inventory一致性；resolver 做局部 shape/binding檢查。篡改 present pack 在 HTTP 前失敗。
6. context變更以 fresh prepare workspace 為預設；不得在執行中修改 material，或把現有成功 state 當新輸入復用。若日後提供 migration，需重算 items、清除 affected outputs、QA/review acceptance 並重驗 inventory；本輪不設計自動 migration。

舊 manifest schemas `1.0`/`1.1` 目前仍只有 baseline；未來支援新 schema時必須保留其原有行為，並拒絕在 legacy manifest 偷塞 context。新版 workspace 的 none/present 狀態須明確可稽核，absence reason 放 prepare coverage report，不送 provider。

## 7. Implementation sequencing 與驗收

本輪交付止於本設計；不改 runtime、不初始化 DB、不產生 provider requests。後續 implementation 建議依序完成：production-owned builder/contract → prepare inline material + schema/integrity → resolver typed context → shared assembly/render + hash/provenance → fixture與mock provider integration驗收 → 才評估啟用新的 production prepare policy。

必要驗收案例：

- 三類可靠 identity 各有 target-only prompt、同 entity related fields、四條安全規則；provider只接收 prepared text。
- 多 identity、definition conflict、generic item node、quest ordinal、stats parent、分類不符、缺 source、Hold、單欄 entity：無 context，baseline messages/hash 不變，理由可追蹤。
- unsupported categories 不得到 context；偽造 present material 在 provider 前失敗。
- 輸入重排、重複 evidence、batch size/split、worker/retry 順序不改 context；同 source/policy repeated prepare 結果一致。
- context source、role、truncation、policy改變會改 input/prompt hashes；material篡改失敗；baseline none 不重置原 input identity。
- prepare後移走 research與原始 source，mock execution仍成功，且不讀遊戲/archive；確認 absence與 corrupt material 分流。
- related field的 runtime tokens 不成為 target保護要求；输出 validation 只針對 target。不能把 token檢查宣稱為 contamination語意驗證。
- related fields不增加 claim、completion count、merge/rebuild records；新 output使舊 QA/review 不再成立。
- 使用已接受 safety fixture檢查 prompt parity；新增 instruction/data boundary與 adversarial source fixture。任何新增實際 provider安全評估需另行記錄，不能把25對pilot當成所有production輸出的保證。

待 implementation review確認的只有工程細節：新schema/version名稱、typed classes位置、hash欄位儲存方式與受驗證的source override contract。核心 materialize層、category allowlist、source-only/read-only policy、absence fallback與禁止execution-time scan已在本設計固定。

## Implementation P1 status

```text
P1 production-owned context contract = implemented
P2 prepare integration = not started
```

## P1.5 public provenance prerequisite

2026-10-05；起始 HEAD `7859bdc2955db37a0774fc390d9adda1fca7998e`。
本節只補 public structural evidence；P1 semantics 不變，P2 prepare、P3、B1-03 均未開始。

### Audit 與 exporter boundary

- `research/stats.py` 原本讀到 localization line 即 yield，entry 後面的 `using`、非 localization data 與完整 definition 尚未保存。現在先完成整個 entry，再附相同 definition digest 到所有 occurrences。
- `research/ui_skill_universe.py::_parse_xml` 原本在 node/direct attributes 選取 UUID、MapKey、Name 或 ordinal 後，只保留值為 `EntityName`。現在另存 `EntityIdentity`／`IdentityOrigin`，完整 GameObjects definition 包含其 nested nodes，nested field 不覆蓋 template identity。
- `research/quest.py` 原本 `enclosing_entity_id` 把 direct native fields 與 generated ordinal 合併為同一個 `entityId` string。現在 explicit `ENTITY_ID`、`FALLBACK_ORDINAL`、無 node 的 `FALLBACK_NODE` 各自可辨。
- `research/context.py` 的 passive evidence 現在附完整 stats provenance；quest candidate filter 與 aggregator 保存每一筆 evidence，consumer 必須逐 evidence 讀取，不能把 aggregate metadata 當唯一 definition。
- `commands/research.py::run_research_map_request` 與既有 UI inheritance／precedence materialization 有 winner/selection semantics。因此新增獨立 `research export-provenance`，直接讀 raw public scan entries，加上 public UI/template provider discovery，不使用 legacy map 的 overlay winners、research retained artifacts 或 provider priority。既有 map/classify/batch 行為保留。

### Public workflow 與 schema

```powershell
python -m bg3loc research scan --game-dir <your-BG3-install> --output <scan.json>
python -m bg3loc research export-provenance --scan <scan.json> --output-dir <output-dir>
```

使用現有 public archive backend；需要使用者自己的 BG3 install，不需要 private retained artifact、manual lookup table 或 hardcoded real identities。
exporter 對選入的 archive extraction、conversion、UTF-8 decoding 與 XML parsing fail closed，不以跳過壞檔宣告成功。支援 stats TXT 與 journal/template LSX、XML、LSF/LSB→LSX；遇到 unsupported selected format 會報錯。

輸出：

| Artifact | Contract |
|---|---|
| `structural-definitions.jsonl` | 每個完整 definition 一筆；包含沒有 localization occurrence 的 definitions |
| `structural-occurrences.jsonl` | `contentUid`、`fieldName`、`fieldRole`、handle version、`occurrenceIndex` 及完整 definition provenance；不含 localized source text |
| `structural-provenance-summary.json` | definition/occurrence origin counts、多 definition identities、distinct fingerprints；不含真實 identity lists |

新 JSONL schema 為 `public-structural-provenance/1`，projection 為 `structural-definition/1`；machine-readable schemas 是 `public-structural-definition-v1.schema.json` 與 `public-structural-occurrence-v1.schema.json`。
每筆都有 `entityIdentity`、`identityOrigin`、`sourceKind`、`sourceResource`、`definitionType`、`definitionFingerprint`、`definitionProjectionVersion`。stats 另有 `entryName`、`entryType`、`using`；entryName 始終是 identity，using 不變成 identity。

Origin contract：`UUID`、`MAP_KEY`、`NAME`、`ENTRY_NAME`、`ENTITY_ID`、`FALLBACK_ORDINAL`、`FALLBACK_NODE`、`UNKNOWN`。
XML 選取明確固定 native field 優先序：UUID/Guid/GUID、MapKey/Key、Name、entityId/EntityId/ID；不同 native keys 全部仍參與 digest。同一 native key 有不同 values 時標 `UNKNOWN`，不選 lowest UUID 或其中一值。
quest 的 native fields 宣告 `ENTITY_ID`；generated fallback 不會因為字串像 UUID 而提升 origin。

既有 research mapping schema 的 evidence properties／metadata 是 extensible object，新 provenance 欄位 additive；`ui-skill-universe.csv` 尾端新增 `EntityIdentity`、`IdentityOrigin`、`DefinitionFingerprint`、`SourceKind`、`SourceResource`，舊欄位與 consumer 讀取方式保留。legacy inherited/comment/raw rows 無完整 direct structural definition 時保留 `UNKNOWN`／空 digest，不偽造證據。P2 應讀取新 raw structural ledgers 作完整 definition universe，而非把 inheritance materialization 當 structural proof。

### Definition fingerprint 與 multi-definition retention

| 類別 | Definition boundary | Canonical projection |
|---|---|---|
| skill_spell/stats | 一個 `new entry`，直到下一 entry 或 EOF | definition type、entryName、全部 type/using directives、全部 data fields（含非 localization fields）、未識別 structural statements |
| item | 一個 `node id="GameObjects"` template | node type、全部 native identity fields、全部 attributes（含 type/value/handle/version/reference）、完整 nested node subtree |
| quest | 一個 journal node；無 node 時為 document fallback | 完整 node subtree、所有 native identity/structural/localization/reference fields；occurrence 關聯最近的 enclosing node |

`SHA-256(UTF-8(canonical JSON))`：object keys 排序、compact separators、Unicode 保留、禁止 NaN；XML attribute field names 排序，stats 不同 field names 排序；同名重複 assignments/attributes 與有序 structural children 保留原始 semantic sequence。實際 semantic child sequence 改變會改 digest，不把有序 list 誤當無序集合。indentation、comments、行號、definition ordinal、resource/provider 路徑、timestamp、parser memory/state 不進 digest。未識別 stats statements 保守參與 digest，不默默丟掉可能的 structural fields。

`sourceResource` 是 normalized relative `<package>/<archive internal path>`；拒絕 absolute、parent traversal、control characters。兩個 install locations 的同 payload 有相同 digest；來源位置保存在 provenance，與 digest 分離。

全部 definitions 先保留，再依完整 serialized row dedup；等價於 identity + origin + fingerprint + source provenance，occurrence 再包含 UID/role/version/index。同 definition 內相同 UID/field/version 的重複 physical occurrences 以 binding-local index 保留；index 是 multiplicity/location metadata，不是 entity identity，也不參與 definition digest。相同 identity 的不同 fingerprints 與不同 source resources 都保留；沒有 first/last/path/UUID/resource-priority winner。JSONL rows 依 canonical serialized row 排序，summary keys 排序；input resource traversal／duplicate order 不改 intended output bytes。

consumer 可從同 identity 的全部 definition rows 判斷 fingerprints 是否一致；summary 的「distinct fingerprints」只表示 competing definition evidence，不宣告 override winner 或已驗證 production conflict。不同種類的 stats entries 都輸出，`entryType` 供 consumer 沿用既有 skill entry type gate；origin 本身不是 production eligibility。

### P1 compatibility 與驗收

`tests/test_public_structural_provenance.py` 只用 fictional fixtures，從 exported public occurrence rows 加 synthetic English source join，構造 `SameEntitySourceRecord`。三類可靠來源：ENTRY_NAME→stats-entry-name、item UUID→template-uuid、quest ENTITY_ID→journal-entity-id；完整 row digest 作 evidence fingerprint、whole-definition digest 作 definition fingerprint、relative source 作 evidence source。三類均可建立 P1 context，新增 differing definition 後均由 P1 判為 `STRUCTURAL_CONFLICT`。
item Name/MapKey、quest ordinal 仍被 P1 reliability gate 拒絕；未新增 production adapter/hook，也未放寬 P1。測試包含 full-definition semantic changes、field/key ordering、來源位置變更、duplicate exact definitions、multiple resources、無 localization fields definitions、nested boundaries、origin export、schemas、byte determinism、public CLI archive layers 與 static path safety。

最終 synthetic targeted：新 provenance suite `39 passed`；full regression：`642 passed, 75 subtests passed, 0 warnings`。Windows 設定 `PYTHONUTF8=1`，pytest basetemp 留在 ignored `workspace/` 後執行 `python -m pytest -q`；預設 CP950 下兩個既有 portable translation tests 讀取 UTF-8 會失敗，未修改它們或 production code。

### Real-corpus aggregate validation

從本機使用者 BG3 install 重新跑 public scan（41,502 discovered resources），再使用最終 exporter 獨立跑兩次；全部 artifacts 留在 ignored workspace。三個輸出檔案逐 byte 相同。全部 49,860 definition rows 與 32,660 occurrence rows 通過新版 schema、origin populated、64-hex fingerprint、relative/non-private sourceResource 以及 occurrence→definition 關聯檢查；沒有 real rows/text/identity lists 放進本文件或 commit。

| 類別／origin | Definitions | Occurrences |
|---|---:|---:|
| skill_spell / ENTRY_NAME | 11,721 | 13,449 |
| other stats / ENTRY_NAME | 4,872 | 0 |
| item / UUID | 0 | 0 |
| item / MAP_KEY | 25,564 | 13,741 |
| item / NAME | 0 | 0 |
| item / fallback | 0 | 0 |
| quest / ENTITY_ID | 4,306 | 4,125 |
| quest / FALLBACK_ORDINAL | 3,397 | 1,345 |

skill_spell aggregate 依既有 entry types `SpellData`、`PassiveData`、`StatusData`、`InterruptData` 計算；exporter 仍保留全部 stats，沒有按此 gate 篩掉 definitions。item 的真實 occurrences 全部 MapKey-derived；即使值呈 UUID 字串形狀，也不宣告 UUID origin。沿用 P1 的 UUID gate 時，此 corpus 的 UUID-origin item coverage 為 0；本輪不放寬 policy。

| Identity aggregate | >1 definition/provenance | >1 distinct fingerprint |
|---|---:|---:|
| skill_spell | 273 | 256 |
| other stats | 181 | 177 |
| all StatsEntry | 454 | 433 |
| item | 4 | 4 |
| quest（全部 exported identity strings，含 fallback） | 468 | 460 |
| quest（native ENTITY_ID only） | 436 | 431 |

fallback 字串的跨 resource 重複不表示已證明同一 production entity；上表只報 raw competing-definition evidence。沒有為降低數字調整 digest、套用 source priority 或選 winner。

Git safety audit：real corpus/text、mass ContentUid、mass UUID/entity list、private absolute path、workspace、secret 均未 commit。變更只有 research parser/exporter、public schemas、fictional tests 與本節；production prepare、TranslationRequest、prompt/provider、DB/hash/resume、P1 semantics 均未修改。

```text
B1-02 Production Integration P1.5 = ACCEPTED
P2 Prepare Integration = READY TO RESUME
P3 = NOT STARTED
B1-03 = NOT STARTED
```

兩個 public provenance blockers 已解除；P2 尚未實作，停在 P1.5 exporter prerequisite。production adapter 後續必須保留完整 definition universe（含沒有 localization occurrence 的 definitions），沿用既有 reliability/conflict gates。
