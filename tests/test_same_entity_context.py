"""Entirely fictional P1 fixtures; no game corpus, providers, or workspace I/O."""
from dataclasses import FrozenInstanceError, fields, replace
from hashlib import sha256
import ast
import inspect
import itertools
import json

import pytest

import bg3loc.same_entity_context as production
from bg3loc.research.context_experiment import build_packs
from bg3loc.same_entity_context import (
    CATEGORIES, ENTITY_TYPES, FIELD_PRIORITY, IDENTITY_KINDS, MAX_CONTEXT_CHARS,
    MAX_RELATED_FIELDS, POLICY_VERSION, SCHEMA_VERSION, ContextAbsenceReason as Reason,
    ContextBuildResult, SameEntityContextValidationError, SameEntityRelatedField,
    SameEntitySourceRecord, StructuralIdentityKind as Kind, build_same_entity_context,
    canonical_json, fingerprint, source_text_sha256, validate_same_entity_context,
)


IDENTITIES = {
    "skill_spell": "Skill_FrostSpark",
    "item": "11111111-2222-4333-8444-555555555555",  # fictional template UUID
    "quest": "Quest_LostCourier",
}


def record(uid="fictional-target", role="DisplayName", text="Frost Spark", category="skill_spell", **changes):
    row = SameEntitySourceRecord(
        uid, category, ENTITY_TYPES[category], IDENTITIES[category], role, text,
        IDENTITY_KINDS[category], "fictional/resources/entity.xml",
        fingerprint({"fictionalEvidence": uid, "role": role}),
        fingerprint({"fictionalCompleteDefinition": IDENTITIES[category]}),
    )
    return replace(row, **changes)


def fixture(category="skill_spell"):
    name_role, description_role = ("QuestTitle", "QuestDescription") if category == "quest" else ("DisplayName", "Description")
    names = {"skill_spell": "Frost Spark", "item": "Moonstone Charm", "quest": "Find the Lost Courier"}
    return (
        record(category=category, role=name_role, text=names[category]),
        record("fictional-detail", description_role, "A fictional clue glows beside the river.", category),
    )


def context(target, rows):
    result = build_same_entity_context(target, rows)
    assert result.absence_reason is None
    assert result.context is not None
    return result.context


def validate(value, target):
    validate_same_entity_context(value, content_uid=target.content_uid,
                                 category=target.category, source_text=target.source_text)


def rehash(value):
    return replace(value, context_fingerprint=fingerprint(value.fingerprint_payload()))


@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_valid_structural_entity(category):
    target, related = fixture(category)
    built = context(target, (related,))
    assert built.schema_version == SCHEMA_VERSION == "same-entity-context/1"
    assert built.policy_version == POLICY_VERSION == "b1-02-structural/2"
    assert built.entity_type == ENTITY_TYPES[category]
    assert json.loads(built.entity_identity)["identity"] == IDENTITIES[category]
    assert built.related_fields == (SameEntityRelatedField(related.content_uid, related.field_role, related.source_text, False),)
    assert built.target_binding.source_text_sha256 == sha256(target.source_text.encode("utf-8")).hexdigest()
    validate(built, target)


@pytest.mark.parametrize("category", ["dialogue", "dialogue_general", "bark", "book_lore", "character_world", "tutorial", "system_message", "ui", "other"])
def test_unsupported_is_absent(category):
    target, related = fixture()
    result = build_same_entity_context(replace(target, category=category), (related,))
    assert result == ContextBuildResult(None, Reason.UNSUPPORTED_CATEGORY)


@pytest.mark.parametrize("category,changes", [
    ("quest", {"entity_identity": "node#12"}),
    ("quest", {"identity_kind": Kind.ORDINAL_FALLBACK, "entity_identity": "node12"}),
    ("item", {"entity_identity": "GameObjects"}),
    ("item", {"identity_kind": Kind.GENERIC_NODE}),
    ("item", {"entity_identity": "00000000-0000-0000-0000-000000000000"}),
    ("skill_spell", {"identity_kind": Kind.STATS_USING_PARENT}),
    ("skill_spell", {"identity_kind": Kind.FILE_GROUP}),
    ("skill_spell", {"entity_identity": "fictional/file.txt"}),
    ("skill_spell", {"entity_type": "Weapon"}),
    ("skill_spell", {"evidence_fingerprint": ""}),
    ("skill_spell", {"definition_fingerprint": "not-a-digest"}),
    ("skill_spell", {"evidence_source": "C:/fictional/private/entity.xml"}),
    ("skill_spell", {"evidence_source": "../fictional/entity.xml"}),
    ("skill_spell", {"entity_scope": "/fictional/private"}),
])
def test_unreliable_identity_is_absent(category, changes):
    target, related = fixture(category)
    result = build_same_entity_context(replace(target, **changes), (related,))
    assert result.absence_reason == Reason.NO_RELIABLE_IDENTITY


def test_using_parent_and_different_entity_not_selected():
    target, related = fixture()
    parent = record("fictional-parent", "ExtraDescription", "A parent clue.",
                    identity_kind=Kind.STATS_USING_PARENT)
    other = record("fictional-other", "Tooltip", "Another entity clue.", entity_identity="Skill_Other")
    assert context(target, (related, parent, other)).related_fields == context(target, (related,)).related_fields


@pytest.mark.parametrize("changes,reason", [
    ({"category": "quest"}, Reason.CATEGORY_MISMATCH),
    ({"eligible": False}, Reason.HOLD_OR_INELIGIBLE),
    ({"entity_identity": "Skill_Other"}, Reason.NO_RELIABLE_IDENTITY),
    ({"field_role": "Description"}, Reason.AMBIGUOUS_FIELD_ROLE),
    ({"source_text": "Different source"}, Reason.STRUCTURAL_CONFLICT),
    ({"source_locale": "OtherLocale"}, Reason.STRUCTURAL_CONFLICT),
])
def test_target_occurrence_conflicts(changes, reason):
    target, related = fixture()
    assert build_same_entity_context(target, (related, replace(target, **changes))).absence_reason == reason


@pytest.mark.parametrize("variant", ["digest", "same_uid_source", "ineligible_definition"])
def test_conflicting_definitions_fail_closed_independent_of_resource_order(variant):
    target, related = fixture()
    if variant == "same_uid_source":
        conflicting = replace(related, source_text="A conflicting clue.")
    else:
        conflicting = replace(related, definition_fingerprint=fingerprint({"different": "definition"}),
                              eligible=variant != "ineligible_definition")
    conflicting = replace(conflicting, evidence_source="aaa/fictional.xml")
    for rows in itertools.permutations((target, related, conflicting)):
        assert build_same_entity_context(target, rows).absence_reason == Reason.STRUCTURAL_CONFLICT


@pytest.mark.parametrize("text", ["", " ", "{fictional}", "%s %1$d", '<LSTag Type="Fictional">{value}</LSTag>', "<b></b>", "123"])
def test_missing_target_source(text):
    target, related = fixture()
    assert build_same_entity_context(replace(target, source_text=text), (related,)).absence_reason == Reason.MISSING_SOURCE


def test_exclusions_and_unknown_role():
    target, related = fixture()
    extras = [
        target, related,
        record("fictional-same-role", target.field_role, "Another name."),
        record("fictional-duplicate", "ExtraDescription", related.source_text),
        record("fictional-upper", "ShortDescription", related.source_text.upper()),
        record("fictional-empty", "Tooltip", ""),
        record("fictional-token", "TokenRole", '{fictional} %s <b></b>'),
        record("fictional-unknown", "MysteryField", "An unknown-role clue."),
    ]
    built = context(target, extras)
    assert [field.content_uid for field in built.related_fields] == [related.content_uid, "fictional-unknown"]


def test_tokens_with_prose_remain_context_data_only():
    target, _ = fixture()
    related = record("fictional-token-prose", "Description", '<LSTag Type="Fictional">A clue {amount} %s</LSTag>')
    built = context(target, (related,))
    assert built.related_fields[0].source_text == related.source_text
    assert "protected_tokens" not in {field.name for field in fields(built)}
    assert "protected_tokens" not in {field.name for field in fields(built.related_fields[0])}
    assert built.target_binding.source_text_sha256 == source_text_sha256(target.source_text)


@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_priority_four_field_limit_and_fallback(category):
    target = record(category=category, role="TargetRole", text="A fictional target.")
    roles = (*FIELD_PRIORITY[category], "ZebraRole", "AlphaRole")
    rows = [record(f"fictional-{i}", role, f"Fictional detail {i}.", category) for i, role in enumerate(roles)]
    built = context(target, reversed(rows))
    assert [field.field_role for field in built.related_fields] == list((*FIELD_PRIORITY[category], "AlphaRole", "ZebraRole")[:4])
    assert len(built.related_fields) == MAX_RELATED_FIELDS == 4


def test_fallback_role_then_uid_order():
    target, _ = fixture()
    rows = [record("fictional-z", "Mystery", "A final clue."),
            record("fictional-b", "Alpha", "A second clue."),
            record("fictional-a", "Alpha", "A first clue.")]
    assert [field.content_uid for field in context(target, rows).related_fields] == ["fictional-a", "fictional-b", "fictional-z"]


@pytest.mark.parametrize("oversize", [4000, 4001, 6000])
def test_single_field_character_budget_and_truncation(oversize):
    target, related = fixture()
    built = context(target, (replace(related, source_text="X" * oversize),))
    assert len(built.related_fields[0].source_text) == MAX_CONTEXT_CHARS == 4000
    assert built.related_fields[0].truncated == (oversize > MAX_CONTEXT_CHARS)


def test_whole_fields_skip_overflow_instead_of_truncating_later_field():
    target, related = fixture()
    rows = [replace(related, source_text="X" * 3990),
            record("fictional-too-large", "ExtraDescription", "Y" * 4001),
            record("fictional-small", "ShortDescription", "Tiny.")]
    built = context(target, rows)
    assert [field.content_uid for field in built.related_fields] == [related.content_uid, "fictional-small"]
    assert sum(len(field.source_text) for field in built.related_fields) == 3995
    assert all(not field.truncated for field in built.related_fields)


def test_no_related_fields_and_ineligible_related_are_absent():
    target, related = fixture()
    for rows in ((), (target,), (replace(related, eligible=False),)):
        assert build_same_entity_context(target, rows).absence_reason == Reason.NO_RELATED_FIELDS


def test_ambiguous_related_uid_not_selected():
    target, related = fixture()
    alias = replace(related, entity_identity="Skill_Other")
    assert build_same_entity_context(target, (related, alias)).absence_reason == Reason.NO_RELATED_FIELDS


def test_source_locale_and_namespace_do_not_mix():
    target, related = fixture()
    for other in (replace(related, source_locale="OtherLocale"), replace(related, entity_scope="other")):
        assert build_same_entity_context(target, (other,)).absence_reason == Reason.NO_RELATED_FIELDS


def test_reorder_duplicates_and_multiple_equivalent_resources_are_deterministic():
    target, related = fixture()
    extra = record("fictional-extra", "Tooltip", "A tooltip clue.")
    equivalent = replace(related, evidence_source="another/fictional.xml", evidence_fingerprint=fingerprint({"evidence": "second"}))
    rows = (target, related, extra, equivalent)
    expected = context(target, rows)
    for order in itertools.permutations(rows):
        assert context(target, order) == expected
        assert context(target, (*order, related, target)) == expected
        assert canonical_json(context(target, order).to_dict()) == canonical_json(expected.to_dict())


def test_normalized_relative_provenance_and_evidence_digest():
    target, related = fixture()
    built = context(target, (related,))
    assert context(target, (replace(related, evidence_source="fictional\\resources\\entity.xml"),)) == built
    changed = context(target, (replace(related, evidence_fingerprint=fingerprint({"changed": "evidence"})),))
    assert built.related_fields == changed.related_fields
    assert built.evidence_fingerprint != changed.evidence_fingerprint
    assert built.context_fingerprint != changed.context_fingerprint
    payload = canonical_json(built.to_dict())
    assert "fictional/resources/entity.xml" not in payload


def test_evidence_digest_includes_nonselected_structural_evidence():
    target, related = fixture()
    excluded = record("fictional-empty", "Tooltip", "")
    first = context(target, (related,))
    second = context(target, (related, excluded))
    assert first.related_fields == second.related_fields
    assert first.evidence_fingerprint != second.evidence_fingerprint


@pytest.mark.parametrize("changed_text", ["Frost Sparx", " Frost Spark", "Frost Spark\n", "霜火", "e\u0301", "é"])
def test_exact_target_binding_changes(changed_text):
    target, related = fixture()
    changed = replace(target, source_text=changed_text)
    assert context(target, (related,)).target_binding.source_text_sha256 != context(changed, (related,)).target_binding.source_text_sha256
    assert source_text_sha256(changed_text) == sha256(changed_text.encode("utf-8")).hexdigest()
    assert source_text_sha256("é") != source_text_sha256("e\u0301")


def test_canonical_contract_and_context_digest():
    target, related = fixture()
    built = context(target, (related,))
    assert canonical_json({"z": "霜", "a": 1}) == '{"a":1,"z":"霜"}'
    assert "contextFingerprint" not in built.fingerprint_payload()
    assert built.context_fingerprint == fingerprint(built.fingerprint_payload())
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


@pytest.mark.parametrize("change", ["fingerprint", "uid", "category", "source_hash", "schema", "policy", "entity_type", "entity_identity", "evidence_hash", "role"])
def test_present_corruption_raises_explicit_error(change):
    target, related = fixture()
    built = context(target, (related,))
    if change in {"uid", "category", "source_hash"}:
        changes = {"uid": {"content_uid": "fictional-wrong"}, "category": {"category": "quest"},
                   "source_hash": {"source_text_sha256": source_text_sha256("Changed")}}[change]
        built = rehash(replace(built, target_binding=replace(built.target_binding, **changes)))
    else:
        changes = {
            "fingerprint": {"context_fingerprint": "0" * 64}, "schema": {"schema_version": "unknown"},
            "policy": {"policy_version": "unknown"}, "entity_type": {"entity_type": "Weapon"},
            "entity_identity": {"entity_identity": "node#4"}, "evidence_hash": {"evidence_fingerprint": "bad"},
            "role": {"target_field_role": ""},
        }[change]
        built = replace(built, **changes)
        if change != "fingerprint":
            built = rehash(built)
    with pytest.raises(SameEntityContextValidationError):
        validate(built, target)


@pytest.mark.parametrize("case", ["target_uid", "duplicate_uid", "duplicate_text", "target_text", "empty", "tokens", "same_role", "too_many", "too_long", "empty_fields", "bad_truncation_boundary"])
def test_validator_enforces_fields_even_after_rehash(case):
    target, related = fixture()
    built = context(target, (related,))
    field = built.related_fields[0]
    new_fields = {
        "target_uid": (replace(field, content_uid=target.content_uid),),
        "duplicate_uid": (field, replace(field, field_role="Tooltip", source_text="Different clue.")),
        "duplicate_text": (field, replace(field, content_uid="fictional-other", field_role="Tooltip")),
        "target_text": (replace(field, source_text=target.source_text),),
        "empty": (replace(field, source_text=""),),
        "tokens": (replace(field, source_text="{amount} %s"),),
        "same_role": (replace(field, field_role=target.field_role),),
        "too_many": tuple(replace(field, content_uid=f"fictional-{i}", source_text=f"Clue {i}") for i in range(5)),
        "too_long": (replace(field, source_text="X" * 4001),), "empty_fields": (),
        "bad_truncation_boundary": (replace(field, truncated=True),),
    }[case]
    invalid = replace(built, related_fields=new_fields)
    invalid = rehash(invalid)
    with pytest.raises(SameEntityContextValidationError):
        validate(invalid, target)


def test_validator_none_and_unsupported_present():
    validate_same_entity_context(None, content_uid="fictional-any", category="dialogue", source_text="Any.")
    target, related = fixture()
    with pytest.raises(SameEntityContextValidationError, match="unsupported"):
        validate_same_entity_context(context(target, (related,)), content_uid=target.content_uid,
                                     category="dialogue", source_text=target.source_text)
    with pytest.raises(SameEntityContextValidationError, match="expected"):
        validate_same_entity_context({}, content_uid=target.content_uid, category=target.category, source_text=target.source_text)


def test_contract_immutability_and_result_invariant():
    target, related = fixture()
    built = context(target, (related,))
    for obj, attribute in ((target, "source_text"), (built, "context_fingerprint"),
                           (built.target_binding, "category"), (built.related_fields[0], "source_text")):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attribute, "changed")
    with pytest.raises(SameEntityContextValidationError, match="tuple"):
        replace(built, related_fields=list(built.related_fields))
    for value, reason in ((None, None), (built, Reason.NO_RELATED_FIELDS)):
        with pytest.raises(ValueError):
            ContextBuildResult(value, reason)


@pytest.mark.parametrize("changes", [
    {"related_fields": ("invalid-field",)}, {"target_binding": []},
    {"entity_identity": []}, {"schema_version": []},
])
def test_malformed_contract_shape_rejected_at_construction(changes):
    target, related = fixture()
    with pytest.raises(SameEntityContextValidationError):
        replace(context(target, (related,)), **changes)


def test_related_and_binding_contracts_reject_mutable_or_wrong_types():
    target, related = fixture()
    built = context(target, (related,))
    with pytest.raises(SameEntityContextValidationError):
        replace(built.related_fields[0], truncated="false")
    with pytest.raises(SameEntityContextValidationError):
        replace(built.related_fields[0], source_text=[])
    with pytest.raises(SameEntityContextValidationError):
        replace(built.target_binding, content_uid=[])


@pytest.mark.parametrize("category", sorted(CATEGORIES))
@pytest.mark.parametrize("scenario", ["ordinary", "overflow", "oversized", "duplicates"])
def test_research_selector_parity_in_shared_policy(category, scenario):
    target, related = fixture(category)
    rows = [target, related,
            record("fictional-tooltip", "Tooltip" if category != "quest" else "QuestField", "A tooltip clue.", category),
            record("fictional-unknown", "MysteryField", "A mystery clue.", category)]
    if scenario == "overflow":
        rows[1] = replace(related, source_text="X" * 3990)
    if scenario == "oversized":
        rows[1] = replace(related, source_text="X" * 4001)
    if scenario == "duplicates":
        rows += [related, record("fictional-duplicate", "ZebraRole", related.source_text.upper(), category)]
    research_rows = [{"contentUid": row.content_uid, "category": row.category,
                      "entityKey": row.entity_identity, "fieldRole": row.field_role, "sourceText": row.source_text,
                      "structuralEvidence": {"entityType": row.entity_type}} for row in rows]
    packs, _ = build_packs(research_rows)
    research = next(pack for pack in packs if pack["target"]["contentUid"] == target.content_uid)
    assert [field.to_dict() for field in context(target, rows).related_fields] == research["relatedFields"]


def test_module_has_no_research_or_execution_dependency():
    tree = ast.parse(inspect.getsource(production))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert [name for name in imports if name and name.startswith("bg3loc.")] == ["bg3loc.protected_syntax"]


def map_key_fixture(identity="FictionalRootTemplateKey"):
    return tuple(replace(row, identity_kind=Kind.TEMPLATE_MAP_KEY, entity_identity=identity,
                         identity_origin="MAP_KEY", template_type="item",
                         identity_is_native=True, field_is_direct=True)
                 for row in fixture("item"))


@pytest.mark.parametrize("identity", ["FictionalRootTemplateKey", IDENTITIES["item"]])
def test_verified_native_item_map_key_is_allowed_and_validates(identity):
    target, related = map_key_fixture(identity)
    built = context(target, (related,))
    assert json.loads(built.entity_identity)["identity"] == identity
    validate(built, target)
    assert built.related_fields[0].content_uid == related.content_uid
    assert not {"identityOrigin", "templateType", "definitionFingerprint", "identityIsNative", "fieldIsDirect"} & built.to_dict().keys()


@pytest.mark.parametrize("changes", [
    {"identity_origin": ""}, {"identity_origin": "UUID"}, {"identity_origin": "NAME"},
    {"identity_origin": "FALLBACK_ORDINAL"}, {"identity_origin": "FALLBACK_NODE"},
    {"identity_origin": "UNKNOWN"}, {"identity_is_native": False},
    {"template_type": ""}, {"template_type": "character"}, {"template_type": "scenery"},
    {"template_type": "other"}, {"template_type": "Item"},
    {"entity_type": "UiNode"}, {"evidence_source": ""}, {"evidence_fingerprint": ""},
    {"definition_fingerprint": ""}, {"field_is_direct": False},
    {"field_role": "GameMasterSpawnSubSection"}, {"field_role": "UnverifiedRole"},
    {"entity_identity": "node#12"}, {"identity_kind": Kind.GENERIC_NODE},
    {"identity_kind": Kind.ORDINAL_FALLBACK}, {"identity_kind": Kind.TEMPLATE_UUID},
])
def test_map_key_missing_or_invalid_structural_proof_is_not_reliable(changes):
    target, related = map_key_fixture(IDENTITIES["item"])
    assert build_same_entity_context(replace(target, **changes), (related,)).absence_reason == Reason.NO_RELIABLE_IDENTITY


@pytest.mark.parametrize("kind", [Kind.GENERIC_NODE, Kind.ORDINAL_FALLBACK, Kind.FILE_GROUP])
def test_item_name_and_fallback_do_not_gain_map_key_reliability(kind):
    target, related = map_key_fixture()
    target = replace(target, identity_kind=kind, identity_origin="NAME" if kind == Kind.GENERIC_NODE else "FALLBACK_ORDINAL")
    assert build_same_entity_context(target, (related,)).absence_reason == Reason.NO_RELIABLE_IDENTITY


def test_explicit_uuid_compatibility_and_origin_mismatch():
    target, related = fixture("item")
    assert context(target, (related,))
    target, related = (replace(row, identity_origin="UUID", template_type="item", identity_is_native=True)
                       for row in (target, related))
    assert context(target, (related,))
    assert build_same_entity_context(replace(target, identity_origin="MAP_KEY"), (related,)).absence_reason == Reason.NO_RELIABLE_IDENTITY


@pytest.mark.parametrize("changes", [
    {}, {"eligible": False}, {"template_type": "character"}, {"template_type": "scenery"},
    {"identity_is_native": False}, {"identity_origin": "UNKNOWN"},
    {"identity_kind": Kind.GENERIC_NODE}, {"entity_type": "UiNode"},
    {"content_uid": "", "field_role": "", "source_text": "", "eligible": False},
    {"content_uid": "fictional-target"},
])
def test_map_key_conflict_includes_all_retained_definitions_before_filtering(changes):
    target, related = map_key_fixture()
    conflict = replace(related, content_uid="fictional-competing", evidence_source="another/definition.lsx",
                       definition_fingerprint=fingerprint({"otherWholeDefinition": True}), **{
                           key: value for key, value in changes.items() if key != "content_uid"})
    if "content_uid" in changes:
        conflict = replace(conflict, content_uid=changes["content_uid"])
    for rows in itertools.permutations((target, related, conflict)):
        assert build_same_entity_context(target, rows).absence_reason == Reason.STRUCTURAL_CONFLICT


@pytest.mark.parametrize("changes", [{"template_type": "character"}, {"identity_is_native": False},
                                      {"identity_origin": "UNKNOWN"}, {"evidence_source": ""},
                                      {"evidence_fingerprint": ""}])
def test_map_key_same_fingerprint_does_not_override_bad_definition_proof(changes):
    target, related = map_key_fixture()
    retained = replace(related, content_uid="", field_role="", source_text="", eligible=False, **changes)
    assert build_same_entity_context(target, (related, retained)).absence_reason == Reason.NO_RELIABLE_IDENTITY


def test_map_key_identical_multi_resource_definitions_and_empty_definition_are_allowed():
    target, related = map_key_fixture()
    duplicate = replace(related, evidence_source="another/definition.lsx",
                        evidence_fingerprint=fingerprint({"secondOccurrenceEvidence": True}))
    retained = replace(target, content_uid="", field_role="", source_text="", eligible=False,
                       field_is_direct=False, evidence_source="retained/definition.lsx",
                       evidence_fingerprint=fingerprint({"retainedDefinitionOnly": True}))
    expected = context(target, (related, duplicate, retained))
    for rows in itertools.permutations((related, duplicate, retained)):
        assert context(target, rows) == expected
    assert len(expected.related_fields) == 1


def test_map_key_grouping_preserves_category_scope_and_exact_native_key():
    target, related = map_key_fixture()
    others = [replace(related, category="quest", entity_type="Quest", identity_kind=Kind.JOURNAL_ENTITY_ID),
              replace(related, entity_scope="other-snapshot"),
              replace(related, entity_identity=target.entity_identity.lower())]
    for other in others:
        other = replace(other, content_uid="fictional-isolated")
        assert build_same_entity_context(target, (other,)).absence_reason == Reason.NO_RELATED_FIELDS
        assert context(target, (related, other)) == context(target, (related,))


def test_nested_and_unverified_map_key_fields_are_excluded_without_changing_selection_limits():
    target, related = map_key_fixture()
    nested = replace(related, content_uid="fictional-nested", field_role="Description",
                     source_text="Nested metadata.", field_is_direct=False)
    category = replace(related, content_uid="fictional-category", field_role="GameMasterSpawnSubSection",
                       source_text="An editor category.")
    built = context(target, (related, nested, category))
    assert built.related_fields == context(target, (related,)).related_fields
    assert MAX_RELATED_FIELDS == 4 and MAX_CONTEXT_CHARS == 4000
    assert FIELD_PRIORITY["item"] == ("DisplayName", "Description", "Tooltip")
    assert build_same_entity_context(target, (nested, category)).absence_reason == Reason.NO_RELATED_FIELDS


def test_map_key_evidence_digest_binds_structural_proof_and_nonselected_provenance():
    target, related = map_key_fixture()
    first = context(target, (related,))
    retained = replace(target, content_uid="", field_role="", source_text="", eligible=False, field_is_direct=False)
    second = context(target, (related, retained))
    third = context(target, (related, replace(retained, field_is_direct=True)))
    assert first.related_fields == second.related_fields == third.related_fields
    assert len({built.evidence_fingerprint for built in (first, second, third)}) == 3
    payload = production._evidence_payload(target)
    assert (payload["identityOrigin"], payload["templateType"], payload["identityIsNative"], payload["fieldIsDirect"]) == ("MAP_KEY", "item", True, True)


def test_policy_version_changes_context_fingerprint_with_same_fields_and_binding():
    target, related = map_key_fixture()
    current = context(target, (related,))
    previous = rehash(replace(current, policy_version="b1-02-structural/1"))
    assert previous.related_fields == current.related_fields
    assert previous.target_binding == current.target_binding
    assert previous.evidence_fingerprint == current.evidence_fingerprint
    assert previous.context_fingerprint != current.context_fingerprint
    with pytest.raises(SameEntityContextValidationError, match="policy version"):
        validate(previous, target)


@pytest.mark.parametrize("changes", [{"evidence_fingerprint": ""}, {"entity_identity": "{}"},
                                      {"entity_identity": '{"scope":"","identity":"FictionalRootTemplateKey"}'},
                                      {"entity_identity": '{"scope":"default","identity":"node#12"}'}])
def test_map_key_present_context_requires_scoped_identity_and_valid_evidence_digest(changes):
    target, related = map_key_fixture()
    invalid = rehash(replace(context(target, (related,)), **changes))
    with pytest.raises(SameEntityContextValidationError):
        validate(invalid, target)


@pytest.mark.parametrize("changes", [{"identity_origin": []}, {"template_type": []},
                                      {"identity_is_native": "true"}, {"field_is_direct": 1}])
def test_new_provenance_metadata_is_typed(changes):
    target, _ = map_key_fixture()
    with pytest.raises(ValueError):
        replace(target, **changes)
