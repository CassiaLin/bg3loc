"""B1-02 offline same-entity experiment. No provider calls or production hooks."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

from bg3loc.chat_prompt import render_chat_messages
from bg3loc.prompt_assembly import assemble_translation_prompt
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.ruleset_io import load_ruleset
from bg3loc.translation_request import TranslationRequest

CATEGORIES = ("skill_spell", "item", "quest")
PRIORITY = {
    "skill_spell": ("DisplayName", "Description", "ExtraDescription", "ShortDescription", "Tooltip"),
    "item": ("DisplayName", "Description", "Tooltip", "ShortDescription"),
    "quest": ("QuestTitle", "QuestDescription", "QuestField"),
}
SCHEMA_VERSION = "b1-02-context-pack/1"
SAFETY = (
    "The related fields are context only.",
    "Translate only the target source text.",
    "Do not add information that appears only in the context.",
    "Do not translate or return the context fields.",
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextSourceRecord:
    content_uid: str
    category: str
    entity_key: str
    entity_type: str
    field_role: str
    source_text: str
    evidence_type: str
    resource_identity: str = ""


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    """Allowlist source-side fields; fail closed on unproved entity identity."""
    uid = str(row.get("contentUid", ""))
    category = str(row.get("category", ""))
    role = str(row.get("fieldRole", ""))
    source = str(row.get("sourceText", ""))
    evidence = row.get("structuralEvidence")
    if category not in CATEGORIES or not uid or not role or not isinstance(evidence, dict):
        raise ValueError("row requires contentUid, supported category, fieldRole and structuralEvidence")
    identity_field = {"skill_spell": "entryName", "item": "templateId", "quest": "entityId"}[category]
    identity = str(evidence.get(identity_field, ""))
    evidence_type = str(evidence.get("evidenceType", ""))
    resource = str(evidence.get("resourceIdentity", ""))
    if not identity or not evidence_type or (category == "item" and not resource):
        raise ValueError(f"{category} needs structural {identity_field}, evidenceType and item resourceIdentity")
    if category == "skill_spell" and evidence_type != "StatsDefinition":
        raise ValueError("skill_spell requires StatsDefinition")
    if category == "quest" and evidence_type != "QuestJournal":
        raise ValueError("quest requires QuestJournal")
    if category == "quest" and "#" in identity:
        raise ValueError("quest requires explicit entityId, not a parser ordinal fallback")
    if category == "item" and evidence_type != "GameObjectTemplate":
        raise ValueError("item requires GameObjectTemplate")
    return {"contentUid": uid, "category": category, "entityKey": identity,
            "fieldRole": role, "sourceText": source,
            "structuralEvidence": {"entityType": {"skill_spell": "StatsEntry", "item": "GameObjectTemplate", "quest": "Quest"}[category],
                                   "entityKey": identity, "evidenceType": evidence_type,
                                   "resourceIdentity": resource}}


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(_clean(json.loads(line)))
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"input line {line_number}: {exc}") from exc
    return rows


def normalize_records(records: list[ContextSourceRecord]) -> list[dict[str, Any]]:
    """Adapter for future extractors that already hold source-side records in memory."""
    identity_field = {"skill_spell": "entryName", "item": "templateId", "quest": "entityId"}
    expected_type = {"skill_spell": "StatsEntry", "item": "GameObjectTemplate", "quest": "Quest"}
    if any(record.category not in expected_type or record.entity_type != expected_type[record.category]
           for record in records):
        raise ValueError("record category/entity_type mismatch")
    return [_clean({"contentUid": record.content_uid, "category": record.category,
                    "fieldRole": record.field_role, "sourceText": record.source_text,
                    "structuralEvidence": {identity_field[record.category]: record.entity_key,
                                           "evidenceType": record.evidence_type,
                                           "resourceIdentity": record.resource_identity}})
            for record in records]


def _usable(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and any(ch.isalpha() for ch in stripped)
                and not all(part in extract_protected_tokens(stripped) for part in stripped.split()))


def _rank(category: str, role: str) -> tuple[int, str]:
    priorities = PRIORITY[category]
    folded = role.casefold()
    matching = next((index for index, value in enumerate(priorities) if value.casefold() == folded), len(priorities))
    return (matching, folded)


def build_packs(rows: list[dict[str, Any]], max_fields: int = 4,
                max_chars: int = 4000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_fields < 1 or max_chars < 1:
        raise ValueError("context limits must be positive")
    unique = {canonical(row): row for row in rows}
    ordered = sorted(unique.values(), key=lambda r: (r["category"], r["entityKey"], r["fieldRole"], r["contentUid"], r["sourceText"]))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        groups[(row["category"], row["entityKey"])].append(row)
    packs = []
    eligible = Counter()
    covered = Counter()
    entities = defaultdict(set)
    for row in ordered:
        if not _usable(row["sourceText"]):
            continue
        category = row["category"]
        eligible[category] += 1
        candidates = []
        seen_text = {row["sourceText"].strip().casefold()}
        seen_uid = {row["contentUid"]}
        for other in sorted(groups[(category, row["entityKey"])],
                            key=lambda r: (_rank(category, r["fieldRole"]), r["contentUid"].casefold(), r["sourceText"])):
            normalized = other["sourceText"].strip().casefold()
            if (other["fieldRole"] == row["fieldRole"] or other["contentUid"] in seen_uid
                    or not _usable(other["sourceText"]) or normalized in seen_text):
                continue
            seen_uid.add(other["contentUid"])
            seen_text.add(normalized)
            candidates.append(other)
        if not candidates:
            continue
        covered[category] += 1
        entities[category].add(row["entityKey"])
        selected = []
        used_chars = 0
        for other in candidates:
            if len(selected) == max_fields:
                break
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            source = other["sourceText"][:remaining]
            if len(other["sourceText"]) > remaining and (selected or len(other["sourceText"]) <= max_chars):
                continue  # Only truncate an oversized field when it is the first selected field.
            selected.append({"contentUid": other["contentUid"], "fieldRole": other["fieldRole"],
                             "sourceText": source, "truncated": len(source) < len(other["sourceText"])})
            used_chars += len(source)
        if not selected:
            continue
        packs.append({"schemaVersion": SCHEMA_VERSION,
                      "target": {key: row[key] for key in ("contentUid", "category", "entityKey", "fieldRole", "sourceText")},
                      "relatedFields": selected, "structuralEvidence": row["structuralEvidence"]})
    coverage = {category: {"eligibleTargetRows": eligible[category], "rowsWithRelatedField": covered[category],
                           "coveragePercent": round(100 * covered[category] / eligible[category], 2) if eligible[category] else None,
                           "eligibleEntityCount": len(entities[category])} for category in CATEGORIES}
    return packs, coverage


def _stratum(pack: dict[str, Any]) -> str:
    target = pack["target"]
    role = target["fieldRole"].lower()
    size = len(target["sourceText"])
    kind = "name" if "name" in role or "title" in role else "instruction" if "tooltip" in role else "description"
    length = "short" if size < 80 else "medium" if size < 250 else "long"
    return f"{kind}:{length}"


def sample_packs(packs: list[dict[str, Any]], per_category: int = 100) -> list[dict[str, Any]]:
    """Round robin across observed strata, with stable hash ordering inside each."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pack in packs:
        buckets[(pack["target"]["category"], _stratum(pack))].append(pack)
    result = []
    for category in CATEGORIES:
        strata = sorted(k for k in buckets if k[0] == category)
        for key in strata:
            buckets[key].sort(key=lambda p: (digest(p["target"]), p["target"]["contentUid"]))
        while len([p for p in result if p["target"]["category"] == category]) < per_category:
            progressed = False
            for key in strata:
                if buckets[key] and len([p for p in result if p["target"]["category"] == category]) < per_category:
                    result.append(buckets[key].pop(0))
                    progressed = True
            if not progressed:
                break
    return result


def blind_candidate_order(sample_id: str, baseline: str, context: str) -> tuple[str, str]:
    """Future review export: hide A/B behind a stable sample-ID swap."""
    if not sample_id:
        raise ValueError("sample_id is required")
    swap = int(sha256(sample_id.encode("utf-8")).hexdigest(), 16) & 1
    return (context, baseline) if swap else (baseline, context)


def render_pair(pack: dict[str, Any], ruleset: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    target = pack["target"]
    request = TranslationRequest(target["contentUid"], "research", 1, "research", target["sourceText"],
                                 target["category"], "", (), tuple(extract_protected_tokens(target["sourceText"])))
    messages = render_chat_messages(assemble_translation_prompt(request, ruleset))
    baseline = [{"role": message.role, "content": message.content} for message in messages]
    baseline_payload = json.loads(baseline[1]["content"])
    baseline_payload["targetFieldRole"] = target["fieldRole"]
    baseline[1]["content"] = canonical(baseline_payload)
    context = [dict(message) for message in baseline]
    context[0]["content"] += "\n\n" + "\n".join(SAFETY)
    payload = json.loads(context[1]["content"])
    payload["entityType"] = pack["structuralEvidence"]["entityType"]
    payload["relatedFields"] = [{"fieldRole": field["fieldRole"], "sourceText": field["sourceText"],
                                 "truncated": field["truncated"]}
                                for field in pack["relatedFields"]]
    context[1]["content"] = canonical(payload)
    return baseline, context


def run(input_path: Path, ruleset_path: Path, output_dir: Path,
        per_category: int = 100, max_fields: int = 4, max_chars: int = 4000) -> dict[str, Any]:
    rows = read_rows(input_path)
    ruleset = load_ruleset(ruleset_path)
    packs, coverage = build_packs(rows, max_fields, max_chars)
    sample = sample_packs(packs, per_category)
    records = []
    for pack in sample:
        a, b = render_pair(pack, ruleset)
        a_chars = len(canonical(a))
        b_chars = len(canonical(b))
        records.append({"contextPack": pack, "contextPackFingerprint": digest(pack),
                        "baselinePrompt": a, "contextPrompt": b,
                        "baselinePromptHash": digest(a), "contextPromptHash": digest(b),
                        "baselinePromptChars": a_chars, "contextPromptChars": b_chars,
                        "deltaChars": b_chars - a_chars,
                        "contextChars": sum(len(f["sourceText"]) for f in pack["relatedFields"]),
                        "relatedFieldCount": len(pack["relatedFields"])})
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "b1-02-prompts.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(canonical(record) + "\n")
    counts = Counter(record["contextPack"]["target"]["category"] for record in records)
    by_category = {}
    for category in CATEGORIES:
        group = [r for r in records if r["contextPack"]["target"]["category"] == category]
        by_category[category] = {"sampleCount": len(group), "averageRelatedFields": mean(r["relatedFieldCount"] for r in group) if group else None,
                                 "averageBaselineChars": mean(r["baselinePromptChars"] for r in group) if group else None,
                                 "averageContextChars": mean(r["contextPromptChars"] for r in group) if group else None,
                                 "averageDeltaChars": mean(r["deltaChars"] for r in group) if group else None,
                                 "medianContextSourceChars": median(r["contextChars"] for r in group) if group else None,
                                 "relatedFieldDistribution": dict(sorted(Counter(r["relatedFieldCount"] for r in group).items())),
                                 "contextSourceCharDistribution": dict(sorted(Counter(r["contextChars"] for r in group).items()))}
    manifest = {"schemaVersion": "b1-02/1", "sourceCorpusFingerprint": digest(sorted(rows, key=canonical)),
                "sampleFingerprint": digest([r["contextPack"] for r in records]),
                "sampleCount": len(records), "categoryCounts": {c: counts[c] for c in CATEGORIES},
                "coverage": coverage, "categoryMetrics": by_category,
                "selectionPolicy": "stable canonical deduplication; observed kind:length strata round robin; SHA-256 target ordering",
                "maxRelatedFields": max_fields, "maxContextChars": max_chars,
                "contextLimits": {"maxRelatedFields": max_fields, "maxContextChars": max_chars,
                                  "overflow": "field priority, role, UID; skip a field that could fit whole later; truncate only a field longer than the total budget"},
                "rulesetFingerprint": ruleset.fingerprint(),
                "promptVariantHashes": {"A": digest([r["baselinePromptHash"] for r in records]),
                                        "B": digest([r["contextPromptHash"] for r in records])},
                "providerExecution": "not-run", "provider": None, "model": None}
    (output_dir / "b1-02-experiment-manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Local source-side JSONL, never committed")
    parser.add_argument("--ruleset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=100)
    parser.add_argument("--max-related-fields", type=int, default=4)
    parser.add_argument("--max-context-chars", type=int, default=4000)
    args = parser.parse_args()
    if args.per_category < 1:
        parser.error("--per-category must be positive")
    print(canonical(run(args.input, args.ruleset, args.output, args.per_category,
                        args.max_related_fields, args.max_context_chars)))


if __name__ == "__main__":
    main()
