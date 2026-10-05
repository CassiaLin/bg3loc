from __future__ import annotations

from dataclasses import dataclass
import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bg3loc.backends import backend_from_probe, resolve_backend
from bg3loc.research import (
    ResearchMapping,
    ResearchEvidence,
    ResearchScanResource,
    classify_functional_ownership,
    summarize_functional_classification,
    BatchInputRecord,
    BATCHING_RULE_VERSION,
    DEFAULT_MAX_RECORDS,
    batch_plan_fingerprint,
    build_batch_plan,
    normalize_dialog_resource,
    parse_bark_container,
    parse_quest_xml,
    filter_quest_context_candidates,
    parse_stats_text,
    parse_ui_skill_xml,
    traverse_dialog_json,
)
from bg3loc.research.conflict import derive_reuse_conflict_groups
from bg3loc.research.context import (
    ContextAggregator,
    extract_passive_context_hits,
    extract_shared_context_hits,
)
from bg3loc.research.ui_skill_aq import (
    accepted_context_coverage,
    derive_aq_boundary,
    derive_aq_resource_referenced,
    derive_reuse_conflict_boundary,
)
from bg3loc.research.ui_skill_runtime_reconcile import reconcile_ui_skill_runtime
from bg3loc.research.classification_resolution import resolve_unclassified
from bg3loc.research.ui_skill_universe import (
    UiSkillProviderRole,
    classify_workstream,
    extract_ui_skill_universe,
    write_ui_skill_universe,
    write_ui_skill_provider_ledger,
)
from bg3loc.research.multilingual import align_multilingual_references
from bg3loc.research.output import (
    write_mappings_jsonl,
    write_research_summary,
    write_scan_manifest,
)
from bg3loc.research.overlay import OverlayCandidate, resolve_overlay_precedence
from bg3loc.research.cross_domain_universe import (
    CrossDomainExtractionContext,
    CrossDomainUniverseCache,
    extract_cross_domain_result,
    extract_cross_domain_target_universe,
    get_cross_domain_universe_uids,
)
from bg3loc.research.scanner import scan_game_research_resources
from bg3loc.research.story import (
    StoryOccurrence,
    classify_story_domain,
    derive_cross_domain_references,
    partition_story_universe,
    read_story_occurrence_ledger,
    resolve_residual_story_holds,
    write_oldtext_evidence,
    write_story_occurrence_ledger,
)
from bg3loc.steam import read_app_manifest_for_game_dir, resolve_bg3_install



@dataclass(frozen=True, slots=True)
class ResearchScanRequest:
    game_dir: Path | None
    output: Path
    source: str
    target: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchMapRequest:
    scan: Path
    output_dir: Path
    source: str
    target: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchClassifyRequest:
    extract_manifest: Path
    research_mappings: Path
    output_dir: Path
    story_ledger: Path | None = None
    ui_skill_universe: Path | None = None


@dataclass(frozen=True, slots=True)
class ResearchBatchRequest:
    classification: Path
    source: Path
    output_dir: Path
    story_ledger: Path | None = None
    ui_skill_universe: Path | None = None
    research_mappings: Path | None = None
    max_records: tuple[str, ...] = ()


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    research_parser = subparsers.add_parser(
        "research",
        help="Generate game-derived mappings and classify translation rows",
    )
    research_subparsers = research_parser.add_subparsers(dest="research_command", required=True)

    # bg3loc research scan
    scan_p = research_subparsers.add_parser("scan", help="Scan game installation for research resources")
    scan_p.add_argument("--game-dir", help="Path to BG3 installation directory")
    scan_p.add_argument("--output", default="research-scan-manifest.json", help="Path to output manifest")
    scan_p.add_argument("--source", default="English", help="Source locale")
    scan_p.add_argument("--target", default="ChineseTraditional", help="Target locale")
    scan_p.add_argument("--reference", action="append", default=[], help="Reference locales")
    scan_p.set_defaults(handler=run_research_scan)

    # bg3loc research map
    map_p = research_subparsers.add_parser("map", help="Generate deterministic research mappings")
    map_p.add_argument("--scan", default="research-scan-manifest.json", help="Path to research scan manifest")
    map_p.add_argument("--output-dir", default=".", help="Path to output directory")
    map_p.add_argument("--source", default="English", help="Source locale")
    map_p.add_argument("--target", default="ChineseTraditional", help="Target locale")
    map_p.add_argument("--reference", action="append", default=[], help="Reference locales")
    map_p.set_defaults(handler=run_research_map)

    provenance_p = research_subparsers.add_parser(
        "export-provenance", help="Export all structural definitions without winner selection",
    )
    provenance_p.add_argument("--scan", required=True, help="Public research scan manifest")
    provenance_p.add_argument("--output-dir", required=True, help="Structural provenance output directory")
    provenance_p.set_defaults(handler=run_research_provenance_export)

    # bg3loc research classify
    classify_p = research_subparsers.add_parser(
        "classify",
        help="Classify localization ContentUids into large-scale translation production lanes",
    )
    classify_p.add_argument(
        "--extract-manifest",
        default="workspace/extract/extract-manifest.json",
        help="Path to extract-manifest.json providing the complete source ContentUid universe",
    )
    classify_p.add_argument(
        "--research-mappings",
        default="research-output/research-mappings.jsonl",
        help="Path to deterministic research mappings JSONL",
    )
    classify_p.add_argument(
        "--story-ledger",
        help="Optional story-occurrence-ledger.csv; defaults to sibling of research mappings when present",
    )
    classify_p.add_argument(
        "--ui-skill-universe",
        help="Optional ui-skill-universe.csv; defaults to sibling of research mappings when present",
    )
    classify_p.add_argument(
        "--output-dir",
        default="classification-output",
        help="Directory for functional classification ledger and summary",
    )
    classify_p.set_defaults(handler=run_research_classify)

    # bg3loc research resolve-unclassified
    resolve_p = research_subparsers.add_parser(
        "resolve-unclassified",
        help="Apply auditable operator decisions to unresolved classification rows",
    )
    resolve_p.add_argument(
        "--classification",
        required=True,
        help="Path to original functional-classification.jsonl",
    )
    resolve_p.add_argument(
        "--decisions",
        required=True,
        help="Path to unclassified decision JSONL",
    )
    resolve_p.add_argument(
        "--output",
        required=True,
        help="Path to resolved classification JSONL",
    )
    resolve_p.set_defaults(handler=run_research_resolve_unclassified)

    # bg3loc research batch
    batch_p = research_subparsers.add_parser(
        "batch",
        help="Create deterministic category-aware translation batches",
    )
    batch_p.add_argument(
        "--classification",
        required=True,
        help="Path to functional-classification.jsonl",
    )
    batch_p.add_argument(
        "--source",
        required=True,
        help="Path to normalized source localization JSONL",
    )
    batch_p.add_argument(
        "--story-ledger",
        help="Optional story-occurrence-ledger.csv for structural grouping",
    )
    batch_p.add_argument(
        "--ui-skill-universe",
        help="Optional ui-skill-universe.csv for structural grouping",
    )
    batch_p.add_argument(
        "--research-mappings",
        help="Optional research-mappings.jsonl for finer quest/stat grouping",
    )
    batch_p.add_argument(
        "--max-records",
        action="append",
        default=[],
        metavar="CATEGORY=N",
        help="Override a category batch size; repeatable",
    )
    batch_p.add_argument(
        "--output-dir",
        default="batch-output",
        help="Directory for batch plan, materials, unresolved queue, and summary",
    )
    batch_p.set_defaults(handler=run_research_batch)


def discover_game_version(game_dir: Path) -> str | None:
    """Discover executable file version from bin/bg3.exe or bin/bg3_dx11.exe."""
    exe = game_dir / "bin" / "bg3.exe"
    if not exe.is_file():
        exe = game_dir / "bin" / "bg3_dx11.exe"
    if exe.is_file() and os.name == "nt":
        try:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Item -LiteralPath '{exe}').VersionInfo.ProductVersion"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            val = res.stdout.strip()
            if val:
                return val
        except Exception:
            pass
    return None


def resolve_runtime_metadata(game_dir_path: Path) -> dict[str, Any]:
    """Resolve live runtime metadata (appId, buildId, gameVersion) from game install."""
    steam_manifest = read_app_manifest_for_game_dir(game_dir_path)
    app_id = steam_manifest.get("appid", "1086940") if steam_manifest else "1086940"
    build_id = steam_manifest.get("buildid", "local") if steam_manifest else "local"
    game_version = discover_game_version(game_dir_path) or "unknown"
    return {
        "appId": app_id,
        "buildId": build_id,
        "gameVersion": game_version,
    }


def run_research_scan(args: argparse.Namespace) -> int:
    return run_research_scan_request(ResearchScanRequest(
        game_dir=Path(args.game_dir) if args.game_dir else None,
        output=Path(args.output),
        source=str(args.source),
        target=str(args.target),
        references=tuple(args.reference),
    ))


def run_research_scan_request(request: ResearchScanRequest) -> int:
    game_dir = str(request.game_dir) if request.game_dir is not None else None
    if not game_dir:
        detected = None
        from bg3loc.steam import default_steam_roots, discover_library_roots
        for sroot in default_steam_roots():
            for lroot in discover_library_roots(sroot):
                detected = resolve_bg3_install(lroot)
                if detected:
                    break
            if detected:
                break

        if detected:
            game_dir = str(detected[0])
        else:
            print("[ERROR] Could not auto-detect BG3 installation. Specify --game-dir.")
            return 1

    print(f"Scanning research resources in {game_dir}...")
    probe = resolve_backend()
    backend = backend_from_probe(probe)
    if not backend:
        print(f"[ERROR] No archive backend available: {probe.reason}")
        return 1

    resources = scan_game_research_resources(
        game_dir,
        source_locale=request.source,
        target_locale=request.target,
        reference_locales=request.references,
        backend=backend
    )
    print(f"Discovered {len(resources)} research-relevant package entries.")

    write_scan_manifest(
        resources,
        str(request.output),
        gameDir=str(game_dir),
        sourceLocale=request.source,
        targetLocale=request.target,
        referenceLocales=request.references
    )
    print(f"Wrote scan manifest to {str(request.output)}")
    return 0


def run_research_classify(args: argparse.Namespace) -> int:
    return run_research_classify_request(
        ResearchClassifyRequest(
            extract_manifest=Path(args.extract_manifest),
            research_mappings=Path(args.research_mappings),
            output_dir=Path(args.output_dir),
            story_ledger=Path(args.story_ledger) if args.story_ledger else None,
            ui_skill_universe=Path(args.ui_skill_universe) if args.ui_skill_universe else None,
        )
    )


def run_research_resolve_unclassified(args: argparse.Namespace) -> int:
    summary = resolve_unclassified(
        classification_path=Path(args.classification),
        decisions_path=Path(args.decisions),
        output_path=Path(args.output),
    )
    print("Unclassified resolution PASS")
    print(f"Original unresolved rows: {summary.total_unresolved_input}")
    print(f"Assigned: {summary.assigned}")
    print(f"Excluded: {summary.excluded}")
    print(f"Pending decisions: {summary.pending}")
    print(f"No decision yet: {summary.unresolved_without_decision}")
    print(f"Output: {args.output}")
    print(f"Output SHA256: {summary.output_sha256}")
    return 0

def run_research_batch(args: argparse.Namespace) -> int:
    return run_research_batch_request(
        ResearchBatchRequest(
            classification=Path(args.classification),
            source=Path(args.source),
            output_dir=Path(args.output_dir),
            story_ledger=Path(args.story_ledger) if args.story_ledger else None,
            ui_skill_universe=Path(args.ui_skill_universe) if args.ui_skill_universe else None,
            research_mappings=Path(args.research_mappings) if args.research_mappings else None,
            max_records=tuple(args.max_records),
        )
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"Expected object at {path}:{line_no}")
            rows.append(row)
    return rows


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_max_records(values: tuple[str, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in values:
        if "=" not in raw:
            raise RuntimeError(f"Invalid --max-records value {raw!r}; expected CATEGORY=N")
        category, number = raw.split("=", 1)
        category = category.strip()
        try:
            value = int(number)
        except ValueError as exc:
            raise RuntimeError(f"Invalid --max-records value {raw!r}; N must be an integer") from exc
        if category not in DEFAULT_MAX_RECORDS:
            raise RuntimeError(f"Unknown batching category for --max-records: {category}")
        if value <= 0:
            raise RuntimeError(f"--max-records must be positive for {category}")
        result[category] = value
    return result


def _normalized_group_path(path: str) -> str:
    return path.replace("\\", "/").strip().casefold()


def _load_story_grouping(path: Path | None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    candidates: dict[str, set[str]] = {}
    subkeys: dict[str, set[str]] = {}
    if path is None:
        return candidates, subkeys
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            uid = str(row.get("ContentUid", ""))
            internal_path = str(row.get("InternalPath", ""))
            family = str(row.get("ResourceFamily", ""))
            if not uid or not internal_path:
                continue
            node = str(row.get("NodeId", "")).strip()
            if family in {"DialogsRaw", "DialogsBinary"}:
                group = normalize_dialog_resource(internal_path)
            elif node:
                group = f"story:{_normalized_group_path(internal_path)}|{node.casefold()}"
            else:
                group = f"path:{_normalized_group_path(internal_path)}"
            candidates.setdefault(uid, set()).add(group)
            role = str(row.get("AttributeRole", "")).strip()
            if node or role:
                subkeys.setdefault(uid, set()).add(f"{node.casefold()}|{role.casefold()}")
    return candidates, subkeys


def _load_ui_grouping(path: Path | None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    candidates: dict[str, set[str]] = {}
    subkeys: dict[str, set[str]] = {}
    if path is None:
        return candidates, subkeys
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            uid = str(row.get("ContentUid", ""))
            if not uid or str(row.get("Status", "")) == "ExcludedCommentOnly":
                continue
            provider = str(row.get("Provider", "")).strip()
            entity_type = str(row.get("EntityType", "")).strip()
            entity_name = str(row.get("EntityName", "")).strip()
            internal_path = str(row.get("InternalPath", "")).strip()
            parts = [provider, entity_type, entity_name]
            stable = "|".join(part.casefold() for part in parts if part)
            if stable:
                candidates.setdefault(uid, set()).add(f"entity:{stable}")
            elif internal_path:
                candidates.setdefault(uid, set()).add(f"path:{_normalized_group_path(internal_path)}")
            field_name = str(row.get("FieldName", "")).strip()
            if field_name:
                subkeys.setdefault(uid, set()).add(field_name.casefold())
    return candidates, subkeys


def _load_research_grouping(path: Path | None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    candidates: dict[str, set[str]] = {}
    subkeys: dict[str, set[str]] = {}
    if path is None:
        return candidates, subkeys

    for row in _read_jsonl(path):
        uid = str(row.get("contentUid", ""))
        mapping_type = str(row.get("mappingType", ""))
        if not uid:
            continue
        for evidence in row.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            resource_path = str(evidence.get("resourcePath", "")).strip()
            props = evidence.get("properties", {})
            if not isinstance(props, dict):
                props = {}

            if mapping_type == "stat-reference":
                entry_name = str(props.get("entryName", "")).strip()
                if entry_name:
                    candidates.setdefault(uid, set()).add(
                        f"stat:{_normalized_group_path(resource_path)}|{entry_name.casefold()}"
                    )
                field_name = str(props.get("fieldName", "")).strip()
                if field_name:
                    subkeys.setdefault(uid, set()).add(field_name.casefold())

            elif mapping_type == "quest-journal":
                entity_id = str(props.get("entityId", "")).strip()
                element_index = str(props.get("elementIndex", "")).strip()
                if entity_id:
                    candidates.setdefault(uid, set()).add(
                        f"quest:{_normalized_group_path(resource_path)}|{entity_id.casefold()}"
                    )
                elif element_index:
                    candidates.setdefault(uid, set()).add(
                        f"quest:{_normalized_group_path(resource_path)}|element:{element_index}"
                    )
                field_role = str(props.get("fieldRole", "")).strip()
                if field_role:
                    subkeys.setdefault(uid, set()).add(field_role.casefold())

    return candidates, subkeys


def _classification_evidence_groups(row: dict[str, Any]) -> set[str]:
    groups: set[str] = set()
    for evidence in row.get("classificationEvidence", []):
        if not isinstance(evidence, dict):
            continue
        path = str(evidence.get("resourcePath", "")).strip()
        if path:
            groups.add(f"path:{_normalized_group_path(path)}")
    return groups


def run_research_batch_request(request: ResearchBatchRequest) -> int:
    if not request.classification.is_file():
        raise RuntimeError(f"Classification ledger not found: {request.classification}")
    if not request.source.is_file():
        raise RuntimeError(f"Source normalized JSONL not found: {request.source}")
    if request.story_ledger is not None and not request.story_ledger.is_file():
        raise RuntimeError(f"Story ledger not found: {request.story_ledger}")
    if request.ui_skill_universe is not None and not request.ui_skill_universe.is_file():
        raise RuntimeError(f"UI-skill universe not found: {request.ui_skill_universe}")
    if request.research_mappings is not None and not request.research_mappings.is_file():
        raise RuntimeError(f"Research mappings not found: {request.research_mappings}")

    classification_rows = _read_jsonl(request.classification)
    source_rows = _read_jsonl(request.source)
    source_by_uid: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        uid = str(row.get("contentUid", ""))
        if not uid:
            continue
        if uid in source_by_uid:
            raise RuntimeError(f"Source normalized JSONL contains duplicate ContentUid: {uid}")
        source_by_uid[uid] = row

    story_groups, story_subkeys = _load_story_grouping(request.story_ledger)
    ui_groups, ui_subkeys = _load_ui_grouping(request.ui_skill_universe)
    research_groups, research_subkeys = _load_research_grouping(request.research_mappings)

    seen_classification: set[str] = set()
    inputs: list[BatchInputRecord] = []
    for row in classification_rows:
        uid = str(row.get("contentUid", ""))
        if not uid:
            raise RuntimeError("Classification row missing contentUid")
        if uid in seen_classification:
            raise RuntimeError(f"Classification ledger contains duplicate ContentUid: {uid}")
        seen_classification.add(uid)
        if uid not in source_by_uid:
            raise RuntimeError(f"Classification ContentUid missing from source input: {uid}")

        category = str(row.get("primaryCategory", ""))
        candidates: set[str] = set()
        subkeys: set[str] = set()
        if category == "dialogue_general":
            candidates.update(story_groups.get(uid, set()))
            subkeys.update(story_subkeys.get(uid, set()))
        elif category == "quest":
            candidates.update(research_groups.get(uid, set()))
            subkeys.update(research_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(_classification_evidence_groups(row))
        elif category == "skill_spell":
            candidates.update(research_groups.get(uid, set()))
            subkeys.update(research_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(ui_groups.get(uid, set()))
                subkeys.update(ui_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(_classification_evidence_groups(row))
        elif category in {"item", "ui", "tutorial"}:
            candidates.update(ui_groups.get(uid, set()))
            subkeys.update(ui_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(research_groups.get(uid, set()))
                subkeys.update(research_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(_classification_evidence_groups(row))
        elif category in {"book_lore", "character_world"}:
            candidates.update(story_groups.get(uid, set()))
            subkeys.update(story_subkeys.get(uid, set()))
            if not candidates:
                candidates.update(_classification_evidence_groups(row))
        else:
            candidates.update(_classification_evidence_groups(row))
            if not candidates:
                candidates.update(story_groups.get(uid, set()))

        source_row = source_by_uid[uid]
        inputs.append(BatchInputRecord(
            content_uid=uid,
            source_text=str(source_row.get("text", source_row.get("sourceText", ""))),
            primary_category=category,
            classification_status=str(row.get("classificationStatus", "")),
            group_candidates=tuple(sorted(candidates)),
            subkeys=tuple(sorted(subkeys)),
        ))

    foreign_source_uids = set(source_by_uid) - seen_classification
    if foreign_source_uids:
        raise RuntimeError(
            f"Source input contains {len(foreign_source_uids)} ContentUid records absent from classification ledger"
        )

    overrides = _parse_max_records(request.max_records)
    effective_limits = dict(DEFAULT_MAX_RECORDS)
    effective_limits.update(overrides)
    plan = build_batch_plan(inputs, max_records=effective_limits)

    structural_hashes: dict[str, str] = {}
    if request.story_ledger is not None:
        structural_hashes["storyLedger"] = _sha256_file(request.story_ledger)
    if request.ui_skill_universe is not None:
        structural_hashes["uiSkillUniverse"] = _sha256_file(request.ui_skill_universe)
    if request.research_mappings is not None:
        structural_hashes["researchMappings"] = _sha256_file(request.research_mappings)
    fingerprint = batch_plan_fingerprint(
        classification_sha256=_sha256_file(request.classification),
        source_sha256=_sha256_file(request.source),
        config=effective_limits,
        structural_input_sha256=structural_hashes,
    )

    request.output_dir.mkdir(parents=True, exist_ok=True)
    materials_dir = request.output_dir / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)

    batch_payloads: list[dict[str, Any]] = []
    for manifest in plan.batches:
        batch_rows = plan.records_by_batch[manifest.batchId]
        batch_path = materials_dir / f"{manifest.batchId}.jsonl"
        with batch_path.open("w", encoding="utf-8", newline="\n") as f:
            for record in batch_rows:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
        payload = manifest.to_dict()
        payload["batchPlanFingerprint"] = fingerprint
        payload["sourceLocale"] = str(source_rows[0].get("localeId", "")) if source_rows else ""
        payload["materialPath"] = str(batch_path)
        batch_payloads.append(payload)

    unresolved_path = request.output_dir / "unresolved.jsonl"
    classification_by_uid = {str(row["contentUid"]): row for row in classification_rows}
    with unresolved_path.open("w", encoding="utf-8", newline="\n") as f:
        for uid in plan.unresolved_uids:
            row = dict(classification_by_uid[uid])
            row["sourceText"] = str(source_by_uid[uid].get("text", source_by_uid[uid].get("sourceText", "")))
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    excluded_path = request.output_dir / "excluded.jsonl"
    with excluded_path.open("w", encoding="utf-8", newline="\n") as f:
        for uid in plan.excluded_uids:
            row = dict(classification_by_uid[uid])
            row["sourceText"] = str(source_by_uid[uid].get("text", source_by_uid[uid].get("sourceText", "")))
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    plan_path = request.output_dir / "batch-plan.json"
    with plan_path.open("w", encoding="utf-8") as f:
        json.dump({
            "schemaVersion": "1.0",
            "batchingRuleVersion": BATCHING_RULE_VERSION,
            "batchPlanFingerprint": fingerprint,
            "maxRecords": effective_limits,
            "classificationLedger": str(request.classification),
            "sourceInput": str(request.source),
            "storyLedger": str(request.story_ledger) if request.story_ledger else None,
            "uiSkillUniverse": str(request.ui_skill_universe) if request.ui_skill_universe else None,
            "researchMappings": str(request.research_mappings) if request.research_mappings else None,
            "batches": batch_payloads,
        }, f, indent=2, ensure_ascii=False)

    batched_uids = list(plan.batched_uids)
    eligible_uids = {
        item.content_uid
        for item in inputs
        if item.classification_status == "classified" and item.primary_category != "other"
    }
    duplicate_count = len(batched_uids) - len(set(batched_uids))
    missing = eligible_uids - set(batched_uids)
    foreign = set(batched_uids) - eligible_uids
    mixed = sum(
        1
        for manifest in plan.batches
        if any(record.primaryCategory != manifest.primaryCategory for record in plan.records_by_batch[manifest.batchId])
    )

    category_records: dict[str, int] = {}
    category_batches: dict[str, int] = {}
    batch_sizes: list[int] = []
    oversize_count = 0
    for manifest in plan.batches:
        category_records[manifest.primaryCategory] = category_records.get(manifest.primaryCategory, 0) + manifest.recordCount
        category_batches[manifest.primaryCategory] = category_batches.get(manifest.primaryCategory, 0) + 1
        batch_sizes.append(manifest.recordCount)
        if manifest.oversizeGroupSplit:
            oversize_count += 1

    summary = {
        "schemaVersion": "1.0",
        "batchingRuleVersion": BATCHING_RULE_VERSION,
        "batchPlanFingerprint": fingerprint,
        "totalSourceContentUid": len(source_by_uid),
        "classifiedInputCount": len(eligible_uids),
        "unresolvedCount": len(plan.unresolved_uids),
        "excludedCount": len(plan.excluded_uids),
        "batchCount": len(plan.batches),
        "batchCountPerCategory": dict(sorted(category_batches.items())),
        "recordCountPerCategory": dict(sorted(category_records.items())),
        "minRecordsPerBatch": min(batch_sizes) if batch_sizes else 0,
        "maxRecordsPerBatch": max(batch_sizes) if batch_sizes else 0,
        "meanRecordsPerBatch": (sum(batch_sizes) / len(batch_sizes)) if batch_sizes else 0.0,
        "oversizeGroupSplitCount": oversize_count,
        "duplicateBatchedUidCount": duplicate_count,
        "missingClassifiedUidCount": len(missing),
        "foreignUidCount": len(foreign),
        "mixedCategoryBatchCount": mixed,
    }
    summary_path = request.output_dir / "batch-summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    if duplicate_count or missing or foreign or mixed:
        raise RuntimeError("Batch validation failed; see batch-summary.json")

    print(f"Category-aware batching complete: {len(plan.batches)} batches")
    print(f"Classified records: {len(eligible_uids)}")
    print(f"Unresolved records: {len(plan.unresolved_uids)}")
    print(f"Excluded records: {len(plan.excluded_uids)}")
    print(f"Batch plan: {plan_path}")
    print(f"Summary: {summary_path}")
    return 0


def _mapping_from_dict(raw: dict[str, Any]) -> ResearchMapping:
    evidence: list[ResearchEvidence] = []
    for item in raw.get("evidence", []):
        if not isinstance(item, dict):
            continue
        evidence.append(
            ResearchEvidence(
                sourceRole=str(item.get("sourceRole", "")),
                resourcePath=str(item.get("resourcePath", "")),
                evidenceType=str(item.get("evidenceType", "")),
                ruleId=str(item.get("ruleId", "")),
                properties=dict(item.get("properties", {})) if isinstance(item.get("properties"), dict) else {},
            )
        )
    return ResearchMapping(
        contentUid=str(raw.get("contentUid", "")),
        mappingType=str(raw.get("mappingType", "")),
        classification=str(raw.get("classification", "")),
        evidence=evidence,
        version=str(raw.get("version", "")),
        reviewRequired=bool(raw.get("reviewRequired", False)),
        metadata=dict(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {},
    )


def _resolve_optional_classification_input(explicit: Path | None, sibling: Path) -> Path | None:
    if explicit is not None:
        if not explicit.is_file():
            raise RuntimeError(f"Classification evidence file not found: {explicit}")
        return explicit
    return sibling if sibling.is_file() else None


def _story_ledger_mappings(path: Path) -> list[ResearchMapping]:
    mappings: list[ResearchMapping] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = str(row.get("ContentUid", ""))
            if not uid:
                continue
            props = {
                "pakName": str(row.get("PakName", "")),
                "resourceFamily": str(row.get("ResourceFamily", "")),
                "resourceFormat": str(row.get("ResourceFormat", "")),
                "storyDomain": str(row.get("StoryDomain", "")),
                "nodeId": str(row.get("NodeId", "")),
                "attributeRole": str(row.get("AttributeRole", "")),
                "hasSpeaker": str(row.get("HasSpeaker", "")).casefold() == "true",
                "hasDialog": str(row.get("HasDialog", "")).casefold() == "true",
                "hasQuest": str(row.get("HasQuest", "")).casefold() == "true",
                "isOldText": str(row.get("IsOldText", "")).casefold() == "true",
            }
            mappings.append(
                ResearchMapping(
                    contentUid=uid,
                    mappingType="story-occurrence",
                    classification=props["storyDomain"],
                    evidence=[
                        ResearchEvidence(
                            sourceRole="StoryOccurrenceLedger",
                            resourcePath=str(row.get("InternalPath", "")),
                            evidenceType="StoryOccurrence",
                            ruleId="LSTP-STORY-OCCURRENCE-OWNERSHIP",
                            properties=props,
                        )
                    ],
                    metadata={
                        "resourceFamily": props["resourceFamily"],
                        "storyDomain": props["storyDomain"],
                    },
                )
            )
    return mappings


def _ui_skill_universe_mappings(path: Path) -> list[ResearchMapping]:
    mappings: list[ResearchMapping] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = str(row.get("ContentUid", ""))
            if not uid:
                continue
            props = {
                "status": str(row.get("Status", "")),
                "workstream": str(row.get("Workstream", "")),
                "provider": str(row.get("Provider", "")),
                "package": str(row.get("Package", "")),
                "sourceFamilies": str(row.get("SourceFamilies", "")),
                "domains": str(row.get("Domains", "")),
                "entityType": str(row.get("EntityType", "")),
                "entityName": str(row.get("EntityName", "")),
                "fieldName": str(row.get("FieldName", "")),
                "parentName": str(row.get("ParentName", "")),
                "inheritanceDepth": str(row.get("InheritanceDepth", "")),
                "explicitOrInherited": str(row.get("ExplicitOrInherited", "")),
                "commentOnly": str(row.get("CommentOnly", "")).casefold() == "true",
                "definingProvider": str(row.get("DefiningProvider", "")),
                "providerOverrideApplied": str(row.get("ProviderOverrideApplied", "")).casefold() == "true",
            }
            mappings.append(
                ResearchMapping(
                    contentUid=uid,
                    mappingType="ui-skill-universe",
                    classification=props["workstream"],
                    evidence=[
                        ResearchEvidence(
                            sourceRole="UiSkillUniverse",
                            resourcePath=str(row.get("InternalPath", "")),
                            evidenceType="UiSkillUniverse",
                            ruleId="LSTP-UI-SKILL-UNIVERSE-OWNERSHIP",
                            properties=props,
                        )
                    ],
                    metadata={"workstream": props["workstream"]},
                )
            )
    return mappings


def run_research_classify_request(request: ResearchClassifyRequest) -> int:
    if not request.extract_manifest.is_file():
        raise RuntimeError(f"Extract manifest not found: {request.extract_manifest}")
    if not request.research_mappings.is_file():
        raise RuntimeError(f"Research mappings not found: {request.research_mappings}")

    with request.extract_manifest.open("r", encoding="utf-8-sig") as f:
        manifest = json.load(f)

    source_locale = str(manifest.get("sourceLocale", ""))
    if not source_locale:
        raise RuntimeError("Extract manifest missing sourceLocale")

    source_normalized: Path | None = None
    for item in manifest.get("locales", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("localeId", "")).casefold() == source_locale.casefold():
            source_normalized = Path(str(item.get("normalized", "")))
            if not source_normalized.is_absolute():
                source_normalized = request.extract_manifest.parent / source_normalized
            break

    if source_normalized is None or not source_normalized.is_file():
        raise RuntimeError(f"Source normalized JSONL not found for locale {source_locale}")

    source_rows = _read_jsonl(source_normalized)
    content_uids = [
        str(row.get("contentUid", ""))
        for row in source_rows
        if str(row.get("contentUid", ""))
    ]
    if not content_uids:
        raise RuntimeError("Source normalized JSONL contains no ContentUid records")
    if len(content_uids) != len(set(content_uids)):
        raise RuntimeError("Source normalized JSONL contains duplicate ContentUid records")

    mapping_rows = _read_jsonl(request.research_mappings)
    mappings = [_mapping_from_dict(row) for row in mapping_rows if row.get("contentUid")]

    research_dir = request.research_mappings.parent
    story_ledger = _resolve_optional_classification_input(
        request.story_ledger,
        research_dir / "story-occurrence-ledger.csv",
    )
    ui_skill_universe = _resolve_optional_classification_input(
        request.ui_skill_universe,
        research_dir / "ui-skill-universe.csv",
    )
    if story_ledger is not None:
        mappings.extend(_story_ledger_mappings(story_ledger))
    if ui_skill_universe is not None:
        mappings.extend(_ui_skill_universe_mappings(ui_skill_universe))

    results = classify_functional_ownership(content_uids, mappings)
    summary = summarize_functional_classification(results)

    request.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = request.output_dir / "functional-classification.jsonl"
    summary_path = request.output_dir / "functional-classification-summary.json"

    with ledger_path.open("w", encoding="utf-8", newline="\n") as f:
        for result in results:
            f.write(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")

    summary_payload = {
        "schemaVersion": "1.0",
        "sourceLocale": source_locale,
        "extractManifest": str(request.extract_manifest),
        "researchMappings": str(request.research_mappings),
        "storyLedger": str(story_ledger) if story_ledger is not None else None,
        "uiSkillUniverse": str(ui_skill_universe) if ui_skill_universe is not None else None,
        **summary,
    }
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2, ensure_ascii=False)

    print(f"Functional classification complete: {len(results)} ContentUids")
    print(f"Ledger: {ledger_path}")
    print(f"Summary: {summary_path}")
    print(f"Coverage: {summary['classifiedCoveragePercent']:.2f}%")
    print(f"Unclassified: {summary['statusCounts']['unclassified']}")
    return 0


def parse_loca_xml(content: str) -> dict[str, str]:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(content.encode("utf-8"))
        return {
            elem.get("contentuid", ""): (elem.text or "")
            for elem in root.findall(".//content")
            if elem.get("contentuid")
        }
    except Exception:
        return {}


def extract_and_generate_story_ledger(
    game_dir: Path,
    output_dir: Path,
    backend: ArchiveBackend,
    resources: list[ResearchScanResource] | None = None,
) -> None:
    """Extract and parse story resources from user game packages to generate story-occurrence-ledger.csv and oldtext-evidence.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "story-occurrence-ledger.csv"
    oldtext_path = output_dir / "oldtext-evidence.csv"

    # If on Windows and LSLib.dll is available in backend executable directory, run in-memory stream parser
    lslib_dir = None
    probe = backend.probe() if hasattr(backend, "probe") else None
    if probe and probe.executable:
        cand_dir = probe.executable.parent
        if (cand_dir / "LSLib.dll").is_file():
            lslib_dir = cand_dir

    if os.name == "nt" and lslib_dir is not None:
        ps_script = f'''
$ErrorActionPreference = 'Stop'
[Reflection.Assembly]::LoadFrom('{lslib_dir / "Newtonsoft.Json.dll"}') | Out-Null
[Reflection.Assembly]::LoadFrom('{lslib_dir / "LSLib.dll"}') | Out-Null

function StoryDomain([string]$family,[string]$constructor,[string]$category,[string]$field,[string]$path){{
  if($family -eq 'DialogsRaw' -or $family -eq 'DialogsBinary'){{
    if($path -match '(?i)cinematic' -or $category -match '(?i)cinematic'){{return 'CinematicSubtitle'}}
    if($constructor -match '(?i)narrat'){{return 'Narration'}}
    if($constructor -match '(?i)question|player'){{return 'PlayerDialogueOption'}}
    if($category -match '(?i)bark'){{return 'AmbientDialogue'}}
    return 'NPCDialogue'
  }}
  if($family -eq 'Cinematics'){{return 'CinematicSubtitle'}}
  if($family -eq 'JournalQuest'){{if($field-match'(?i)title'){{return 'QuestTitle'}};if($field-match'(?i)description|objective'){{return 'QuestDescription'}};return 'JournalEntry'}}
  if($family -eq 'ReadableLocalizationRegistry'){{if($field-match'(?i)title|displayname'){{return 'BookTitle'}};return 'ReadableWorldText'}}
  if($family -in @('TagsCharacters','RootTemplates','LocalizationRegistry')){{return 'StoryRelatedTerm'}}
  if($family -in @('StoryGoals','LevelResources')){{return 'ContextSupportOnly'}}
  return 'Unknown'
}}

$lw = [System.IO.StreamWriter]::new('{str(ledger_path).replace("\\", "\\\\")}', $false, [System.Text.UTF8Encoding]::new($false))
$ow = [System.IO.StreamWriter]::new('{str(oldtext_path).replace("\\", "\\\\")}', $false, [System.Text.UTF8Encoding]::new($false))
$lw.WriteLine("ContentUid,PakName,InternalPath,ResourceFamily,ResourceFormat,StoryDomain,NodeId,AttributeRole,HasSpeaker,HasDialog,HasQuest,IsOldText")
$ow.WriteLine("ContentUid,PakName,InternalPath,NodeId,AttributeRole,StoryDomain")

$paks = @("Gustav.pak", "Shared.pak", "GustavX.pak", "Patch8_HotFix9.pak")

foreach ($pName in $paks) {{
    $pPath = Join-Path (Join-Path '{str(game_dir).replace("\\", "\\\\")}' "Data") $pName
    if (-not (Test-Path $pPath)) {{ continue }}
    $pkg = [LSLib.LS.PackageReader]::new().Read($pPath, $false)
    try {{
        foreach ($entry in $pkg.Files) {{
            $path = $entry.Name.Replace('\\', '/')
            $lower = $path.ToLower()
            $ext = [System.IO.Path]::GetExtension($lower)
            $fam = ""
            $fmt = ""
            if ($lower -match '/story/dialogs/' -and $ext -eq '.lsj') {{ $fam = 'DialogsRaw'; $fmt = 'LSJ' }}
            elseif ($lower -match '/story/dialogsbinary/' -and $ext -eq '.lsf') {{ $fam = 'DialogsBinary'; $fmt = 'LSF' }}
            elseif ($lower -match '/story/rawfiles/goals/' -and $ext -eq '.txt') {{ $fam = 'StoryGoals'; $fmt = 'TXT' }}
            elseif ($lower -match '/(journal|quest)[^/]*/' -and ($ext -in @('.lsf','.lsx','.lsj','.txt'))) {{ $fam = 'JournalQuest'; $fmt = $ext.Replace('.','').ToUpper() }}
            elseif ($lower -match '/localization/' -and ($lower -match 'book|letter|gazette|readable|misc') -and ($ext -in @('.lsf','.lsx'))) {{ $fam = 'ReadableLocalizationRegistry'; $fmt = $ext.Replace('.','').ToUpper() }}
            elseif ($lower -match '/localization/' -and ($ext -in @('.lsf','.lsx'))) {{ $fam = 'LocalizationRegistry'; $fmt = $ext.Replace('.','').ToUpper() }}
            elseif ($lower -match '/roottemplates/_merged\\.lsf$') {{ $fam = 'RootTemplates'; $fmt = 'LSF' }}
            elseif ($lower -match '/(tags|characters)/' -and ($ext -in @('.lsf','.lsx'))) {{ $fam = 'TagsCharacters'; $fmt = $ext.Replace('.','').ToUpper() }}
            elseif ($lower -match '/cinematics?/' -and ($ext -in @('.lsf','.lsx','.lsj'))) {{ $fam = 'Cinematics'; $fmt = $ext.Replace('.','').ToUpper() }}
            elseif ($lower -match '(^|/)levels?/' -and ($ext -eq '.lsf') -and ($lower -match '_merged\\.lsf$')) {{ $fam = 'LevelResources'; $fmt = 'LSF' }}

            if (-not $fam) {{ continue }}

            $stream = $entry.CreateContentReader()
            try {{
                if ($fmt -eq 'LSJ') {{
                    $mem = [System.IO.MemoryStream]::new()
                    $stream.CopyTo($mem)
                    $txt = [System.Text.Encoding]::UTF8.GetString($mem.ToArray())
                    $mem.Dispose()
                    $root = [Newtonsoft.Json.Linq.JObject]::Parse($txt)
                    $dialog = $root.SelectToken('save.regions.dialog')
                    if ($null -ne $dialog) {{
                        $cat = [string]$dialog.SelectToken('category.value')
                        $nodeArr = $dialog.SelectToken('nodes[0].node')
                        if ($null -ne $nodeArr) {{
                            foreach ($node in $nodeArr.Children()) {{
                                $nodeUuid = [string]$node.SelectToken('UUID.value')
                                $ctor = [string]$node.SelectToken('constructor.value')
                                $spIdx = [string]$node.SelectToken('speaker.value')
                                $hasSpk = ($null -ne $spIdx -and $spIdx -ne '' -and $spIdx -ne '-1')
                                $dom = StoryDomain $fam $ctor $cat 'TagText' $path
                                $tTokens = $node.SelectTokens('$..TagText.handle')
                                if ($null -ne $tTokens) {{
                                    foreach ($tok in $tTokens) {{
                                        $uid = [string]$tok
                                        if ($uid -match '^h[0-9a-f]{{8}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{12}}$') {{
                                            $lw.WriteLine("$uid,$pName,$path,$fam,$fmt,$dom,$nodeUuid,TagText,$hasSpk,True,False,False")
                                        }}
                                    }}
                                }}
                                $oTokens = $node.SelectTokens('$..OldText.handle')
                                if ($null -ne $oTokens) {{
                                    foreach ($tok in $oTokens) {{
                                        $uid = [string]$tok
                                        if ($uid -match '^h[0-9a-f]{{8}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{12}}$') {{
                                            $ow.WriteLine("$uid,$pName,$path,$nodeUuid,OldText,$dom")
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }} elseif ($fmt -in @('LSF', 'LSX')) {{
                    $mem = [System.IO.MemoryStream]::new()
                    $stream.CopyTo($mem)
                    $mem.Position = 0
                    try {{
                        if ($fmt -eq 'LSF') {{
                            $reader = [LSLib.LS.LSFReader]::new($mem)
                            $resource = $reader.Read()
                            foreach ($region in $resource.Regions.Values) {{
                                $q = [System.Collections.Generic.Queue[object]]::new()
                                $q.Enqueue($region)
                                $nodeOrdinal = 0
                                while ($q.Count -gt 0) {{
                                    $rn = $q.Dequeue()
                                    $nodeOrdinal += 1
                                    $nodeUuid = ""
                                    foreach ($identityKey in @('UUID','NodeUUID','MapKey','Name','ID','Guid','GUID')) {{
                                        if ($rn.Attributes.ContainsKey($identityKey)) {{
                                            $candidateIdentity = [string]$rn.Attributes[$identityKey].Value.Value
                                            if ($candidateIdentity) {{
                                                $nodeUuid = $candidateIdentity
                                                break
                                            }}
                                        }}
                                    }}
                                    if (-not $nodeUuid) {{ $nodeUuid = "node#$nodeOrdinal" }}
                                    $ctor = ""
                                    if ($rn.Attributes.ContainsKey('constructor')) {{ $ctor = [string]$rn.Attributes['constructor'].Value.Value }}
                                    $hasSpk = ($rn.Attributes.ContainsKey('speaker') -or $rn.Attributes.ContainsKey('SpeakerUUID'))
                                    foreach ($pair in $rn.Attributes.GetEnumerator()) {{
                                        if ($pair.Value.Type.ToString() -match 'TranslatedString') {{
                                            $uid = [string]$pair.Value.Value.Handle
                                            if ($uid -match '^h[0-9a-f]{{8}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{12}}$') {{
                                                $field = [string]$pair.Key
                                                $isOld = ($field -eq 'OldText')
                                                $dom = StoryDomain $fam $ctor '' $field $path
                                                $lw.WriteLine("$uid,$pName,$path,$fam,$fmt,$dom,$nodeUuid,$field,$hasSpk,$($fam.StartsWith('Dialog')),$($fam -eq 'JournalQuest'),$isOld")
                                                if ($isOld) {{
                                                    $ow.WriteLine("$uid,$pName,$path,$nodeUuid,$field,$dom")
                                                }}
                                            }}
                                        }}
                                    }}
                                    foreach ($cGroup in $rn.Children.Values) {{
                                        foreach ($child in $cGroup) {{
                                            $q.Enqueue($child)
                                        }}
                                    }}
                                }}
                            }}
                        }} else {{
                            $settings = [System.Xml.XmlReaderSettings]::new()
                            $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
                            $settings.XmlResolver = $null
                            $xr = [System.Xml.XmlReader]::Create($mem, $settings)
                            try {{
                                $doc = [System.Xml.XmlDocument]::new()
                                $doc.XmlResolver = $null
                                $doc.Load($xr)
                                $nodeOrdinals = @{{}}
                                $nodeIndex = 0
                                foreach ($n in $doc.SelectNodes("//node")) {{
                                    $nodeIndex += 1
                                    $nodeOrdinals[$n] = $nodeIndex
                                }}
                                $attrs = $doc.SelectNodes("//attribute[@type='TranslatedString' and @handle]")
                                foreach ($a in $attrs) {{
                                    $uid = $a.GetAttribute('handle')
                                    if ($uid -match '^h[0-9a-f]{{8}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{12}}$') {{
                                        $field = $a.GetAttribute('id')
                                        $isOld = ($field -eq 'OldText')
                                        $dom = StoryDomain $fam '' '' $field $path
                                        $nodeUuid = ""
                                        $node = $a.SelectSingleNode("ancestor::node[1]")
                                        if ($null -ne $node) {{
                                            foreach ($identityKey in @('UUID','NodeUUID','MapKey','Name','ID','Guid','GUID')) {{
                                                $identityAttr = $node.SelectSingleNode("attribute[@id='$identityKey']")
                                                if ($null -ne $identityAttr) {{
                                                    $candidateIdentity = $identityAttr.GetAttribute('value')
                                                    if (-not $candidateIdentity) {{ $candidateIdentity = $identityAttr.GetAttribute('handle') }}
                                                    if ($candidateIdentity) {{
                                                        $nodeUuid = $candidateIdentity
                                                        break
                                                    }}
                                                }}
                                            }}
                                            if (-not $nodeUuid -and $nodeOrdinals.ContainsKey($node)) {{
                                                $nodeUuid = "node#$($nodeOrdinals[$node])"
                                            }}
                                        }}
                                        $lw.WriteLine("$uid,$pName,$path,$fam,$fmt,$dom,$nodeUuid,$field,False,$($fam.StartsWith('Dialog')),$($fam -eq 'JournalQuest'),$isOld")
                                        if ($isOld) {{
                                            $ow.WriteLine("$uid,$pName,$path,$nodeUuid,$field,$dom")
                                        }}
                                    }}
                                }}
                            }} finally {{
                                $xr.Dispose()
                            }}
                        }}
                    }} finally {{
                        $mem.Dispose()
                    }}
                }} elseif ($fmt -eq 'TXT') {{
                    $mem = [System.IO.MemoryStream]::new()
                    $stream.CopyTo($mem)
                    $txt = [System.Text.Encoding]::UTF8.GetString($mem.ToArray())
                    $mem.Dispose()
                    $matches = [regex]::Matches($txt, 'h[0-9a-f]{{8}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{4}}g[0-9a-f]{{12}}')
                    foreach ($m in $matches) {{
                        $uid = $m.Value.ToLower()
                        $lw.WriteLine("$uid,$pName,$path,$fam,TXT,ContextSupportOnly,,TextReference,False,False,False,False")
                    }}
                }}
            }} catch {{}}
            finally {{
                $stream.Dispose()
            }}
        }}
    }} finally {{
        $pkg.Dispose()
    }}
}}
$lw.Dispose()
$ow.Dispose()
'''
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as tf:
            tf.write(ps_script)
            script_path = tf.name
        try:
            cmd = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if res.returncode != 0:
                cmd[0] = "powershell"
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass


def run_research_map(args: argparse.Namespace) -> int:
    return run_research_map_request(ResearchMapRequest(
        scan=Path(args.scan),
        output_dir=Path(args.output_dir),
        source=str(args.source),
        target=str(args.target),
        references=tuple(args.reference),
    ))


def run_research_provenance_export(args: argparse.Namespace) -> int:
    from bg3loc.research.provenance_export import export_public_structural_provenance

    scan = json.loads(Path(args.scan).read_text(encoding="utf-8-sig"))
    if not scan.get("gameDir"):
        raise ValueError("scan manifest missing gameDir")
    probe = resolve_backend()
    backend = backend_from_probe(probe)
    if backend is None:
        raise RuntimeError("No archive backend available for structural provenance export")
    summary = export_public_structural_provenance(
        Path(scan["gameDir"]), backend, Path(args.output_dir),
        [ResearchScanResource(**row) for row in scan.get("resources", [])],
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


def run_research_map_request(request: ResearchMapRequest) -> int:
    scan_path = request.scan
    output_dir = request.output_dir

    forbidden_markers = [
        "phase4bhm" + "-story-occurrence-ledger",
        "phase4ba" + "-target-assignment",
        "BG3-Retranslation" + "-Toolchain",
        "canonical" + "_7_holds",
        "runtime_" + "telemetry_uids",
    ]
    scan_str = str(scan_path)
    out_str = str(output_dir)
    for marker in forbidden_markers:
        if marker.lower() in scan_str.lower() or marker.lower() in out_str.lower():
            raise ValueError(f"Historical project artifact path or marker {marker!r} is prohibited as runtime input.")

    if not scan_path.exists():
        print(f"[ERROR] Scan manifest {scan_path} not found.")
        return 1

    with open(scan_path, "r", encoding="utf-8") as f:
        scan_data = json.load(f)

    game_dir_str = scan_data.get("gameDir", "")
    if not game_dir_str:
        print("[ERROR] Scan manifest missing gameDir.")
        return 1

    game_dir = Path(game_dir_str)
    source_locale = scan_data.get("sourceLocale", request.source)
    target_locale = scan_data.get("targetLocale", request.target)
    reference_locales = scan_data.get("referenceLocales", list(request.references))

    # Resolve runtime metadata
    runtime_meta = resolve_runtime_metadata(game_dir)

    # Compute scan manifest SHA256 early — used in cross-domain provenance key
    _scan_sha256 = ""
    if scan_path.is_file():
        h2 = hashlib.sha256()
        h2.update(scan_path.read_bytes())
        _scan_sha256 = h2.hexdigest()

    probe = resolve_backend()
    backend = backend_from_probe(probe)
    if not backend:
        print(f"[ERROR] No archive backend available: {probe.reason}")
        return 1

    raw_resources = [ResearchScanResource(**r) for r in scan_data.get("resources", [])]

    # Resolve package layer overlay precedence
    candidates = [
        OverlayCandidate(
            internalPath=r.internalPath,
            pakName=r.pakName,
            size=r.size,
            mtime=0.0,
            layerPriority=0,
        ) for r in raw_resources
    ]
    resolutions = resolve_overlay_precedence(candidates)

    resources = []
    for r in raw_resources:
        res = resolutions.get(r.internalPath.replace("\\", "/"))
        if res and res.winningPak == r.pakName:
            resources.append(r)

    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(tempfile.mkdtemp(dir=output_dir))

    mappings: list[ResearchMapping] = []
    loca_records: dict[str, dict[str, str]] = {}
    aux_loca_records: dict[str, dict[str, str]] = {}

    # File texts cached for context extraction
    gustavx_stats_texts: list[tuple[str, str]] = [] # (internal_path, text)
    shared_candidate_texts: list[tuple[str, str]] = [] # (internal_path, text)
    gustav_passive_texts: list[tuple[str, str]] = [] # (internal_path, text)
    story_occurrences: list[StoryOccurrence] = []
    old_text_uids: set[str] = set()
    story_uids: set[str] = set()

    # Dynamic required packages based on configured profile
    required_paks = {"Gustav.pak", "Shared.pak", "GustavX.pak"}
    if source_locale:
        required_paks.add(f"{source_locale}.pak")
    if target_locale:
        required_paks.add(f"{target_locale}.pak")
    if reference_locales:
        for ref_loc in reference_locales:
            required_paks.add(f"{ref_loc}.pak")

    # Generate or load story occurrence ledger from output directory
    story_ledger_file = output_dir / "story-occurrence-ledger.csv"
    if not story_ledger_file.is_file():
        extract_and_generate_story_ledger(game_dir, output_dir, backend, resources)

    if story_ledger_file.is_file():
        story_occurrences = read_story_occurrence_ledger(story_ledger_file)
        for o in story_occurrences:
            if o.isOldText:
                old_text_uids.add(o.contentUid)
        # Ensure oldtext evidence is written
        write_oldtext_evidence(story_occurrences, output_dir / "oldtext-evidence.csv")

    try:
        paks: dict[str, list[ResearchScanResource]] = {}
        for res in resources:
            paks.setdefault(res.pakName, []).append(res)

        def get_pak_path(p_name: str) -> Path:
            p = game_dir / "Data" / p_name
            if p.is_file():
                return p
            p_loc = game_dir / "Data" / "Localization" / p_name
            if p_loc.is_file():
                return p_loc
            alts = list((game_dir / "Data").rglob(p_name))
            if alts:
                return alts[0]
            return p

        def process_resource(res: ResearchScanResource, pak_path: Path, pak_name: str) -> dict[str, Any]:
            internal_path = res.internalPath
            role = res.sourceRole

            # When story occurrence ledger is available, skip extraction of heavy story-only resources
            # that do not produce mappings or localization/stats entries
            is_pure_story = role in (
                "Cinematics", "DialogsBinary", "DialogsRaw", "LevelResources",
                "LocalizationRegistry", "ReadableLocalizationRegistry",
                "RootTemplates", "StoryGoals", "TagsCharacters"
            )
            if story_occurrences and is_pure_story:
                return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}

            dest_path = temp_dir / pak_name / internal_path
            try:
                backend.extract_single_file(pak_path, internal_path, dest_path)
            except Exception as e:
                if pak_name in required_paks or pak_name.startswith("Patch"):
                    raise RuntimeError(f"Failed to extract REQUIRED resource {internal_path} from {pak_name}") from e
                else:
                    return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}

            format_ext = res.resourceFormat.upper()
            converted_path = dest_path

            if format_ext in ("LSF", "LSB", "LSX"):
                if format_ext != "LSX":
                    if res.sourceRole in ("DialogResource", "BarkContainer"):
                        converted_path = dest_path.with_suffix(".lsj")
                    else:
                        converted_path = dest_path.with_suffix(".lsx")
                    try:
                        backend.convert_resource(dest_path, converted_path)
                    except Exception as e:
                        # Some dialog files contain 0x1E which fails LSJ JSON serialization in Divine.exe, fallback to LSX
                        if converted_path.suffix == ".lsj":
                            converted_path = dest_path.with_suffix(".lsx")
                            try:
                                backend.convert_resource(dest_path, converted_path)
                            except Exception:
                                if pak_name in required_paks or pak_name.startswith("Patch"):
                                    raise RuntimeError(f"Failed to convert REQUIRED resource {dest_path}") from e
                                else:
                                    return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}
                        elif pak_name in required_paks or pak_name.startswith("Patch"):
                            raise RuntimeError(f"Failed to convert REQUIRED resource {dest_path}") from e
                        else:
                            return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}

            elif format_ext == "LOCA":
                converted_path = dest_path.with_suffix(".xml")
                try:
                    backend.convert_loca(dest_path, converted_path)
                except Exception as e:
                    if pak_name in required_paks:
                        raise RuntimeError(f"Failed to convert REQUIRED LOCA {dest_path}") from e
                    else:
                        return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}

            try:
                with open(converted_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                if pak_name in required_paks:
                    raise RuntimeError(f"Failed to read REQUIRED resource {converted_path}") from e
                return {"mappings": [], "loca": {}, "aux_loca": {}, "story_occ": [], "old_text": set(), "text_cache": None}

            role = res.sourceRole
            new_mappings: list[ResearchMapping] = []
            new_loca: dict[str, dict[str, str]] = {}
            new_aux_loca: dict[str, dict[str, str]] = {}
            new_story_occ: list[StoryOccurrence] = []
            new_old_text: set[str] = set()
            text_cache_info = None

            # Cache stats and candidate text for context extraction
            lower_path = internal_path.lower()
            if pak_name == "GustavX.pak" and "/stats/generated/data/" in lower_path:
                text_cache_info = ("gustavx", internal_path, content)
            elif pak_name == "Shared.pak" and (
                "/stats/generated/data/" in lower_path or
                "story/dialogs/crimes/" in lower_path or
                "content/ui/" in lower_path
            ):
                text_cache_info = ("shared", internal_path, content)
            elif pak_name == "Gustav.pak" and lower_path.endswith("/passive.txt"):
                text_cache_info = ("passive", internal_path, content)

            # Role-specific parsing
            if role == "StatsResource":
                new_mappings.extend(parse_stats_text(content, resource_path=internal_path, provider=pak_name))
            elif role == "DialogResource":
                if converted_path.suffix == ".lsj":
                    try:
                        dialog_data = json.loads(content)
                        new_mappings.extend(traverse_dialog_json(dialog_data, resource_path=internal_path, pak_name=pak_name))
                    except Exception as e:
                        if pak_name in required_paks:
                            raise RuntimeError(f"Failed to parse REQUIRED LSJ {converted_path}") from e
                # Check for OldText attributes in dialog XML/LSX/LSJ
                for m in re.finditer(r'OldText.*?handle="(?P<uid>h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12})"', content):
                    new_old_text.add(m.group("uid"))
            elif role == "BarkContainer":
                if converted_path.suffix == ".lsj":
                    try:
                        dialog_data = json.loads(content)
                        new_mappings.extend(parse_bark_container(dialog_data, internal_path=internal_path, pak_name=pak_name))
                    except Exception as e:
                        if pak_name in required_paks:
                            raise RuntimeError(f"Failed to parse REQUIRED LSJ bark {converted_path}") from e
            elif role in ("QuestJournalResource", "JournalQuest"):
                if converted_path.suffix.lower() in (".lsx", ".xml"):
                    new_mappings.extend(parse_quest_xml(content, resource_path=internal_path, pak_name=pak_name))
            elif role == "UiResource":
                new_mappings.extend(parse_ui_skill_xml(content, resource_path=internal_path, provider=pak_name))
            elif role in ("SourceLocalization", "TargetLocalization", "ReferenceLocalization"):
                actual_locale = ""
                if f"/{source_locale.lower()}/" in lower_path:
                    actual_locale = source_locale
                elif f"/{target_locale.lower()}/" in lower_path:
                    actual_locale = target_locale
                else:
                    for ref in reference_locales:
                        if f"/{ref.lower()}/" in lower_path:
                            actual_locale = ref
                            break
                if actual_locale:
                    new_loca[actual_locale] = parse_loca_xml(content)
            elif role in ("AuxiliarySourceLocalization", "AuxiliaryTargetLocalization", "AuxiliaryReferenceLocalization"):
                actual_locale = ""
                if f"/{source_locale.lower()}/" in lower_path:
                    actual_locale = source_locale
                elif f"/{target_locale.lower()}/" in lower_path:
                    actual_locale = target_locale
                else:
                    for ref in reference_locales:
                        if f"/{ref.lower()}/" in lower_path:
                            actual_locale = ref
                            break
                if actual_locale:
                    new_aux_loca[actual_locale] = parse_loca_xml(content)

            # Story occurrence extraction
            if "story/" in lower_path:
                for match in re.finditer(r'(?P<uid>h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12})', content):
                    suid = match.group("uid")
                    new_story_occ.append(StoryOccurrence(
                        contentUid=suid,
                        sourcePak=pak_name,
                        internalPath=internal_path,
                        resourceType=format_ext,
                        storyDomain="MainStory" if "mainstory" in lower_path or "dialog" in lower_path else "ContextSupportOnly",
                        hasDialog="dialog" in lower_path,
                        hasQuest="journal" in lower_path,
                    ))

            return {
                "mappings": new_mappings,
                "loca": new_loca,
                "aux_loca": new_aux_loca,
                "story_occ": new_story_occ,
                "old_text": new_old_text,
                "text_cache": text_cache_info,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
            futures = []
            for pak_name, res_list in paks.items():
                pak_path = get_pak_path(pak_name)
                if not pak_path.is_file():
                    if pak_name in required_paks:
                        raise RuntimeError(f"Required package {pak_path} not found.")
                    continue
                for res in res_list:
                    futures.append(executor.submit(process_resource, res, pak_path, pak_name))

            for f in concurrent.futures.as_completed(futures):
                r = f.result()
                mappings.extend(r["mappings"])
                for k, v in r["loca"].items():
                    loca_records.setdefault(k, {}).update(v)
                for k, v in r["aux_loca"].items():
                    aux_loca_records.setdefault(k, {}).update(v)
                old_text_uids.update(r["old_text"])
                tc = r["text_cache"]
                if tc:
                    category, ipath, ctext = tc
                    if category == "gustavx":
                        gustavx_stats_texts.append((ipath, ctext))
                    elif category == "shared":
                        shared_candidate_texts.append((ipath, ctext))
                    elif category == "passive":
                        gustav_passive_texts.append((ipath, ctext))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


    # 1. Reuse Conflict Analysis (CONFLICT-001)
    source_loca = loca_records.get(source_locale, {})
    target_loca = loca_records.get(target_locale, {})

    conflict_res = derive_reuse_conflict_groups(source_loca, target_loca)
    conflict_001_uids = conflict_res.conflict_001_uids
    other_54_uids = conflict_res.all_conflict_uids - conflict_001_uids

    # 2. Shared Context Extraction (GustavX + Shared)
    shared_context_mappings: list[ResearchMapping] = []
    gustavx_hits: set[str] = set()
    shared_hits: set[str] = set()

    for ipath, text in gustavx_stats_texts:
        for m in extract_shared_context_hits(text, resource_path=ipath, pak_name="GustavX.pak", target_uids=conflict_001_uids):
            shared_context_mappings.append(m)
            gustavx_hits.add(m.contentUid)

    for ipath, text in shared_candidate_texts:
        for m in extract_shared_context_hits(text, resource_path=ipath, pak_name="Shared.pak", target_uids=conflict_001_uids):
            shared_context_mappings.append(m)
            shared_hits.add(m.contentUid)

    shared_context_union = gustavx_hits | shared_hits
    mappings.extend(shared_context_mappings)

    # 3. Passive Context Extraction (Gustav Passives)
    passive_context_mappings: list[ResearchMapping] = []
    passive_gustav_hits: set[str] = set()
    passive_gustavdev_hits: set[str] = set()
    passive_honour_hits: set[str] = set()

    for ipath, text in gustav_passive_texts:
        for m in extract_passive_context_hits(text, resource_path=ipath, pak_name="Gustav.pak", target_uids=conflict_001_uids):
            passive_context_mappings.append(m)
            lower_p = ipath.lower()
            if "/gustavdev/" in lower_p:
                passive_gustavdev_hits.add(m.contentUid)
            elif "/honour/" in lower_p:
                passive_honour_hits.add(m.contentUid)
            else:
                passive_gustav_hits.add(m.contentUid)

    passive_context_union = passive_gustav_hits | passive_gustavdev_hits | passive_honour_hits
    mappings.extend(passive_context_mappings)

    # 4. Quest Context Candidates
    uncovered_c001 = conflict_001_uids - shared_context_union - passive_context_union
    quest_raw_mappings = [m for m in mappings if m.mappingType == "quest-journal"]
    quest_context_candidates = filter_quest_context_candidates(
        quest_raw_mappings,
        uncovered_target_uids=uncovered_c001
    )
    quest_94_uids = set(m.contentUid for m in quest_context_candidates)

    # 5. Dialog / Bark Context for Other 54 groups
    # Only include UIDs with real game-derived dialog/bark evidence.
    # No synthetic fallback — a mapping may exist only if actual game evidence was found.
    dialog_bark_by_uid: dict[str, ResearchMapping] = {
        m.contentUid: m for m in mappings
        if m.mappingType in ("dialog-context", "bark-speaker") and m.contentUid in other_54_uids
    }
    dialog_bark_mappings: list[ResearchMapping] = [
        dialog_bark_by_uid[uid] for uid in other_54_uids if uid in dialog_bark_by_uid
    ]
    other_54_without_evidence: set[str] = other_54_uids - set(dialog_bark_by_uid)
    dialog_bark_evidence_uids: set[str] = set(dialog_bark_by_uid)
    dialog_bark_289_uids: set[str] = set(m.contentUid for m in dialog_bark_mappings)

    # 6. Multilingual References
    ref_loca_dicts = {ref: loca_records.get(ref, {}) for ref in reference_locales}
    multi_mappings = list(align_multilingual_references(
        source_records=source_loca,
        target_records=target_loca,
        reference_records_by_locale=ref_loca_dicts,
        target_boundary_uids=set(source_loca) - set(target_loca)
    ))
    mappings.extend(multi_mappings)

    # 7. Context Aggregator — union derived from real game evidence only.
    # Shared + Passive + Quest + Dialog/Bark (evidence-backed only; no synthetic fallback).
    ctx_agg = ContextAggregator()
    ctx_agg.add_mappings(shared_context_mappings)
    ctx_agg.add_mappings(passive_context_mappings)
    ctx_agg.add_mappings(quest_context_candidates)
    # Only real game-derived dialog/bark mappings; no fabricated fallback.
    ctx_agg.add_mappings(dialog_bark_mappings)

    context_unified_mappings = ctx_agg.get_mappings()
    mappings.extend(context_unified_mappings)
    ctx_summary = ctx_agg.summary()

    # 8. Complete UI / Skill provider and relation universe.  This inventory is
    # independent of the narrower cross-domain scan and retains every collision
    # provider.  AQ routing is derived from current locale and context evidence.
    ui_skill_result = extract_ui_skill_universe(game_dir, backend, output_dir)
    ui_skill_reconciliation = reconcile_ui_skill_runtime(
        game_dir,
        backend,
        ui_skill_result.providers,
        ui_skill_result.direct_occurrences,
    )
    ui_skill_result.materialized_occurrences = list(
        ui_skill_reconciliation.materialized_occurrences
    )
    ui_skill_result.hold_uids = set(ui_skill_reconciliation.hold_uids)
    ui_skill_warning_uids = set(ui_skill_reconciliation.warning_uids)
    aq_reuse = derive_reuse_conflict_boundary(source_loca, target_loca)
    accepted_context = accepted_context_coverage(
        shared_uids=shared_context_union,
        passive_uids=passive_context_union,
        dialog_bark_uids=dialog_bark_evidence_uids,
        quest_uids=quest_94_uids,
    )
    aq_boundary = derive_aq_boundary(aq_reuse.exact_conflict_uids, accepted_context)
    resource_uids = ui_skill_result.unique_uids
    aq_resource_referenced = derive_aq_resource_referenced(aq_boundary, resource_uids)

    # Phase 4AV TargetDisposition priority:
    # Existing383 authority -> AQ routing -> Hold -> New candidate.
    # Higher-priority routed UIDs must not remain precedence hold/warning
    # targets even when their lineage reaches an unresolved inheritance edge.
    priority_routed_uids = (
        set(dialog_bark_289_uids)
        | set(quest_94_uids)
        | set(aq_resource_referenced)
    )
    ui_skill_result.hold_uids.difference_update(priority_routed_uids)
    ui_skill_warning_uids.difference_update(priority_routed_uids)

    locale_hold_uids = resource_uids - set(source_loca)
    locale_context_hold_uids = locale_hold_uids | ui_skill_warning_uids
    all_hold_uids = set(ui_skill_result.hold_uids) | locale_context_hold_uids
    comment_occurrences = [item for item in ui_skill_result.direct_occurrences if item.comment_only]
    ui_skill_relations = [*ui_skill_result.materialized_occurrences, *comment_occurrences]

    ui_skill_provider_path = output_dir / "ui-skill-provider-ledger.csv"
    ui_skill_universe_path = output_dir / "ui-skill-universe.csv"
    write_ui_skill_provider_ledger(ui_skill_provider_path, ui_skill_result.providers)
    write_ui_skill_universe(
        ui_skill_universe_path,
        ui_skill_relations,
        hold_uids=set(ui_skill_result.hold_uids),
        aq_uids=set(aq_resource_referenced),
        locale_hold_uids=locale_context_hold_uids,
    )

    eligible_by_uid: dict[str, list[Any]] = {}
    for item in ui_skill_result.materialized_occurrences:
        if item.content_uid not in all_hold_uids:
            eligible_by_uid.setdefault(item.content_uid, []).append(item)
    ui_workstream_counts: dict[str, int] = {}
    for uid, uid_relations in eligible_by_uid.items():
        workstream = (
            "AQResourceReferencedReview" if uid in aq_resource_referenced
            else classify_workstream(uid_relations)
        )
        ui_workstream_counts[workstream] = ui_workstream_counts.get(workstream, 0) + 1
    format_counts: dict[str, int] = {}
    candidate_format_counts: dict[str, int] = {}
    package_counts: dict[str, int] = {}
    provider_role_counts: dict[str, int] = {}
    for provider in ui_skill_result.providers:
        format_counts[provider.resource_format] = format_counts.get(provider.resource_format, 0) + 1
        package_counts[provider.package] = package_counts.get(provider.package, 0) + 1
        provider_role_counts[provider.role.value] = provider_role_counts.get(provider.role.value, 0) + 1
        if provider.role is UiSkillProviderRole.CANDIDATE_EVIDENCE:
            candidate_format_counts[provider.resource_format] = candidate_format_counts.get(provider.resource_format, 0) + 1
    ui_skill_summary = {
        "providerDiscovery": {
            "functionalProviders": len(ui_skill_result.providers),
            "formats": format_counts,
            "roles": provider_role_counts,
            "candidateParserFormats": candidate_format_counts,
            "packages": package_counts,
            "crossPackageCollisionProviders": sum(item.collision for item in ui_skill_result.providers),
        },
        "references": {
            "rawContentUidLikeReferences": ui_skill_result.raw_reference_count,
            "acceptedPhysicalOccurrences": sum(not item.comment_only for item in ui_skill_result.direct_occurrences),
            "uniqueResourceContentUid": len(resource_uids),
            "commentOnlyExcluded": len(comment_occurrences),
        },
        "inheritance": {
            "inheritanceEdges": len({
                (item.provider, item.entity_name, item.parent_name)
                for item in ui_skill_result.direct_occurrences if item.parent_name and not item.comment_only
            }),
            "candidateDefinitions": ui_skill_reconciliation.candidate_definition_count,
            "supportProviders": ui_skill_reconciliation.support_provider_count,
            "supportDefinitions": ui_skill_reconciliation.support_definition_count,
            "inheritedRelations": ui_skill_reconciliation.inherited_relation_count,
            "ambiguousNonEquivalentEdges": ui_skill_reconciliation.ambiguous_edge_count,
            "selfNameWarningEdges": ui_skill_reconciliation.self_name_warning_edge_count,
            "packageLayerHoldUid": ui_skill_reconciliation.package_layer_hold_count,
            "moduleMetadataCount": ui_skill_reconciliation.module_count,
            "directModuleDependencies": ui_skill_reconciliation.direct_dependency_count,
            "precedenceHoldUid": len(ui_skill_result.hold_uids),
            "contextWarningUid": len(ui_skill_warning_uids),
            "unresolvedPrecedenceUid": len(ui_skill_result.hold_uids),
            "holds": len(all_hold_uids),
        },
        "aq": {
            "sourceOnly": len(aq_reuse.source_only_uids),
            "exactSharedTextCandidate": aq_reuse.exact_candidate_count,
            **aq_reuse.classification_counts,
            "formalExactConflict": len(aq_reuse.exact_conflict_uids),
            "acceptedContextCoverage": len(accepted_context),
            "boundary": len(aq_boundary),
            "resourceReferenced": len(aq_resource_referenced),
            "residualNotReferenced": len(aq_boundary - resource_uids),
        },
        "finalReview": {
            "total": len(eligible_by_uid),
            "workstreams": ui_workstream_counts,
            "duplicateContentUid": 0,
            "maxRelationsPerCandidate": max((len(rows) for rows in eligible_by_uid.values()), default=0),
        },
        "generationInputs": {
            "currentGameResources": True,
            "historicalWorkbook": False,
            "historicalUidList": False,
            "historicalGeneratedReviewPackage": False,
        },
    }
    ui_skill_summary_path = output_dir / "ui-skill-universe-summary.json"
    ui_skill_summary_path.write_text(
        json.dumps(ui_skill_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 9. Story Universe Partitioning & Residual Resolution
    # ExistingAuthority = evidence-backed Dialog/Bark UIDs | evidence-backed Quest UIDs.
    # No fabricated dialog mappings may enter Story partitioning.
    existing_383 = dialog_bark_289_uids | quest_94_uids

    # Build cross-domain extraction context from runtime information already available.
    # The context carries all provenance needed for cache-key identity.
    _cd_cache = CrossDomainUniverseCache()
    _cd_ctx = CrossDomainExtractionContext(
        game_dir=game_dir,
        backend=backend,
        resources=resources,
        build_id=runtime_meta.get("buildId", "local"),
        game_version=runtime_meta.get("gameVersion", "unknown"),
        scan_manifest_sha256=_scan_sha256,
    )

    # Query cross-domain target universe (derived live from game resources with inheritance closure)
    cross_domain_result = extract_cross_domain_result(_cd_ctx, cache=_cd_cache)
    cross_domain_targets = cross_domain_result.targets_by_uid
    other_domain_targets = set(cross_domain_targets.keys())

    # Write cross-domain-entity-layer-audit.csv (layered entity definitions before effective provider materialization)
    cross_domain_entity_layer_audit_path = output_dir / "cross-domain-entity-layer-audit.csv"
    with open(cross_domain_entity_layer_audit_path, "w", encoding="utf-8", newline="") as eaf:
        eaw = csv.writer(eaf)
        eaw.writerow([
            "Entity", "Provider", "InternalPath", "Priority", "Using",
            "ExplicitFieldCount", "SelectedAsEffective", "OverrideReason"
        ])
        for rec in cross_domain_result.layer_audit_records:
            eaw.writerow([
                rec.entity,
                rec.provider,
                rec.internalPath,
                rec.priority,
                rec.using,
                rec.explicitFieldCount,
                rec.selectedAsEffective,
                rec.overrideReason,
            ])

    # Write cross-domain-materialization.csv (all relations including inherited closure and provider overrides)
    cross_domain_materialization_path = output_dir / "cross-domain-materialization.csv"
    with open(cross_domain_materialization_path, "w", encoding="utf-8", newline="") as pmf:
        pmw = csv.writer(pmf)
        pmw.writerow([
            "ContentUid", "Classification", "Domain", "EffectiveProvider", "DefiningProvider",
            "InternalPath", "Entity", "Field", "InheritedFrom",
            "InheritanceDepth", "ExplicitOrInherited", "ProviderOverrideApplied"
        ])
        for rel in cross_domain_result.relations:
            pmw.writerow([
                rel.contentUid,
                rel.classification,
                rel.domain,
                rel.effectiveProvider,
                rel.definingProvider,
                rel.internalPath,
                rel.entity,
                rel.field,
                rel.inheritedFrom,
                rel.inheritanceDepth,
                rel.explicitOrInherited,
                rel.providerOverrideApplied,
            ])

    # Write cross-domain-universe.csv (late deduplicated ContentUid targets)
    cross_domain_universe_path = output_dir / "cross-domain-universe.csv"
    with open(cross_domain_universe_path, "w", encoding="utf-8", newline="") as pf:
        pw = csv.writer(pf)
        pw.writerow(["ContentUid", "Classification", "Domain", "Provider", "InternalPath", "Entity", "Field", "InheritedFrom", "RuleId"])
        for tgt in sorted(cross_domain_targets.values(), key=lambda t: t.contentUid):
            pw.writerow([
                tgt.contentUid,
                tgt.classification,
                tgt.domain,
                tgt.provider,
                tgt.internalPath,
                tgt.entity,
                tgt.field,
                tgt.inheritedFrom,
                tgt.ruleId,
            ])

    # Write cross-domain-coverage-reconciliation.csv
    cross_domain_reconciliation_path = output_dir / "cross-domain-coverage-reconciliation.csv"
    with open(cross_domain_reconciliation_path, "w", encoding="utf-8", newline="") as prf:
        prw = csv.writer(prf)
        prw.writerow(["ContentUid", "Classification", "Domain", "Provider", "InternalPath", "Entity", "Field", "Reason"])
        for tgt in sorted(cross_domain_targets.values(), key=lambda t: t.contentUid):
            if tgt.classification == "HistoricalCompatibilityReference":
                if tgt.field.lower() == "gamemasterspawnsubsection":
                    reason = "HistoricalGameMasterMetadata"
                else:
                    reason = "HistoricalDialogKeywordHeuristic"
            else:
                if tgt.domain == "ProgressionUI":
                    reason = "ProgressionDescriptionLocalization"
                elif "Game.pak" in tgt.provider:
                    reason = "GamePakUIXaml"
                elif tgt.field in ("OnUseDescription", "DisplayNameAlchemy", "TechnicalDescription", "UnknownDescription", "UnknownDisplayName"):
                    reason = "RootTemplatesSemanticField"
                elif tgt.inheritedFrom:
                    reason = "StatsInheritedClosure"
                else:
                    reason = "SemanticPlayerFacingDefinition"
            prw.writerow([
                tgt.contentUid,
                tgt.classification,
                tgt.domain,
                tgt.provider,
                tgt.internalPath,
                tgt.entity,
                tgt.field,
                reason,
            ])

    unique_story_uids = set(o.contentUid for o in story_occurrences)

    # Dynamically derive cross domain references
    # Uses full reproduction universe (semantic + historical compatibility)
    other_domain_targets = cross_domain_result.reproduction_universe_uids
    cross_domain_uids = derive_cross_domain_references(
        unique_story_uids,
        other_domain_targets,
        existing_383_uids=existing_383,
    )

    # Partition story universe dynamically without hardcoded historical lists
    story_partition = partition_story_universe(
        story_occurrences,
        english_records=source_loca,
        existing_383_uids=existing_383,
        cross_domain_uids=cross_domain_uids,
        known_context_holds=None,
    )

    partitioned_cross_domain_set = set(story_partition.cross_domain_references)
    cross_domain_semantic = partitioned_cross_domain_set & cross_domain_result.semantic_target_uids
    cross_domain_historical = partitioned_cross_domain_set & cross_domain_result.historical_compatibility_uids

    occ_by_uid: dict[str, list[StoryOccurrence]] = {}
    for o in story_occurrences:
        occ_by_uid.setdefault(o.contentUid, []).append(o)

    res_result, residual_mappings = resolve_residual_story_holds(
        story_partition,
        english_records=source_loca,
        occurrences_by_uid=occ_by_uid,
        old_text_uids=old_text_uids,
        auxiliary_locales=aux_loca_records,
    )
    mappings.extend(residual_mappings)

    # Output writing
    jsonl_path = output_dir / "research-mappings.jsonl"
    write_mappings_jsonl(mappings, str(jsonl_path))

    # Write story-context-hold-candidate-audit.csv and story-context-hold-evidence.csv
    candidate_audit_path = output_dir / "story-context-hold-candidate-audit.csv"
    context_hold_evidence_path = output_dir / "story-context-hold-evidence.csv"

    with open(candidate_audit_path, "w", encoding="utf-8", newline="") as caf, \
         open(context_hold_evidence_path, "w", encoding="utf-8", newline="") as chf:
        caw = csv.writer(caf)
        chw = csv.writer(chf)
        caw.writerow([
            "ContentUid", "PakName", "InternalPath", "ResourceFamily", "AttributeRole",
            "StoryDomain", "EnglishState", "CandidateRule", "FinalDisposition", "Reason"
        ])
        chw.writerow([
            "ContentUid", "PakName", "InternalPath", "ResourceFamily", "AttributeRole",
            "EnglishState", "Reason", "Classification"
        ])
        for uid in story_partition.story_context_holds:
            u_occs = occ_by_uid.get(uid, [])
            primary_occ = u_occs[0] if u_occs else None
            p_pak = primary_occ.sourcePak if primary_occ else ""
            p_path = primary_occ.internalPath if primary_occ else ""
            p_fam = primary_occ.resourceType if primary_occ else ""
            p_role = primary_occ.attributeRole if primary_occ else ""
            p_dom = primary_occ.storyDomain if primary_occ else ""
            eng_val = source_loca.get(uid)
            eng_state = "Missing" if eng_val is None else ("EmptySentinel" if eng_val == "%%% EMPTY" else "Empty")
            if uid in res_result.requires_external_runtime_evidence:
                cls_name = "RequiresExternalRuntimeEvidence"
                reason_str = "Static resource role exists across multiple providers/telemetry; runtime selection requires instrumentation"
                cand_rule = "RootTemplatesMultiPakOrTelemetry"
            elif uid in res_result.proven_context_support_only:
                cls_name = "ProvenContextSupportOnly"
                reason_str = "Exact official English sentinel proves intentional no-display text"
                cand_rule = "TagsCharactersEmptySentinel"
            else:
                cls_name = "RetainedResidualHold"
                reason_str = "Localized template attribute has no official English source"
                cand_rule = "RootTemplatesMissingEnglish"

            caw.writerow([
                uid, p_pak, p_path, p_fam, p_role, p_dom, eng_state, cand_rule, cls_name, reason_str
            ])
            chw.writerow([uid, p_pak, p_path, p_fam, p_role, eng_state, reason_str, cls_name])

    # Write source-unconfirmed-verification.csv
    source_unconfirmed_path = output_dir / "source-unconfirmed-verification.csv"
    with open(source_unconfirmed_path, "w", encoding="utf-8", newline="") as suf:
        suw = csv.writer(suf)
        suw.writerow(["ContentUid", "EnglishPresent", "EnglishNonEmpty", "ActiveOccurrenceCount", "OldTextOccurrenceCount", "StoryDomains", "VerificationRule", "Verified", "Reason"])
        for uid in story_partition.story_source_unconfirmed_holds:
            u_occs = occ_by_uid.get(uid, [])
            eng_val = source_loca.get(uid)
            eng_pres = (uid in source_loca)
            eng_nonempty = bool(eng_val and eng_val != "%%% EMPTY" and eng_val.strip())
            act_cnt = sum(1 for o in u_occs if not o.isOldText)
            old_cnt = sum(1 for o in u_occs if o.isOldText)
            dom_str = ";".join(sorted(set(o.storyDomain for o in u_occs)))
            is_cleared = uid in res_result.cleared_for_translation_supplement
            reas = "ClearedForTranslationSupplement" if is_cleared else "RetainedResidualHold"
            suw.writerow([
                uid,
                "true" if eng_pres else "false",
                "true" if eng_nonempty else "false",
                act_cnt,
                old_cnt,
                dom_str,
                "BG3-STORY-SOURCE-UNCONFIRMED-VERIFICATION",
                "true" if is_cleared else "false",
                reas,
            ])

    # Diagnostics generation: story-resource-audit.csv, story-domain-summary.csv, cross-domain-summary.csv
    # 1. story-domain-summary.csv
    domain_agg: dict[str, dict[str, Any]] = {}
    res_audit_agg: dict[tuple[str, str], dict[str, Any]] = {}
    for occ in story_occurrences:
        d = occ.storyDomain
        if d not in domain_agg:
            domain_agg[d] = {"occurrences": 0, "uids": set()}
        domain_agg[d]["occurrences"] += 1
        domain_agg[d]["uids"].add(occ.contentUid)

        rk = (occ.sourcePak, occ.internalPath)
        if rk not in res_audit_agg:
            res_audit_agg[rk] = {
                "pakName": occ.sourcePak,
                "internalPath": occ.internalPath,
                "resourceType": occ.resourceType,
                "storyDomain": d,
                "occurrences": 0,
                "uids": set(),
            }
        res_audit_agg[rk]["occurrences"] += 1
        res_audit_agg[rk]["uids"].add(occ.contentUid)

    domain_summary_path = output_dir / "story-domain-summary.csv"
    with open(domain_summary_path, "w", encoding="utf-8", newline="") as df:
        dw = csv.writer(df)
        dw.writerow(["StoryDomain", "OccurrenceCount", "UniqueUidCount"])
        for dom, dinfo in sorted(domain_agg.items()):
            dw.writerow([dom, dinfo["occurrences"], len(dinfo["uids"])])

    # 2. cross-domain-summary.csv
    cross_domain_summary_path = output_dir / "cross-domain-summary.csv"
    with open(cross_domain_summary_path, "w", encoding="utf-8", newline="") as cdf:
        cdw = csv.writer(cdf)
        cdw.writerow(["Metric", "Count", "RuleId"])
        cdw.writerow(["StoryUniverseUniqueUids", story_partition.total_unique_story_uids, "BG3-STORY-MATERIAL-PARTITION"])
        cdw.writerow(["CrossDomainUniverse", len(other_domain_targets), "BG3-CROSS-DOMAIN-UNIVERSE"])
        cdw.writerow(["CrossDomainSemanticUniverse", len(cross_domain_result.semantic_target_uids), "BG3-CROSS-DOMAIN-UNIVERSE"])
        cdw.writerow(["CrossDomainHistoricalCompatibilityUniverse", len(cross_domain_result.historical_compatibility_uids), "BG3-CROSS-DOMAIN-HISTORICAL-COMPATIBILITY"])
        cdw.writerow(["CrossDomainReference", len(story_partition.cross_domain_references), "BG3-CROSS-DOMAIN-OVERLAP"])
        cdw.writerow(["CrossDomainSemantic", len(cross_domain_semantic), "BG3-CROSS-DOMAIN-SEMANTIC"])
        cdw.writerow(["CrossDomainHistoricalCompatibility", len(cross_domain_historical), "BG3-CROSS-DOMAIN-HISTORICAL-COMPATIBILITY"])
        cdw.writerow(["ExistingAuthorityExcluded", len(existing_383), "BG3-EXISTING-AUTHORITY-EXCLUSION"])

    # 3. story-resource-audit.csv
    resource_audit_path = output_dir / "story-resource-audit.csv"
    with open(resource_audit_path, "w", encoding="utf-8", newline="") as raf:
        raw = csv.writer(raf)
        raw.writerow(["PakName", "InternalPath", "ResourceType", "Included", "InclusionRule", "ExclusionRule", "OccurrenceCount", "UniqueUidCount", "StoryDomain"])
        for res in resources:
            rk = (res.pakName, res.internalPath)
            info = res_audit_agg.get(rk)
            occs_cnt = info["occurrences"] if info else 0
            uids_cnt = len(info["uids"]) if info else 0
            dom_val = info["storyDomain"] if info else (res.sourceRole or "Unknown")
            is_story = res.sourceRole in ("Cinematics", "DialogsBinary", "DialogsRaw", "JournalQuest", "LevelResources", "LocalizationRegistry", "ReadableLocalizationRegistry", "RootTemplates", "StoryGoals", "TagsCharacters")
            inc_rule = f"SourceFamily:{res.sourceRole}" if is_story else "NonStoryScopedResource"
            raw.writerow([res.pakName, res.internalPath, res.resourceFormat, "true" if is_story else "false", inc_rule, "none", occs_cnt, uids_cnt, dom_val])

    mapping_counts: dict[str, int] = {"total": len(mappings)}
    for m in mappings:
        mapping_counts[m.mappingType] = mapping_counts.get(m.mappingType, 0) + 1

    summary_dict = {
        "appId": runtime_meta["appId"],
        "buildId": runtime_meta["buildId"],
        "gameVersion": runtime_meta["gameVersion"],
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
        "referenceLocales": reference_locales,
        "generationInputs": {
            "gameInstall": True,
            "historicalWorkbooks": False,
            "historicalCsv": False,
            "historicalUidLists": False,
            "embeddedHistoricalUniverse": False,
            "coverageCensusCsvUsedAtRuntime": False,
        },
        "complete": True,
        "mappingCounts": mapping_counts,
        "reuseConflict": {
            "sourceOnlyBoundary": conflict_res.source_only_count,
            "sharedCount": conflict_res.shared_count,
            "reuseConflictItems": conflict_res.conflict_items_count,
            "reuseConflictGroups": len(conflict_res.conflict_groups),
            "conflict001Members": len(conflict_001_uids),
            "singleReuseCount": conflict_res.single_reuse_count,
            "consensusReuseCount": conflict_res.consensus_reuse_count,
            "noCandidateCount": conflict_res.no_candidate_count,
        },
        "sharedContext": {
            "gustavX": len(gustavx_hits),
            "shared": len(shared_hits),
            "union": len(shared_context_union),
            "ruleId": "BG3-SHARED-CONTEXT-CONFLICT-REFERENCE",
        },
        "passiveContext": {
            "gustav": len(passive_gustav_hits),
            "gustavDev": len(passive_gustavdev_hits),
            "honour": len(passive_honour_hits),
            "union": len(passive_context_union),
            "ruleId": "BG3-PASSIVE-CONTEXT-GUSTAV-REFERENCE",
        },
        "context": ctx_summary,
        "dialogEvidence": {
            "other54Universe": len(other_54_uids),
            "realEvidenceUids": len(dialog_bark_evidence_uids),
            "missingEvidenceUids": len(other_54_without_evidence),
            "fabricatedFallbackRemaining": 0,
            "evidenceRecords": len(dialog_bark_mappings),
        },
        "existingAuthority": {
            "dialogBarkEvidenceBacked": len(dialog_bark_289_uids),
            "questEvidenceBacked": len(quest_94_uids),
            "actual": len(existing_383),
        },
        "story": {
            "rawOccurrences": len(story_occurrences),
            "uniqueUniverse": story_partition.total_unique_story_uids,
            "newStoryTranslationTarget": len(story_partition.new_story_translation_targets),
            "existingAuthority": len(story_partition.existing_authority_targets),
            "crossDomainReference": len(story_partition.cross_domain_references),
            "crossDomainSemantic": len(cross_domain_semantic),
            "crossDomainHistoricalCompatibility": len(cross_domain_historical),
            "storyHold": story_partition.total_holds,
            "holds": {
                "storyContextHold": len(story_partition.story_context_holds),
                "storyMissingEnglishHold": len(story_partition.story_missing_english_holds),
                "storySourceUnconfirmedHold": len(story_partition.story_source_unconfirmed_holds),
            },
            "resolution": {
                "clearedForTranslationSupplement": len(res_result.cleared_for_translation_supplement),
                "provenContextSupportOnly": len(res_result.proven_context_support_only),
                "retainedResidualHold": len(res_result.retained_residual_holds),
                "requiresExternalRuntimeEvidence": len(res_result.requires_external_runtime_evidence),
            },
        },
        "crossDomain": {
            "semanticUniverse": len(cross_domain_result.semantic_target_uids),
            "historicalCompatibilityUniverse": len(cross_domain_result.historical_compatibility_uids),
            "reproductionUniverse": len(cross_domain_result.reproduction_universe_uids),
            "relationsCount": len(cross_domain_result.relations),
            "effectiveEntities": cross_domain_result.effective_entities,
        },
        "uiSkill": ui_skill_summary,
    }

    # Ledger provenance — bind ledger to appId/buildId/gameVersion/scan manifest hash
    _ledger_sha256 = ""
    if story_ledger_file.is_file():
        h = hashlib.sha256()
        h.update(story_ledger_file.read_bytes())
        _ledger_sha256 = h.hexdigest()
    # _scan_sha256 already computed early in this function for cross-domain provenance
    summary_dict["ledgerProvenance"] = {
        "appId": runtime_meta["appId"],
        "buildId": runtime_meta["buildId"],
        "gameVersion": runtime_meta["gameVersion"],
        "ledgerPath": str(story_ledger_file),
        "ledgerSHA256": _ledger_sha256,
        "scanManifestPath": str(scan_path),
        "scanManifestSHA256": _scan_sha256,
    }

    summary_dict["diagnostics"] = {
        "crossDomainUniverse": str(cross_domain_universe_path),
        "crossDomainCoverageReconciliation": str(cross_domain_reconciliation_path),
        "crossDomainMaterialization": str(cross_domain_materialization_path),
        "crossDomainEntityLayerAudit": str(cross_domain_entity_layer_audit_path),
        "uiSkillProviderLedger": str(ui_skill_provider_path),
        "uiSkillUniverse": str(ui_skill_universe_path),
        "uiSkillUniverseSummary": str(ui_skill_summary_path),
        "storyContextHoldEvidence": str(context_hold_evidence_path),
        "storyContextHoldCandidateAudit": str(candidate_audit_path),
        "sourceUnconfirmedVerification": str(source_unconfirmed_path),
        "storyResourceAudit": str(resource_audit_path),
        "storyDomainSummary": str(domain_summary_path),
        "crossDomainSummary": str(cross_domain_summary_path),
    }
    summary_dict["warnings"] = []
    summary_dict["errors"] = []

    summary_path = output_dir / "research-summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, indent=2, ensure_ascii=False)

    print(f"Research mapping complete. Emitted {len(mappings)} mappings to {jsonl_path}")
    return 0
