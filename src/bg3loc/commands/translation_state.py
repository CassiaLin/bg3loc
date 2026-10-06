from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bg3loc.execution_runner import run_worker
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.providers.openai_compatible import (
    OpenAICompatibleChatConfig,
    OpenAICompatibleChatProvider,
    openai_compatible_execution_config_hash,
)
from bg3loc.ruleset_io import load_ruleset
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.production_context import context_from_material, material_context_fingerprint
from bg3loc.translation_identity import TranslationInputParameters, translation_input_hash, execution_context_contract


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "translation-state",
        help="Initialize and inspect durable large-scale translation execution state",
    )
    subs = parser.add_subparsers(dest="translation_state_command", required=True)

    init_p = subs.add_parser(
        "init",
        help="Initialize or reconcile an execution database from a batch plan",
    )
    init_p.add_argument("--batch-plan", required=True, help="Path to LSTP-01B batch-plan.json")
    init_p.add_argument("--db", required=True, help="Path to execution.sqlite3")
    init_p.add_argument(
        "--prompt-version",
        default="prompt-v1",
        help="Legacy prompt/rule identity used when --ruleset is not supplied",
    )
    init_p.add_argument(
        "--ruleset",
        help="Versioned ruleset JSON; preferred for real provider execution",
    )
    init_p.set_defaults(handler=run_init)

    summary_p = subs.add_parser("summary", help="Show current translation execution state counts")
    summary_p.add_argument("--db", required=True, help="Path to execution.sqlite3")
    summary_p.set_defaults(handler=run_summary)

    run_start_p = subs.add_parser("run-start", help="Start one execution run")
    run_start_p.add_argument("--db", required=True)
    run_start_p.add_argument("--run-id", required=True)
    run_start_p.add_argument("--batch-plan", required=True)
    run_start_p.add_argument("--provider", required=True)
    run_start_p.add_argument("--model", required=True)
    run_start_p.add_argument("--prompt-version", required=True)
    run_start_p.add_argument("--execution-config-hash")
    run_start_p.set_defaults(handler=run_run_start)

    claim_p = subs.add_parser("claim", help="Claim the next executable ContentUid")
    claim_p.add_argument("--db", required=True)
    claim_p.add_argument("--run-id", required=True)
    claim_p.add_argument("--worker-id", required=True)
    claim_p.add_argument("--lease-seconds", type=int, default=300)
    claim_p.add_argument("--max-attempts", type=int, default=3)
    claim_p.set_defaults(handler=run_claim)

    succeed_p = subs.add_parser("succeed", help="Complete one claimed attempt successfully")
    succeed_p.add_argument("--db", required=True)
    succeed_p.add_argument("--attempt-id", type=int, required=True)
    succeed_p.add_argument("--worker-id", required=True)
    succeed_p.add_argument("--text", required=True)
    succeed_p.add_argument("--provider-request-id")
    succeed_p.set_defaults(handler=run_succeed)

    fail_p = subs.add_parser("fail", help="Complete one claimed attempt as failed")
    fail_p.add_argument("--db", required=True)
    fail_p.add_argument("--attempt-id", type=int, required=True)
    fail_p.add_argument("--worker-id", required=True)
    fail_p.add_argument("--error-code", required=True)
    fail_p.add_argument("--error-message", required=True)
    fail_p.add_argument("--retryable", action="store_true")
    fail_p.add_argument("--max-attempts", type=int, default=3)
    fail_p.add_argument("--provider-request-id")
    fail_p.set_defaults(handler=run_fail)

    recover_p = subs.add_parser("recover", help="Recover expired worker leases")
    recover_p.add_argument("--db", required=True)
    recover_p.set_defaults(handler=run_recover)

    finish_p = subs.add_parser("run-finish", help="Finish a run and derive its completion state")
    finish_p.add_argument("--db", required=True)
    finish_p.add_argument("--run-id", required=True)
    finish_p.set_defaults(handler=run_run_finish)

    oa_start = subs.add_parser(
        "run-start-openai-compatible",
        help="Start an OpenAI-compatible execution run with full non-secret config provenance",
    )
    _add_openai_compatible_common_args(oa_start)
    oa_start.add_argument("--run-id", required=True)
    oa_start.set_defaults(handler=run_openai_compatible_start)

    oa_worker = subs.add_parser(
        "worker-openai-compatible",
        help="Run a translation worker against an OpenAI-compatible chat endpoint",
    )
    _add_openai_compatible_common_args(oa_worker)
    oa_worker.add_argument("--run-id", required=True)
    oa_worker.add_argument("--worker-id", required=True)
    oa_worker.add_argument("--api-key-env", default="BG3LOC_API_KEY")
    oa_worker.add_argument("--lease-seconds", type=int, default=300)
    oa_worker.add_argument("--max-attempts", type=int, default=3)
    oa_worker.add_argument("--max-items", type=int)
    oa_worker.set_defaults(handler=run_openai_compatible_worker)


def _add_openai_compatible_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", required=True)
    parser.add_argument("--batch-plan", required=True)
    parser.add_argument("--ruleset", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--temperature", type=float)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    return rows


def _material_path(batch_plan_path: Path, batch_id: str) -> Path:
    return batch_plan_path.parent / "materials" / f"{batch_id}.jsonl"


def load_execution_items(
    batch_plan_path: Path,
    *,
    prompt_version: str,
    ruleset_fingerprint: str = "",
    source_locale: str = "",
    target_locale: str = "",
) -> tuple[str, list[ExecutionItem]]:
    with batch_plan_path.open("r", encoding="utf-8") as f:
        plan = json.load(f)
    fingerprint = str(plan.get("batchPlanFingerprint", ""))
    if not fingerprint:
        raise RuntimeError("batch plan is missing batchPlanFingerprint")

    seen: set[str] = set()
    items: list[ExecutionItem] = []
    for batch in plan.get("batches", []):
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("batchId", ""))
        if not batch_id:
            raise RuntimeError("batch plan contains a batch without batchId")
        material = _material_path(batch_plan_path, batch_id)
        if not material.is_file():
            raise RuntimeError(f"batch material not found: {material}")

        for row in _read_jsonl(material):
            uid = str(row.get("ContentUid", row.get("contentUid", "")))
            if not uid:
                raise RuntimeError(f"{material}: row missing ContentUid")
            if uid in seen:
                raise RuntimeError(f"duplicate ContentUid across batch materials: {uid}")
            seen.add(uid)

            category = str(row.get("primaryCategory", batch.get("primaryCategory", "")))
            source_text = str(row.get("SourceText", row.get("sourceText", "")))
            protected = row.get("protectedSyntax", row.get("protectedTokens", None))
            input_hash = translation_input_hash(
                content_uid=uid, source_text=source_text, category=category, protected_syntax=protected,
                parameters=TranslationInputParameters(prompt_version, ruleset_fingerprint, source_locale, target_locale),
                context=context_from_material(row),
            )
            items.append(ExecutionItem(uid, batch_id, input_hash))

    expected_count = sum(int(batch.get("recordCount", 0)) for batch in plan.get("batches", []) if isinstance(batch, dict))
    if expected_count and expected_count != len(items):
        raise RuntimeError(
            f"batch material count mismatch: plan={expected_count}, materialRows={len(items)}"
        )
    return fingerprint, items


def run_init(args: argparse.Namespace) -> int:
    batch_plan = Path(args.batch_plan)
    db_path = Path(args.db)
    if not batch_plan.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan}")
    manifest_path = batch_plan.parent.parent / "production-manifest.json"
    if manifest_path.is_file():
        recorded = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if recorded.get("schemaVersion") == "1.2":
            raise RuntimeError("sealed context workspace cannot be reconciled in place; use fresh prepare")

    ruleset = load_ruleset(args.ruleset) if args.ruleset else None
    prompt_version = ruleset.version if ruleset is not None else str(args.prompt_version)
    ruleset_fingerprint = ruleset.fingerprint() if ruleset is not None else ""
    source_locale = ruleset.source_locale if ruleset is not None else ""
    target_locale = ruleset.target_locale if ruleset is not None else ""

    fingerprint, items = load_execution_items(
        batch_plan,
        prompt_version=prompt_version,
        ruleset_fingerprint=ruleset_fingerprint,
        source_locale=source_locale,
        target_locale=target_locale,
    )

    store = TranslationExecutionStore(db_path)
    store.initialize()
    store.seed_items(items, updated_at=f"plan:{fingerprint}")
    store.set_metadata({
        "batchPlanFingerprint": fingerprint,
        "promptVersion": prompt_version,
        "rulesetFingerprint": ruleset_fingerprint,
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
    })
    contract = getattr(args, "context_contract", None)
    if contract is not None:
        store.set_metadata({"executionContextContractFingerprint": contract["contextContractFingerprint"]})

    summary = store.summary()
    total = sum(summary.values())
    print(f"Execution state initialized: {db_path}")
    print(f"Batch plan fingerprint: {fingerprint}")
    print(f"Rows: {total}")
    print(f"Prompt version: {prompt_version}")
    if ruleset is not None:
        print(f"Ruleset fingerprint: {ruleset_fingerprint}")
        print(f"Source locale: {source_locale}")
        print(f"Target locale: {target_locale}")
    for status, count in sorted(summary.items()):
        print(f"{status}: {count}")
    return 0


def run_summary(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.is_file():
        raise RuntimeError(f"execution database not found: {db_path}")
    store = TranslationExecutionStore(db_path)
    summary = store.summary()
    print(f"Execution database: {db_path}")
    print(f"Rows: {sum(summary.values())}")
    for status, count in sorted(summary.items()):
        print(f"{status}: {count}")
    return 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _require_db(path: Path) -> TranslationExecutionStore:
    if not path.is_file():
        raise RuntimeError(f"execution database not found: {path}")
    return TranslationExecutionStore(path)


def _plan_fingerprint(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"batch plan not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    fingerprint = str(payload.get("batchPlanFingerprint", ""))
    if not fingerprint:
        raise RuntimeError("batch plan is missing batchPlanFingerprint")
    return fingerprint


def run_run_start(args: argparse.Namespace) -> int:
    store = _require_db(Path(args.db))
    store.initialize()
    plan = Path(args.batch_plan)
    fingerprint = _plan_fingerprint(plan)
    config_hash = str(args.execution_config_hash or _stable_hash({
        "provider": str(args.provider),
        "model": str(args.model),
        "promptVersion": str(args.prompt_version),
    }))
    started_at = _iso(_utc_now())
    store.start_run(
        run_id=str(args.run_id),
        batch_plan_fingerprint=fingerprint,
        provider=str(args.provider),
        model=str(args.model),
        prompt_version=str(args.prompt_version),
        execution_config_hash=config_hash,
        started_at=started_at,
    )
    print(f"Run started: {args.run_id}")
    print(f"Batch plan fingerprint: {fingerprint}")
    print(f"Provider: {args.provider}")
    print(f"Model: {args.model}")
    return 0


def run_claim(args: argparse.Namespace) -> int:
    if args.lease_seconds <= 0:
        raise RuntimeError("--lease-seconds must be positive")
    if args.max_attempts <= 0:
        raise RuntimeError("--max-attempts must be positive")
    store = _require_db(Path(args.db))
    started = _utc_now()
    claim = store.claim_next(
        run_id=str(args.run_id),
        worker_id=str(args.worker_id),
        lease_expires_at=_iso(started + timedelta(seconds=int(args.lease_seconds))),
        started_at=_iso(started),
        max_attempts=int(args.max_attempts),
    )
    if claim is None:
        print("No executable ContentUid available.")
        return 0
    print(f"attemptId: {claim.attempt_id}")
    print(f"ContentUid: {claim.content_uid}")
    print(f"batchId: {claim.batch_id}")
    print(f"attemptNumber: {claim.attempt_number}")
    print(f"inputHash: {claim.input_hash}")
    print(f"leaseOwner: {claim.lease_owner}")
    print(f"leaseExpiresAt: {claim.lease_expires_at}")
    return 0


def run_succeed(args: argparse.Namespace) -> int:
    store = _require_db(Path(args.db))
    text = str(args.text)
    output_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    store.complete_success(
        attempt_id=int(args.attempt_id),
        worker_id=str(args.worker_id),
        translated_text=text,
        output_hash=output_hash,
        finished_at=_iso(_utc_now()),
        provider_request_id=str(args.provider_request_id) if args.provider_request_id else None,
    )
    print(f"Attempt succeeded: {args.attempt_id}")
    print(f"outputHash: {output_hash}")
    return 0


def run_fail(args: argparse.Namespace) -> int:
    if args.max_attempts <= 0:
        raise RuntimeError("--max-attempts must be positive")
    store = _require_db(Path(args.db))
    status = store.complete_failure(
        attempt_id=int(args.attempt_id),
        worker_id=str(args.worker_id),
        error_code=str(args.error_code),
        error_message=str(args.error_message),
        retryable=bool(args.retryable),
        max_attempts=int(args.max_attempts),
        finished_at=_iso(_utc_now()),
        provider_request_id=str(args.provider_request_id) if args.provider_request_id else None,
    )
    print(f"Attempt failed: {args.attempt_id}")
    print(f"status: {status}")
    return 0


def run_recover(args: argparse.Namespace) -> int:
    store = _require_db(Path(args.db))
    recovered = store.recover_stale_leases(now=_iso(_utc_now()))
    print(f"Recovered stale leases: {recovered}")
    return 0


def run_run_finish(args: argparse.Namespace) -> int:
    store = _require_db(Path(args.db))
    store.finish_run(run_id=str(args.run_id), finished_at=_iso(_utc_now()))
    summary = store.summary()
    print(f"Run finished: {args.run_id}")
    print(f"Rows: {sum(summary.values())}")
    for status, count in sorted(summary.items()):
        print(f"{status}: {count}")
    return 0


def _openai_compatible_config_from_args(
    args: argparse.Namespace,
    *,
    api_key: str | None,
) -> OpenAICompatibleChatConfig:
    if args.timeout_seconds <= 0:
        raise RuntimeError("--timeout-seconds must be positive")
    if args.max_output_tokens is not None and args.max_output_tokens <= 0:
        raise RuntimeError("--max-output-tokens must be positive")
    return OpenAICompatibleChatConfig(
        base_url=str(args.base_url),
        model=str(args.model),
        api_key=api_key,
        timeout_seconds=float(args.timeout_seconds),
        max_output_tokens=int(args.max_output_tokens) if args.max_output_tokens is not None else None,
        temperature=float(args.temperature) if args.temperature is not None else None,
    )


def _validate_openai_run(
    store: TranslationExecutionStore,
    *,
    run_id: str,
    fingerprint: str,
    config: OpenAICompatibleChatConfig,
    ruleset,
    context_contract=None,
) -> None:
    run = store.get_run(run_id)
    if run is None:
        raise RuntimeError(f"unknown run_id: {run_id}")
    if str(run["status"]) != "running":
        raise RuntimeError(f"run is not active: {run_id}")
    if str(run["provider"]) != "openai-compatible":
        raise RuntimeError(
            f"run provider mismatch: expected openai-compatible, got {run['provider']}"
        )
    if str(run["model"]) != config.model:
        raise RuntimeError(
            f"run model mismatch: expected {run['model']}, got {config.model}"
        )
    if str(run["prompt_version"]) != ruleset.version:
        raise RuntimeError(
            f"run prompt/ruleset mismatch: expected {run['prompt_version']}, got {ruleset.version}"
        )
    if str(run["batch_plan_fingerprint"]) != fingerprint:
        raise RuntimeError("run batch plan fingerprint does not match requested batch plan")
    expected_config_hash = openai_compatible_execution_config_hash(config, ruleset, context_contract=context_contract)
    if str(run["execution_config_hash"]) != expected_config_hash:
        raise RuntimeError("run execution config hash does not match worker configuration")

    metadata = store.get_metadata()
    if metadata.get("rulesetFingerprint", "") != ruleset.fingerprint():
        raise RuntimeError("execution database ruleset fingerprint does not match worker ruleset")
    if metadata.get("sourceLocale", "") != ruleset.source_locale:
        raise RuntimeError("execution database source locale does not match worker ruleset")
    if metadata.get("targetLocale", "") != ruleset.target_locale:
        raise RuntimeError("execution database target locale does not match worker ruleset")


def _sealed_execution_contract(batch_plan: Path, db: Path, ruleset) -> dict | None:
    manifest_path = batch_plan.parent.parent / "production-manifest.json"
    if manifest_path.is_file():
        from bg3loc.production_workspace import verify_production_workspace
        binding = verify_production_workspace(manifest_path.parent)
        if binding.batch_plan.resolve() != batch_plan.resolve() or binding.database.resolve() != db.resolve():
            raise RuntimeError("execution paths do not match sealed workspace")
        if load_ruleset(binding.ruleset).fingerprint() != ruleset.fingerprint():
            raise RuntimeError("worker ruleset does not match sealed workspace")
        return binding.manifest["execution"].get("contextContract")
    _, present = material_context_fingerprint(batch_plan, enabled=True)
    if present or (db.is_file() and TranslationExecutionStore(db).get_metadata().get("executionContextContractFingerprint")):
        raise RuntimeError("context execution requires a sealed production workspace; use fresh prepare")
    return None


def run_openai_compatible_start(args: argparse.Namespace) -> int:
    batch_plan = Path(args.batch_plan)
    ruleset = load_ruleset(args.ruleset)
    context_contract = _sealed_execution_contract(batch_plan, Path(args.db), ruleset)
    store = _require_db(Path(args.db))
    store.initialize()
    batch_plan = Path(args.batch_plan)
    fingerprint = _plan_fingerprint(batch_plan)
    ruleset = load_ruleset(args.ruleset)
    config = _openai_compatible_config_from_args(args, api_key=None)
    config_hash = openai_compatible_execution_config_hash(config, ruleset, context_contract=context_contract)
    store.start_run(
        run_id=str(args.run_id),
        batch_plan_fingerprint=fingerprint,
        provider="openai-compatible",
        model=config.model,
        prompt_version=ruleset.version,
        execution_config_hash=config_hash,
        started_at=_iso(_utc_now()),
    )
    print(f"Run started: {args.run_id}")
    print("Provider: openai-compatible")
    print(f"Model: {config.model}")
    print(f"Ruleset version: {ruleset.version}")
    print(f"Ruleset fingerprint: {ruleset.fingerprint()}")
    print(f"Execution config hash: {config_hash}")
    return 0


def run_openai_compatible_worker(args: argparse.Namespace) -> int:
    if args.lease_seconds <= 0:
        raise RuntimeError("--lease-seconds must be positive")
    if args.max_attempts <= 0:
        raise RuntimeError("--max-attempts must be positive")
    if args.max_items is not None and args.max_items <= 0:
        raise RuntimeError("--max-items must be positive")

    ruleset = load_ruleset(args.ruleset)
    context_contract = _sealed_execution_contract(Path(args.batch_plan), Path(args.db), ruleset)
    store = _require_db(Path(args.db))
    store.initialize()
    batch_plan = Path(args.batch_plan)
    fingerprint = _plan_fingerprint(batch_plan)
    ruleset = load_ruleset(args.ruleset)
    api_key = os.environ.get(str(args.api_key_env)) if args.api_key_env else None
    config = _openai_compatible_config_from_args(args, api_key=api_key)

    # The API key is intentionally excluded from this validation/hash.
    _validate_openai_run(
        store,
        run_id=str(args.run_id),
        fingerprint=fingerprint,
        config=config,
        ruleset=ruleset,
        context_contract=context_contract,
    )

    resolver = BatchMaterialResolver(batch_plan, input_parameters=TranslationInputParameters(
        ruleset.version, ruleset.fingerprint(), ruleset.source_locale, ruleset.target_locale))
    provider = OpenAICompatibleChatProvider(config=config, ruleset=ruleset)
    summary = run_worker(
        store,
        run_id=str(args.run_id),
        worker_id=str(args.worker_id),
        provider=provider,
        request_resolver=resolver.resolve,
        max_attempts=int(args.max_attempts),
        lease_seconds=int(args.lease_seconds),
        max_items=int(args.max_items) if args.max_items is not None else None,
        retry_policy=getattr(args, "retry_policy", None),
        sleeper=getattr(args, "sleeper", None) or time.sleep,
        monotonic=getattr(args, "monotonic", None) or time.monotonic,
    )
    print(f"claimed: {summary.claimed}")
    print(f"succeeded: {summary.succeeded}")
    print(f"failed-retryable: {summary.failed_retryable}")
    print(f"failed-final: {summary.failed_final}")
    return 0
