"""Fictional structural fixtures: no real dialogue IDs, text or actor mappings."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from bg3loc.cli import build_parser
from bg3loc.research.dialogue_context import DialogueAudit, parse_dialogue
from bg3loc.research.dialogue_export import (
    discover_dialogues, export_dialogue_research, load_dialogue_targets,
)
from bg3loc.backends import ArchiveEntry, BackendProbe
from bg3loc.schema import SchemaStore


def attr(v, kind="FixedString"):
    return {"type": kind, "value": v}


def uid(n):
    return f"h{n:08x}g0000g0000g0000g000000000000"


def node(name, *, text=None, children=(), speaker=0, kind="TagAnswer", **fields):
    result = {"UUID": attr(name), "constructor": attr(kind),
              "children": [{"child": [{"UUID": attr(c)} for c in children]}], **fields}
    if speaker is not None:
        result["speaker"] = attr(speaker, "int32")
    if text is not None:
        result["TaggedTexts"] = [{"TaggedText": [{"HasTagRule": attr(False, "bool"),
            "TagTexts": [{"TagText": [{"LineId": attr("fictional-line-" + name),
                "TagText": {"type": "TranslatedString", "handle": text, "version": 1}}]}]}]}]
    return result


def dialogue(nodes, *, mappings=None):
    if mappings is None:
        mappings = [{"index": attr("0"), "SpeakerMappingId": attr("fictional-speaker-map"),
                     "list": attr("00000000-0000-0000-0000-000000000001", "LSString")}]
    return {"save": {"header": {"time": 1}, "regions": {"dialog": {
        "UUID": attr("Dialogue_FrozenBridge"), "nodes": [{"node": nodes}],
        "speakerlist": [{"speaker": mappings}]}}}}


def parse(data, resource="Story/Dialogs/FrozenBridge.lsj"):
    return parse_dialogue(data, package="Fictional.pak", resource=resource)


def analyze(data):
    audit = DialogueAudit(); audit.add(parse(data))
    rows, summary = audit.analyze()
    return {r["nodeId"]: r for r in rows if r["recordType"] == "targetEvidence"}, summary


def linear():
    return dialogue([node("N1", text=uid(1), children=["N2"]), node("N2", text=uid(2), children=["N3"]),
                     node("N3", text=uid(3), speaker=1)])


def test_native_identity_and_occurrence_roles():
    rows = parse(linear())
    first = next(r for r in rows if r["recordType"] == "node")
    assert first["dialogueId"] == "Dialogue_FrozenBridge"
    assert first["nodeId"] == "N1"
    assert first["dialogueIdentityOrigin"] == first["nodeIdentityOrigin"] == "native_UUID"
    occurrence = next(r for r in rows if r["recordType"] == "occurrence")
    assert occurrence["contentUid"] == uid(1)
    assert occurrence["lineId"] == "fictional-line-N1"
    assert occurrence["fieldRole"] == "TaggedTexts.TaggedText.TagTexts.TagText"
    assert "sourceText" not in json.dumps(rows)


def test_identity_origin_comes_from_field_not_string_shape():
    data = dialogue([node("node#1", text=uid(1))])
    assert parse(data)[0]["nodeIdentityOrigin"] == "native_UUID"
    data["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["UUID"] = attr(None)
    assert parse(data)[0]["nodeIdentityOrigin"] == "fallback_ordinal"


@pytest.mark.parametrize("missing", ["dialogue", "node", "both"])
def test_fallback_origin_is_explicit_and_unusable(missing):
    data = linear(); root = data["save"]["regions"]["dialog"]
    if missing in {"dialogue", "both"}: del root["UUID"]
    if missing in {"node", "both"}: del root["nodes"][0]["node"][0]["UUID"]
    rows = parse(data); first = next(r for r in rows if r["recordType"] == "node")
    assert first["dialogueIdentityOrigin"] == ("resource_scope" if missing != "node" else "native_UUID")
    assert first["nodeIdentityOrigin"] == ("fallback_ordinal" if missing != "dialogue" else "native_UUID")
    audit = DialogueAudit(); audit.add(rows); resolved, _ = audit.analyze()
    if missing != "node": assert not any(r.get("structuralStatus") == "DIRECT" for r in resolved)
    else: assert not any(r.get("fromNode") == "ordinal:0" and r.get("structuralStatus") == "DIRECT" for r in resolved)


@pytest.mark.parametrize("slot,mappings,status", [
    (0, None, "explicit_reference"), (1, [], "slot_only"),
    (-1, [], "slot_only"), (-666, [], "slot_only"), (None, [], "missing"),
    (0, [{"index": attr("0"), "list": attr("runtime-list") }], "slot_only"),
    (0, [{"index": attr("0"), "list": attr("00000000-0000-0000-0000-000000000000")}], "slot_only"),
    (0, [{"index": attr("0"), "list": attr("00000000-0000-0000-0000-000000000001;00000000-0000-0000-0000-000000000002")}], "ambiguous"),
    (0, [{"index": attr("0"), "list": attr("actor-a")}, {"index": attr("0"), "list": attr("actor-b")}], "ambiguous"),
])
def test_speaker_evidence_is_not_a_character_name(slot, mappings, status):
    rows = parse(dialogue([node("N", text=uid(1), speaker=slot)], mappings=mappings))
    speaker = next(r["speaker"] for r in rows if r["recordType"] == "node")
    assert speaker["status"] == status
    assert speaker["slot"] == (str(slot) if slot is not None else "")
    assert speaker["resolution"] == "static_reference_only"
    assert "name" not in speaker


def test_linear_direct_edges_and_speaker_change():
    rows, summary = analyze(linear())
    assert rows["N2"]["directPredecessors"] == ["N1"]
    assert rows["N2"]["directSuccessors"] == ["N3"]
    assert rows["N3"]["speaker"]["slot"] == "1"
    assert summary["directLocalizedPredecessors"] == {"none": 1, "one": 2}


def test_branch_choice_merge_preserves_all_alternatives():
    data = dialogue([node("N1", text=uid(1), children=["P1", "P2"]),
        node("P1", text=uid(2), kind="TagQuestion", children=["N2"], speaker=1),
        node("P2", text=uid(3), kind="TagQuestion", children=["N2"], speaker=1),
        node("N2", text=uid(4))])
    rows, summary = analyze(data)
    assert rows["N1"]["directSuccessors"] == ["P1", "P2"]
    assert rows["N2"]["directPredecessors"] == ["P1", "P2"]
    assert rows["N2"]["relationReliability"] == "AMBIGUOUS"
    assert summary["nodesWithMultiplePredecessors"] == summary["nodesWithMultipleSuccessors"] == 1


def test_structural_traversal_is_separate_from_direct_relation():
    data = dialogue([node("N1", text=uid(1), children=["Control"]),
                     node("Control", kind="Visual State", speaker=None, children=["N2"]),
                     node("N2", text=uid(2))])
    rows, summary = analyze(data)
    assert rows["N2"]["directPredecessors"] == ["Control"]
    assert rows["N2"]["directLocalizedPredecessors"] == []
    assert rows["N2"]["nearestLocalizedPredecessors"]["nodes"] == [{"nodeId": "N1", "hops": 2}]
    assert summary["nodeKinds"]["structural_only"] == 1
    assert summary["indirectLocalizedNodes"] == 2


@pytest.mark.parametrize("field,kind", [("jumptarget", "Jump"), ("SourceNode", "Alias"),
                                       ("NestedDialogNodeUUID", "Nested Dialog")])
def test_jump_alias_nested_references_do_not_invent_temporal_flow(field, kind):
    data = dialogue([node("Reference", kind=kind, speaker=None, **{field: attr("N2"),
                     "jumptargetpoint": attr(2, "uint8")}), node("N2", text=uid(1))])
    audit = DialogueAudit(); audit.add(parse(data)); rows, _ = audit.analyze()
    edge = next(r for r in rows if r["recordType"] == "edge")
    assert edge["edgeType"] == field and edge["structuralStatus"] == "reference_only"
    target = next(r for r in rows if r["recordType"] == "targetEvidence")
    assert target["directPredecessors"] == []
    assert edge["referenceParameters"]["jumptargetpoint"]["value"] == 2


def test_localized_to_structural_jump_retains_reference_without_guessed_neighbour():
    data = dialogue([node("N1", text=uid(1), children=["J"]),
        node("J", kind="Jump", speaker=None, jumptarget=attr("N2"), jumptargetpoint=attr(1,"uint8")),
        node("N2", text=uid(2))])
    rows, summary = analyze(data)
    assert rows["N1"]["directSuccessors"] == ["J"]
    assert rows["N1"]["nearestLocalizedSuccessors"]["nodes"] == []
    assert rows["N2"]["directPredecessors"] == []
    assert summary["edgeTypes"]["jumptarget"] == 1
    assert summary["nodeKinds"]["structural_only"] == 1


def test_same_speaker_and_dialogue_do_not_establish_adjacency():
    rows, _ = analyze(dialogue([node("N1", text=uid(1)), node("N2", text=uid(2))]))
    assert all(r["directPredecessors"] == r["directSuccessors"] == [] for r in rows.values())


def test_node_ids_are_scoped_by_dialogue_and_never_joined_across_graphs():
    a = dialogue([node("N1",text=uid(1),children=["N2"])])
    b = dialogue([node("N2",text=uid(2))]); b["save"]["regions"]["dialog"]["UUID"] = attr("Dialogue_Other")
    audit = DialogueAudit(); audit.add(parse(a)); audit.add(parse(b,"Story/Dialogs/other.lsj"))
    rows, report = audit.analyze()
    assert report["edgeStatus"]["missing_endpoint"] == 1
    assert all(r.get("directPredecessors",[]) == [] for r in rows)


def test_speaker_table_input_order_does_not_change_definitions():
    a = linear(); a["save"]["regions"]["dialog"]["speakerlist"][0]["speaker"].append(
        {"index":attr("1"),"list":attr("00000000-0000-0000-0000-000000000002")})
    b = deepcopy(a); b["save"]["regions"]["dialog"]["speakerlist"][0]["speaker"].reverse()
    aa = DialogueAudit(); aa.add(parse(a)); bb = DialogueAudit(); bb.add(parse(b))
    assert aa.analyze() == bb.analyze()


def test_reorder_nodes_and_metadata_keeps_definition_fingerprint(tmp_path):
    a = linear(); b = deepcopy(a)
    b["save"]["header"]["time"] = 999
    ns = b["save"]["regions"]["dialog"]["nodes"][0]["node"]
    ns.reverse()
    for n in ns: n["editorData"] = [{"absolutePath": "fictional-editor-path", "time": 999}]
    def fingerprints(data, resource):
        return sorted((r["recordType"],r.get("nodeId"),r["definitionFingerprint"]) for r in parse(data, resource)
                      if r["recordType"] in {"dialogue", "node"})
    assert fingerprints(a, "Story/Dialogs/a.lsj") == fingerprints(b, "Story/Dialogs/b.lsj")
    aa = DialogueAudit(); aa.add(parse(a)); bb = DialogueAudit(); bb.add(reversed(parse(a)))
    assert aa.write(tmp_path/"a") == bb.write(tmp_path/"b")
    for path in (tmp_path/"a").glob("*.jsonl"):
        assert path.read_bytes() == (tmp_path/"b"/path.name).read_bytes()


def test_ordered_choices_and_conditions_remain_in_fingerprint():
    a = dialogue([node("N1", text=uid(1), children=["P1", "P2"]), node("P1"), node("P2")])
    b = deepcopy(a); b["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["children"][0]["child"].reverse()
    assert parse(a)[0]["definitionFingerprint"] != parse(b)[0]["definitionFingerprint"]


def test_duplicate_identical_definitions_and_conflicts_never_select_winner():
    a = linear(); audit = DialogueAudit(); audit.add(parse(a,"Story/Dialogs/a.lsj")); audit.add(parse(a,"Story/DialogsBinary/a.lsf"))
    _, report = audit.analyze()
    assert report["identicalDuplicateDialogues"] == 1 and report["identicalDuplicateNodes"] == 3
    b = deepcopy(a); b["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["speaker"] = attr(9,"int32")
    audit.add(parse(b,"Story/Dialogs/c.lsj")); rows, report = audit.analyze()
    assert report["conflictingDialogues"] == report["conflictingNodes"] == 1
    assert report["winnerSelection"] is False
    assert not any(r.get("structuralStatus") == "DIRECT" for r in rows)
    assert len(next(r for r in rows if r["recordType"] == "targetEvidence" and r["nodeId"] == "N1")["definitionFingerprints"]) == 2


def test_speaker_consensus_does_not_require_choosing_conflicted_definition():
    a = linear(); b = deepcopy(a)
    b["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["endnode"] = attr(True, "bool")
    audit = DialogueAudit(); audit.add(parse(a)); audit.add(parse(b,"Story/Dialogs/other.lsj"))
    rows, report = audit.analyze()
    target = next(r for r in rows if r["recordType"] == "targetEvidence" and r["nodeId"] == "N1")
    assert target["conflict"] and target["directSuccessors"] == []
    assert target["speaker"]["status"] == "explicit_reference"
    assert len(target["speakerEvidenceVariants"]) == 1
    assert report["winnerSelection"] is False


def test_changed_speaker_table_cannot_overwrite_identical_node_body():
    a = linear(); b = deepcopy(a)
    b["save"]["regions"]["dialog"]["speakerlist"][0]["speaker"][0]["list"] = attr("00000000-0000-0000-0000-000000000002")
    audit = DialogueAudit(); audit.add(parse(a)); audit.add(parse(b,"Story/Dialogs/other.lsj"))
    rows, report = audit.analyze()
    target = next(r for r in rows if r["recordType"] == "targetEvidence" and r["nodeId"] == "N1")
    assert len(target["definitionFingerprints"]) == len(target["speakerEvidenceVariants"]) == 2
    assert target["speaker"]["status"] == "ambiguous"
    assert report["conflictingNodes"] == 2
    assert report["winnerSelection"] is False


def test_shared_uid_multiple_nodes_not_unique_production_context():
    data = linear(); data["save"]["regions"]["dialog"]["nodes"][0]["node"][2]["TaggedTexts"] = deepcopy(data["save"]["regions"]["dialog"]["nodes"][0]["node"][0]["TaggedTexts"])
    audit = DialogueAudit(); audit.add(parse(data)); _, report = audit.analyze({uid(1):"dialogue_general"})
    assert report["productionEstimate"]["atLeastOneOccurrenceWithDirectRelation"] == 1
    assert report["productionEstimate"]["reliableUnambiguousDirectRelation"] == 0


def test_cycle_unknown_missing_endpoint_and_traversal_bound():
    data = dialogue([node("N1", text=uid(1), children=["Logic"]), node("Logic", kind="Unknown", children=["N1", "Absent"]), node("N2", text=uid(2))])
    rows, summary = analyze(data)
    assert rows["N1"]["nearestLocalizedSuccessors"]["blockedUnknown"]
    assert summary["edgeStatus"]["missing_endpoint"] == 1
    data = dialogue([node("N1", text=uid(1), children=["Control"]), node("Control", kind="Visual State", children=["Control", "N2"]), node("N2", text=uid(2))])
    audit = DialogueAudit(); audit.add(parse(data)); rows, _ = audit.analyze(max_hops=1)
    target = next(r for r in rows if r["recordType"] == "targetEvidence" and r["nodeId"] == "N1")
    assert target["nearestLocalizedSuccessors"]["boundReached"]
    rows, _ = audit.analyze()
    target = next(r for r in rows if r["recordType"] == "targetEvidence" and r["nodeId"] == "N1")
    assert target["nearestLocalizedSuccessors"]["revisitedNode"]


def test_sentinel_is_counted_but_not_a_localized_occurrence():
    rows = parse(dialogue([node("N", text="ls::TranslatedStringRepository::s_HandleUnknown")]))
    assert not any(r["recordType"] == "occurrence" for r in rows)
    assert rows[0]["unresolvedLocalizationHandles"] == 1
    with pytest.raises(ValueError, match="unrecognized"):
        parse(dialogue([node("N", text="unsupported-handle")]))


@pytest.mark.parametrize("path", ["/absolute/dialog.lsj", "drive:/dialog.lsj", "../dialog.lsj"])
def test_absolute_and_escaping_provenance_is_rejected(path):
    with pytest.raises(ValueError): parse(linear(), path)


def test_schema_all_families_and_no_real_text(tmp_path):
    audit = DialogueAudit(); audit.add(parse(linear())); audit.write(tmp_path)
    store = SchemaStore()
    for path in tmp_path.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            store.validate("research/dialogue-context-evidence-v1.schema.json", json.loads(line))


def test_portable_public_export_and_cli(tmp_path, monkeypatch):
    game = tmp_path/"game"; (game/"Data").mkdir(parents=True)
    (game/"Data"/"Fictional.pak").touch()
    backend = Mock(); backend.probe.return_value = BackendProbe("mock", True)
    backend.list_archive.return_value = [ArchiveEntry("Mods/Fictional/Story/Dialogs/a.lsj",1,0)]
    backend.extract_single_file.side_effect = lambda package,path,dest: dest.write_text(json.dumps(linear()),encoding="utf-8")
    classification = tmp_path/"classification.jsonl"
    classification.write_text(json.dumps({"contentUid":uid(1),"primaryCategory":"dialogue_general","classificationStatus":"classified"})+"\n",encoding="utf-8")
    report = export_dialogue_research(game, backend, tmp_path/"out", classification=classification)
    assert report["productionEstimate"]["coveragePercent"] == 100
    assert report["extraction"]["generationInputs"]["privateDataset"] is False
    assert report["providerCalls"] == 0
    args = build_parser().parse_args(["research","dialogue-audit","--game-dir",str(game),"--output-dir",str(tmp_path/"out")])
    assert args.handler.__name__ == "run_dialogue_audit"
    with classification.open("a",encoding="utf-8") as f: f.write(classification.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="duplicate"): load_dialogue_targets(classification)


def test_discovery_fails_closed_for_unreadable_primary_archive(tmp_path):
    (tmp_path/"Data").mkdir(); (tmp_path/"Data"/"Fictional.pak").touch()
    backend = Mock(); backend.list_archive.side_effect = RuntimeError("unreadable")
    with pytest.raises(RuntimeError): discover_dialogues(tmp_path, backend)
