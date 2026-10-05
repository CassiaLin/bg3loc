from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from bg3loc.commands.research import (
    ResearchBatchRequest,
    ResearchClassifyRequest,
    run_research_batch_request,
    run_research_classify_request,
)
from bg3loc.commands.translation_state import run_init
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.production_context import materialize_contexts
from bg3loc.research.classification_resolution import resolve_unclassified
from bg3loc.ruleset_io import load_ruleset
from bg3loc.production_workspace import (
    batch_materials_fingerprint,
    execution_inventory_fingerprint,
)


@dataclass(frozen=True, slots=True)
class ProductionPrepareRequest:
    extract_manifest: Path
    source: Path
    research_mappings: Path
    ruleset: Path
    output_dir: Path
    story_ledger: Path | None = None
    ui_skill_universe: Path | None = None
    unclassified_decisions: Path | None = None
    max_records: tuple[str, ...] = ()
    structural_provenance: Path | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _count_jsonl(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as handle:
        return sum(1 for line in handle if line.strip())


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")


def _manifest_source_path(
    extract_payload: dict[str, Any],
    *,
    manifest_path: Path,
    source_locale: str,
) -> Path:
    for item in extract_payload.get("locales", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("localeId", "")).casefold() != source_locale.casefold():
            continue
        raw = str(item.get("normalized", "")).strip()
        if not raw:
            break
        path = Path(raw)
        return path if path.is_absolute() else manifest_path.parent / path
    raise RuntimeError(
        f"extract manifest has no normalized source path for locale {source_locale}"
    )


def prepare_production_workspace(request: ProductionPrepareRequest) -> dict[str, Any]:
    _require_file(request.extract_manifest, "extract manifest")
    _require_file(request.source, "normalized source")
    if not request.research_mappings.is_file():
        raise RuntimeError(
            f"research mappings not found: {request.research_mappings}; "
            "run 'bg3loc research scan' then 'bg3loc research map' on your game installation"
        )
    _require_file(request.ruleset, "ruleset")
    if request.structural_provenance is not None:
        for name in ("structural-definitions.jsonl", "structural-occurrences.jsonl"):
            _require_file(request.structural_provenance / name, "public structural provenance")
    research_dir = request.research_mappings.parent
    effective_story_ledger = request.story_ledger
    if effective_story_ledger is None:
        sibling = research_dir / "story-occurrence-ledger.csv"
        effective_story_ledger = sibling if sibling.is_file() else None
    effective_ui_skill_universe = request.ui_skill_universe
    if effective_ui_skill_universe is None:
        sibling = research_dir / "ui-skill-universe.csv"
        effective_ui_skill_universe = sibling if sibling.is_file() else None

    if effective_story_ledger is not None:
        _require_file(effective_story_ledger, "story ledger")
    if effective_ui_skill_universe is not None:
        _require_file(effective_ui_skill_universe, "UI-skill universe")
    if request.unclassified_decisions is not None:
        _require_file(request.unclassified_decisions, "unclassified decisions")

    output = request.output_dir
    if output.exists() and not output.is_dir():
        raise RuntimeError(f"production output path is not a directory: {output}")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(
            f"production output directory is not empty; use a fresh directory: {output}"
        )
    output.mkdir(parents=True, exist_ok=True)

    manifest_path = output / "production-manifest.json"
    if manifest_path.exists():
        raise RuntimeError(f"production manifest already exists: {manifest_path}")

    extract_payload = _load_json(request.extract_manifest)
    source_locale = str(extract_payload.get("sourceLocale", "")).strip()
    target_locale = str(extract_payload.get("targetLocale", "")).strip()
    if not source_locale:
        raise RuntimeError("extract manifest missing sourceLocale")
    if request.structural_provenance is not None and source_locale.casefold() != "english":
        raise RuntimeError("same-entity context requires normalized English source")
    if not target_locale:
        raise RuntimeError("extract manifest missing targetLocale")

    manifest_source = _manifest_source_path(
        extract_payload,
        manifest_path=request.extract_manifest,
        source_locale=source_locale,
    )
    if manifest_source.resolve() != request.source.resolve():
        raise RuntimeError(
            "normalized source does not match the source artifact recorded by extract manifest: "
            f"manifest={manifest_source} requested={request.source}"
        )

    ruleset = load_ruleset(request.ruleset)
    if ruleset.source_locale.casefold() != source_locale.casefold():
        raise RuntimeError(
            f"ruleset sourceLocale mismatch: extract={source_locale} "
            f"ruleset={ruleset.source_locale}; edit the ruleset and prepare a fresh workspace"
        )
    if ruleset.target_locale.casefold() != target_locale.casefold():
        raise RuntimeError(
            f"ruleset targetLocale mismatch: extract={target_locale} "
            f"ruleset={ruleset.target_locale}; edit the ruleset and prepare a fresh workspace"
        )

    classification_dir = output / "classification"
    batches_dir = output / "batches"
    inputs_dir = output / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    ruleset_snapshot = inputs_dir / "ruleset.json"
    shutil.copyfile(request.ruleset, ruleset_snapshot)

    run_research_classify_request(
        ResearchClassifyRequest(
            extract_manifest=request.extract_manifest,
            research_mappings=request.research_mappings,
            output_dir=classification_dir,
            story_ledger=effective_story_ledger,
            ui_skill_universe=effective_ui_skill_universe,
        )
    )

    automatic_classification = classification_dir / "functional-classification.jsonl"
    classification_summary_path = (
        classification_dir / "functional-classification-summary.json"
    )
    batch_classification = automatic_classification
    resolved_classification: Path | None = None

    if request.unclassified_decisions is not None:
        resolved_classification = classification_dir / "resolved-classification.jsonl"
        resolve_unclassified(
            classification_path=automatic_classification,
            decisions_path=request.unclassified_decisions,
            output_path=resolved_classification,
        )
        batch_classification = resolved_classification

    run_research_batch_request(
        ResearchBatchRequest(
            classification=batch_classification,
            source=request.source,
            output_dir=batches_dir,
            story_ledger=effective_story_ledger,
            ui_skill_universe=effective_ui_skill_universe,
            research_mappings=request.research_mappings,
            max_records=request.max_records,
        )
    )

    batch_plan = batches_dir / "batch-plan.json"
    batch_summary_path = batches_dir / "batch-summary.json"
    batch_plan_payload = _load_json(batch_plan)
    used_categories = {
        str(batch.get("primaryCategory", ""))
        for batch in batch_plan_payload.get("batches", [])
        if isinstance(batch, dict) and str(batch.get("primaryCategory", ""))
    }
    missing_rules = sorted(
        category for category in used_categories if category not in ruleset.category_rules
    )
    if missing_rules:
        raise RuntimeError(
            "ruleset is missing categoryRules for prepared batches: "
            + ", ".join(missing_rules)
        )

    context_metadata = None
    if request.structural_provenance is not None:
        context_metadata = materialize_contexts(
            batch_plan=batch_plan, classification=batch_classification,
            source=request.source, provenance_dir=request.structural_provenance,
            summary_path=output / "context-materialization-summary.json",
            ui_skill_universe=effective_ui_skill_universe,
        )

    db_path = output / "execution.sqlite3"
    run_init(
        Namespace(
            batch_plan=str(batch_plan),
            db=str(db_path),
            prompt_version="prompt-v1",
            ruleset=str(ruleset_snapshot),
        )
    )

    classification_summary = _load_json(classification_summary_path)
    batch_summary = _load_json(batch_summary_path)
    execution = TranslationExecutionStore(db_path)
    execution_summary = execution.summary()
    execution_metadata = execution.get_metadata()

    manifest: dict[str, Any] = {
        "schemaVersion": "1.2" if context_metadata is not None else "1.1",
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
        "inputs": {
            "extractManifest": {
                "path": str(request.extract_manifest.resolve()),
                "sha256": _sha256_file(request.extract_manifest),
            },
            "source": {
                "path": str(request.source.resolve()),
                "sha256": _sha256_file(request.source),
            },
            "researchMappings": {
                "path": str(request.research_mappings.resolve()),
                "sha256": _sha256_file(request.research_mappings),
            },
            "ruleset": {
                "path": "inputs/ruleset.json",
                "sha256": _sha256_file(ruleset_snapshot),
                "version": ruleset.version,
                "fingerprint": ruleset.fingerprint(),
            },
        },
        "classification": {
            "automaticPath": "classification/functional-classification.jsonl",
            "automaticSha256": _sha256_file(automatic_classification),
            "resolvedPath": (
                "classification/resolved-classification.jsonl"
                if resolved_classification
                else None
            ),
            "resolvedSha256": (
                _sha256_file(resolved_classification)
                if resolved_classification is not None
                else None
            ),
            "batchInputPath": str(batch_classification.relative_to(output)).replace("\\", "/"),
            "counts": classification_summary.get("statusCounts", {}),
        },
        "batching": {
            "batchPlan": "batches/batch-plan.json",
            "batchPlanSha256": _sha256_file(batch_plan),
            "batchMaterialsFingerprint": batch_materials_fingerprint(batch_plan),
            "batchPlanFingerprint": str(
                batch_plan_payload.get("batchPlanFingerprint", "")
            ),
            "batchCount": int(batch_summary.get("batchCount", 0)),
            "classifiedInputCount": int(
                batch_summary.get("classifiedInputCount", 0)
            ),
            "unresolvedCount": int(batch_summary.get("unresolvedCount", 0)),
            "excludedCount": int(batch_summary.get("excludedCount", 0)),
        },
        "execution": {
            "database": "execution.sqlite3",
            "inventoryFingerprint": execution_inventory_fingerprint(db_path),
            "seededContentUidCount": sum(execution_summary.values()),
            "batchPlanFingerprint": execution_metadata.get(
                "batchPlanFingerprint", ""
            ),
            "rulesetFingerprint": execution_metadata.get(
                "rulesetFingerprint", ""
            ),
        },
    }

    if context_metadata is not None:
        manifest["sameEntityContext"] = context_metadata

    if effective_story_ledger is not None:
        manifest["inputs"]["storyLedger"] = {
            "path": str(effective_story_ledger.resolve()),
            "sha256": _sha256_file(effective_story_ledger),
        }
    if effective_ui_skill_universe is not None:
        manifest["inputs"]["uiSkillUniverse"] = {
            "path": str(effective_ui_skill_universe.resolve()),
            "sha256": _sha256_file(effective_ui_skill_universe),
        }
    if request.unclassified_decisions is not None:
        manifest["inputs"]["unclassifiedDecisions"] = {
            "path": str(request.unclassified_decisions.resolve()),
            "sha256": _sha256_file(request.unclassified_decisions),
        }

    if (
        manifest["batching"]["batchPlanFingerprint"]
        != manifest["execution"]["batchPlanFingerprint"]
    ):
        raise RuntimeError("execution state is not bound to the produced batch plan")
    if (
        manifest["inputs"]["ruleset"]["fingerprint"]
        != manifest["execution"]["rulesetFingerprint"]
    ):
        raise RuntimeError("execution state is not bound to the requested ruleset")
    if (
        manifest["execution"]["seededContentUidCount"]
        != manifest["batching"]["classifiedInputCount"]
    ):
        raise RuntimeError(
            "execution-state row count does not match classified batch input count"
        )

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
