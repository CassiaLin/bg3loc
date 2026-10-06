from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3

from bg3loc.qa import QA_ROUTE_REVIEW, QA_RULESET_VERSION
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
        qa = qa_store.get_result(
            content_uid,
            current_rule_set_version=QA_RULESET_VERSION,
        )
        if qa is None:
            raise ValueError(f"QA result not found: {content_uid}")
        if qa.qa_status != QA_STATUS_CHECKED:
            raise ValueError(f"QA result is stale: {content_uid}")
        if qa.route != QA_ROUTE_REVIEW:
            raise ValueError(f"QA route is not REVIEW for {content_uid}: {qa.route}")

        with closing(self.connect()) as conn, conn:
            state = conn.execute(
                "SELECT status, translated_text, output_hash, input_hash FROM content_state WHERE content_uid = ?",
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
            if qa.output_hash != current_hash:
                raise ValueError(f"QA result is stale: {content_uid}")
            if not input_binding_current(qa.execution_input_hash, str(state["input_hash"]), required=requires_input_binding(conn)):
                raise ValueError("review input identity is stale")

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

            cursor = conn.execute(
                """
                INSERT INTO qa_review_resolutions(
                    content_uid, decision, qa_rule_set_version, qa_input_hash,
                    base_output_hash, resolved_output_hash, reviewer, note, resolved_at, execution_input_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_uid, decision, qa.qa_rule_set_version, qa.qa_input_hash,
                    current_hash, resolved_hash, reviewer.strip(), note, resolved_at,
                    str(state["input_hash"]),
                ),
            )
            resolution_id = int(cursor.lastrowid)

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
        self,
        content_uid: str,
        *,
        current_output_hash: str,
        qa_rule_set_version: str = QA_RULESET_VERSION,
    ) -> StoredReviewResolution | None:
        with closing(self.connect()) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='qa_review_resolutions'"
            ).fetchone()
            if exists is None:
                return None
            row = conn.execute(
                """
                SELECT *
                FROM qa_review_resolutions
                WHERE content_uid = ?
                  AND decision = ?
                  AND qa_rule_set_version = ?
                  AND base_output_hash = ?
                  AND resolved_output_hash = ?
                ORDER BY resolution_id DESC
                LIMIT 1
                """,
                (
                    content_uid, REVIEW_DECISION_ACCEPT, qa_rule_set_version,
                    current_output_hash, current_output_hash,
                ),
            ).fetchone()
            if row is None:
                return None
            state = conn.execute("SELECT input_hash FROM content_state WHERE content_uid=?", (content_uid,)).fetchone()
            recorded = row["execution_input_hash"] if "execution_input_hash" in row.keys() else None
            if state is None or not input_binding_current(recorded, str(state["input_hash"]), required=requires_input_binding(conn)):
                return None
            return StoredReviewResolution(
                resolution_id=int(row["resolution_id"]),
                content_uid=str(row["content_uid"]),
                decision=str(row["decision"]),
                base_output_hash=str(row["base_output_hash"]),
                resolved_output_hash=str(row["resolved_output_hash"]),
                reviewer=str(row["reviewer"]),
                note=str(row["note"]),
                resolved_at=str(row["resolved_at"]),
            )
