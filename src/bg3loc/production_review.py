from __future__ import annotations

from contextlib import closing, ExitStack
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
import json

from bg3loc.qa import QA_ROUTE_REVIEW, QA_RULESET_VERSION
from bg3loc.qa import QA_ROUTE_FAIL, QA_ROUTE_RETRY, QaInput, evaluate_translation, qa_input_hash
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.dialogue_review import is_dialogue_workspace, validated_stage3_material, apply_dialogue_semantic_review, semantic_gate_present
from bg3loc.dialogue_context import dialogue_context_from_material
from bg3loc.qa_state import QA_STATUS_CHECKED, TranslationQaStore, input_binding_current, requires_input_binding, stored_input_binding_expression


REVIEW_DECISION_ACCEPT = "ACCEPT"
REVIEW_DECISION_REVISE = "REVISE"


@dataclass(frozen=True, slots=True)
class StoredReviewResolution:
    resolution_id: int
    content_uid: str
    decision: str
    base_output_hash: str
    resolved_output_hash: str
    reviewer: str
    note: str
    resolved_at: str


class ProductionReviewStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        if not self.path.is_file():
            raise RuntimeError(f"execution database not found: {self.path}")
        with closing(self.connect()) as conn, conn:
            required = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content_state'"
            ).fetchone()
            if required is None:
                raise RuntimeError("execution database is missing content_state")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS qa_review_resolutions (
                    resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_uid TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    qa_rule_set_version TEXT NOT NULL,
                    qa_input_hash TEXT NOT NULL,
                    base_output_hash TEXT NOT NULL,
                    resolved_output_hash TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    note TEXT NOT NULL,
                    resolved_at TEXT NOT NULL,
                    FOREIGN KEY(content_uid) REFERENCES content_state(content_uid)
                );

                CREATE INDEX IF NOT EXISTS idx_qa_review_resolution_uid
                    ON qa_review_resolutions(content_uid, resolution_id);
                """
            )
            if stored_input_binding_expression(conn, "qa_review_resolutions") == "NULL":
                conn.execute("ALTER TABLE qa_review_resolutions ADD COLUMN execution_input_hash TEXT")

    def resolve(
        self,
        *,
        content_uid: str,
        decision: str,
        reviewer: str,
        note: str,
        resolved_at: str,
        revised_text: str | None = None,
        batch_plan_path: str | Path | None = None,
        stage3_validation_only: bool = False,
        expected_execution_input_hash: str | None = None,
        expected_output_hash: str | None = None,
        expected_qa_input_hash: str | None = None,
        expected_qa_rule_set_version: str | None = None,
    ) -> StoredReviewResolution:
        if decision not in {REVIEW_DECISION_ACCEPT, REVIEW_DECISION_REVISE}:
            raise ValueError(f"unsupported review decision: {decision}")
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if decision == REVIEW_DECISION_REVISE and revised_text is None:
            raise ValueError("REVISE requires revised_text")
        if decision == REVIEW_DECISION_ACCEPT and revised_text is not None:
            raise ValueError("ACCEPT must not include revised_text")

        qa_store = TranslationQaStore(self.path)
        qa_store.initialize()
        modern = is_dialogue_workspace(self.path)
        material = None
        dialogue_required = False
        if modern:
            material = validated_stage3_material(self.path, batch_plan=batch_plan_path,
                validation_only=stage3_validation_only)[content_uid]
            dialogue_required = dialogue_context_from_material(material) is not None
        qa = qa_store.get_result(
            content_uid,
            current_rule_set_version=QA_RULESET_VERSION,
            dialogue_context_required=dialogue_required,
        )
        if qa is None:
            raise ValueError(f"QA result not found: {content_uid}")
        if qa.qa_status != QA_STATUS_CHECKED:
            raise ValueError(f"QA result is stale: {content_uid}")
        if qa.route != QA_ROUTE_REVIEW:
            raise ValueError(f"QA route is not REVIEW for {content_uid}: {qa.route}")
        snapshot = (expected_execution_input_hash, expected_output_hash, expected_qa_input_hash, expected_qa_rule_set_version)
        current_snapshot = (qa.execution_input_hash, qa.output_hash, qa.qa_input_hash, qa.qa_rule_set_version)
        if (modern and any(value is None for value in snapshot)) or (
                any(value is not None for value in snapshot) and snapshot != current_snapshot):
            raise ValueError("review snapshot changed or incomplete")

        with ExitStack() as assets, closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                "SELECT status, translated_text, output_hash, input_hash, batch_id FROM content_state WHERE content_uid = ?",
                (content_uid,),
            ).fetchone()
            if state is None:
                raise ValueError(f"unknown ContentUid: {content_uid}")
            if str(state["status"]) != "succeeded":
                raise ValueError(f"ContentUid is not succeeded: {content_uid}")
            current_text = state["translated_text"]
            current_hash = str(state["output_hash"] or "")
            if current_text is None or not current_hash:
                raise ValueError(f"ContentUid has no completed output: {content_uid}")
            if (not isinstance(current_text, str) or
                    hashlib.sha256(current_text.encode("utf-8")).hexdigest() != current_hash):
                raise ValueError("review base output bytes do not match declared output hash")
            if qa.output_hash != current_hash:
                raise ValueError(f"QA result is stale: {content_uid}")
            if not input_binding_current(qa.execution_input_hash, str(state["input_hash"]), required=requires_input_binding(conn)):
                raise ValueError("review input identity is stale")
            current_qa = conn.execute("SELECT * FROM qa_results WHERE content_uid=?", (content_uid,)).fetchone()
            if (current_qa is None or current_qa["route"] != QA_ROUTE_REVIEW or current_qa["qa_input_hash"] != qa.qa_input_hash
                    or current_qa["qa_rule_set_version"] != qa.qa_rule_set_version or current_qa["output_hash"] != current_hash
                    or current_qa["execution_input_hash"] != qa.execution_input_hash):
                raise ValueError("review QA snapshot changed")
            if modern:
                locked_snapshot = (state["input_hash"], current_hash,
                                   current_qa["qa_input_hash"], current_qa["qa_rule_set_version"])
                if snapshot != locked_snapshot:
                    raise ValueError("review snapshot changed or incomplete")
                refreshed = validated_stage3_material(self.path, batch_plan=batch_plan_path,
                    validation_only=True, _connection=conn)[content_uid]
                if refreshed != material:
                    raise ValueError("review material changed")
                source = str(refreshed.get("sourceText", refreshed.get("SourceText", "")))
                base_qa_input = QaInput(content_uid, source, current_text,
                    str(refreshed["primaryCategory"]), tuple(extract_protected_tokens(source)))
                if qa_input_hash(base_qa_input) != current_qa["qa_input_hash"]:
                    raise ValueError("review QA snapshot does not match base output")
                if dialogue_required:
                    issues = [{"issueCode":r[0],"action":r[1],"details":tuple(json.loads(r[2]))}
                              for r in conn.execute("SELECT issue_code,action,details_json FROM qa_issues WHERE content_uid=?", (content_uid,))]
                    if not semantic_gate_present(issues):
                        raise ValueError("current dialogue review gate is missing")
            else:
                from bg3loc.legacy_qa_material import LegacyQaMaterial
                legacy = LegacyQaMaterial(self.path, batch_plan_path, connection=conn)
                assets.callback(legacy.close)
                source_row = legacy.source(content_uid, state)
                if not legacy.current(content_uid, state, current_qa['qa_input_hash']):
                    raise ValueError('review QA snapshot does not match base output')
                material = {'SourceText': source_row.source_text, 'primaryCategory': source_row.category}
            revised_qa = None
            if decision == REVIEW_DECISION_REVISE:
                assert material is not None and revised_text is not None
                source = str(material.get("sourceText", material.get("SourceText", "")))
                revised_qa = evaluate_translation(QaInput(content_uid, source, revised_text,
                    str(material["primaryCategory"]), tuple(extract_protected_tokens(source))))
                if revised_qa.route in {QA_ROUTE_FAIL, QA_ROUTE_RETRY}:
                    raise ValueError("revised candidate failed technical QA")
                revised_qa = apply_dialogue_semantic_review(revised_qa, dialogue_context_present=dialogue_required)

            duplicate = conn.execute(
                """
                SELECT resolution_id
                FROM qa_review_resolutions
                WHERE content_uid = ?
                  AND decision = ?
                  AND qa_rule_set_version = ?
                  AND qa_input_hash = ?
                  AND base_output_hash = ?
                  AND execution_input_hash = ?
                ORDER BY resolution_id DESC
                LIMIT 1
                """,
                (
                    content_uid,
                    decision,
                    qa.qa_rule_set_version,
                    qa.qa_input_hash,
                    current_hash,
                    str(state["input_hash"]),
                ),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(
                    f"duplicate review decision for current QA evidence: {content_uid}"
                )

            if decision == REVIEW_DECISION_ACCEPT:
                resolved_hash = current_hash
            else:
                assert revised_text is not None
                resolved_hash = hashlib.sha256(revised_text.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    UPDATE content_state
                    SET translated_text = ?, output_hash = ?, updated_at = ?
                    WHERE content_uid = ?
                    """,
                    (revised_text, resolved_hash, resolved_at, content_uid),
                )
                if modern:
                    qa_store.record_result(revised_qa, checked_at=resolved_at,
                        expected_input_hash=str(state["input_hash"]), expected_output_hash=resolved_hash, _connection=conn)

            cursor = conn.execute(
                """
                INSERT INTO qa_review_resolutions(
                    content_uid, decision, qa_rule_set_version, qa_input_hash,
                    base_output_hash, resolved_output_hash, reviewer, note, resolved_at, execution_input_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_uid, decision, qa.qa_rule_set_version,
                    revised_qa.qa_input_hash if modern and revised_qa is not None else qa.qa_input_hash,
                    current_hash, resolved_hash, reviewer.strip(), note, resolved_at,
                    str(state["input_hash"]),
                ),
            )
            resolution_id = int(cursor.lastrowid)
            if not modern:
                legacy.check()  # Before commit; pins remain live through commit.

        return StoredReviewResolution(
            resolution_id=resolution_id,
            content_uid=content_uid,
            decision=decision,
            base_output_hash=current_hash,
            resolved_output_hash=resolved_hash,
            reviewer=reviewer.strip(),
            note=note,
            resolved_at=resolved_at,
        )

    def get_current_acceptance(
        self, content_uid: str, *, current_output_hash: str,
        qa_rule_set_version: str = QA_RULESET_VERSION,
    ) -> StoredReviewResolution | None:
        modern = is_dialogue_workspace(self.path)
        required = False
        if modern:
            material = validated_stage3_material(self.path, validation_only=True)[content_uid]
            required = dialogue_context_from_material(material) is not None
        qa = TranslationQaStore(self.path).get_result(content_uid, current_rule_set_version=qa_rule_set_version,
                                                      dialogue_context_required=required)
        if qa is None or qa.qa_status != QA_STATUS_CHECKED or qa.route != QA_ROUTE_REVIEW or qa.output_hash != current_output_hash:
            return None
        with closing(self.connect()) as conn:
            conn.execute("BEGIN")
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='qa_review_resolutions'").fetchone() is None:
                return None
            state = conn.execute("SELECT input_hash,output_hash,status,translated_text,batch_id FROM content_state WHERE content_uid=?", (content_uid,)).fetchone()
            if state is None or state["status"] != "succeeded" or state["output_hash"] != current_output_hash:
                return None
            current = conn.execute("SELECT * FROM qa_results WHERE content_uid=?", (content_uid,)).fetchone()
            if (current is None or current["route"] != QA_ROUTE_REVIEW or current["qa_input_hash"] != qa.qa_input_hash
                    or current["qa_rule_set_version"] != qa_rule_set_version or current["output_hash"] != current_output_hash):
                return None
            if not modern:
                from bg3loc.legacy_qa_material import LegacyQaMaterial
                try:
                    with LegacyQaMaterial(self.path, connection=conn) as legacy:
                        if not legacy.current(content_uid, state, current['qa_input_hash']):
                            return None
                except (ValueError, KeyError, OSError):
                    return None
            if required:
                issues = [{"issueCode":r[0],"action":r[1],"details":tuple(json.loads(r[2]))} for r in
                          conn.execute("SELECT issue_code,action,details_json FROM qa_issues WHERE content_uid=?",(content_uid,))]
                if not semantic_gate_present(issues):
                    return None
            rows = conn.execute("""SELECT * FROM qa_review_resolutions WHERE content_uid=?
                AND decision IN ('ACCEPT','REVISE') AND qa_rule_set_version=? AND qa_input_hash=?
                AND resolved_output_hash=? ORDER BY resolution_id DESC""",
                (content_uid, qa_rule_set_version, qa.qa_input_hash, current_output_hash)).fetchall()
            for row in rows:
                recorded = row["execution_input_hash"] if "execution_input_hash" in row.keys() else None
                if (not input_binding_current(recorded, str(state["input_hash"]), required=requires_input_binding(conn))
                        or (row["decision"] == REVIEW_DECISION_ACCEPT and row["base_output_hash"] != current_output_hash)):
                    continue
                return StoredReviewResolution(int(row["resolution_id"]), str(row["content_uid"]), str(row["decision"]),
                    str(row["base_output_hash"]), str(row["resolved_output_hash"]), str(row["reviewer"]), str(row["note"]), str(row["resolved_at"]))
            return None
