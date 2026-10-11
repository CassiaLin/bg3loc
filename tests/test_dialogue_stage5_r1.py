"""Decision integrity in complete fictional 1.3 workspaces; no transport."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import sqlite3

import pytest

from bg3loc.dialogue_review import apply_dialogue_semantic_review
from bg3loc.production_review import ProductionReviewStore
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import TranslationQaStore
from test_dialogue_stage4 import prepared, finish_all
from test_production_context import material_rows


NOW = "2026-10-10T01:00:00Z"
FAMILIES = ("H0", "HSE", "HD")
DECISIONS = ("ACCEPT", "REVISE")


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def database_contents(path):
    # Include every table, history and sequence, not just the decision row.
    with closing(sqlite3.connect(path)) as conn:
        return tuple(conn.iterdump())


def review_candidate(root, family):
    request, backend, _ = prepared(root)
    finish_all(request, backend)
    rows = material_rows(request.output_dir)
    key, material = next((key, row) for key, row in rows.items() if
        ("HD" if "dialogueContext" in row else
         "HSE" if "sameEntityContext" in row else "H0") == family)
    database = request.output_dir / "execution.sqlite3"
    source = material["sourceText"]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE content_state SET translated_text=?,output_hash=? WHERE content_uid=?",
                     (source, digest(source), key))
        input_hash = conn.execute("SELECT input_hash FROM content_state WHERE content_uid=?", (key,)).fetchone()[0]
    qa = TranslationQaStore(database)
    result = apply_dialogue_semantic_review(evaluate_translation(QaInput(
        key, source, source, material["primaryCategory"], tuple(extract_protected_tokens(source)))),
        dialogue_context_present=family == "HD")
    assert result.route == "REVIEW"
    qa.record_result(result, checked_at=NOW, expected_input_hash=input_hash, expected_output_hash=digest(source))
    return ProductionReviewStore(database), qa, key, material


def decision_arguments(qa, key, material, decision):
    result = qa.get_result(key)
    return dict(content_uid=key, decision=decision, reviewer="SYNTHETIC test reviewer",
        note="Synthetic engineering evidence, not human semantic review", resolved_at=NOW,
        revised_text="SYNTHETIC revised " + material["sourceText"] if decision == "REVISE" else None,
        stage3_validation_only=True, expected_execution_input_hash=result.execution_input_hash,
        expected_output_hash=result.output_hash, expected_qa_input_hash=result.qa_input_hash,
        expected_qa_rule_set_version=result.qa_rule_set_version)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("decision", DECISIONS)
def test_s5_b1_six_stale_base_byte_probes_reject_without_any_writes(tmp_path, family, decision):
    review, qa, key, material = review_candidate(tmp_path / "input", family)
    arguments = decision_arguments(qa, key, material, decision)
    with closing(sqlite3.connect(review.path)) as conn, conn:
        conn.execute("UPDATE content_state SET translated_text=? WHERE content_uid=?",
                     ("SYNTHETIC unbound changed candidate", key))
    before = database_contents(review.path)
    with pytest.raises(ValueError, match="base output bytes"):
        review.resolve(**arguments)
    assert database_contents(review.path) == before


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("decision", DECISIONS)
def test_current_accept_and_revise_preserve_bindings_and_semantic_gate(tmp_path, family, decision):
    review, qa, key, material = review_candidate(tmp_path / "input", family)
    arguments = decision_arguments(qa, key, material, decision)
    resolved = review.resolve(**arguments)
    result = qa.get_result(key, dialogue_context_required=family == "HD")
    expected_route = "PASS" if decision == "REVISE" and family != "HD" else "REVIEW"
    assert result.qa_status == "checked" and result.route == expected_route
    assert result.execution_input_hash == arguments["expected_execution_input_hash"]
    assert resolved.base_output_hash == arguments["expected_output_hash"]
    assert resolved.resolved_output_hash == result.output_hash
    if expected_route == "REVIEW":
        assert review.get_current_acceptance(key, current_output_hash=result.output_hash) == resolved
    else:
        assert review.get_current_acceptance(key, current_output_hash=result.output_hash) is None
    with closing(sqlite3.connect(review.path)) as conn:
        text, declared = conn.execute("SELECT translated_text,output_hash FROM content_state WHERE content_uid=?", (key,)).fetchone()
    assert digest(text) == declared == result.output_hash
    assert text == (arguments["revised_text"] if decision == "REVISE" else material["sourceText"])
    if family == "HD":
        from bg3loc.dialogue_review import semantic_gate_present
        assert semantic_gate_present(result.issues)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("decision", DECISIONS)
def test_qa_snapshot_for_other_actual_bytes_rejects_even_with_matching_expected_tokens(tmp_path, family, decision):
    review, qa, key, material = review_candidate(tmp_path / "input", family)
    other_result = evaluate_translation(QaInput(key, material["sourceText"], "SYNTHETIC other bytes",
        material["primaryCategory"], tuple(extract_protected_tokens(material["sourceText"]))))
    with closing(sqlite3.connect(review.path)) as conn, conn:
        conn.execute("UPDATE qa_results SET qa_input_hash=? WHERE content_uid=?", (other_result.qa_input_hash, key))
    arguments = decision_arguments(qa, key, material, decision)
    before = database_contents(review.path)
    with pytest.raises(ValueError, match="QA snapshot does not match base output"):
        review.resolve(**arguments)
    assert database_contents(review.path) == before


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("decision", DECISIONS)
def test_committed_concurrent_bytes_mutation_between_preflight_and_writer_rejects(tmp_path, family, decision, monkeypatch):
    review, qa, key, material = review_candidate(tmp_path / "input", family)
    arguments = decision_arguments(qa, key, material, decision)
    get_result = TranslationQaStore.get_result
    after_mutation = []

    def mutate():
        with closing(sqlite3.connect(review.path)) as conn, conn:
            conn.execute("UPDATE content_state SET translated_text=? WHERE content_uid=?", ("SYNTHETIC concurrent mutation", key))

    def racing_get_result(self, *args, **kwargs):
        result = get_result(self, *args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(mutate).result(timeout=5)
        after_mutation.append(database_contents(review.path))
        return result

    monkeypatch.setattr(TranslationQaStore, "get_result", racing_get_result)
    with pytest.raises(ValueError, match="base output bytes"):
        review.resolve(**arguments)
    assert len(after_mutation) == 1
    assert database_contents(review.path) == after_mutation[0]


@pytest.mark.parametrize("decision", DECISIONS)
@pytest.mark.parametrize("change", ("base_hash", "input", "qa_hash", "qa_ruleset", "qa_route", "qa_binding"))
def test_concurrent_current_identity_and_qa_changes_reject_without_decision_writes(tmp_path, decision, change, monkeypatch):
    review, qa, key, material = review_candidate(tmp_path / "input", "HD")
    arguments = decision_arguments(qa, key, material, decision)
    get_result = TranslationQaStore.get_result
    after_mutation = []

    def mutate():
        with closing(sqlite3.connect(review.path)) as conn, conn:
            if change == "base_hash":
                text = "SYNTHETIC different declared candidate"
                conn.execute("UPDATE content_state SET translated_text=?,output_hash=? WHERE content_uid=?", (text, digest(text), key))
            elif change == "input":
                conn.execute("UPDATE content_state SET input_hash=? WHERE content_uid=?", (digest("SYNTHETIC changed input"), key))
            elif change == "qa_hash":
                conn.execute("UPDATE qa_results SET qa_input_hash=? WHERE content_uid=?", (digest("SYNTHETIC changed QA"), key))
            elif change == "qa_ruleset":
                conn.execute("UPDATE qa_results SET qa_rule_set_version='SYNTHETIC other version' WHERE content_uid=?", (key,))
            elif change == "qa_route":
                conn.execute("UPDATE qa_results SET route='PASS' WHERE content_uid=?", (key,))
            else:
                conn.execute("UPDATE qa_results SET execution_input_hash=NULL WHERE content_uid=?", (key,))

    def racing_get_result(self, *args, **kwargs):
        result = get_result(self, *args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(mutate).result(timeout=5)
        after_mutation.append(database_contents(review.path))
        return result

    monkeypatch.setattr(TranslationQaStore, "get_result", racing_get_result)
    with pytest.raises(ValueError, match="stale|snapshot changed"):
        review.resolve(**arguments)
    assert len(after_mutation) == 1
    assert database_contents(review.path) == after_mutation[0]


@pytest.mark.parametrize("decision", DECISIONS)
@pytest.mark.parametrize("journal_mode", ("DELETE", "WAL"))
def test_writer_transaction_blocks_concurrent_candidate_update(tmp_path, decision, journal_mode, monkeypatch):
    review, qa, key, material = review_candidate(tmp_path / "input", "HD")
    with closing(sqlite3.connect(review.path)) as conn:
        assert conn.execute("PRAGMA journal_mode=" + journal_mode).fetchone()[0].upper() == journal_mode
    arguments = decision_arguments(qa, key, material, decision)
    import bg3loc.production_review as module
    validate = module.validated_stage3_material
    observed = []

    def competing_writer():
        with closing(sqlite3.connect(review.path, timeout=0.05)) as other, other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE content_state SET translated_text=? WHERE content_uid=?", ("SYNTHETIC concurrent overwrite", key))
        return "blocked"

    def validate_with_competitor(*args, **kwargs):
        conn = kwargs.get("_connection")
        if conn is not None:
            assert conn.in_transaction
            with ThreadPoolExecutor(max_workers=1) as pool:
                observed.append(pool.submit(competing_writer).result(timeout=5))
        return validate(*args, **kwargs)

    monkeypatch.setattr(module, "validated_stage3_material", validate_with_competitor)
    resolved = review.resolve(**arguments)
    assert observed == ["blocked"]
    assert resolved.resolved_output_hash == digest(arguments["revised_text"] or material["sourceText"])


@pytest.mark.parametrize("family", FAMILIES)
def test_revise_late_persistence_failure_rolls_back_candidate_qa_and_all_history(tmp_path, family):
    review, qa, key, material = review_candidate(tmp_path / "input", family)
    arguments = decision_arguments(qa, key, material, "REVISE")
    with closing(sqlite3.connect(review.path)) as conn:
        conn.execute("CREATE TRIGGER synthetic_decision_failure BEFORE INSERT ON qa_review_resolutions "
                     "BEGIN SELECT RAISE(ABORT, 'SYNTHETIC decision persistence failure'); END")
    before = database_contents(review.path)
    with pytest.raises(sqlite3.IntegrityError, match="SYNTHETIC decision persistence failure"):
        review.resolve(**arguments)
    assert database_contents(review.path) == before


@pytest.mark.parametrize("version", ("1.0", "1.1", "1.2"))
@pytest.mark.parametrize("decision", DECISIONS)
def test_legacy_decisions_keep_optional_snapshots_and_unknown_null_history(version, decision):
    from test_production_review import TestProductionReviewResolution
    temp, database, plan, source = TestProductionReviewResolution()._fixture()
    with temp, closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE metadata SET value=? WHERE key='schemaVersion'", (version,))
        conn.execute("UPDATE qa_results SET execution_input_hash=NULL")
        conn.execute("INSERT INTO qa_review_resolutions(content_uid,decision,qa_rule_set_version,qa_input_hash,"
                     "base_output_hash,resolved_output_hash,reviewer,note,resolved_at,execution_input_hash) "
                     "VALUES('uid-review','ACCEPT','historical','historical','historical','historical',"
                     "'SYNTHETIC history','UNKNOWN binding','historical',NULL)")
        conn.commit()
        resolved = ProductionReviewStore(database).resolve(content_uid="uid-review", decision=decision,
            reviewer="SYNTHETIC legacy reviewer", note="Synthetic compatibility", resolved_at=NOW,
            revised_text="開啟古老的大門" if decision == "REVISE" else None, batch_plan_path=plan)
        assert resolved.decision == decision and resolved.base_output_hash == digest(source)
        assert conn.execute("SELECT execution_input_hash FROM qa_review_resolutions WHERE resolved_at='historical'").fetchone()[0] is None
        # Legacy REVISE retains the existing stale-QA behavior instead of rewriting it.
        assert conn.execute("SELECT execution_input_hash FROM qa_results").fetchone()[0] is None
