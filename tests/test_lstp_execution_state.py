from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from argparse import Namespace
from bg3loc.commands.translation_state import (
    load_execution_items,
    run_claim,
    run_fail,
    run_run_finish,
    run_run_start,
    run_succeed,
)
from bg3loc.execution_runner import (
    TranslationFailure,
    TranslationSuccess,
    run_worker,
)
from bg3loc.prompt_assembly import (
    GlossaryEntry,
    TranslationRuleSet,
    assemble_translation_prompt,
)
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.execution_state import (
    ExecutionItem,
    STATUS_FAILED_FINAL,
    STATUS_FAILED_RETRYABLE,
    STATUS_INVALIDATED,
    STATUS_PENDING,
    STATUS_SUCCEEDED,
    TranslationExecutionStore,
)


class TestTranslationExecutionState(unittest.TestCase):
    def make_store(self, root: Path) -> TranslationExecutionStore:
        store = TranslationExecutionStore(root / "execution.sqlite3")
        store.initialize()
        return store

    def start_run(
        self,
        store: TranslationExecutionStore,
        run_id: str,
        *,
        provider: str = "provider-a",
        model: str = "model-a",
    ) -> None:
        store.start_run(
            run_id=run_id,
            batch_plan_fingerprint="plan-1",
            provider=provider,
            model=model,
            prompt_version="prompt-v1",
            execution_config_hash=f"config-{provider}-{model}",
            started_at="2026-09-23T00:00:00Z",
        )

    def test_prompt_assembly_is_deterministic_and_category_aware(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-prompt","batches":['
                '{"batchId":"bark-0001","primaryCategory":"bark","recordCount":1}'
                ']}',
                encoding="utf-8",
            )
            (materials / "bark-0001.jsonl").write_text(
                '{"contentUid":"uid-a","sourceText":"Hello {PLAYER} %s",'
                '"translationText":"","primaryCategory":"bark","batchId":"bark-0001",'
                '"canonicalGroupKey":"dialog:act1/foo",'
                '"contextGroupKeys":["dialog:act1/foo","speaker:a"]}\n',
                encoding="utf-8",
            )

            _, items = load_execution_items(plan, prompt_version="prompt-v1")
            store = self.make_store(root)
            store.seed_items(items, updated_at="seed")
            self.start_run(store, "run-prompt")
            claim = store.claim_next(
                run_id="run-prompt",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert claim is not None
            request = BatchMaterialResolver(plan).resolve(claim)

            self.assertEqual(request.protected_tokens, ("{PLAYER}", "%s"))

            ruleset = TranslationRuleSet(
                version="rules-v1",
                common_rules=("Preserve meaning.", "Preserve protected tokens exactly."),
                category_rules={
                    "bark": ("Keep bark lines concise.",),
                    "item": ("Use item terminology.",),
                },
                glossary=(
                    GlossaryEntry("Sword", "劍"),
                    GlossaryEntry("Shield", "盾"),
                ),
            )
            first = assemble_translation_prompt(request, ruleset)
            second = assemble_translation_prompt(request, ruleset)

            self.assertEqual(first.instructions, (
                "Preserve meaning.",
                "Preserve protected tokens exactly.",
                "Keep bark lines concise.",
            ))
            self.assertEqual(first.protected_tokens, ("{PLAYER}", "%s"))
            self.assertEqual(first.ruleset_fingerprint, second.ruleset_fingerprint)
            self.assertEqual(first.effective_prompt_hash, second.effective_prompt_hash)
            self.assertEqual(
                [entry.source for entry in first.glossary],
                ["Shield", "Sword"],
            )

            changed = TranslationRuleSet(
                version="rules-v2",
                common_rules=("Preserve meaning.", "Preserve protected tokens exactly."),
                category_rules={"bark": ("Keep bark lines concise.",)},
            )
            changed_prompt = assemble_translation_prompt(request, changed)
            self.assertNotEqual(
                first.ruleset_fingerprint,
                changed_prompt.ruleset_fingerprint,
            )
            self.assertNotEqual(
                first.effective_prompt_hash,
                changed_prompt.effective_prompt_hash,
            )

    def test_prompt_assembly_fails_closed_without_category_rules(self) -> None:
        from bg3loc.translation_request import TranslationRequest

        request = TranslationRequest(
            content_uid="uid-a",
            batch_id="bark-0001",
            attempt_number=1,
            input_hash="input-a",
            source_text="Hello",
            primary_category="bark",
            canonical_group_key="dialog:act1/foo",
            context_group_keys=("dialog:act1/foo",),
            protected_tokens=(),
        )
        ruleset = TranslationRuleSet(
            version="rules-v1",
            common_rules=("Preserve meaning.",),
            category_rules={"item": ("Use item terminology.",)},
        )
        with self.assertRaisesRegex(ValueError, "no translation rules configured"):
            assemble_translation_prompt(request, ruleset)

    def test_material_aware_worker_receives_real_translation_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-material","batches":['
                '{"batchId":"bark-0001","primaryCategory":"bark","recordCount":2}'
                ']}',
                encoding="utf-8",
            )
            (materials / "bark-0001.jsonl").write_text(
                '{"contentUid":"uid-a","sourceText":"Hello","translationText":"",'
                '"primaryCategory":"bark","batchId":"bark-0001",'
                '"canonicalGroupKey":"dialog:act1/foo",'
                '"contextGroupKeys":["dialog:act1/foo","speaker:a"]}\n'
                '{"contentUid":"uid-b","sourceText":"Goodbye","translationText":"",'
                '"primaryCategory":"bark","batchId":"bark-0001",'
                '"canonicalGroupKey":"dialog:act1/foo",'
                '"contextGroupKeys":["dialog:act1/foo","speaker:b"]}\n',
                encoding="utf-8",
            )

            fingerprint, items = load_execution_items(plan, prompt_version="prompt-v1")
            self.assertEqual(fingerprint, "fp-material")

            store = self.make_store(root)
            store.seed_items(items, updated_at="seed")
            self.start_run(store, "run-material")

            resolver = BatchMaterialResolver(plan)
            seen = []

            def fake_provider(request):
                seen.append(request)
                return TranslationSuccess(
                    text=f"ZH:{request.source_text}",
                    provider_request_id=f"req-{request.content_uid}",
                )

            summary = run_worker(
                store,
                run_id="run-material",
                worker_id="worker-material",
                provider=fake_provider,
                request_resolver=resolver.resolve,
                max_attempts=3,
                lease_seconds=300,
            )

            self.assertEqual(summary.claimed, 2)
            self.assertEqual(summary.succeeded, 2)
            self.assertEqual([r.content_uid for r in seen], ["uid-a", "uid-b"])
            self.assertEqual(seen[0].source_text, "Hello")
            self.assertEqual(seen[0].primary_category, "bark")
            self.assertEqual(seen[0].canonical_group_key, "dialog:act1/foo")
            self.assertEqual(
                seen[0].context_group_keys,
                ("dialog:act1/foo", "speaker:a"),
            )
            self.assertEqual(store.get_state("uid-a")["translated_text"], "ZH:Hello")
            self.assertEqual(store.get_state("uid-b")["translated_text"], "ZH:Goodbye")

    def test_material_resolution_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-material","batches":['
                '{"batchId":"bark-0001","primaryCategory":"bark","recordCount":1}'
                ']}',
                encoding="utf-8",
            )
            (materials / "bark-0001.jsonl").write_text(
                '{"contentUid":"different-uid","sourceText":"Hello","translationText":"",'
                '"primaryCategory":"bark","batchId":"bark-0001",'
                '"canonicalGroupKey":"dialog:act1/foo","contextGroupKeys":[]}\n',
                encoding="utf-8",
            )

            store = self.make_store(root)
            store.seed_items(
                [ExecutionItem("uid-a", "bark-0001", "input-a")],
                updated_at="seed",
            )
            self.start_run(store, "run-material")
            resolver = BatchMaterialResolver(plan)

            called = False

            def fake_provider(_request):
                nonlocal called
                called = True
                return TranslationSuccess(text="should-not-run")

            summary = run_worker(
                store,
                run_id="run-material",
                worker_id="worker-material",
                provider=fake_provider,
                request_resolver=resolver.resolve,
                max_attempts=3,
                lease_seconds=300,
            )

            self.assertFalse(called)
            self.assertEqual(summary.claimed, 1)
            self.assertEqual(summary.failed_final, 1)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_FAILED_FINAL)
            attempts = store.get_attempts("uid-a")
            self.assertEqual(attempts[0]["error_code"], "MATERIAL_RESOLUTION_ERROR")

    def test_provider_neutral_worker_loop_retries_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.make_store(root)
            store.seed_items(
                [
                    ExecutionItem("uid-a", "item-0001", "input-a"),
                    ExecutionItem("uid-b", "item-0001", "input-b"),
                ],
                updated_at="seed",
            )
            self.start_run(store, "run-worker")

            calls: dict[str, int] = {}

            def fake_provider(claim):
                calls[claim.content_uid] = calls.get(claim.content_uid, 0) + 1
                if claim.content_uid == "uid-a" and calls[claim.content_uid] == 1:
                    return TranslationFailure(
                        error_code="HTTP_429",
                        error_message="rate limited",
                        retryable=True,
                        provider_request_id="req-a1",
                    )
                return TranslationSuccess(
                    text=f"translated:{claim.content_uid}",
                    provider_request_id=f"req-{claim.content_uid}-{calls[claim.content_uid]}",
                )

            summary = run_worker(
                store,
                run_id="run-worker",
                worker_id="worker-1",
                provider=fake_provider,
                max_attempts=3,
                lease_seconds=300,
            )

            self.assertEqual(summary.claimed, 3)
            self.assertEqual(summary.succeeded, 2)
            self.assertEqual(summary.failed_retryable, 1)
            self.assertEqual(summary.failed_final, 0)
            self.assertEqual(store.get_state("uid-a")["status"], STATUS_SUCCEEDED)
            self.assertEqual(store.get_state("uid-b")["status"], STATUS_SUCCEEDED)
            self.assertEqual(len(store.get_attempts("uid-a")), 2)
            self.assertEqual(len(store.get_attempts("uid-b")), 1)

    def test_provider_exception_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.make_store(root)
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="seed",
            )
            self.start_run(store, "run-worker")

            def broken_provider(_claim):
                raise RuntimeError("boom")

            summary = run_worker(
                store,
                run_id="run-worker",
                worker_id="worker-1",
                provider=broken_provider,
                max_attempts=3,
                lease_seconds=300,
            )

            self.assertEqual(summary.claimed, 1)
            self.assertEqual(summary.failed_final, 1)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_FAILED_FINAL)
            attempts = store.get_attempts("uid-a")
            self.assertEqual(attempts[0]["error_code"], "PROVIDER_EXCEPTION")

    def test_manual_cli_lifecycle_retry_resume_and_provider_switch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "execution.sqlite3"
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-cli","batches":['
                '{"batchId":"item-0001","primaryCategory":"item","recordCount":2}'
                ']}',
                encoding="utf-8",
            )
            (materials / "item-0001.jsonl").write_text(
                '{"ContentUid":"uid-a","SourceText":"Sword","primaryCategory":"item"}\n'
                '{"ContentUid":"uid-b","SourceText":"Shield","primaryCategory":"item"}\n',
                encoding="utf-8",
            )
            _, items = load_execution_items(plan, prompt_version="prompt-v1")
            store = self.make_store(root)
            store.seed_items(items, updated_at="seed")

            self.assertEqual(
                run_run_start(Namespace(
                    db=str(db),
                    run_id="run-cli-1",
                    batch_plan=str(plan),
                    provider="provider-a",
                    model="model-a",
                    prompt_version="prompt-v1",
                    execution_config_hash=None,
                )),
                0,
            )
            self.assertEqual(
                run_claim(Namespace(
                    db=str(db),
                    run_id="run-cli-1",
                    worker_id="worker-a",
                    lease_seconds=300,
                    max_attempts=3,
                )),
                0,
            )
            attempts = store.get_attempts("uid-a")
            self.assertEqual(len(attempts), 1)
            first_attempt = int(attempts[0]["attempt_id"])

            self.assertEqual(
                run_fail(Namespace(
                    db=str(db),
                    attempt_id=first_attempt,
                    worker_id="worker-a",
                    error_code="HTTP_429",
                    error_message="rate limited",
                    retryable=True,
                    max_attempts=3,
                    provider_request_id=None,
                )),
                0,
            )
            self.assertEqual(store.get_state("uid-a")["status"], STATUS_FAILED_RETRYABLE)

            self.assertEqual(
                run_claim(Namespace(
                    db=str(db),
                    run_id="run-cli-1",
                    worker_id="worker-a",
                    lease_seconds=300,
                    max_attempts=3,
                )),
                0,
            )
            attempts = store.get_attempts("uid-a")
            self.assertEqual(len(attempts), 2)
            retry_attempt = int(attempts[-1]["attempt_id"])
            self.assertEqual(int(attempts[-1]["attempt_number"]), 2)

            self.assertEqual(
                run_succeed(Namespace(
                    db=str(db),
                    attempt_id=retry_attempt,
                    worker_id="worker-a",
                    text="劍",
                    provider_request_id="req-1",
                )),
                0,
            )
            self.assertEqual(store.get_state("uid-a")["status"], STATUS_SUCCEEDED)

            self.assertEqual(
                run_run_finish(Namespace(db=str(db), run_id="run-cli-1")),
                0,
            )

            self.assertEqual(
                run_run_start(Namespace(
                    db=str(db),
                    run_id="run-cli-2",
                    batch_plan=str(plan),
                    provider="provider-b",
                    model="model-b",
                    prompt_version="prompt-v1",
                    execution_config_hash=None,
                )),
                0,
            )
            self.assertEqual(
                run_claim(Namespace(
                    db=str(db),
                    run_id="run-cli-2",
                    worker_id="worker-b",
                    lease_seconds=300,
                    max_attempts=3,
                )),
                0,
            )
            self.assertEqual(len(store.get_attempts("uid-a")), 2)
            self.assertEqual(store.get_state("uid-a")["status"], STATUS_SUCCEEDED)
            self.assertEqual(store.get_state("uid-b")["status"], "running")
            attempts_b = store.get_attempts("uid-b")
            self.assertEqual(attempts_b[-1]["provider"], "provider-b")
            self.assertEqual(attempts_b[-1]["model"], "model-b")

    def test_batch_plan_materials_seed_execution_items(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-1","batches":['
                '{"batchId":"item-0001","primaryCategory":"item","recordCount":2}'
                ']}',
                encoding="utf-8",
            )
            (materials / "item-0001.jsonl").write_text(
                '{"ContentUid":"uid-a","SourceText":"Sword","primaryCategory":"item"}\n'
                '{"ContentUid":"uid-b","SourceText":"Shield","primaryCategory":"item"}\n',
                encoding="utf-8",
            )

            fingerprint, items = load_execution_items(plan, prompt_version="prompt-v1")
            self.assertEqual(fingerprint, "fp-1")
            self.assertEqual([item.content_uid for item in items], ["uid-a", "uid-b"])
            self.assertNotEqual(items[0].input_hash, items[1].input_hash)

            store = self.make_store(root)
            store.seed_items(items, updated_at="seed")
            self.assertEqual(store.summary(), {STATUS_PENDING: 2})

    def test_reseed_same_batch_plan_preserves_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            materials.mkdir()
            plan = root / "batch-plan.json"
            plan.write_text(
                '{"batchPlanFingerprint":"fp-1","batches":['
                '{"batchId":"item-0001","primaryCategory":"item","recordCount":1}'
                ']}',
                encoding="utf-8",
            )
            (materials / "item-0001.jsonl").write_text(
                '{"ContentUid":"uid-a","SourceText":"Sword","primaryCategory":"item"}\n',
                encoding="utf-8",
            )
            _, items = load_execution_items(plan, prompt_version="prompt-v1")

            store = self.make_store(root)
            store.seed_items(items, updated_at="seed-1")
            self.start_run(store, "run-1")
            claim = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert claim is not None
            store.complete_success(
                attempt_id=claim.attempt_id,
                worker_id="worker-a",
                translated_text="劍",
                output_hash="out-a",
                finished_at="2026-09-23T00:02:00Z",
            )

            _, same_items = load_execution_items(plan, prompt_version="prompt-v1")
            store.seed_items(same_items, updated_at="seed-2")
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_SUCCEEDED)
            self.assertEqual(state["translated_text"], "劍")
            self.assertEqual(state["attempt_count"], 1)

    def test_store_operations_release_windows_file_handle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "execution.sqlite3"
            store = self.make_store(root)
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.assertTrue(db_path.is_file())
            db_path.unlink()
            self.assertFalse(db_path.exists())

    def test_success_is_durable_and_not_claimed_again(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1")

            claim = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            self.assertIsNotNone(claim)
            assert claim is not None
            store.complete_success(
                attempt_id=claim.attempt_id,
                worker_id="worker-a",
                translated_text="譯文",
                output_hash="out-a",
                finished_at="2026-09-23T00:02:00Z",
            )

            state = store.get_state("uid-a")
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state["status"], STATUS_SUCCEEDED)
            self.assertEqual(state["translated_text"], "譯文")
            self.assertEqual(state["attempt_count"], 1)

            again = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:20:00Z",
                started_at="2026-09-23T00:03:00Z",
                max_attempts=3,
            )
            self.assertIsNone(again)

    def test_retryable_failure_retries_only_failed_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [
                    ExecutionItem("uid-a", "item-0001", "input-a"),
                    ExecutionItem("uid-b", "item-0001", "input-b"),
                ],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1")

            first = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert first is not None
            self.assertEqual(first.content_uid, "uid-a")
            status = store.complete_failure(
                attempt_id=first.attempt_id,
                worker_id="worker-a",
                error_code="HTTP_429",
                error_message="rate limited",
                retryable=True,
                max_attempts=3,
                finished_at="2026-09-23T00:02:00Z",
            )
            self.assertEqual(status, STATUS_FAILED_RETRYABLE)

            retry = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:20:00Z",
                started_at="2026-09-23T00:03:00Z",
                max_attempts=3,
            )
            assert retry is not None
            self.assertEqual(retry.content_uid, "uid-a")
            self.assertEqual(retry.attempt_number, 2)
            store.complete_success(
                attempt_id=retry.attempt_id,
                worker_id="worker-a",
                translated_text="A",
                output_hash="out-a",
                finished_at="2026-09-23T00:04:00Z",
            )

            next_claim = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:30:00Z",
                started_at="2026-09-23T00:05:00Z",
                max_attempts=3,
            )
            assert next_claim is not None
            self.assertEqual(next_claim.content_uid, "uid-b")

    def test_retry_limit_becomes_final_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1")

            for attempt_number in (1, 2, 3):
                claim = store.claim_next(
                    run_id="run-1",
                    worker_id="worker-a",
                    lease_expires_at=f"2026-09-23T00:{attempt_number + 10:02d}:00Z",
                    started_at=f"2026-09-23T00:0{attempt_number}:00Z",
                    max_attempts=3,
                )
                assert claim is not None
                status = store.complete_failure(
                    attempt_id=claim.attempt_id,
                    worker_id="worker-a",
                    error_code="TEMP",
                    error_message="temporary failure",
                    retryable=True,
                    max_attempts=3,
                    finished_at=f"2026-09-23T00:0{attempt_number}:30Z",
                )

            self.assertEqual(status, STATUS_FAILED_FINAL)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_FAILED_FINAL)
            self.assertEqual(state["attempt_count"], 3)
            self.assertIsNone(
                store.claim_next(
                    run_id="run-1",
                    worker_id="worker-a",
                    lease_expires_at="2026-09-23T01:00:00Z",
                    started_at="2026-09-23T00:10:00Z",
                    max_attempts=3,
                )
            )

    def test_stale_lease_is_recovered_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1")
            claim = store.claim_next(
                run_id="run-1",
                worker_id="dead-worker",
                lease_expires_at="2026-09-23T00:05:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert claim is not None

            recovered = store.recover_stale_leases(now="2026-09-23T00:06:00Z")
            self.assertEqual(recovered, 1)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_FAILED_RETRYABLE)
            self.assertIsNone(state["lease_owner"])

            attempts = store.get_attempts("uid-a")
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["outcome"], "abandoned")
            self.assertEqual(attempts[0]["error_code"], "LEASE_EXPIRED")

            retry = store.claim_next(
                run_id="run-1",
                worker_id="worker-b",
                lease_expires_at="2026-09-23T00:20:00Z",
                started_at="2026-09-23T00:07:00Z",
                max_attempts=3,
            )
            assert retry is not None
            self.assertEqual(retry.attempt_number, 2)

    def test_same_input_can_move_batch_without_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_PENDING)

            store.seed_items(
                [ExecutionItem("uid-a", "item-0099", "input-a")],
                updated_at="2026-09-23T00:01:00Z",
            )
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_PENDING)
            self.assertEqual(state["batch_id"], "item-0099")

    def test_changed_input_explicitly_invalidates_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [ExecutionItem("uid-a", "item-0001", "input-a")],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1")
            claim = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert claim is not None
            store.complete_success(
                attempt_id=claim.attempt_id,
                worker_id="worker-a",
                translated_text="old translation",
                output_hash="out-old",
                finished_at="2026-09-23T00:02:00Z",
            )

            store.seed_items(
                [ExecutionItem("uid-a", "item-0002", "input-b")],
                updated_at="2026-09-23T00:03:00Z",
            )
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], STATUS_INVALIDATED)
            self.assertEqual(state["input_hash"], "input-b")
            self.assertEqual(state["attempt_count"], 0)
            self.assertEqual(state["translated_text"], "old translation")

    def test_new_provider_run_preserves_success_and_picks_unfinished(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(Path(td))
            store.seed_items(
                [
                    ExecutionItem("uid-a", "item-0001", "input-a"),
                    ExecutionItem("uid-b", "item-0001", "input-b"),
                ],
                updated_at="2026-09-23T00:00:00Z",
            )
            self.start_run(store, "run-1", provider="provider-a", model="model-a")
            first = store.claim_next(
                run_id="run-1",
                worker_id="worker-a",
                lease_expires_at="2026-09-23T00:10:00Z",
                started_at="2026-09-23T00:01:00Z",
                max_attempts=3,
            )
            assert first is not None
            self.assertEqual(first.content_uid, "uid-a")
            store.complete_success(
                attempt_id=first.attempt_id,
                worker_id="worker-a",
                translated_text="A",
                output_hash="out-a",
                finished_at="2026-09-23T00:02:00Z",
            )
            store.finish_run(run_id="run-1", finished_at="2026-09-23T00:03:00Z")

            self.start_run(store, "run-2", provider="provider-b", model="model-b")
            second = store.claim_next(
                run_id="run-2",
                worker_id="worker-b",
                lease_expires_at="2026-09-23T00:20:00Z",
                started_at="2026-09-23T00:04:00Z",
                max_attempts=3,
            )
            assert second is not None
            self.assertEqual(second.content_uid, "uid-b")

            attempts_a = store.get_attempts("uid-a")
            self.assertEqual(len(attempts_a), 1)
            self.assertEqual(attempts_a[0]["provider"], "provider-a")
            self.assertEqual(attempts_a[0]["model"], "model-a")


if __name__ == "__main__":
    unittest.main()
