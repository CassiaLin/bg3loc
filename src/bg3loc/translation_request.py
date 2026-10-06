from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from bg3loc.execution_state import ClaimedAttempt
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.production_context import context_from_material
from bg3loc.same_entity_context import SameEntityContext


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    content_uid: str
    batch_id: str
    attempt_number: int
    input_hash: str
    source_text: str
    primary_category: str
    canonical_group_key: str
    context_group_keys: tuple[str, ...]
    protected_tokens: tuple[str, ...]
    same_entity_context: SameEntityContext | None = None

    def __post_init__(self) -> None:
        if self.same_entity_context is not None and not isinstance(self.same_entity_context, SameEntityContext):
            raise TypeError("same_entity_context must be an immutable SameEntityContext or None")


class BatchMaterialResolver:
    """Resolve one claimed ContentUid back to its LSTP-01B material row."""

    def __init__(self, batch_plan_path: str | Path) -> None:
        self.batch_plan_path = Path(batch_plan_path)
        if not self.batch_plan_path.is_file():
            raise RuntimeError(f"batch plan not found: {self.batch_plan_path}")
        with self.batch_plan_path.open("r", encoding="utf-8") as f:
            plan = json.load(f)

        self.batch_plan_fingerprint = str(plan.get("batchPlanFingerprint", ""))
        if not self.batch_plan_fingerprint:
            raise RuntimeError("batch plan is missing batchPlanFingerprint")

        self._batch_ids = {
            str(batch.get("batchId", ""))
            for batch in plan.get("batches", [])
            if isinstance(batch, dict) and batch.get("batchId")
        }
        self._cache_batch_id: str | None = None
        self._cache_rows: dict[str, dict[str, object]] = {}

    def _material_path(self, batch_id: str) -> Path:
        return self.batch_plan_path.parent / "materials" / f"{batch_id}.jsonl"

    def _load_batch(self, batch_id: str) -> None:
        if batch_id not in self._batch_ids:
            raise RuntimeError(f"batchId not present in batch plan: {batch_id}")
        path = self._material_path(batch_id)
        if not path.is_file():
            raise RuntimeError(f"batch material not found: {path}")

        rows: dict[str, dict[str, object]] = {}
        with path.open("r", encoding="utf-8-sig") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise RuntimeError(f"{path}:{line_no}: expected JSON object")
                uid = str(row.get("contentUid", row.get("ContentUid", "")))
                if not uid:
                    raise RuntimeError(f"{path}:{line_no}: missing ContentUid")
                if uid in rows:
                    raise RuntimeError(f"{path}: duplicate ContentUid: {uid}")
                material_batch = str(row.get("batchId", batch_id))
                if material_batch != batch_id:
                    raise RuntimeError(
                        f"{path}:{line_no}: batchId mismatch: {material_batch} != {batch_id}"
                    )
                rows[uid] = row

        self._cache_batch_id = batch_id
        self._cache_rows = rows

    def resolve(self, claim: ClaimedAttempt) -> TranslationRequest:
        if self._cache_batch_id != claim.batch_id:
            self._load_batch(claim.batch_id)

        row = self._cache_rows.get(claim.content_uid)
        if row is None:
            raise RuntimeError(
                f"ContentUid {claim.content_uid} missing from material for {claim.batch_id}"
            )

        context_raw = row.get("contextGroupKeys", [])
        if not isinstance(context_raw, list):
            raise RuntimeError(
                f"ContentUid {claim.content_uid}: contextGroupKeys must be a list"
            )

        return TranslationRequest(
            content_uid=claim.content_uid,
            batch_id=claim.batch_id,
            attempt_number=claim.attempt_number,
            input_hash=claim.input_hash,
            source_text=str(row.get("sourceText", row.get("SourceText", ""))),
            primary_category=str(row.get("primaryCategory", "")),
            canonical_group_key=str(row.get("canonicalGroupKey", "")),
            context_group_keys=tuple(str(value) for value in context_raw),
            protected_tokens=tuple(extract_protected_tokens(
                str(row.get("sourceText", row.get("SourceText", "")))
            )),
            same_entity_context=context_from_material(row),
        )
