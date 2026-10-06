from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import re
from typing import Iterable


EXECUTION_SCHEMA_VERSION = "1.2"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED_RETRYABLE = "failed-retryable"
STATUS_FAILED_FINAL = "failed-final"
STATUS_SKIPPED = "skipped"
STATUS_INVALIDATED = "invalidated"

EXECUTABLE_STATUSES = (
    STATUS_PENDING,
    STATUS_FAILED_RETRYABLE,
    STATUS_INVALIDATED,
)


@dataclass(frozen=True, slots=True)
class ExecutionItem:
    content_uid: str
    batch_id: str
    input_hash: str


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    attempt_id: int
    run_id: str
    content_uid: str
    batch_id: str
    attempt_number: int
    input_hash: str
    lease_owner: str
    lease_expires_at: str


class TranslationExecutionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    batch_plan_fingerprint TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    execution_config_hash TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS content_state (
                    content_uid TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    translated_text TEXT,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT,
                    last_successful_run_id TEXT,
                    last_attempt_id INTEGER,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(last_successful_run_id) REFERENCES runs(run_id),
                    FOREIGN KEY(last_attempt_id) REFERENCES attempts(attempt_id)
                );

                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    content_uid TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    outcome TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    provider_request_id TEXT,
                    input_hash TEXT NOT NULL,
                    output_hash TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_content_state_status
                    ON content_state(status, lease_expires_at, content_uid);

                CREATE INDEX IF NOT EXISTS idx_attempts_content_uid
                    ON attempts(content_uid, attempt_id);

                CREATE INDEX IF NOT EXISTS idx_attempts_run_id
                    ON attempts(run_id, attempt_id);
                """
            )
            attempt_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(attempts)")
            }
            for column in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            ):
                if column not in attempt_columns:
                    conn.execute(f"ALTER TABLE attempts ADD COLUMN {column} INTEGER")
            for column in ("context_fingerprint", "effective_prompt_hash", "chat_messages_fingerprint", "prompt_renderer_version"):
                if column not in attempt_columns:
                    conn.execute(f"ALTER TABLE attempts ADD COLUMN {column} TEXT")
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schemaVersion', ?)",
                (EXECUTION_SCHEMA_VERSION,),
            )

    def set_metadata(self, values: dict[str, str]) -> None:
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
                [(str(key), str(value)) for key, value in values.items()],
            )

    def get_metadata(self) -> dict[str, str]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT key, value FROM metadata ORDER BY key"
            ).fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}

    def start_run(
        self,
        *,
        run_id: str,
        batch_plan_fingerprint: str,
        provider: str,
        model: str,
        prompt_version: str,
        execution_config_hash: str,
        started_at: str,
    ) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, batch_plan_fingerprint, provider, model,
                    prompt_version, execution_config_hash, started_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
                """,
                (
                    run_id,
                    batch_plan_fingerprint,
                    provider,
                    model,
                    prompt_version,
                    execution_config_hash,
                    started_at,
                ),
            )

    def seed_items(self, items: Iterable[ExecutionItem], *, updated_at: str) -> None:
        with closing(self.connect()) as conn, conn:
            for item in items:
                existing = conn.execute(
                    "SELECT input_hash, status FROM content_state WHERE content_uid = ?",
                    (item.content_uid,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO content_state(
                            content_uid, batch_id, status, input_hash,
                            attempt_count, updated_at
                        ) VALUES (?, ?, ?, ?, 0, ?)
                        """,
                        (
                            item.content_uid,
                            item.batch_id,
                            STATUS_PENDING,
                            item.input_hash,
                            updated_at,
                        ),
                    )
                    continue

                if str(existing["input_hash"]) == item.input_hash:
                    conn.execute(
                        """
                        UPDATE content_state
                        SET batch_id = ?, updated_at = ?
                        WHERE content_uid = ?
                        """,
                        (item.batch_id, updated_at, item.content_uid),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE content_state
                        SET batch_id = ?,
                            status = ?,
                            input_hash = ?,
                            attempt_count = 0,
                            lease_owner = NULL,
                            lease_expires_at = NULL,
                            updated_at = ?
                        WHERE content_uid = ?
                        """,
                        (
                            item.batch_id,
                            STATUS_INVALIDATED,
                            item.input_hash,
                            updated_at,
                            item.content_uid,
                        ),
                    )

    def claim_next(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_expires_at: str,
        started_at: str,
        max_attempts: int,
    ) -> ClaimedAttempt | None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT provider, model, status FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown run_id: {run_id}")
            if str(run["status"]) != "running":
                raise ValueError(f"run is not active: {run_id}")

            placeholders = ",".join("?" for _ in EXECUTABLE_STATUSES)
            row = conn.execute(
                f"""
                SELECT content_uid, batch_id, input_hash, attempt_count
                FROM content_state
                WHERE status IN ({placeholders})
                  AND attempt_count < ?
                  AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY batch_id, content_uid
                LIMIT 1
                """,
                (*EXECUTABLE_STATUSES, max_attempts, started_at),
            ).fetchone()
            if row is None:
                return None

            attempt_number = int(row["attempt_count"]) + 1
            cursor = conn.execute(
                """
                INSERT INTO attempts(
                    run_id, content_uid, batch_id, attempt_number,
                    provider, model, started_at, outcome, input_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    run_id,
                    str(row["content_uid"]),
                    str(row["batch_id"]),
                    attempt_number,
                    str(run["provider"]),
                    str(run["model"]),
                    started_at,
                    str(row["input_hash"]),
                ),
            )
            attempt_id = int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE content_state
                SET status = ?,
                    attempt_count = ?,
                    last_attempt_id = ?,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE content_uid = ?
                """,
                (
                    STATUS_RUNNING,
                    attempt_number,
                    attempt_id,
                    worker_id,
                    lease_expires_at,
                    started_at,
                    str(row["content_uid"]),
                ),
            )

            return ClaimedAttempt(
                attempt_id=attempt_id,
                run_id=run_id,
                content_uid=str(row["content_uid"]),
                batch_id=str(row["batch_id"]),
                attempt_number=attempt_number,
                input_hash=str(row["input_hash"]),
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
            )

    def has_executable(self, *, now: str, max_attempts: int) -> bool:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        placeholders = ",".join("?" for _ in EXECUTABLE_STATUSES)
        with closing(self.connect()) as conn:
            row = conn.execute(
                f"""
                SELECT 1
                FROM content_state
                WHERE status IN ({placeholders})
                  AND attempt_count < ?
                  AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= ?)
                LIMIT 1
                """,
                (*EXECUTABLE_STATUSES, max_attempts, now),
            ).fetchone()
        return row is not None

    def complete_success(
        self,
        *,
        attempt_id: int,
        worker_id: str,
        translated_text: str,
        output_hash: str,
        finished_at: str,
        provider_request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        _validate_usage(prompt_tokens, completion_tokens, total_tokens)
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt, state = self._load_attempt_and_state(conn, attempt_id)
            self._assert_live_owner(attempt, state, worker_id)
            conn.execute(
                """
                UPDATE attempts
                SET finished_at = ?,
                    outcome = 'succeeded',
                    provider_request_id = ?,
                    output_hash = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?
                WHERE attempt_id = ?
                """,
                (
                    finished_at,
                    provider_request_id,
                    output_hash,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    attempt_id,
                ),
            )
            conn.execute(
                """
                UPDATE content_state
                SET status = ?,
                    translated_text = ?,
                    output_hash = ?,
                    last_successful_run_id = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE content_uid = ?
                """,
                (
                    STATUS_SUCCEEDED,
                    translated_text,
                    output_hash,
                    str(attempt["run_id"]),
                    finished_at,
                    str(attempt["content_uid"]),
                ),
            )

    def complete_failure(
        self,
        *,
        attempt_id: int,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        max_attempts: int,
        finished_at: str,
        provider_request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> str:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        _validate_usage(prompt_tokens, completion_tokens, total_tokens)

        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt, state = self._load_attempt_and_state(conn, attempt_id)
            self._assert_live_owner(attempt, state, worker_id)
            attempts_used = int(state["attempt_count"])
            final_status = (
                STATUS_FAILED_RETRYABLE
                if retryable and attempts_used < max_attempts
                else STATUS_FAILED_FINAL
            )
            outcome = (
                "failed-retryable"
                if final_status == STATUS_FAILED_RETRYABLE
                else "failed-final"
            )
            conn.execute(
                """
                UPDATE attempts
                SET finished_at = ?,
                    outcome = ?,
                    error_code = ?,
                    error_message = ?,
                    provider_request_id = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?
                WHERE attempt_id = ?
                """,
                (
                    finished_at,
                    outcome,
                    error_code,
                    error_message,
                    provider_request_id,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    attempt_id,
                ),
            )
            conn.execute(
                """
                UPDATE content_state
                SET status = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE content_uid = ?
                """,
                (
                    final_status,
                    finished_at,
                    str(attempt["content_uid"]),
                ),
            )
            return final_status

    def reopen_after_qa_retry(
        self,
        *,
        content_uid: str,
        max_attempts: int,
        updated_at: str,
    ) -> str:
        """Reopen a succeeded ContentUid after QA rejected its current candidate."""
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                """
                SELECT status, attempt_count, translated_text, output_hash
                FROM content_state
                WHERE content_uid = ?
                """,
                (content_uid,),
            ).fetchone()
            if state is None:
                raise ValueError(f"unknown ContentUid: {content_uid}")
            if str(state["status"]) != STATUS_SUCCEEDED:
                raise ValueError(f"ContentUid is not succeeded: {content_uid}")
            if state["translated_text"] is None or not str(state["output_hash"] or ""):
                raise ValueError(f"ContentUid has no completed translation output: {content_uid}")

            attempts_used = int(state["attempt_count"])
            next_status = (
                STATUS_FAILED_RETRYABLE
                if attempts_used < max_attempts
                else STATUS_FAILED_FINAL
            )
            conn.execute(
                """
                UPDATE content_state
                SET status = ?,
                    translated_text = NULL,
                    output_hash = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE content_uid = ?
                """,
                (next_status, updated_at, content_uid),
            )
            return next_status

    def recover_stale_leases(self, *, now: str) -> int:
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT content_uid, last_attempt_id
                FROM content_state
                WHERE status = ?
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY content_uid
                """,
                (STATUS_RUNNING, now),
            ).fetchall()

            for row in rows:
                attempt_id = row["last_attempt_id"]
                if attempt_id is not None:
                    conn.execute(
                        """
                        UPDATE attempts
                        SET finished_at = ?,
                            outcome = 'abandoned',
                            error_code = 'LEASE_EXPIRED',
                            error_message = 'Worker lease expired before terminal result'
                        WHERE attempt_id = ?
                          AND outcome = 'running'
                        """,
                        (now, int(attempt_id)),
                    )
                conn.execute(
                    """
                    UPDATE content_state
                    SET status = ?,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE content_uid = ?
                    """,
                    (STATUS_FAILED_RETRYABLE, now, str(row["content_uid"])),
                )

            return len(rows)

    def finish_run(self, *, run_id: str, finished_at: str) -> None:
        summary = self.summary()
        run_status = "completed"
        if summary.get(STATUS_PENDING, 0) or summary.get(STATUS_RUNNING, 0) or summary.get(STATUS_FAILED_RETRYABLE, 0):
            run_status = "incomplete"
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (finished_at, run_status, run_id),
            )

    def summary(self) -> dict[str, int]:
        with closing(self.connect()) as conn, conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM content_state GROUP BY status"
            ).fetchall()
            return {str(row["status"]): int(row["count"]) for row in rows}

    def list_states_by_status(self, status: str) -> list[dict[str, object]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM content_state
                WHERE status = ?
                ORDER BY batch_id, content_uid
                """,
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, object] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_state(self, content_uid: str) -> dict[str, object] | None:
        with closing(self.connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM content_state WHERE content_uid = ?",
                (content_uid,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_attempts(self, content_uid: str) -> list[dict[str, object]]:
        with closing(self.connect()) as conn, conn:
            rows = conn.execute(
                "SELECT * FROM attempts WHERE content_uid = ? ORDER BY attempt_id",
                (content_uid,),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_prompt_provenance(self, *, attempt_id: int, worker_id: str, input_hash: str,
                                context_fingerprint: str | None, effective_prompt_hash: str,
                                chat_messages_fingerprint: str, prompt_renderer_version: str | None) -> None:
        for value in (context_fingerprint, effective_prompt_hash, chat_messages_fingerprint):
            if value is not None and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None):
                raise ValueError("invalid prompt provenance fingerprint")
        if not effective_prompt_hash or not chat_messages_fingerprint:
            raise ValueError("actual prompt and messages provenance required")
        values = (context_fingerprint, effective_prompt_hash, chat_messages_fingerprint, prompt_renderer_version)
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt, state = self._load_attempt_and_state(conn, attempt_id)
            self._assert_live_owner(attempt, state, worker_id)
            if input_hash != attempt["input_hash"] or input_hash != state["input_hash"]:
                raise ValueError("attempt input identity mismatch")
            previous = tuple(attempt[name] for name in ("context_fingerprint", "effective_prompt_hash", "chat_messages_fingerprint", "prompt_renderer_version"))
            if any(value is not None for value in previous) and previous != values:
                raise ValueError("attempt prompt provenance is already bound")
            conn.execute("UPDATE attempts SET context_fingerprint=?,effective_prompt_hash=?,chat_messages_fingerprint=?,prompt_renderer_version=? WHERE attempt_id=?", (*values, attempt_id))

    @staticmethod
    def _load_attempt_and_state(
        conn: sqlite3.Connection,
        attempt_id: int,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        attempt = conn.execute(
            "SELECT * FROM attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if attempt is None:
            raise ValueError(f"unknown attempt_id: {attempt_id}")
        if str(attempt["outcome"]) != "running":
            raise ValueError(f"attempt already terminal: {attempt_id}")
        state = conn.execute(
            "SELECT * FROM content_state WHERE content_uid = ?",
            (str(attempt["content_uid"]),),
        ).fetchone()
        if state is None:
            raise ValueError(f"missing content state for attempt: {attempt_id}")
        return attempt, state

    @staticmethod
    def _assert_live_owner(
        attempt: sqlite3.Row,
        state: sqlite3.Row,
        worker_id: str,
    ) -> None:
        if str(state["status"]) != STATUS_RUNNING:
            raise ValueError(f"ContentUid is not running: {attempt['content_uid']}")
        if str(state["lease_owner"] or "") != worker_id:
            raise ValueError(f"worker does not own lease for {attempt['content_uid']}")
        if int(state["last_attempt_id"] or 0) != int(attempt["attempt_id"]):
            raise ValueError(f"attempt is not current for {attempt['content_uid']}")
        if state["input_hash"] != attempt["input_hash"]:
            raise ValueError("attempt input identity is no longer current")


def _validate_usage(*values: int | None) -> None:
    if any(
        value is not None
        and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
        for value in values
    ):
        raise ValueError("provider token usage must contain non-negative integers")
