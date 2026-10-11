"""Stage 1 production contracts with fictional native evidence only."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from bg3loc.cli import build_parser
from bg3loc.commands.translation_state import load_execution_items, run_init
from bg3loc.dialogue_context import (
    DialogueContextValidationError, DialogueSourceVariant, canonical_bytes,
    decode_dialogue_context, dialogue_context_from_material, evidence_projection,
    fingerprint, strict_json_loads,
)
from bg3loc.dialogue_materialization import DialogueEvidenceAdapter, materialize_inventory
from bg3loc.dialogue_stage_prepare import load_prepared_inventory, prepare_dialogue_stage
from bg3loc.research.dialogue_context import DialogueAudit
from test_dialogue_context_research import attr, dialogue, node, parse, uid

ROOT = Path(__file__).resolve().parents[1]


def graph_data():
    return dialogue([node("T", text=uid(1), children=["Z", "A"]),
                     node("P", text=uid(2), children=["T"]),
                     node("Z", text=uid(3)), node("A", text=uid(4))])


def sources():
    return {uid(1): "Fictional target.", uid(2): "Fictional predecessor.",
            uid(3): "Fictional successor Z.", uid(4): "Fictional successor A."}


def adapter(data=None, text=None):
    return DialogueEvidenceAdapter.from_records(parse(data or graph_data()), text or sources())


def context(data=None, text=None):
    source = text or sources()
    return adapter(data, source).materialize(uid(1), "dialogue_general", source[uid(1)]).context


def decode(value):
    return decode_dialogue_context(value, content_uid=uid(1), category="dialogue_general",
                                   source_text=sources()[uid(1)])


def resign(value):
    value["evidenceFingerprint"] = fingerprint(evidence_projection(value))
    value.pop("contextFingerprint", None)
    value["contextFingerprint"] = fingerprint(value)
    return value


def test_deep_immutable_and_detached_wire():
    dto = context()
    assert dto is not None
    with pytest.raises(FrozenInstanceError):
        dto.source_codepoints = 1
    with pytest.raises(FrozenInstanceError):
        dto.possible_successors[0].source_variants[0].source_text = "changed"
    with pytest.raises(TypeError):
        dto.possible_successors[0] = None
    wire = dto.to_dict()
    wire["possibleSuccessors"][0]["sourceVariants"][0]["sourceText"] = "changed"
    assert dto == decode(dto.to_dict())
    with pytest.raises(DialogueContextValidationError):
        replace(dto, possible_successors=list(dto.possible_successors))
    with pytest.raises(DialogueContextValidationError):
        DialogueSourceVariant(uid(2), "Text", [fingerprint("occ")])


def test_frozen_schema_registry_and_exact_fingerprint_projection():
    wire = context().to_dict()
    contract = json.loads((ROOT / "docs/research/b1-03-stage0-contracts/dialogue-context.schema.json").read_text())
    Draft202012Validator(contract).validate(wire)
    registry = json.loads((ROOT / "docs/research/b1-03-stage0-contracts/version-registry.json").read_text())
    assert wire["budgetContract"] == registry["budgetContract"]
    assert wire["schemaVersion"] == registry["versions"]["dialogueSchema"]
    assert wire["policyVersion"] == registry["versions"]["structuralPolicy"]
    assert wire["evidenceFingerprint"] == fingerprint(evidence_projection(wire))
    assert wire["contextFingerprint"] == fingerprint({k: v for k, v in wire.items() if k != "contextFingerprint"})


@pytest.mark.parametrize("path", [(), ("budgetContract",), ("targetBinding",), ("targetProof",),
    ("possiblePredecessors", 0), ("possiblePredecessors", 0, "nativeChildProof"),
    ("possiblePredecessors", 0, "sourceVariants", 0)])
@pytest.mark.parametrize("mode", ["unknown", "missing", "null"])
def test_closed_schema_every_level(path, mode):
    wire = context().to_dict()
    item = wire
    for part in path:
        item = item[part]
    if mode == "unknown":
        item["unexpected"] = "synthetic"
    else:
        key = next(iter(item))
        if mode == "missing":
            del item[key]
        else:
            item[key] = None
    with pytest.raises(DialogueContextValidationError):
        decode(wire)


@pytest.mark.parametrize("field", ["schemaVersion", "policyVersion", "orderingVersion"])
def test_wrong_versions(field):
    wire = context().to_dict()
    wire[field] += "-unsupported"
    with pytest.raises(DialogueContextValidationError, match="DLG_VERSION_UNSUPPORTED"):
        decode(wire)


@pytest.mark.parametrize("value", [True, 2000.0, "2000", 1999])
def test_budget_contract_exact_type(value):
    wire = context().to_dict()
    wire["budgetContract"]["maxSourceCodepoints"] = value
    with pytest.raises(DialogueContextValidationError):
        decode(wire)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
    '{"x":"\\ud800"}', '\ufeff{}', '{', b'"\xff"', b'\xef\xbb\xbf{}', '{}'.encode('utf-16')])
def test_strict_json_transport(text):
    with pytest.raises(DialogueContextValidationError, match="DLG_SHAPE_INVALID"):
        strict_json_loads(text)


@pytest.mark.parametrize("mutation,code", [
    (lambda w: w["targetProof"].update(nodeIdentityOrigin="fallback_ordinal"), "DLG_BINDING_MISMATCH"),
    (lambda w: w["possiblePredecessors"][0]["nativeChildProof"].update(edgeType="jumptarget"), "DLG_BINDING_MISMATCH"),
    (lambda w: w["possiblePredecessors"][0]["nativeChildProof"].update(toNodeId="wrong"), "DLG_BINDING_MISMATCH"),
    (lambda w: w["possibleSuccessors"].reverse(), "DLG_ORDER_INVALID"),
    (lambda w: w["possibleSuccessors"].append(w["possibleSuccessors"][-1]), "DLG_ORDER_INVALID"),
    (lambda w: w["possiblePredecessors"][0]["sourceVariants"][0].update(contentUid=uid(1)), "DLG_BINDING_MISMATCH"),
    (lambda w: w.update(sourceCodepoints=True), "DLG_BUDGET_MISMATCH"),
    (lambda w: w.update(sourceCodepoints=1), "DLG_BUDGET_MISMATCH"),
    (lambda w: w.update(evidenceFingerprint=fingerprint("wrong")), "DLG_FINGERPRINT_MISMATCH"),
    (lambda w: w.update(contextFingerprint=fingerprint("wrong")), "DLG_FINGERPRINT_MISMATCH"),
])
def test_semantic_strict_decoder(mutation, code):
    wire = context().to_dict()
    mutation(wire)
    with pytest.raises(DialogueContextValidationError, match=code):
        decode(wire)


@pytest.mark.parametrize("binding", [{"content_uid": uid(2)}, {"source_text": "changed"},
    {"category": "bark"}, {"source_locale": "French"}])
def test_target_binding(binding):
    kwargs = {"content_uid": uid(1), "source_text": sources()[uid(1)], "category": "dialogue_general"}
    kwargs.update(binding)
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        decode_dialogue_context(context().to_dict(), **kwargs)


@pytest.mark.parametrize("value", [None, {}, [], "", False])
def test_absent_vs_malformed_and_both_families(value):
    row = {"contentUid": uid(1), "primaryCategory": "dialogue_general", "sourceText": sources()[uid(1)]}
    assert dialogue_context_from_material(row) is None
    row["dialogueContext"] = value
    with pytest.raises(DialogueContextValidationError):
        dialogue_context_from_material(row)
    row["sameEntityContext"] = None
    with pytest.raises(DialogueContextValidationError, match="BOTH_CONTEXT_FAMILIES"):
        dialogue_context_from_material(row)


def test_complete_branches_variants_occurrences_and_no_text_deduplication():
    data = graph_data()
    a = data["save"]["regions"]["dialog"]["nodes"][0]["node"][-1]
    leaves = a["TaggedTexts"][0]["TaggedText"][0]["TagTexts"][0]["TagText"]
    extra = deepcopy(leaves[0]); extra["TagText"]["handle"] = uid(5); leaves.append(extra)
    same_uid = deepcopy(leaves[0]); same_uid["LineId"] = attr("another-conditional-line"); leaves.append(same_uid)
    source = sources(); source[uid(5)] = source[uid(4)]; source[uid(3)] = source[uid(4)]
    dto = context(data, source)
    assert [g.node_id for g in dto.possible_successors] == ["A", "Z"]
    assert [v.content_uid for v in dto.possible_successors[0].source_variants] == [uid(4), uid(5)]
    assert len(dto.possible_successors[0].source_variants[0].occurrence_fingerprints) == 2
    assert dto.source_codepoints == len(source[uid(2)]) + 3 * len(source[uid(4)])


@pytest.mark.parametrize("size,present", [(1999, True), (2000, True), (2001, False)])
def test_raw_codepoint_boundaries_whole_set(size, present):
    source = sources()
    source[uid(2)] = "<b>😀</b> \n[1]"  # markup, non-BMP, whitespace all count
    source[uid(3)] = "é"
    source[uid(4)] = "x" * (size - len(source[uid(2)]) - 1)
    result = adapter(text=source).materialize(uid(1), "dialogue_general", source[uid(1)])
    assert (result.context is not None) == present
    if present:
        assert result.context.source_codepoints == size
        assert result.context.possible_predecessors[0].source_variants[0].source_text == source[uid(2)]
    else:
        assert result.absence_reason == "BUDGET_EXCEEDED"


@pytest.mark.parametrize("missing", [None, "", " \n", "%%% EMPTY"])
def test_incomplete_any_branch_rejects_entire_set(missing):
    source = sources()
    if missing is None:
        del source[uid(4)]
    else:
        source[uid(4)] = missing
    result = adapter(text=source).materialize(uid(1), "dialogue_general", source[uid(1)])
    assert result.context is None and result.absence_reason == "INCOMPLETE_ENGLISH_CONTEXT"


def test_structural_conflicts_fallback_and_incompatible_occurrences():
    rows = parse(graph_data())
    changed = graph_data(); changed["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["speaker"] = attr(2)
    conflict = DialogueEvidenceAdapter.from_records(rows + parse(changed), sources())
    assert conflict.materialize(uid(1), "dialogue_general", sources()[uid(1)]).absence_reason == "STRUCTURAL_CONFLICT"
    fallback = graph_data(); del fallback["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["UUID"]
    assert adapter(fallback).materialize(uid(1), "dialogue_general", sources()[uid(1)]).absence_reason == "FALLBACK_IDENTITY"
    incompatible = graph_data(); incompatible["save"]["regions"]["dialog"]["nodes"][0]["node"].append(node("Other", text=uid(1)))
    assert adapter(incompatible).materialize(uid(1), "dialogue_general", sources()[uid(1)]).absence_reason == "INCOMPATIBLE_OCCURRENCES"


def test_no_speaker_inference_no_control_crossing_no_references_and_bark_baseline():
    data = dialogue([node("T", text=uid(1), children=["Control"], jumptarget=attr("Z")),
                     node("Control", kind="Visual State", children=["Z"]), node("Z", text=uid(3))])
    graph = adapter(data)
    assert graph.materialize(uid(1), "dialogue_general", sources()[uid(1)]).absence_reason == "NO_LOCALIZED_RELATION"
    assert adapter().materialize(uid(1), "bark", sources()[uid(1)]).absence_reason == "UNSUPPORTED_CATEGORY"
    wire = canonical_bytes(context().to_dict())
    assert b"speaker" not in wire.lower() and b"sourceResource" not in wire


def test_adapter_copies_inputs_and_order_resource_duplicates_determinism():
    rows = parse(graph_data()); source = sources()
    graph = DialogueEvidenceAdapter.from_records(rows, source)
    duplicate_resource = parse(graph_data(), resource="Other/Fictional.lsj")
    duplicate = DialogueEvidenceAdapter.from_records(list(reversed(rows + duplicate_resource)), sources())
    assert graph.materialize(uid(1), "dialogue_general", source[uid(1)]).context == duplicate.materialize(uid(1), "dialogue_general", source[uid(1)]).context
    rows.clear(); source[uid(2)] = "changed"
    assert graph.sources[uid(2)] == sources()[uid(2)]
    with pytest.raises(TypeError):
        graph.sources[uid(2)] = "changed"
    results, summary = materialize_inventory(graph, {key: "dialogue_general" for key in sources()})
    reversed_results, reversed_summary = materialize_inventory(graph, {key: "dialogue_general" for key in reversed(sources())})
    assert results == reversed_results and summary == reversed_summary


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(unexpected=True),
    lambda r: r.update(definitionFingerprint=fingerprint("wrong-owner")),
    lambda r: r.update(fromNode="wrong-owner"),
    lambda r: r["referenceParameters"]["UUID"].update(value="wrong-destination"),
    lambda r: r.update(childIndex=True),
])
def test_malformed_evidence_is_fatal_not_absence(mutation):
    rows = parse(graph_data()); edge = next(r for r in rows if r["recordType"] == "edge")
    mutation(edge)
    edge["evidenceId"] = fingerprint({k: v for k, v in edge.items() if k != "evidenceId"})
    with pytest.raises(DialogueContextValidationError):
        DialogueEvidenceAdapter.from_records(rows, sources())


def write_stage_inputs(tmp_path, split=False):
    evidence = tmp_path / "evidence"; audit = DialogueAudit(); audit.add(parse(graph_data())); audit.write(evidence)
    source = tmp_path / "English.jsonl"
    source.write_bytes(b"".join(canonical_bytes({"contentUid": key, "text": text, "localeId": "English"}) + b"\n" for key, text in sources().items()))
    root = tmp_path / "batches"; (root / "materials").mkdir(parents=True)
    groups = [[key] for key in reversed(sources())] if split else [list(sources())]
    batches = []
    for i, group in enumerate(groups):
        batch_id = f"fictional-{i}"
        batches.append({"batchId": batch_id, "primaryCategory": "dialogue_general", "recordCount": len(group), "contentUids": group})
        (root / "materials" / f"{batch_id}.jsonl").write_bytes(b"".join(canonical_bytes({
            "contentUid": key, "sourceText": sources()[key], "primaryCategory": "dialogue_general", "batchId": batch_id}) + b"\n" for key in group))
    plan = root / "batch-plan.json"
    plan.write_bytes(canonical_bytes({"batchPlanFingerprint": fingerprint("fictional-plan"), "batches": batches}))
    return {"evidence_dir": evidence, "source_snapshot": source, "batch_plan": plan,
            "output_dir": tmp_path / "staged", "enabled": True}


def test_safe_stage_prepare_opt_in_batch_split_order_and_runtime_rejection(tmp_path):
    a = write_stage_inputs(tmp_path / "a"); b = write_stage_inputs(tmp_path / "b", split=True)
    assert prepare_dialogue_stage(**a) == prepare_dialogue_stage(**b)
    for path in a["output_dir"].iterdir():
        assert path.read_bytes() == (b["output_dir"] / path.name).read_bytes()
    manifest = a["output_dir"] / "stage1-manifest.json"
    assert json.loads(manifest.read_text())["status"] == "NOT_EXECUTABLE"
    assert not (a["output_dir"] / "production-manifest.json").exists()
    with pytest.raises(RuntimeError, match="missing batchPlanFingerprint"):
        load_execution_items(manifest, prompt_version="fictional")
    db = tmp_path / "must-not-exist.sqlite3"
    with pytest.raises(RuntimeError, match="missing batchPlanFingerprint"):
        run_init(SimpleNamespace(batch_plan=manifest, db=db, ruleset=None, prompt_version="fictional"))
    assert not db.exists()
    with pytest.raises(DialogueContextValidationError):
        prepare_dialogue_stage(**a)  # no overwrite
    with pytest.raises(DialogueContextValidationError):
        prepare_dialogue_stage(**{**a, "enabled": False})


def test_seal_failure_and_target_mismatch_do_not_publish(tmp_path):
    args = write_stage_inputs(tmp_path)
    material = args["batch_plan"].parent / "materials/fictional-0.jsonl"
    rows = [json.loads(line) for line in material.read_text().splitlines()]
    rows[0]["sourceText"] = "changed"
    material.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        prepare_dialogue_stage(**args)
    assert not args["output_dir"].exists()
    edge_path = args["evidence_dir"] / "dialogue-edge.jsonl"
    edge_path.write_text(edge_path.read_text() + edge_path.read_text().splitlines()[0] + "\n")
    with pytest.raises(DialogueContextValidationError, match="DLG_FINGERPRINT_MISMATCH"):
        prepare_dialogue_stage(**args)
    assert not args["output_dir"].exists()


def test_cli_requires_opt_in_and_no_production_default_changes():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["research", "dialogue-stage-prepare", "--evidence-dir", "e",
                           "--source-snapshot", "s", "--batch-plan", "b", "--output-dir", "o"])
    args = parser.parse_args(["research", "dialogue-stage-prepare", "--enable-dialogue-context", "--evidence-dir", "e",
                             "--source-snapshot", "s", "--batch-plan", "b", "--output-dir", "o"])
    assert args.enable_dialogue_context is True


def test_binding_checked_before_stale_fingerprint_and_proof_changes_seal():
    wire = context().to_dict()
    wire["targetBinding"]["contentUid"] = uid(99)
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        decode(wire)
    original = context()
    changed = original.to_dict()
    changed["targetProof"]["sourceOccurrenceFingerprint"] = fingerprint("changed-native-occurrence")
    changed = decode(resign(changed))
    assert changed.context_fingerprint != original.context_fingerprint
    assert changed.evidence_fingerprint != original.evidence_fingerprint


def test_normal_absence_summary_exact_inventory_and_source_evidence_binding():
    graph = adapter()
    inventory = {uid(1): "dialogue_general", uid(2): "bark", uid(3): "item", uid(4): "dialogue_general"}
    results, summary = materialize_inventory(graph, inventory)
    assert summary["preparedTargets"] == len(inventory) == len(results)
    assert summary["withContext"] + sum(summary["absenceReasonCounts"].values()) == len(inventory)
    assert summary["absenceReasonCounts"] == {"UNSUPPORTED_CATEGORY": 2}
    assert set(summary) == {"schemaVersion", "contract", "preparedTargets", "withContext", "absenceReasonCounts",
                            "byCategory", "sourceCharsStats", "lineCardinalityStats", "inputDigests",
                            "dialogueContextMaterialFingerprint", "summaryFingerprint"}
    assert summary["summaryFingerprint"] == fingerprint({k: v for k, v in summary.items() if k != "summaryFingerprint"})
    assert summary["dialogueContextMaterialFingerprint"] == fingerprint({key: result.context.context_fingerprint
        if result.context else "absent" for key, result in results.items()})
    source = sources(); source[uid(4)] += " changed"
    _, changed = materialize_inventory(adapter(text=source), inventory)
    assert changed["inputDigests"]["source"] != summary["inputDigests"]["source"]
    assert changed["dialogueContextMaterialFingerprint"] != summary["dialogueContextMaterialFingerprint"]
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        graph.materialize(uid(1), "dialogue_general", "wrong-source")
    extra = {**sources(), uid(99): "Unreferenced fictional source."}
    no_occurrence = adapter(text=extra).materialize(uid(99), "dialogue_general", extra[uid(99)])
    assert no_occurrence.absence_reason == "NO_DIALOGUE_OCCURRENCE"


@pytest.mark.parametrize("family_fields", [
    {"sameEntityContext": None}, {"dialogueContext": None},
    {"sameEntityContext": None, "dialogueContext": None},
])
def test_stage_does_not_ignore_malformed_present_families(tmp_path, family_fields):
    args = write_stage_inputs(tmp_path)
    material = args["batch_plan"].parent / "materials/fictional-0.jsonl"
    rows = [json.loads(line) for line in material.read_text().splitlines()]
    rows[0].update(family_fields)
    material.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
    with pytest.raises(DialogueContextValidationError):
        prepare_dialogue_stage(**args)
    assert not args["output_dir"].exists()


def test_missing_owning_evidence_and_tampered_native_assertion_fail():
    rows = parse(graph_data())
    occurrence = next(r for r in rows if r["recordType"] == "occurrence")
    rows.remove(next(r for r in rows if r["recordType"] == "node" and r["nodeId"] == occurrence["nodeId"]))
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        DialogueEvidenceAdapter.from_records(rows, sources())
    rows = parse(graph_data())
    rows[0]["nodeKind"] = "unknown"  # stale evidenceId is fatal before exclusion
    with pytest.raises(DialogueContextValidationError, match="DLG_FINGERPRINT_MISMATCH"):
        DialogueEvidenceAdapter.from_records(rows, sources())


def test_source_variant_uid_and_occurrence_order_are_not_repaired():
    wire = context().to_dict()
    variants = wire["possibleSuccessors"][0]["sourceVariants"]
    variants.append({**deepcopy(variants[0]), "contentUid": uid(99)})
    variants.reverse()
    with pytest.raises(DialogueContextValidationError, match="DLG_ORDER_INVALID"):
        decode(wire)
    wire = context().to_dict()
    seals = wire["possibleSuccessors"][0]["sourceVariants"][0]["occurrenceFingerprints"]
    seals.append(seals[0])
    with pytest.raises(DialogueContextValidationError, match="DLG_ORDER_INVALID"):
        decode(wire)


def test_declared_research_status_is_cross_checked_not_trusted():
    rows = parse(graph_data())
    edge = next(r for r in rows if r["recordType"] == "edge")
    edge["structuralStatus"] = "conflict_or_fallback"
    with pytest.raises(DialogueContextValidationError, match="DLG_BINDING_MISMATCH"):
        DialogueEvidenceAdapter.from_records(rows, sources())
