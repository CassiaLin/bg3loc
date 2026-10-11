"""Frozen semantic REVIEW policy; no grading or execution authorization."""
from dataclasses import replace
from pathlib import Path
from contextlib import closing
import sqlite3

from bg3loc.dialogue_context import dialogue_context_from_material, fail, strict_json_loads
from bg3loc.dialogue_prompt import SEMANTIC_REVIEW_VERSION
from bg3loc.qa import QaIssue, QaResult, QA_ROUTE_PASS, QA_ROUTE_REVIEW

DIALOGUE_SEMANTIC_REVIEW_REQUIRED = "DIALOGUE_SEMANTIC_REVIEW_REQUIRED"
DIALOGUE_REVIEW_GATE_NOT_APPLIED = "DIALOGUE_REVIEW_GATE_NOT_APPLIED"


def semantic_gate_present(issues) -> bool:
    return any((issue.issue_code if isinstance(issue, QaIssue) else issue.get("issueCode")) == DIALOGUE_SEMANTIC_REVIEW_REQUIRED
               and (issue.action if isinstance(issue, QaIssue) else issue.get("action")) == QA_ROUTE_REVIEW
               and tuple(issue.details if isinstance(issue, QaIssue) else issue.get("details", ())) == (SEMANTIC_REVIEW_VERSION,)
               for issue in issues)


def apply_dialogue_semantic_review(result: QaResult, *, dialogue_context_present: bool) -> QaResult:
    if not dialogue_context_present or result.route not in {QA_ROUTE_PASS, QA_ROUTE_REVIEW}:
        return result
    issues = result.issues
    if not semantic_gate_present(issues):
        issues = (*issues, QaIssue(DIALOGUE_SEMANTIC_REVIEW_REQUIRED, "info", QA_ROUTE_REVIEW,
            "Dialogue context requires human semantic review; this is not a detected semantic error.",
            (SEMANTIC_REVIEW_VERSION,)))
    return replace(result, route=QA_ROUTE_REVIEW, issues=issues)


def is_dialogue_workspace(database: str | Path, *, _connection=None) -> bool:
    root = Path(database).resolve().parent
    marker = root / "production-manifest.json"
    if marker.is_file() and strict_json_loads(marker.read_bytes()).get("schemaVersion") == "1.3":
        return True
    if (root / "dialogue-context-materialization-summary.json").exists():
        return True
    from contextlib import nullcontext
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) if _connection is None else nullcontext(_connection) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone() is None:
            return False
        metadata = dict(conn.execute("SELECT key,value FROM metadata"))
    return (metadata.get("schemaVersion") == "1.3" or
            metadata.get("executionContextContractVersion") == "production-context-contract/2" or
            "dialogueContextMaterialFingerprint" in metadata)


def validated_stage3_material(database: str | Path, *, batch_plan: str | Path | None = None,
                              validation_only: bool = False, _connection=None) -> dict[str, dict]:
    """Offline 1.3 foundations; public execution stop guards remain unchanged."""
    from bg3loc.dialogue_execution_contract import validate_stage2_workspace, reject_dialogue_execution
    if not validation_only:
        reject_dialogue_execution()
    db = Path(database).resolve()
    binding = validate_stage2_workspace(db.parent,_connection=_connection)
    if binding.database.resolve() != db or (batch_plan is not None and binding.batch_plan.resolve() != Path(batch_plan).resolve()):
        fail("CONTEXT_CONTRACT_MISMATCH")
    plan = strict_json_loads(binding.batch_plan.read_bytes())
    rows = {}
    for batch in plan["batches"]:
        path = binding.batch_plan.parent / "materials" / f"{batch['batchId']}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            row = strict_json_loads(line)
            dialogue_context_from_material(row)
            rows[row["contentUid"]] = row
    return rows
