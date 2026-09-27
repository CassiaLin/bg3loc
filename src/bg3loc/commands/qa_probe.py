from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil

from bg3loc.execution_state import (
    ExecutionItem,
    TranslationExecutionStore,
)
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.qa import QA_RULESET_VERSION


def register_probe(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    probe = subparsers.add_parser(
        "smoke-probe",
        help="Create a controlled real-material QA smoke probe without calling a translation provider",
    )
    probe.add_argument("--batch-plan", required=True)
    probe.add_argument("--work-dir", required=True)
    probe.set_defaults(handler=run_smoke_probe)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_LANGUAGE_BEARING_RE = re.compile(r"[A-Za-z]{4,}")


def _probe_material_rows(batch_plan: Path) -> list[dict[str, object]]:
    with batch_plan.open("r", encoding="utf-8") as f:
        plan = json.load(f)

    usable: list[dict[str, object]] = []
    review_row: dict[str, object] | None = None
    seen: set[str] = set()

    for batch in plan.get("batches", []):
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("batchId", ""))
        if not batch_id:
            continue
        material = batch_plan.parent / "materials" / f"{batch_id}.jsonl"
        if not material.is_file():
            raise RuntimeError(f"batch material not found: {material}")
        with material.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                uid = str(row.get("ContentUid", row.get("contentUid", "")))
                source = str(row.get("SourceText", row.get("sourceText", "")))
                category = str(row.get("primaryCategory", batch.get("primaryCategory", "")))
                if not uid or not source or not category or uid in seen:
                    continue
                seen.add(uid)
                normalized = {
                    "ContentUid": uid,
                    "SourceText": source,
                    "primaryCategory": category,
                    "batchId": batch_id,
                }
                usable.append(normalized)
                if review_row is None and _LANGUAGE_BEARING_RE.search(source):
                    review_row = normalized

                if len(usable) >= 3 and review_row is not None:
                    pass_row = next(
                        item for item in usable
                        if item["ContentUid"] != review_row["ContentUid"]
                    )
                    retry_row = next(
                        item for item in usable
                        if item["ContentUid"] not in {
                            review_row["ContentUid"],
                            pass_row["ContentUid"],
                        }
                    )
                    return [pass_row, review_row, retry_row]

    raise RuntimeError(
        "batch plan does not contain three usable rows including one language-bearing row"
    )


def _safe_pass_candidate(source: str) -> str:
    protected = extract_protected_tokens(source)
    visible_target_length = max(4, len(source) // 2)
    candidate = "譯" * visible_target_length
    if protected:
        candidate += " " + " ".join(protected)
    return candidate

def run_smoke_probe(args: argparse.Namespace) -> int:
    batch_plan = Path(args.batch_plan)
    work_dir = Path(args.work_dir)
    if not batch_plan.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan}")

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    rows = _probe_material_rows(batch_plan)
    db = work_dir / "execution.sqlite3"
    store = TranslationExecutionStore(db)
    store.initialize()

    items = [
        ExecutionItem(
            content_uid=str(row["ContentUid"]),
            batch_id=str(row["batchId"]),
            input_hash=f"qa-smoke:{index}",
        )
        for index, row in enumerate(rows, start=1)
    ]
    store.seed_items(items, updated_at="qa-smoke-seed")
    store.start_run(
        run_id="qa-smoke",
        batch_plan_fingerprint="qa-smoke",
        provider="controlled-probe",
        model="none",
        prompt_version="qa-smoke",
        execution_config_hash="qa-smoke",
        started_at="2026-09-23T00:00:00Z",
    )

    # Candidate 1: structurally clean synthetic translation -> expected PASS.
    # Preserve all protected tokens extracted from the real source.
    source1 = str(rows[0]["SourceText"])
    pass_text = _safe_pass_candidate(source1)

    # Candidate 2: exact source echo -> expected REVIEW for language-bearing English text.
    review_text = str(rows[1]["SourceText"])

    # Candidate 3: empty output -> expected RETRY.
    retry_text = ""

    candidates_by_uid = {
        str(rows[0]["ContentUid"]): pass_text,
        str(rows[1]["ContentUid"]): review_text,
        str(rows[2]["ContentUid"]): retry_text,
    }
    for index in range(1, 4):
        claim = store.claim_next(
            run_id="qa-smoke",
            worker_id="probe-worker",
            lease_expires_at=f"2026-09-23T01:00:0{index}Z",
            started_at=f"2026-09-23T00:00:0{index}Z",
            max_attempts=3,
        )
        if claim is None:
            raise RuntimeError("unexpectedly unable to claim smoke-probe row")
        candidate = candidates_by_uid.get(claim.content_uid)
        if candidate is None:
            raise RuntimeError(
                f"unexpected ContentUid claimed by smoke probe: {claim.content_uid}"
            )
        store.complete_success(
            attempt_id=claim.attempt_id,
            worker_id="probe-worker",
            translated_text=candidate,
            output_hash=_hash_text(candidate),
            finished_at=f"2026-09-23T00:10:0{index}Z",
        )

    manifest = {
        "qaRuleSetVersion": QA_RULESET_VERSION,
        "batchPlan": str(batch_plan),
        "database": str(db),
        "rows": [
            {
                **row,
                "probeRole": role,
            }
            for row, role in zip(rows, ("PASS", "REVIEW", "RETRY"))
        ],
    }
    (work_dir / "probe-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Smoke probe database: {db}")
    print(f"Manifest: {work_dir / 'probe-manifest.json'}")
    for row, role in zip(rows, ("PASS", "REVIEW", "RETRY")):
        print(f"{role}: {row['ContentUid']} [{row['primaryCategory']}]")
    print("Next: run bg3loc qa run against this database and the same batch plan.")
    return 0
