"""Source-only adapter and measurements for B1-02 real corpus validation.

Inputs are existing research outputs, not a game installation or archive format.
No target localization file is read by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean, median

from bg3loc.research.context_experiment import (
    CATEGORIES, _usable, build_packs, canonical, read_rows, run,
)


def file_hash(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_universe(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("localeId") != "English":
                raise ValueError("source input must contain English rows only")
            uid = str(row.get("contentUid", ""))
            if not uid or uid in result:
                raise ValueError("source input has missing or duplicate ContentUid")
            result[uid] = str(row.get("text", ""))
    return result


def structural_occurrences(mappings: Path, ui_skill_universe: Path):
    """Yield (uid, category, identity, role, evidence, resource, status)."""
    with mappings.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.get("mappingType")
            if kind == "stat-reference":
                for evidence in row.get("evidence", []):
                    props = evidence.get("properties", {})
                    if evidence.get("evidenceType") != "StatsDefinition" or props.get("entryType") not in {
                        "SpellData", "PassiveData", "StatusData", "InterruptData",
                    }:
                        continue
                    yield (row["contentUid"], "skill_spell", props.get("entryName", ""),
                           props.get("fieldName", ""), "StatsDefinition", evidence.get("resourcePath", ""), "Eligible")
            elif kind == "quest-journal":
                for evidence in row.get("evidence", []):
                    props = evidence.get("properties", {})
                    if evidence.get("evidenceType") == "QuestJournal":
                        yield (row["contentUid"], "quest", props.get("entityId", ""),
                               props.get("fieldRole", ""), "QuestJournal", evidence.get("resourcePath", ""), "Eligible")
    with ui_skill_universe.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("Workstream") != "ItemsEquipment"
                    or row.get("EntityType") != "GameObjects"
                    or "Root Templates" not in row.get("SourceFamilies", "")):
                continue
            yield (row["ContentUid"], "item", row.get("EntityName", ""),
                   row.get("FieldName", ""), "GameObjectTemplate", row.get("Provider", ""), row.get("Status", ""))


def adapt(source: Path, mappings: Path, ui_skill_universe: Path):
    texts = source_universe(source)
    occurrences = defaultdict(list)
    for uid, category, identity, role, evidence, resource, status in structural_occurrences(mappings, ui_skill_universe):
        occurrences[(category, uid)].append((identity, role, evidence, resource, status))
    all_counts = Counter(category for category, _ in occurrences)
    uid_categories = defaultdict(set)
    for category, uid in occurrences:
        uid_categories[uid].add(category)
    records = []
    exclusions = Counter()
    for (category, uid), evidence_rows in sorted(occurrences.items()):
        if len(uid_categories[uid]) > 1:
            exclusions[(category, "structuralConflictRows")] += 1
            continue
        if any(status == "Hold" for *_, status in evidence_rows):
            exclusions[(category, "holdRows")] += 1
            continue
        accepted = [r for r in evidence_rows if r[4] == "Eligible"]
        if not accepted:
            exclusions[(category, "commentOnlyRows")] += 1
            continue
        identities = {(identity, role) for identity, role, _, _, _ in accepted}
        if (len(identities) != 1 or any(not identity or not role or "#" in identity for identity, role in identities)
                or (category == "item" and any(not resource for _, _, _, resource, _ in accepted))):
            exclusions[(category, "structuralConflictRows")] += 1
            continue
        text = texts.get(uid, "")
        if not _usable(text):
            exclusions[(category, "emptyOrNonlinguisticSource")] += 1
            continue
        identity, role = next(iter(identities))
        evidence_type = {"skill_spell": "StatsDefinition", "item": "GameObjectTemplate", "quest": "QuestJournal"}[category]
        identity_field = {"skill_spell": "entryName", "item": "templateId", "quest": "entityId"}[category]
        entity_type = {"skill_spell": "StatsEntry", "item": "GameObjectTemplate", "quest": "Quest"}[category]
        records.append({"contentUid": uid, "category": category, "entityKey": identity,
                        "entityType": entity_type, "fieldRole": role, "sourceText": text,
                        "structuralEvidence": {identity_field: identity, "evidenceType": evidence_type,
                                               "resourceIdentity": min(r[3] for r in accepted)}})
    return records, all_counts, exclusions


def percentile(values: list[int], fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * int(fraction * 100) + 99) // 100 - 1)]


def summarize(records, all_counts, exclusions, prompts):
    packs, coverage = build_packs(records)
    by_uid = {(p["target"]["category"], p["target"]["contentUid"]): p for p in packs}
    category_data = {}
    for category in CATEGORIES:
        rows = [r for r in records if r["category"] == category]
        group = [p for p in prompts if p["contextPack"]["target"]["category"] == category]
        entity_roles = defaultdict(set)
        role_counts = defaultdict(lambda: Counter())
        distribution = Counter()
        for row in rows:
            entity_roles[row["entityKey"]].add(row["contentUid"])
            pack = by_uid.get((category, row["contentUid"]))
            count = len(pack["relatedFields"]) if pack else 0
            distribution[str(min(count, 4)) + ("+" if count >= 4 else "")] += 1
            role_counts[row["fieldRole"]]["eligible"] += 1
            role_counts[row["fieldRole"]]["withContext"] += bool(pack)
        sizes = list(map(len, entity_roles.values()))
        deltas = [p["deltaChars"] for p in group]
        fields = [p["relatedFieldCount"] for p in group]
        category_data[category] = {
            "allCategoryRows": all_counts.get(category, 0), "eligibleRows": len(rows),
            "rowsWithContext": len([r for r in rows if (category, r["contentUid"]) in by_uid]),
            "rowsWithoutContext": len(rows) - len([r for r in rows if (category, r["contentUid"]) in by_uid]),
            "coveragePercent": coverage[category]["coveragePercent"],
            "exclusions": {name: count for (cat, name), count in sorted(exclusions.items()) if cat == category},
            "fieldRoles": {role: {**count, "coveragePercent": round(100 * count["withContext"] / count["eligible"], 2)}
                           for role, count in sorted(role_counts.items())},
            "entities": {"count": len(sizes), "singleField": sizes.count(1),
                         "multiField": sum(n > 1 for n in sizes), "maxFields": max(sizes, default=0),
                         "meanFields": mean(sizes) if sizes else None, "medianFields": median(sizes) if sizes else None,
                         "p95Fields": percentile(sizes, .95)},
            "relatedFieldDistribution": {key: distribution[key] for key in ("0", "1", "2", "3", "4+")},
            "sampleCount": len(group),
            "promptCost": {"meanDeltaChars": mean(deltas) if deltas else None,
                           "medianDeltaChars": median(deltas) if deltas else None,
                           "p95DeltaChars": percentile(deltas, .95), "maxDeltaChars": max(deltas, default=None),
                           "meanContextFields": mean(fields) if fields else None,
                           "medianContextFields": median(fields) if fields else None},
            "limits": {"maxRelatedFieldsHit": sum(p["relatedFieldCount"] == 4 for p in group),
                       "maxContextCharsHit": sum(p["contextChars"] == 4000 for p in group),
                       "singleFieldTruncation": sum(any(f["truncated"] for f in p["contextPack"]["relatedFields"]) for p in group)},
        }
    return category_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "mappings", "ui-skill-universe", "ruleset", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    records, all_counts, exclusions = adapt(args.source, args.mappings, args.ui_skill_universe)
    record_path = output / "real-context-records.jsonl"
    record_path.write_text("".join(canonical(row) + "\n" for row in records), encoding="utf-8")
    experiment = run(record_path, args.ruleset, output)
    prompt_path = output / "b1-02-prompts.jsonl"
    prompts = [json.loads(line) for line in prompt_path.read_text(encoding="utf-8").splitlines()]
    normalized = read_rows(record_path)
    identities = {(row["category"], row["contentUid"]): row["entityKey"] for row in normalized}
    english_text = {(row["category"], row["contentUid"]): row["sourceText"] for row in normalized}
    for prompt in prompts:
        pack = prompt["contextPack"]
        target = pack["target"]
        baseline_payload = json.loads(prompt["baselinePrompt"][1]["content"])
        context_payload = json.loads(prompt["contextPrompt"][1]["content"])
        if "relatedFields" in baseline_payload or len(context_payload.get("relatedFields", [])) != len(pack["relatedFields"]):
            raise ValueError("prompt variant boundary violation")
        if any(field["contentUid"] == target["contentUid"] or field["sourceText"].strip().casefold() == target["sourceText"].strip().casefold()
               for field in pack["relatedFields"]):
            raise ValueError("duplicate target in same-entity context")
        if any(identities.get((target["category"], field["contentUid"])) != target["entityKey"]
               for field in pack["relatedFields"]):
            raise ValueError("cross-entity context")
        if any((not english_text.get((target["category"], field["contentUid"]), "").startswith(field["sourceText"])
                if field["truncated"] else english_text.get((target["category"], field["contentUid"])) != field["sourceText"])
               for field in pack["relatedFields"]):
            raise ValueError("related field is not bound to English source")
        if any("translation" in field for field in pack["relatedFields"]):
            raise ValueError("target translation field in prompt context")
    summary = {"schemaVersion": "b1-02-real-corpus/1", "categories": summarize(read_rows(record_path), all_counts, exclusions, prompts),
               "promptSafety": {"targetTranslationLeakage": 0, "crossEntityContext": 0, "duplicateTargetInContext": 0},
               "tokenEstimate": "NOT MEASURED"}
    fingerprints = {"sourceCorpus": file_hash(args.source), "researchMappings": file_hash(args.mappings),
                    "uiSkillUniverse": file_hash(args.ui_skill_universe)}
    manifest = {"schemaVersion": "b1-02-real-experiment/1", "sourceLocale": "English", "targetLocale": "ChineseTraditional",
                "sourceCorpusFingerprint": fingerprints["sourceCorpus"],
                "structuralEvidenceFingerprints": {"researchMappings": fingerprints["researchMappings"],
                                                   "uiSkillUniverse": fingerprints["uiSkillUniverse"]},
                "categoryCounts": {c: summary["categories"][c]["eligibleRows"] for c in CATEGORIES},
                "selectionPolicy": experiment["selectionPolicy"], "maxRelatedFields": 4, "maxContextChars": 4000,
                "sampleFingerprint": experiment["sampleFingerprint"], "promptVariantHashes": experiment["promptVariantHashes"]}
    (output / "b1-02-real-experiment-manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    (output / "real-corpus-summary.json").write_text(canonical(summary) + "\n", encoding="utf-8")
    lines = ["# B1-02 Real-Corpus Phase 1", "", "| Category | All rows | Eligible | With context | Without | Coverage |", "|---|---:|---:|---:|---:|---:|"]
    for category, data in summary["categories"].items():
        lines.append(f"| {category} | {data['allCategoryRows']} | {data['eligibleRows']} | {data['rowsWithContext']} | {data['rowsWithoutContext']} | {data['coveragePercent']}% |")
    lines += ["", "## Field-role coverage", "", "| Category | Role | Eligible | With context | Coverage |", "|---|---|---:|---:|---:|"]
    for category, data in summary["categories"].items():
        for role, count in data["fieldRoles"].items():
            lines.append(f"| {category} | {role} | {count['eligible']} | {count['withContext']} | {count['coveragePercent']}% |")
    lines += ["", "## Entity and sample measurements", "", "| Category | Entities | Single | Multi | Mean fields | Median fields | Sample | Mean delta chars | Median | P95 | Max | Mean context fields | 4-field hits | 4000-char hits | Truncation |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def display(value):
        return f"{value:.2f}" if isinstance(value, float) else ("N/A" if value is None else str(value))
    for category, data in summary["categories"].items():
        entities, cost, limits = data["entities"], data["promptCost"], data["limits"]
        lines.append(f"| {category} | {entities['count']} | {entities['singleField']} | {entities['multiField']} | {display(entities['meanFields'])} | {display(entities['medianFields'])} | {data['sampleCount']} | {display(cost['meanDeltaChars'])} | {display(cost['medianDeltaChars'])} | {display(cost['p95DeltaChars'])} | {display(cost['maxDeltaChars'])} | {display(cost['meanContextFields'])} | {limits['maxRelatedFieldsHit']} | {limits['maxContextCharsHit']} | {limits['singleFieldTruncation']} |")
    lines += ["", "## Reproducibility and safety", "", f"Sample fingerprint: `{manifest['sampleFingerprint']}`", "",
              f"Variant A prompt hash: `{manifest['promptVariantHashes']['A']}`", "",
              f"Variant B prompt hash: `{manifest['promptVariantHashes']['B']}`", "",
              "No provider execution. Token estimate: NOT MEASURED. Target translation leakage, cross-entity context, and duplicate target-in-context: 0."]
    (output / "real-corpus-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(canonical(manifest))


if __name__ == "__main__":
    main()
