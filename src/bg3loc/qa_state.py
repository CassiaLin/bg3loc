from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.qa import QA_ROUTE_RETRY, QaResult


QA_STATUS_CHECKED = "checked"
QA_STATUS_STALE = "stale"


@dataclass(frozen=True, slots=True)
class StoredQaResult:
    content_uid: str
    qa_status: str
    route: str
    issue_count: int
    qa_rule_set_version: str
    qa_input_hash: str
    output_hash: str
    checked_at: str
    issues: tuple[dict[str, object], ...]


class TranslationQaStore:
    """Persist QA decisions beside execution state without changing 01C status semantics."""

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
                CREATE TABLE IF NOT EXISTS qa_results (
                    content_uid TEXT PRIMARY KEY,
                    route TEXT NOT NULL,
                    qa_rule_set_version TEXT NOT NULL,
                    qa_input_hash TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    FOREIGN KEY(content_uid) REFERENCES content_state(content_uid)
                );

                CREATE TABLE IF NOT EXISTS qa_issues (
                    content_uid TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    issue_code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    PRIMARY KEY(content_uid, ordinal),
                    FOREIGN KEY(content_uid) REFERENCES qa_results(content_uid)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_qa_results_route
                    ON qa_results(route, content_uid);

                CREATE TABLE IF NOT EXISTS qa_rejected_candidates (
                    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_uid TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    output_hash TEXT NOT NULL,
                    qa_rule_set_version TEXT NOT NULL,
                    qa_input_hash TEXT NOT NULL,
                    route TEXT NOT NULL,
                    issues_json TEXT NOT NULL,
                    rejected_at TEXT NOT NULL,
                    FOREIGN KEY(content_uid) REFERENCES content_state(content_uid)
                );

                CREATE INDEX IF NOT EXISTS idx_qa_issues_code
                    ON qa_issues(issue_code, content_uid);

                CREATE INDEX IF NOT EXISTS idx_qa_rejected_content_uid
                    ON qa_rejected_candidates(content_uid, rejection_id);
                """
            )

    def record_result(
        self,
        result: QaResult,
        *,
        checked_at: str,
    ) -> None:
        with closing(self.connect()) as conn, conn:
            state = conn.execute(
                """
                SELECT output_hash, translated_text
                FROM content_state
                WHERE content_uid = ?
                """,
                (result.content_uid,),
            ).fetchone()
            if state is None:
                raise ValueError(f"unknown ContentUid: {result.content_uid}")

            output_hash = str(state["output_hash"] or "")
            translated_text = state["translated_text"]
            if not output_hash or translated_text is None:
                raise ValueError(
                    f"ContentUid has no completed translation output: {result.content_uid}"
                )

            conn.execute(
                """
                INSERT INTO qa_results(
                    content_uid, route, qa_rule_set_version,
                    qa_input_hash, output_hash, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_uid) DO UPDATE SET
                    route = excluded.route,
                    qa_rule_set_version = excluded.qa_rule_set_version,
                    qa_input_hash = excluded.qa_input_hash,
                    output_hash = excluded.output_hash,
                    checked_at = excluded.checked_at
                """,
                (
                    result.content_uid,
                    result.route,
                    result.qa_rule_set_version,
                    result.qa_input_hash,
                    output_hash,
                    checked_at,
                ),
            )
            conn.execute(
                "DELETE FROM qa_issues WHERE content_uid = ?",
                (result.content_uid,),
            )
            conn.executemany(
                """
                INSERT INTO qa_issues(
                    content_uid, ordinal, issue_code, severity,
                    action, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.content_uid,
                        ordinal,
                        issue.issue_code,
                        issue.severity,
                        issue.action,
                        issue.message,
                        json.dumps(
                            list(issue.details),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                    for ordinal, issue in enumerate(result.issues)
                ],
            )

    def handoff_retry(
        self,
        result: QaResult,
        *,
        max_attempts: int,
        rejected_at: str,
    ) -> str:
        """Archive a QA-rejected candidate, then reopen its ContentUid in 01C."""
        if result.route != QA_ROUTE_RETRY:
            raise ValueError("QA handoff requires a RETRY result")

        with closing(self.connect()) as conn, conn:
            state = conn.execute(
                """
                SELECT status, translated_text, output_hash
                FROM content_state
                WHERE content_uid = ?
                """,
                (result.content_uid,),
            ).fetchone()
            if state is None:
                raise ValueError(f"unknown ContentUid: {result.content_uid}")
            translated_text = state["translated_text"]
            output_hash = str(state["output_hash"] or "")
            if translated_text is None or not output_hash:
                raise ValueError(
                    f"ContentUid has no completed translation output: {result.content_uid}"
                )

            stored = conn.execute(
                """
                SELECT qa_input_hash, output_hash
                FROM qa_results
                WHERE content_uid = ?
                """,
                (result.content_uid,),
            ).fetchone()
            if stored is None:
                raise ValueError(f"QA result is not persisted: {result.content_uid}")
            if str(stored["qa_input_hash"]) != result.qa_input_hash:
                raise ValueError(f"QA result hash mismatch: {result.content_uid}")
            if str(stored["output_hash"]) != output_hash:
                raise ValueError(f"QA result is stale: {result.content_uid}")

            issues_json = json.dumps(
                [
                    {
                        "issueCode": issue.issue_code,
                        "severity": issue.severity,
                        "action": issue.action,
                        "message": issue.message,
                        "details": list(issue.details),
                    }
                    for issue in result.issues
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO qa_rejected_candidates(
                    content_uid, translated_text, output_hash,
                    qa_rule_set_version, qa_input_hash,
                    route, issues_json, rejected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.content_uid,
                    str(translated_text),
                    output_hash,
                    result.qa_rule_set_version,
                    result.qa_input_hash,
                    result.route,
                    issues_json,
                    rejected_at,
                ),
            )

        execution = TranslationExecutionStore(self.path)
        return execution.reopen_after_qa_retry(
            content_uid=result.content_uid,
            max_attempts=max_attempts,
            updated_at=rejected_at,
        )

    def get_rejected_candidates(
        self,
        content_uid: str,
    ) -> list[dict[str, object]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM qa_rejected_candidates
                WHERE content_uid = ?
                ORDER BY rejection_id
                """,
                (content_uid,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_result(
        self,
        content_uid: str,
        *,
        current_rule_set_version: str | None = None,
    ) -> StoredQaResult | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT
                    q.content_uid,
                    q.route,
                    q.qa_rule_set_version,
                    q.qa_input_hash,
                    q.output_hash AS qa_output_hash,
                    q.checked_at,
                    c.output_hash AS current_output_hash
                FROM qa_results AS q
                JOIN content_state AS c USING(content_uid)
                WHERE q.content_uid = ?
                """,
                (content_uid,),
            ).fetchone()
            if row is None:
                return None

            stale = str(row["qa_output_hash"]) != str(row["current_output_hash"] or "")
            if (
                current_rule_set_version is not None
                and str(row["qa_rule_set_version"]) != current_rule_set_version
            ):
                stale = True

            issue_rows = conn.execute(
                """
                SELECT issue_code, severity, action, message, details_json
                FROM qa_issues
                WHERE content_uid = ?
                ORDER BY ordinal
                """,
                (content_uid,),
            ).fetchall()
            issues = tuple(
                {
                    "issueCode": str(issue["issue_code"]),
                    "severity": str(issue["severity"]),
                    "action": str(issue["action"]),
                    "message": str(issue["message"]),
                    "details": tuple(json.loads(str(issue["details_json"]))),
                }
                for issue in issue_rows
            )

            return StoredQaResult(
                content_uid=str(row["content_uid"]),
                qa_status=QA_STATUS_STALE if stale else QA_STATUS_CHECKED,
                route=str(row["route"]),
                issue_count=len(issues),
                qa_rule_set_version=str(row["qa_rule_set_version"]),
                qa_input_hash=str(row["qa_input_hash"]),
                output_hash=str(row["qa_output_hash"]),
                checked_at=str(row["checked_at"]),
                issues=issues,
            )

    def list_by_route(
        self,
        route: str,
        *,
        current_rule_set_version: str | None = None,
    ) -> list[StoredQaResult]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    q.content_uid,
                    q.route,
                    q.qa_rule_set_version,
                    q.qa_input_hash,
                    q.output_hash AS qa_output_hash,
                    q.checked_at,
                    c.output_hash AS current_output_hash,
                    i.ordinal,
                    i.issue_code,
                    i.severity,
                    i.action,
                    i.message,
                    i.details_json
                FROM qa_results AS q
                JOIN content_state AS c USING(content_uid)
                LEFT JOIN qa_issues AS i USING(content_uid)
                WHERE q.route = ?
                ORDER BY q.content_uid, i.ordinal
                """,
                (route,),
            ).fetchall()

        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["content_uid"]), []).append(row)

        results: list[StoredQaResult] = []
        for content_uid, group in grouped.items():
            first = group[0]
            stale = str(first["qa_output_hash"]) != str(
                first["current_output_hash"] or ""
            )
            if (
                current_rule_set_version is not None
                and str(first["qa_rule_set_version"]) != current_rule_set_version
            ):
                stale = True
            issues = tuple(
                {
                    "issueCode": str(row["issue_code"]),
                    "severity": str(row["severity"]),
                    "action": str(row["action"]),
                    "message": str(row["message"]),
                    "details": tuple(json.loads(str(row["details_json"]))),
                }
                for row in group
                if row["ordinal"] is not None
            )
            results.append(
                StoredQaResult(
                    content_uid=content_uid,
                    qa_status=QA_STATUS_STALE if stale else QA_STATUS_CHECKED,
                    route=str(first["route"]),
                    issue_count=len(issues),
                    qa_rule_set_version=str(first["qa_rule_set_version"]),
                    qa_input_hash=str(first["qa_input_hash"]),
                    output_hash=str(first["qa_output_hash"]),
                    checked_at=str(first["checked_at"]),
                    issues=issues,
                )
            )
        return results
