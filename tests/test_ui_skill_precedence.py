from bg3loc.research.ui_skill_precedence import (
    Definition,
    ModuleInfo,
    definition_signature,
    definitions_equivalent,
    dependency_closure,
    exact_parent_candidates,
    inherited_field_map,
    reconcile_definition,
    reconcile_precedence,
)


def _def(
    ident: str,
    *,
    name: str,
    using: str = "",
    entity_type: str = "PassiveData",
    fields: dict[str, str] | None = None,
    provider: str = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt",
    internal_path: str = "Public/Shared/Stats/Generated/Data/Passive.txt",
) -> Definition:
    return Definition(
        id=ident,
        name=name,
        entity_type=entity_type,
        using=using,
        fields=fields or {},
        provider=provider,
        internal_path=internal_path,
    )


def test_definition_signature_uses_complete_raw_field_map() -> None:
    a = _def("a", name="Parent", fields={"DisplayName": "h1", "Description": "h2"})
    b = _def("b", name="Parent", fields={"Description": "h2", "DisplayName": "h1"})
    c = _def("c", name="Parent", fields={"DisplayName": "h1", "Description": "h3"})
    assert definition_signature(a) == definition_signature(b)
    assert definitions_equivalent((a, b))
    assert not definitions_equivalent((a, c))


def test_exact_parent_candidates_excludes_child_and_requires_compatible_type() -> None:
    child = _def("child", name="Child", using="Parent")
    good = _def("good", name="Parent")
    wrong_type = _def("wrong", name="Parent", entity_type="StatusData")
    by_name = {"Parent": (child, good, wrong_type)}
    assert exact_parent_candidates(child, by_name) == (good,)


def test_dependency_closure_records_minimum_depth() -> None:
    closure = dependency_closure({"A": ("B", "C"), "B": ("D",), "C": ("D",), "D": ()})
    assert closure["A"]["B"] == 1
    assert closure["A"]["D"] == 2


def test_reconcile_unique_non_self_parent() -> None:
    child = _def("child", name="Child", using="Parent")
    parent = _def("parent", name="Parent")
    result = reconcile_definition(
        child,
        {"Parent": (parent,)},
        modules_by_folder={},
        direct_dependencies={},
        transitive_dependencies={},
    )
    assert result.status == "ResolvedUniqueCompatibleDefinition"
    assert result.selected_definition_id == "parent"


def test_reconcile_self_name_uses_direct_module_dependency() -> None:
    child = _def(
        "child",
        name="Same",
        using="Same",
        provider="GustavX.pak::Public/GustavX/Stats/Generated/Data/Passive.txt",
        internal_path="Public/GustavX/Stats/Generated/Data/Passive.txt",
        fields={"Description": "new"},
    )
    parent = _def(
        "parent",
        name="Same",
        provider="Gustav.pak::Public/Gustav/Stats/Generated/Data/Passive.txt",
        internal_path="Public/Gustav/Stats/Generated/Data/Passive.txt",
        fields={"Description": "old"},
    )
    modules = {
        "GustavX": ModuleInfo("GustavX", "uuid-x"),
        "Gustav": ModuleInfo("Gustav", "uuid-g"),
    }
    result = reconcile_definition(
        child,
        {"Same": (child, parent)},
        modules_by_folder=modules,
        direct_dependencies={"uuid-x": ("uuid-g",)},
        transitive_dependencies={"uuid-x": {"uuid-g": 1}},
    )
    assert result.status == "ResolvedByDirectModuleDependency"
    assert result.selected_definition_id == "parent"


def test_reconcile_self_name_without_dependency_is_warning_not_ambiguous_hold() -> None:
    child = _def(
        "child",
        name="Same",
        using="Same",
        internal_path="Public/GustavX/Stats/Generated/Data/Passive.txt",
        fields={"Description": "new"},
    )
    parent = _def(
        "parent",
        name="Same",
        internal_path="Public/Shared/Stats/Generated/Data/Passive.txt",
        fields={"Description": "old"},
    )
    modules = {
        "GustavX": ModuleInfo("GustavX", "uuid-x"),
        "Shared": ModuleInfo("Shared", "uuid-s"),
    }
    result = reconcile_definition(
        child,
        {"Same": (child, parent)},
        modules_by_folder=modules,
        direct_dependencies={"uuid-x": ()},
        transitive_dependencies={"uuid-x": {}},
    )
    assert result.status == "SupportedButRuntimeWinnerUnproven"


def test_reconcile_precedence_stops_after_unique_same_provider_parent() -> None:
    provider = "GustavX.pak::Public/GustavX/Stats/Generated/Data/Passive.txt"
    child = _def(
        "child",
        name="Child",
        using="Parent",
        provider=provider,
        internal_path="Public/GustavX/Stats/Generated/Data/Passive.txt",
        fields={"DisplayName": "h11111111g1111g1111g1111g111111111111"},
    )
    same_provider_parent = _def(
        "same-parent",
        name="Parent",
        provider=provider,
        internal_path="Public/GustavX/Stats/Generated/Data/Passive.txt",
        fields={"Description": "h22222222g2222g2222g2222g222222222222"},
    )
    other_provider_parent = _def(
        "other-parent",
        name="Parent",
        provider="Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt",
        internal_path="Public/Shared/Stats/Generated/Data/Passive.txt",
        fields={"Description": "h33333333g3333g3333g3333g333333333333"},
    )
    outcome = reconcile_precedence(
        (child, same_provider_parent),
        (other_provider_parent,),
        target_uids={
            "h11111111g1111g1111g1111g111111111111",
            "h22222222g2222g2222g2222g222222222222",
            "h33333333g3333g3333g3333g333333333333",
        },
        related_content_uids_by_edge={},
        modules_by_folder={},
        direct_dependencies={},
    )
    assert outcome.ambiguous_edge_count == 0
    assert not outcome.hold_uids


def test_reconcile_precedence_uses_edge_lineage_without_definition_field_uids() -> None:
    child = _def(
        "child",
        name="Child",
        using="Parent",
        fields={"DisplayName": "h11111111g1111g1111g1111g111111111111"},
    )
    parent_a = _def(
        "parent-a",
        name="Parent",
        fields={"Description": "h22222222g2222g2222g2222g222222222222"},
        provider="Gustav.pak::Public/Gustav/Stats/Generated/Data/Passive.txt",
        internal_path="Public/Gustav/Stats/Generated/Data/Passive.txt",
    )
    parent_b = _def(
        "parent-b",
        name="Parent",
        fields={"Description": "h33333333g3333g3333g3333g333333333333"},
        provider="GustavX.pak::Public/GustavX/Stats/Generated/Data/Passive.txt",
        internal_path="Public/GustavX/Stats/Generated/Data/Passive.txt",
    )
    direct_uid = "h44444444g4444g4444g4444g444444444444"
    outcome = reconcile_precedence(
        (child,),
        (parent_a, parent_b),
        target_uids={
            direct_uid,
            "h11111111g1111g1111g1111g111111111111",
            "h22222222g2222g2222g2222g222222222222",
            "h33333333g3333g3333g3333g333333333333",
        },
        related_content_uids_by_edge={child.id: {direct_uid}},
        modules_by_folder={},
        direct_dependencies={},
    )
    assert outcome.ambiguous_edge_count == 1
    assert outcome.hold_uids == {direct_uid}


def test_inherited_field_map_child_and_nearer_ancestor_shadow() -> None:
    parent = _def("p", name="P", fields={"A": "p-a", "B": "p-b"}, provider="P")
    grand = _def("g", name="G", fields={"A": "g-a", "C": "g-c"}, provider="G")
    inherited = inherited_field_map({"B"}, (parent, grand))
    assert inherited == {
        "A": ("p-a", "P", 1),
        "C": ("g-c", "G", 2),
    }
