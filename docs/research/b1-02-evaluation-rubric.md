# B1-02 Human evaluation rubric / 人工評分規準

**Future pilot only / 僅供未來試驗。** No candidate translations have been evaluated. / 目前沒有評估任何譯文。

Reviewers see target source, category, field role, protected tokens, and two anonymized outputs: `Candidate1` and `Candidate2`. They may consult a reference translation separately; it never enters the model prompt. / 評審看目標原文、類別、欄位、保護 token 與匿名候選譯文；參考譯文只供評審，不進模型 prompt。

| Dimension / 維度 | 0 / 差 | 1 / 可接受 | 2 / 優 |
|---|---|---|---|
| Meaning accuracy / 語意準確 | Meaning wrong or omitted / 錯誤或遺漏 | Core meaning intact / 核心正確 | Fully faithful / 完整忠實 |
| Naturalness / 自然度 | Awkward or ungrammatical / 生硬錯誤 | Readable / 可讀 | Fluent in target locale / 自然流暢 |
| Terminology consistency / 術語一致 | Conflicts with fixed glossary / 違反固定詞彙 | Acceptable / 可接受 | Consistent and precise / 一致精準 |
| Entity-field consistency / 實體欄位一致 | Contradicts related fields / 與同實體欄位矛盾 | No conflict / 無矛盾 | Coherent across fields / 呼應清楚 |
| Context contamination / 脈絡污染 | Adds unrelated context facts / 加入目標原文未有資訊 | Ambiguous / 有疑慮 | No contamination / 無污染 |

Also record `contaminationFlag` YES/NO and a short reason. Contamination includes adding facts only present in related text, forcing a related-field word into the target, or translating structural metadata into prose. / 另記污染旗標與原因；污染包含加入只在相關欄位出現的資訊、硬塞相關詞、把結構資料譯進正文。

Future blind row / 未來盲評列:

```json
{"sampleId":"sha256-of-target","Candidate1":"...","Candidate2":"...","scores":{"Candidate1":{"meaning":0,"naturalness":0,"terminology":0,"entityField":0,"contamination":0},"Candidate2":{"meaning":0,"naturalness":0,"terminology":0,"entityField":0,"contamination":0}},"preferredCandidate":"tie","contaminationFlags":{"Candidate1":false,"Candidate2":false}}
```

A future exporter swaps A/B by the low bit of SHA-256(`sampleId`) and keeps the mapping hidden until scoring is frozen. Report B better, A better, tie, and contamination count by category and field-role pair. Include positive, negative, contaminated and no-effect examples. / 未來匯出器依 sampleId 雜湊最低位固定交換順序，評分鎖定前隱藏 A/B；按類別與欄位組合回報勝負、平手、污染及代表案例。
