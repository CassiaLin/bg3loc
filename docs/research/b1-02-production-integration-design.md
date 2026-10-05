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

## P1.6 Item MapKey Reliability Audit

2026-10-06；starting HEAD `b1b21139e886d85401a24540cacd5b82de837a69`，branch `feat/b1-02-same-entity-context`。開始前 fetch／checkout 後，HEAD 與 origin 相同且 working tree clean。

**Item MapKey Reliability = CONDITIONAL**。在本次安裝 snapshot 的 RootTemplates universe 中，直接位於 `GameObjects` definition 的非空 MapKey 是可驗證的原生 template key，不是 parser fallback。它不能單獨保證唯一完整 definition：4 個 key 有 competing fingerprints，其中 3 個為 native `Type=item`。建議只接受已驗證的 item boundary、直接 localization roles，並保留全部 definitions，由 whole-definition conflict gate 排除不一致 key；本輪不修改 P1 policy 或任何 runtime code。

### Structural source 與 identity precedence

追查 `ui_skill_universe._parse_xml` → `parse_structural_xml(kind="item")` → `xml_identity`。P1.5 的新 `entityIdentity`／`identityOrigin` 來自中央 structural parser；legacy `EntityName` 仍使用既有 traversal 邏輯，不能取代新 provenance。完整 definition boundary 是 `node id="GameObjects"`，取 boundary 自己的 element attributes 或**直接** `<attribute>` children，不從後代任意搜尋 identity。

實際的六個 RootTemplates archive resources 全為 LSF，使用公開 LSLib 轉換為 LSX 後，每個 boundary 都包含一個直接 `attribute id="MapKey" type="FixedString"`，其非空 `value` 與 exported `entityIdentity` 完全一致。25,564 個 definitions 都如此；沒有從檔名、Name、resource path、ordinal、相似文字或 nested reference 推導 MapKey。原始來源是 definition 本身的欄位，並非 parser 生成值；此檢查限於公開 LSF→LSX decoding 後的結構，不宣告已驗證 engine serializer 的所有版本。

固定 candidate precedence：`UUID` → `Guid` → `GUID` → `MapKey` → `Key` → `Name` → `entityId` → `EntityId` → `ID` → ordinal fallback。選取非空 `value`／`handle`；選中的同名 candidate 有多個不同值時標 `UNKNOWN`，不選 winner。

| Boundary 自己的欄位 | Presence | Nonempty identity candidate |
|---|---:|---:|
| MapKey | 25,564 | 25,564 |
| UUID | 114 | 0 |
| Guid / GUID | 0 | 0 |
| Key | 31 | 30 |
| Name | 25,564 | 25,564 |
| entityId / EntityId / ID | 0 | 0 |

114 個直接 UUID 欄位全部位於 native `Type=decal`，是空 `FixedString`，無非空 handle、無 child elements；不是漏讀藏在 UUID field 裡的 root identity。其餘 25,450 個 boundaries 沒有直接 UUID，包含全部 native items。全部 MapKey origin 的原因是本 corpus 的原生 root key 已 populated，而較高優先序的 UUID candidates 均不可用；不能說「整個 subtree 根本沒有 UUID」。

Subtree 另有 1,548 個 nested UUID：`Item` 142、`Script` 503、`tile` 903；還有 28,856 個 nested MapKey，owner nodes 是 `Object`、`Parameter`、`PickingPhysicsTemplates`。它們屬於各自子結構，沒有作為 enclosing GameObjects identity。直接 `guid`-typed fields 亦有 Race、Faction、AiHint、EquipmentRace 等 reference／property fields；GUID 形狀或 storage type 不足以升格成 template identity。

22,253 個非空 `ParentTemplateId` references 全部精確指向這個 universe 的原生 MapKeys，共涉及 3,041 個 target keys。這是 MapKey 扮演 template address、而非 display metadata 的獨立 structural evidence；沒有用 parent reference 把不同子 template 合併。

公開 [BG3SE template lookup implementation](https://github.com/Norbyte/bg3se/blob/main/BG3Extender/Lua/Libs/ClientTemplate.inl) 以 FixedString template ID 查詢 template bank；[GameObjectTemplate definitions](https://github.com/Norbyte/bg3se/blob/main/BG3Extender/GameDefinitions/RootTemplates.h) 區分 `Id`、`Name`、`ParentTemplateId`，並把 `InventoryItemData.UUID`／`TemplateID` 放在另一個 nested 結構。這些 primary implementation sources 支持 template identifier 與其他 UUID/reference 的角色區分；它們本身沒有證明 serialized MapKey 與 runtime `Id` 的所有版本映射。本 audit 的 native-key 判斷是根據實際 boundary、reference matching 與完整 definition grouping 所作的 structural inference，沒有依靠 GUID-like spelling。

### Corpus 範圍與 aggregates

本次 user-owned install 的 Steam build ID 是 `25605617`。重新使用 P1.5 public scan selection 加 public provider discovery 的 RootTemplates union，核對正好六個資源；由遊戲 archive 重新 extraction／conversion／parsing。fresh definition rows 與 occurrence rows 分別和 P1.5 最終輸出完全相同，沒有讀取舊 private research corpus。

**P1.5 表中的「item」其實是全部 exported `GameObjectTemplate`，不是 native `Type=item`。** 本輪保留該比較範圍，另從原始直接 `Type` field 計算真正 item subset，不修改既有 exporter schema 或 category policy。

| Native Type | Definitions | Localization occurrences |
|---|---:|---:|
| item | 9,331 | 11,553 |
| character | 2,464 | 1,051 |
| scenery | 10,252 | 987 |
| surface | 87 | 150 |
| other types | 3,430 | 0 |
| all GameObjects / P1.5 item bucket | 25,564 | 13,741 |

Definition counts 使用完整 exported definition/provenance rows；fresh physical boundary count 與此相同，沒有被 exact-row dedup 掩蓋的額外同資源 boundaries。Unique key 使用原始非空 MapKey 精確值，不以 sourceResource 分組來隱藏跨 resource 衝突。

| Aggregate | All GameObjects | Native Type=item |
|---|---:|---:|
| Definitions with native MapKey | 25,564 | 9,331 |
| Localization occurrences | 13,741 | 11,553 |
| Unique MapKeys | 25,560 | 9,328 |
| MapKeys used by >1 definition | 4 | 3 |
| Additional definition rows after first per key | 4 | 3 |
| Definition rows under repeated keys | 8 | 6 |
| Same key → exactly one distinct fingerprint | 25,556 | 9,325 |
| Repeated key → exactly one distinct fingerprint | 0 | 0 |
| Same key → >1 distinct fingerprint | 4 | 3 |
| Keys appearing across >1 sourceResource | 4 | 3 |
| Same-resource keys with >1 definition | 0 | 0 |
| MapKey-origin occurrences | 13,741 | 11,553 |
| UUID-origin occurrences | 0 | 0 |
| Name / fallback-origin occurrences | 0 | 0 |
| Occurrences under conflicting keys | 14 | 12 |

Fingerprint distribution：all GameObjects 有 25,556 keys × 1 fingerprint、4 keys × 2 fingerprints；native items 有 9,325 × 1、3 × 2。Definition-count distribution 完全相同；沒有 >2 fingerprints 或跨 resource 同 key 同 fingerprint 的重複 case。

「Duplicate MapKey occurrence」有兩種不同計數：definition 層額外 repeated-key rows 是上表的 4／3；localization 層中，一個 key 本來就能有多個欄位，不能當 collision。All GameObjects 有 9,654 keys 帶 localization、3,551 keys 帶 >1 localization occurrence，扣掉每個 key 的第一 occurrence 後剩 4,087；native items 對應 7,587、3,430、3,966。沒有 localization 的 keys 分別為 15,906／1,741，仍保留於完整 conflict universe。

### Cross-resource competing definitions

4 個 conflicting keys 全部各有兩個不同 sourceResource、兩個不同 fingerprints；native type 一致，分別是 3 item／1 character。Module-pair aggregates：Gustav↔Shared 2、Gustav↔GustavDev 1、Shared↔SharedDev 1。它們跨 module 的分布與 override／alternate definition 相容，但沒有足夠 public load-order／active-definition evidence 判定 winner，也不能排除錯誤 reuse／不同物件撞 key，因此不宣告已證明 patch 或同一 gameplay object。

全部四組的 native Name 與 Stats fields（含缺席狀態）相同；只有一組 ParentTemplateId 相同，只有兩組 DisplayName 相同，三組 Description 相同。全部 nested children projection 都不同。直接 changed-field aggregates 包含 `_OriginalFileVersion_` 4、ParentTemplateId 3、Icon 3、DisplayName 2、Description 1、TechnicalDescription 1，另有 gameplay／visual fields。差異不只是 provenance path 或 formatting；不能以「名稱相同」或「localization 看起來一致」豁免 whole-definition conflict。

本輪沒有套用 package/module priority、first/last winner 或縮減 fingerprint。即使將來能證明是 patch，同 key differing retained definitions 仍必須 fail closed，直到另一個經驗收的 public structural policy 能安全處理。

### Localization relation 與 role gate

獨立逐 XML element 檢查最近 enclosing `GameObjects` boundary，再核對 MapKey、sourceResource、whole-definition fingerprint、handle/version、field role 與 occurrence multiplicity。全部 13,741 occurrences 精確對上 public ledger；全部 storage type 為 `TranslatedString`。Nested identity 欄位不會覆寫 enclosing boundary binding。

| Field role | All GameObjects occurrences | Native item occurrences | Item placement |
|---|---:|---:|---|
| DisplayName | 9,450 | 7,436 | direct |
| Description | 3,445 | 3,375 | direct |
| DisplayNameAlchemy | 83 | 83 | direct |
| OnUseDescription | 222 | 222 | direct |
| TechnicalDescription | 145 | 145 | direct |
| ShortDescription | 3 | 3 | direct |
| UnknownDescription | 58 | 58 | direct |
| UnknownDisplayName | 21 | 21 | direct |
| GameMasterSpawnSubSection | 260 | 210 | nested |
| Title | 54 | 0 | character only |
| Tooltip | 0 | 0 | not observed |

同一 verified native item MapKey、同一完整 definition 的直接 DisplayName／Description 等表中 direct roles，可以視為同一 template 的相關 localization fields。這只證明結構歸屬，不宣告所有字串互相同義、同一 MapKey 等於同一 spawned instance，或任何 subtree handle 都適合作為 item prompt context。

`GameMasterSpawnSubSection` 位於該 definition 的 nested `GameMaster` node，雖有結構上的 subtree 歸屬，本 proposal 不把這個 category role 當 item text。排除此 role 後，native item direct localization occurrences 為 11,343，含 10 個落在 conflicting keys 的 occurrences；這些 conflicting keys 必須整組排除。其他類型的 DisplayName／Title 不因 exporter 使用 `kind="item"` 而變成 item evidence。

按 MapKey 合併 roles 的描述性分布（尚未排除 conflict）如下：all GameObjects 為 single-field 6,104／multi-field 3,550；native items 為 4,157／3,430；native item direct roles only 為 4,154／3,410（7,564 localized keys）。Same key 的 competing definitions 可能有不同欄位集合，上述 aggregate 不代表已通過 P1 的 production context coverage。

### Determinism、public reproduction 與版本限制

P1.5 兩次最終 run 的 definition ledger、occurrence ledger、summary 都逐 byte 相同；因此所有 definition 的 MapKey extraction 完全一致。本輪從安裝重新生成的全部 template rows 亦相同。這證明 deterministic extraction 及本 snapshot 的重建一致性，不能單獨證明跨 build stability 或 semantic identity。

MapKey 可完全由使用者自己的 BG3 install、公開 LSLib backend 與 repository public parser 重建；private artifact required = NO，publicly reconstructible = YES。先設定公開 backend，再以使用者自己的路徑執行：

```powershell
$env:PYTHONUTF8 = '1'
python -m bg3loc research scan --game-dir $gameDir --output $scanFile
python -m bg3loc research export-provenance --scan $scanFile --output-dir $firstOutput
python -m bg3loc research export-provenance --scan $scanFile --output-dir $secondOutput
```

可重現的 audit 計算：在 definition ledger 篩 `definitionType=GameObjectTemplate`，依原始 `entityIdentity` group，分別計算 row count、distinct `sourceResource` count、distinct `definitionFingerprint` count；occurrence ledger 用完整 identity/origin/resource/fingerprint binding join。Native Type／直接 field placement 目前不在 public JSONL row 中，需由同一 raw scan+discovery 選入的 archive resources，經 `ArchiveBackend.extract_single_file`／`convert_resource` 和 `parse_structural_xml` 重新核對；讀每個 GameObjects 的直接 MapKey／Type，保留完整 payload 作 fingerprint，逐 element 檢查最近 boundary。不能只靠現有 ledger 的 `definitionType` 宣告 native item，或依 field name 猜 direct placement。

Audit grouping 不需要英文 localized source text，也沒有使用文字相似度、LLM 判斷或 private retained research。完整 raw payload／identity lists／本機路徑及 one-off analysis outputs 留在 ignored workspace，沒有提交。公開 implementation links 於 audit 日期核對；不以網路文件的其他 corpus counts 代替本次實測。

**Cross-version stability = NOT VERIFIED**。本輪只有目前安裝 snapshot 與同內容的 P1.5 runs，沒有可重現的另一 historical build 作比較。MapKey 建議僅作 snapshot-scoped template identity；更新遊戲、mod 或選入 resource universe 後必須重建並重新驗證 definitions／provenance／fingerprints，不沿用跨 build identity cache 或 context。

### P1 item policy proposal（未實作）

建議將 reliable item identity 擴充為 existing explicit template UUID **或 verified native GameObjects MapKey + no structural conflict**。Verified MapKey 的條件：

1. 公開 raw source 證明它是 RootTemplates 中 enclosing GameObjects definition 的唯一非空直接 MapKey，並保留 native origin；不能將任何 GUID-like string 重新標成 UUID origin，不能接受 Name、fallback、nested MapKey 或 parent/reference IDs。
2. 以原始直接 `Type=item` 證明 item scope；同 key 的全部 retained GameObjects definitions 仍一起參與 conflict check，不能先過濾掉非 item 或無 localization definitions 來隱藏衝突。缺少 type proof 時不接納 item evidence。
3. 全部 retained definitions 的完整 fingerprints 必須一致且 provenance 完整；有不同 fingerprint、ambiguous native field／type 或不完整 definition universe 時整個 key 不提供 context。不發明 active winner，也不以相同 English text 或同 localization role set 消除衝突。
4. Localization occurrence 必須證明直接屬於該 item boundary，只接受本 audit 已驗證的 direct roles；nested category metadata 或未驗證 role 不因共用 key 自動獲准。Direct placement proof 不能只由目前 ledger 的 `fieldRole` 名稱推出。
5. Scope 是當前 source snapshot 的 template；保留 P1 其餘 English source join、conflict、budget、ordering 等 gates。新 identity kind／adapter 和 type/placement proof 的 public transport 仍是後續明確 policy adoption／integration 工作，不在本輪變更。

現行 P1 仍 UUID-only，production item same-entity context coverage 仍為 0。本 audit 提供可安全採用的 policy proposal，沒有建置 production adapter，沒有承諾實際 context coverage。P2 可恢復處理上述 policy adoption 與 public proof integration；在條件被實作及驗收前，MapKey item context 保持 disabled。

### Validation 與停止狀態

本輪 tracked change 只有本 audit 文件。無 runtime／schema／synthetic test change；未修改 production prepare、P1 contract、prompt/provider，未開始 P2、P3 或 B1-03。Full regression 在 Windows `PYTHONUTF8=1` 與 ignored workspace basetemp 下執行 `python -m pytest -q`：`642 passed, 75 subtests passed, 0 warnings`。

```text
Item MapKey Reliability = CONDITIONAL
B1-02 P1.6 = ACCEPTED
P2 Prepare Integration = READY TO RESUME
P1 item policy change = PROPOSAL ONLY / NOT IMPLEMENTED
Current production item context = DISABLED (UUID-origin coverage 0)
P3 = NOT STARTED
B1-03 = NOT STARTED
```

本節取代 P1.5 停止狀態中未處理 item identity policy 的解讀；READY TO RESUME 表示可以安全續做受上述條件約束的後續工作，不表示 policy 已放寬或 P2 已開始。本輪在 audit、aggregate、decision、proposal、docs 與 regression 完成後停止。
