"""Tests for cross-domain target universe extraction — synthetic fixtures only.

All ContentUids, resource content, and pak names used here are synthetic.
No historical game UIDs appear.  Integration comparison against historical
counts lives in a separate external evidence document.

Coverage:
  - Absence of embedded historical payload in cross_domain_universe module
  - Cross-Domain resource selection rule table
  - Provider precedence / patch override
  - Field extraction from stats text
  - Field extraction from LSX/XML
  - Field extraction from XAML
  - Entity identity from nested XML
  - Inheritance (stats "using" field)
  - Domain classification per rule
  - Deduplication (first-provider-wins)
  - Cache isolation (different keys → independent stores)
  - Extraction context cache key determinism
"""
from __future__ import annotations

import re
import inspect
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from bg3loc.research.model import ResearchScanResource
from bg3loc.research.cross_domain_universe import (
    CROSS_DOMAIN_FAMILY_RULES,
    CROSS_DOMAIN_SCOPE_PAKS,
    RULE_CROSS_DOMAIN_UNIVERSE,
    CrossDomainExtractionContext,
    CrossDomainExtractionResult,
    CrossDomainFamilyRule,
    CrossDomainEntityLayerAuditRecord,
    CrossDomainMaterializedRelation,
    CrossDomainTarget,
    CrossDomainUniverseCache,
    _StatEntryRecord,
    _extract_from_lsx_xml,
    _extract_from_stats_text,
    _extract_from_xaml,
    _materialize_stats_entities,
    _parse_stats_entries,
    _resolve_stats_inheritance,
    compute_provider_priority,
    extract_cross_domain_result,
    extract_cross_domain_target_universe,
    get_cross_domain_universe_uids,
    resolve_cross_domain_provider_precedence,
    select_cross_domain_resources,
)

# ---------------------------------------------------------------------------
# Helpers — synthetic UID generator
# ---------------------------------------------------------------------------

def _uid(n: int) -> str:
    """Return a syntactically valid but purely synthetic ContentUid."""
    hex8 = format(n & 0xFFFF_FFFF, "08x")
    return f"h{hex8}g0000g0000g0000g000000000000"


# ---------------------------------------------------------------------------
# 1. Absence of embedded historical payload
# ---------------------------------------------------------------------------

class TestNoEmbeddedPayload(unittest.TestCase):
    def test_no_base64_zlib_imports(self) -> None:
        """cross_domain_universe must not import base64 or zlib."""
        import bg3loc.research.cross_domain_universe as mod
        src = inspect.getsource(mod)
        self.assertNotIn("import base64", src)
        self.assertNotIn("import zlib", src)

    def test_no_DATA_constant(self) -> None:
        """cross_domain_universe must not define a _DATA constant."""
        import bg3loc.research.cross_domain_universe as mod
        self.assertFalse(hasattr(mod, "_DATA"), "_DATA must not exist in cross_domain_universe")

    def test_no_known_historical_uids_in_source(self) -> None:
        """Source code must not contain any hardcoded localization handles."""
        import bg3loc.research.cross_domain_universe as mod
        src = inspect.getsource(mod)
        uid_pattern = re.compile(r'h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12}', re.I)
        matches = uid_pattern.findall(src)
        self.assertEqual(matches, [], f"Found hardcoded UIDs in source: {matches[:5]}")

    def test_no_compressed_blob(self) -> None:
        """Source code must not contain a large base64 string literal."""
        import bg3loc.research.cross_domain_universe as mod
        src = inspect.getsource(mod)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"') and len(stripped) > 200:
                self.fail(f"Suspicious long string literal (possible compressed blob): {stripped[:80]}…")


# ---------------------------------------------------------------------------
# 2. Resource selection
# ---------------------------------------------------------------------------

class TestResourceSelection(unittest.TestCase):
    def _res(self, pak: str, path: str, fmt: str = "TXT") -> ResearchScanResource:
        return ResearchScanResource(pakName=pak, internalPath=path,
                                    resourceFormat=fmt, sourceRole="test", size=0)

    def test_stats_txt_in_gustavx_selected(self) -> None:
        r = self._res("GustavX.pak", "Public/GustavX/Stats/Generated/Data/Spells_Damage.txt")
        selected = select_cross_domain_resources([r])
        self.assertEqual(len(selected), 1)
        self.assertIn("Stats", selected[0][0].family)

    def test_xaml_in_shared_selected(self) -> None:
        r = self._res("Shared.pak", "Content/UI/Tooltips/Shared_Tooltips.xaml", "XAML")
        selected = select_cross_domain_resources([r])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0].family, "UIXaml")

    def test_root_templates_lsf_selected(self) -> None:
        r = self._res("Shared.pak", "Public/Shared/RootTemplates/_merged.lsf", "LSF")
        selected = select_cross_domain_resources([r])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0].family, "RootTemplatesLSX")

    def test_dialog_lsj_not_selected(self) -> None:
        r = self._res("Gustav.pak", "Mods/Gustav/Story/Dialogs/Cutscene_End.lsj", "LSJ")
        self.assertEqual(select_cross_domain_resources([r]), [])

    def test_loca_not_selected(self) -> None:
        r = self._res("English.pak", "Localization/English/English.loca", "LOCA")
        self.assertEqual(select_cross_domain_resources([r]), [])

    def test_out_of_scope_pak_not_selected(self) -> None:
        r = self._res("English.pak", "Public/Shared/Stats/Generated/Data/Test.txt")
        self.assertEqual(select_cross_domain_resources([r]), [])

    def test_patch_pak_stats_selected(self) -> None:
        r = self._res("Patch8_HotFix9.pak", "Public/Patch8_HotFix9/Stats/Generated/Data/Fix.txt")
        self.assertGreater(len(select_cross_domain_resources([r])), 0)

    def test_first_rule_wins_for_ambiguous_path(self) -> None:
        r = self._res("Gustav.pak", "Content/UI/SomeUI.xaml", "XAML")
        selected = select_cross_domain_resources([r])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0].family, "UIXaml")


# ---------------------------------------------------------------------------
# 3. Provider precedence & patch override
# ---------------------------------------------------------------------------

class TestProviderPrecedence(unittest.TestCase):
    def _res(self, pak: str, path: str, size: int = 100) -> ResearchScanResource:
        return ResearchScanResource(pakName=pak, internalPath=path,
                                    resourceFormat="TXT", sourceRole="test", size=size)

    def _rule(self) -> CrossDomainFamilyRule:
        return CROSS_DOMAIN_FAMILY_RULES[1]  # StatsGeneratedGustavX

    def test_patch_beats_base_pak(self) -> None:
        path = "Public/Shared/Stats/Generated/Data/Spells.txt"
        rule = self._rule()
        winning = resolve_cross_domain_provider_precedence([
            (rule, self._res("Shared.pak", path)),
            (rule, self._res("Patch8_HotFix9.pak", path)),
        ])
        self.assertEqual(len(winning), 1)
        self.assertEqual(winning[0][1].pakName, "Patch8_HotFix9.pak")

    def test_gustavx_beats_shared(self) -> None:
        path = "Public/Shared/Stats/Generated/Data/Weapon.txt"
        rule = self._rule()
        winning = resolve_cross_domain_provider_precedence([
            (rule, self._res("Shared.pak", path)),
            (rule, self._res("GustavX.pak", path)),
        ])
        self.assertEqual(len(winning), 1)
        self.assertEqual(winning[0][1].pakName, "GustavX.pak")

    def test_unique_paths_both_survive(self) -> None:
        rule = self._rule()
        winning = resolve_cross_domain_provider_precedence([
            (rule, self._res("Shared.pak", "Public/Shared/Stats/Generated/Data/A.txt")),
            (rule, self._res("Gustav.pak", "Public/Gustav/Stats/Generated/Data/B.txt")),
        ])
        self.assertEqual(len(winning), 2)


# ---------------------------------------------------------------------------
# 4. Stats text field extraction
# ---------------------------------------------------------------------------

class TestStatsTextExtraction(unittest.TestCase):
    def test_displayname_handle_extracted(self) -> None:
        uid = _uid(1)
        text = f'new entry "TestSpell"\ntype "SpellData"\nusing "MagicMissile"\ndata "DisplayName" "{uid};1"\n'
        results = list(_extract_from_stats_text(
            text, pak_name="GustavX.pak", internal_path="S.txt", domain="AbilityOrSkill",
            field_re=re.compile(r"(?i)^DisplayName$"),
        ))
        self.assertEqual(len(results), 1)
        t = results[0]
        self.assertEqual(t.contentUid, uid)
        self.assertEqual(t.entity, "TestSpell")
        self.assertEqual(t.field, "DisplayName")
        self.assertEqual(t.inheritedFrom, "MagicMissile")

    def test_unqualified_field_skipped_with_field_re(self) -> None:
        uid = _uid(2)
        text = f'new entry "T"\ndata "SomeOther" "{uid};1"\n'
        results = list(_extract_from_stats_text(
            text, pak_name="p.pak", internal_path="f.txt", domain="D",
            field_re=re.compile(r"(?i)^DisplayName$"),
        ))
        self.assertEqual(results, [])

    def test_multiple_entries_independent(self) -> None:
        uid_a, uid_b = _uid(10), _uid(11)
        text = f'new entry "A"\ndata "DisplayName" "{uid_a};1"\nnew entry "B"\ndata "DisplayName" "{uid_b};1"\n'
        results = list(_extract_from_stats_text(
            text, pak_name="p.pak", internal_path="f.txt", domain="D",
            field_re=re.compile(r"(?i)^DisplayName$"),
        ))
        self.assertEqual({r.contentUid for r in results}, {uid_a, uid_b})

    def test_inheritance_captured(self) -> None:
        uid = _uid(20)
        text = f'new entry "Child"\nusing "Parent"\ndata "Description" "{uid};2"\n'
        results = list(_extract_from_stats_text(
            text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None
        ))
        self.assertEqual(results[0].inheritedFrom, "Parent")

    def test_comment_lines_skipped(self) -> None:
        uid = _uid(30)
        text = f'// comment\nnew entry "X"\n// another\ndata "DisplayName" "{uid};1"\n'
        results = list(_extract_from_stats_text(
            text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None
        ))
        self.assertEqual(len(results), 1)

    def test_two_pass_inheritance_resolution_single_level(self) -> None:
        uid_p = _uid(101)
        text = f'new entry "Parent"\ndata "DisplayName" "{uid_p};1"\nnew entry "Child"\nusing "Parent"\n'
        entries = _parse_stats_entries(text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None)
        relations = _resolve_stats_inheritance(entries)
        # Parent has explicit DisplayName
        # Child inherits DisplayName from Parent with depth 1
        child_rels = [r for r in relations if r.entity == "Child"]
        self.assertEqual(len(child_rels), 1)
        self.assertEqual(child_rels[0].contentUid, uid_p)
        self.assertEqual(child_rels[0].field, "DisplayName")
        self.assertEqual(child_rels[0].inheritedFrom, "Parent")
        self.assertEqual(child_rels[0].inheritanceDepth, 1)
        self.assertEqual(child_rels[0].explicitOrInherited, "inherited")

    def test_two_pass_inheritance_resolution_multilevel(self) -> None:
        uid_gp = _uid(201)
        uid_p = _uid(202)
        text = (
            f'new entry "GrandParent"\ndata "DisplayName" "{uid_gp};1"\n'
            f'new entry "Parent"\nusing "GrandParent"\ndata "Description" "{uid_p};1"\n'
            f'new entry "Child"\nusing "Parent"\n'
        )
        entries = _parse_stats_entries(text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None)
        relations = _resolve_stats_inheritance(entries)
        child_rels = {r.field: r for r in relations if r.entity == "Child"}
        self.assertIn("DisplayName", child_rels)
        self.assertIn("Description", child_rels)
        # DisplayName came from GrandParent through Parent (depth 2)
        self.assertEqual(child_rels["DisplayName"].contentUid, uid_gp)
        self.assertEqual(child_rels["DisplayName"].inheritanceDepth, 2)
        # Description came from Parent (depth 1)
        self.assertEqual(child_rels["Description"].contentUid, uid_p)
        self.assertEqual(child_rels["Description"].inheritanceDepth, 1)

    def test_two_pass_child_overrides_parent(self) -> None:
        uid_p = _uid(301)
        uid_c = _uid(302)
        text = (
            f'new entry "Parent"\ndata "DisplayName" "{uid_p};1"\n'
            f'new entry "Child"\nusing "Parent"\ndata "DisplayName" "{uid_c};1"\n'
        )
        entries = _parse_stats_entries(text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None)
        relations = _resolve_stats_inheritance(entries)
        child_rels = [r for r in relations if r.entity == "Child"]
        self.assertEqual(len(child_rels), 1)
        self.assertEqual(child_rels[0].contentUid, uid_c)
        self.assertEqual(child_rels[0].inheritanceDepth, 0)
        self.assertEqual(child_rels[0].explicitOrInherited, "explicit")

    def test_two_pass_cycle_detection(self) -> None:
        uid_a = _uid(401)
        uid_b = _uid(402)
        text = (
            f'new entry "A"\nusing "B"\ndata "DisplayName" "{uid_a};1"\n'
            f'new entry "B"\nusing "A"\ndata "Description" "{uid_b};1"\n'
        )
        entries = _parse_stats_entries(text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None)
        # Must not raise RecursionError or loop infinitely
        relations = _resolve_stats_inheritance(entries)
        self.assertTrue(len(relations) >= 2)

    def test_two_pass_missing_parent_handled(self) -> None:
        uid_c = _uid(501)
        text = f'new entry "Child"\nusing "NonExistentParent"\ndata "DisplayName" "{uid_c};1"\n'
        entries = _parse_stats_entries(text, pak_name="p.pak", internal_path="f.txt", domain="D", field_re=None)
        relations = _resolve_stats_inheritance(entries)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0].contentUid, uid_c)


# ---------------------------------------------------------------------------
# 5. LSX / XML extraction
# ---------------------------------------------------------------------------

class TestLSXExtraction(unittest.TestCase):
    def test_translated_string_extracted(self) -> None:
        uid = _uid(100)
        xml = f'<?xml version="1.0" encoding="utf-8"?><save><region id="R"><node id="N"><node id="GameObjectTemplate"><attribute id="DisplayName" type="TranslatedString" handle="{uid}" version="1" /></node></node></region></save>'
        results = list(_extract_from_lsx_xml(
            xml, pak_name="Shared.pak", internal_path="f.lsx", domain="D",
            field_re=re.compile(r"(?i)^DisplayName$"),
        ))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].contentUid, uid)

    def test_non_translated_string_skipped(self) -> None:
        xml = '<?xml version="1.0" encoding="utf-8"?><save><region id="R"><node id="N"><attribute id="Name" type="FixedString" value="X" /></node></region></save>'
        results = list(_extract_from_lsx_xml(xml, pak_name="p", internal_path="f", domain="D", field_re=None))
        self.assertEqual(results, [])

    def test_field_re_filters_attributes(self) -> None:
        uid_a, uid_b = _uid(200), _uid(201)
        xml = f'<?xml version="1.0"?><save><region id="R"><node id="N"><attribute id="DisplayName" type="TranslatedString" handle="{uid_a}" version="1" /><attribute id="Other" type="TranslatedString" handle="{uid_b}" version="1" /></node></region></save>'
        results = list(_extract_from_lsx_xml(
            xml, pak_name="p", internal_path="f", domain="D",
            field_re=re.compile(r"(?i)^DisplayName$"),
        ))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].contentUid, uid_a)

    def test_entity_identity_from_node_id(self) -> None:
        uid = _uid(300)
        xml = f'<?xml version="1.0"?><save><region id="T"><node id="T"><node id="GOTemplate"><attribute id="DisplayName" type="TranslatedString" handle="{uid}" version="1" /></node></node></region></save>'
        results = list(_extract_from_lsx_xml(xml, pak_name="p", internal_path="f", domain="D", field_re=None))
        self.assertEqual(results[0].entity, "GOTemplate")

    def test_malformed_xml_returns_empty(self) -> None:
        results = list(_extract_from_lsx_xml("NOT XML", pak_name="p", internal_path="f", domain="D", field_re=None))
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# 6. XAML extraction
# ---------------------------------------------------------------------------

class TestXAMLExtraction(unittest.TestCase):
    def test_handle_extracted(self) -> None:
        uid = _uid(400)
        results = list(_extract_from_xaml(f'<TextBlock Text="{uid}" />', pak_name="p", internal_path="f.xaml", domain="UserInterface"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].contentUid, uid)

    def test_multiple_handles_extracted(self) -> None:
        uid_a, uid_b = _uid(410), _uid(411)
        results = list(_extract_from_xaml(f'<Label A="{uid_a}" B="{uid_b}" />', pak_name="p", internal_path="f.xaml", domain="D"))
        self.assertEqual(len(results), 2)

    def test_no_uid_returns_empty(self) -> None:
        results = list(_extract_from_xaml('<Button Text="Click me" />', pak_name="p", internal_path="f.xaml", domain="D"))
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# 7. Deduplication — first provider wins
# ---------------------------------------------------------------------------

class TestDeduplication(unittest.TestCase):
    def test_first_provider_wins(self) -> None:
        uid = _uid(500)
        first = CrossDomainTarget(contentUid=uid, domain="D1", provider="Shared.pak::a", internalPath="a", entity="EntA", field="DisplayName")
        second = CrossDomainTarget(contentUid=uid, domain="D2", provider="Gustav.pak::b", internalPath="b", entity="EntB", field="Description")
        uid_map: dict[str, CrossDomainTarget] = {}
        for tgt in [first, second]:
            if tgt.contentUid not in uid_map:
                uid_map[tgt.contentUid] = tgt
        self.assertEqual(uid_map[uid].provider, "Shared.pak::a")


# ---------------------------------------------------------------------------
# 8. Cache isolation
# ---------------------------------------------------------------------------

class TestCacheIsolation(unittest.TestCase):
    def _ctx(self, build_id: str = "b", game_dir: str = "/game", sha: str = "s") -> CrossDomainExtractionContext:
        return CrossDomainExtractionContext(
            game_dir=Path(game_dir), backend=MagicMock(), resources=[],
            build_id=build_id, game_version="v", scan_manifest_sha256=sha,
        )

    def test_different_build_ids_different_keys(self) -> None:
        self.assertNotEqual(self._ctx(build_id="b1").cache_key(), self._ctx(build_id="b2").cache_key())

    def test_different_game_dirs_different_keys(self) -> None:
        self.assertNotEqual(self._ctx(game_dir="/A").cache_key(), self._ctx(game_dir="/B").cache_key())

    def test_different_sha_different_keys(self) -> None:
        self.assertNotEqual(self._ctx(sha="aaa").cache_key(), self._ctx(sha="bbb").cache_key())

    def test_cache_miss_for_different_build(self) -> None:
        cache = CrossDomainUniverseCache()
        uid = _uid(600)
        ctx1 = self._ctx(build_id="b1")
        ctx2 = self._ctx(build_id="b2")
        cache.put(ctx1.cache_key(), {uid: CrossDomainTarget(contentUid=uid, domain="D", provider="p", internalPath="i", entity="e", field="f")})
        self.assertIsNone(cache.get(ctx2.cache_key()))

    def test_cache_hit_same_provenance(self) -> None:
        cache = CrossDomainUniverseCache()
        uid = _uid(700)
        ctx = self._ctx()
        val = {uid: CrossDomainTarget(contentUid=uid, domain="D", provider="p", internalPath="i", entity="e", field="f")}
        cache.put(ctx.cache_key(), val)
        self.assertIs(cache.get(ctx.cache_key()), val)

    def test_two_caches_independent(self) -> None:
        cache1 = CrossDomainUniverseCache()
        cache2 = CrossDomainUniverseCache()
        uid = _uid(800)
        cache1.put("key", {uid: CrossDomainTarget(contentUid=uid, domain="D", provider="p", internalPath="i", entity="e", field="f")})
        self.assertIsNone(cache2.get("key"))


# ---------------------------------------------------------------------------
# 9. Cache key determinism
# ---------------------------------------------------------------------------

class TestCacheKeyDeterminism(unittest.TestCase):
    def test_includes_game_dir(self) -> None:
        ctx = CrossDomainExtractionContext(game_dir=Path("/game/UNIQUEDIR"), backend=MagicMock(), resources=[], build_id="b", game_version="v", scan_manifest_sha256="h")
        self.assertIn("UNIQUEDIR", ctx.cache_key())

    def test_includes_build_id(self) -> None:
        ctx = CrossDomainExtractionContext(game_dir=Path("/g"), backend=MagicMock(), resources=[], build_id="build-XYZ", game_version="v", scan_manifest_sha256="h")
        self.assertIn("build-XYZ", ctx.cache_key())

    def test_includes_scan_hash(self) -> None:
        ctx = CrossDomainExtractionContext(game_dir=Path("/g"), backend=MagicMock(), resources=[], build_id="b", game_version="v", scan_manifest_sha256="UNIQUE_SHA")
        self.assertIn("UNIQUE_SHA", ctx.cache_key())

    def test_same_inputs_same_key(self) -> None:
        kw = dict(game_dir=Path("/g"), backend=MagicMock(), resources=[], build_id="b", game_version="v", scan_manifest_sha256="h")
        self.assertEqual(CrossDomainExtractionContext(**kw).cache_key(), CrossDomainExtractionContext(**kw).cache_key())


# ---------------------------------------------------------------------------
# 10. get_cross_domain_universe_uids helper
# ---------------------------------------------------------------------------

class TestGetUniverseUids(unittest.TestCase):
    def test_returns_key_set(self) -> None:
        uid_a, uid_b = _uid(1000), _uid(1001)
        universe = {
            uid_a: CrossDomainTarget(contentUid=uid_a, domain="D", provider="p", internalPath="i", entity="e", field="f"),
            uid_b: CrossDomainTarget(contentUid=uid_b, domain="D", provider="p", internalPath="i", entity="e", field="f"),
        }
        self.assertEqual(get_cross_domain_universe_uids(universe), {uid_a, uid_b})

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(get_cross_domain_universe_uids({}), set())


# ---------------------------------------------------------------------------
# 11. Rule table sanity
# ---------------------------------------------------------------------------

class TestRuleTableSanity(unittest.TestCase):
    def test_all_rules_have_domain(self) -> None:
        for rule in CROSS_DOMAIN_FAMILY_RULES:
            self.assertTrue(rule.domain, f"{rule.family} has empty domain")

    def test_all_paks_in_scope(self) -> None:
        for rule in CROSS_DOMAIN_FAMILY_RULES:
            for pak in rule.paks:
                self.assertIn(pak, CROSS_DOMAIN_SCOPE_PAKS, f"{rule.family} references out-of-scope pak {pak!r}")

    def test_stats_rules_have_field_re(self) -> None:
        for rule in CROSS_DOMAIN_FAMILY_RULES:
            if ".txt" in rule.formats:
                self.assertIsNotNone(rule.field_re, f"{rule.family} must have field_re")

    def test_unique_families(self) -> None:
        families = [r.family for r in CROSS_DOMAIN_FAMILY_RULES]
        self.assertEqual(len(families), len(set(families)))


# ---------------------------------------------------------------------------
# 12. extract_cross_domain_target_universe — mocked plumbing
# ---------------------------------------------------------------------------

class TestExtractCrossDomainTargetUniverse(unittest.TestCase):
    def _ctx(self) -> CrossDomainExtractionContext:
        return CrossDomainExtractionContext(
            game_dir=Path("/fake"), backend=MagicMock(), resources=[],
            build_id="b0", game_version="0.0", scan_manifest_sha256="0" * 64,
        )

    def test_returns_dict(self) -> None:
        ctx = self._ctx()
        with patch("bg3loc.research.cross_domain_universe._run_extraction", return_value={}) as m:
            result = extract_cross_domain_target_universe(ctx)
        self.assertIsInstance(result, dict)
        m.assert_called_once()

    def test_cache_prevents_second_run(self) -> None:
        ctx = self._ctx()
        cache = CrossDomainUniverseCache()
        uid = _uid(9999)
        pre = {uid: CrossDomainTarget(contentUid=uid, domain="D", provider="p", internalPath="i", entity="e", field="f")}
        cache.put(ctx.cache_key(), pre)
        with patch("bg3loc.research.cross_domain_universe._run_extraction") as m:
            result = extract_cross_domain_target_universe(ctx, cache=cache)
        m.assert_not_called()
        self.assertIs(result, pre)

    def test_result_stored_in_cache(self) -> None:
        ctx = self._ctx()
        cache = CrossDomainUniverseCache()
        uid = _uid(8888)
        fake = {uid: CrossDomainTarget(contentUid=uid, domain="D", provider="p", internalPath="i", entity="e", field="f")}
        with patch("bg3loc.research.cross_domain_universe._run_extraction", return_value=fake):
            extract_cross_domain_target_universe(ctx, cache=cache)
        self.assertIs(cache.get(ctx.cache_key()), fake)

    def test_no_cache_always_runs(self) -> None:
        ctx = self._ctx()
        with patch("bg3loc.research.cross_domain_universe._run_extraction", return_value={}) as m:
            extract_cross_domain_target_universe(ctx, cache=None)
            extract_cross_domain_target_universe(ctx, cache=None)
        self.assertEqual(m.call_count, 2)


# ---------------------------------------------------------------------------
# 11. Entity-Level Provider Materialization & Inheritance Tests
# ---------------------------------------------------------------------------

class TestCrossDomainEntityMaterialization(unittest.TestCase):
    def test_parent_in_shared_overridden_in_patch_child_in_gustav(self) -> None:
        """Section 5: Parent in Shared, Parent overridden in Patch, Child in Gustav
        Child using Parent -> Child must inherit from effective Patch Parent."""
        uid_shared = _uid(1)
        uid_patch = _uid(2)

        parent_shared = _StatEntryRecord(
            name="Parent",
            using="",
            explicit_fields={"DisplayName": uid_shared},
            pak_name="Shared.pak",
            internal_path="Public/Shared/Stats/Generated/Data/Armor.txt",
            domain="Armor",
            priority=compute_provider_priority("Shared.pak", "Public/Shared/..."),
            entry_index=0,
        )
        parent_patch = _StatEntryRecord(
            name="Parent",
            using="",
            explicit_fields={"DisplayName": uid_patch},
            pak_name="Patch8_HotFix9.pak",
            internal_path="Public/Patch/Stats/Generated/Data/Armor.txt",
            domain="Armor",
            priority=compute_provider_priority("Patch8_HotFix9.pak", "Public/Patch/..."),
            entry_index=0,
        )
        child_gustav = _StatEntryRecord(
            name="Child",
            using="Parent",
            explicit_fields={},
            pak_name="Gustav.pak",
            internal_path="Public/Gustav/Stats/Generated/Data/Armor.txt",
            domain="Armor",
            priority=compute_provider_priority("Gustav.pak", "Public/Gustav/..."),
            entry_index=0,
        )

        raw_entries = [parent_shared, child_gustav, parent_patch]
        relations, audit_recs, counts = _materialize_stats_entities(raw_entries)

        child_inherited = [r for r in relations if r.entity == "Child"]
        self.assertEqual(len(child_inherited), 1)
        rel = child_inherited[0]
        self.assertEqual(rel.contentUid, uid_patch)
        self.assertEqual(rel.field, "DisplayName")
        self.assertEqual(rel.inheritedFrom, "Parent")
        self.assertEqual(rel.inheritanceDepth, 1)
        self.assertEqual(rel.explicitOrInherited, "inherited")
        self.assertEqual(rel.effectiveProvider, "Gustav.pak")
        self.assertEqual(rel.definingProvider, "Patch8_HotFix9.pak")
        self.assertTrue(rel.providerOverrideApplied)

    def test_child_override(self) -> None:
        """Child explicitly defining a field overrides parent's field."""
        uid_parent_name = _uid(11)
        uid_parent_desc = _uid(12)
        uid_child_name = _uid(13)

        parent = _StatEntryRecord(
            name="P",
            using="",
            explicit_fields={"DisplayName": uid_parent_name, "Description": uid_parent_desc},
            pak_name="Shared.pak",
            internal_path="path.txt",
            domain="D",
            priority=10,
        )
        child = _StatEntryRecord(
            name="C",
            using="P",
            explicit_fields={"DisplayName": uid_child_name},
            pak_name="Gustav.pak",
            internal_path="path.txt",
            domain="D",
            priority=20,
        )

        relations, _, _ = _materialize_stats_entities([parent, child])
        child_rels = {r.field: r for r in relations if r.entity == "C"}
        self.assertEqual(len(child_rels), 2)
        self.assertEqual(child_rels["DisplayName"].contentUid, uid_child_name)
        self.assertEqual(child_rels["DisplayName"].explicitOrInherited, "explicit")
        self.assertEqual(child_rels["DisplayName"].inheritanceDepth, 0)
        self.assertEqual(child_rels["Description"].contentUid, uid_parent_desc)
        self.assertEqual(child_rels["Description"].explicitOrInherited, "inherited")
        self.assertEqual(child_rels["Description"].inheritanceDepth, 1)

    def test_multi_level_inheritance_across_providers(self) -> None:
        """GrandParent in Shared -> Parent in Gustav -> Child in Patch."""
        uid_gp = _uid(21)
        uid_p = _uid(22)

        gp = _StatEntryRecord(
            name="GP",
            using="",
            explicit_fields={"DisplayName": uid_gp},
            pak_name="Shared.pak",
            internal_path="Shared.txt",
            domain="D",
            priority=10,
        )
        p = _StatEntryRecord(
            name="P",
            using="GP",
            explicit_fields={"Description": uid_p},
            pak_name="Gustav.pak",
            internal_path="Gustav.txt",
            domain="D",
            priority=20,
        )
        c = _StatEntryRecord(
            name="C",
            using="P",
            explicit_fields={},
            pak_name="Patch8_HotFix9.pak",
            internal_path="Patch.txt",
            domain="D",
            priority=40,
        )

        relations, _, _ = _materialize_stats_entities([gp, p, c])
        c_rels = {r.field: r for r in relations if r.entity == "C"}
        self.assertEqual(c_rels["DisplayName"].contentUid, uid_gp)
        self.assertEqual(c_rels["DisplayName"].definingProvider, "Shared.pak")
        self.assertEqual(c_rels["DisplayName"].inheritanceDepth, 2)
        self.assertEqual(c_rels["Description"].contentUid, uid_p)
        self.assertEqual(c_rels["Description"].definingProvider, "Gustav.pak")
        self.assertEqual(c_rels["Description"].inheritanceDepth, 1)

    def test_missing_parent(self) -> None:
        """Child referencing nonexistent parent emits its own fields without crashing."""
        uid_c = _uid(31)
        child = _StatEntryRecord(
            name="Orphan",
            using="GhostParent",
            explicit_fields={"DisplayName": uid_c},
            pak_name="Shared.pak",
            internal_path="Shared.txt",
            domain="D",
            priority=10,
        )
        relations, _, counts = _materialize_stats_entities([child])
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0].contentUid, uid_c)
        self.assertEqual(counts["missing_parents"], 1)

    def test_cycles_handling(self) -> None:
        """Mutual inheritance A -> B -> A is broken cleanly with cycle detection."""
        uid_a = _uid(41)
        uid_b = _uid(42)
        a = _StatEntryRecord(
            name="A", using="B", explicit_fields={"DisplayName": uid_a},
            pak_name="Shared.pak", internal_path="f.txt", domain="D", priority=10,
        )
        b = _StatEntryRecord(
            name="B", using="A", explicit_fields={"Description": uid_b},
            pak_name="Shared.pak", internal_path="f.txt", domain="D", priority=10,
        )
        relations, _, counts = _materialize_stats_entities([a, b])
        self.assertTrue(counts["cycles_detected"] >= 1)
        self.assertTrue(len(relations) >= 2)

    def test_same_entity_in_different_files(self) -> None:
        """Same entity defined in two different internal paths resolved by priority and tie-breaker."""
        uid1 = _uid(51)
        uid2 = _uid(52)
        e1 = _StatEntryRecord(
            name="EntityShared", using="", explicit_fields={"DisplayName": uid1},
            pak_name="Shared.pak", internal_path="Public/Shared/FileA.txt", domain="D", priority=10, entry_index=0,
        )
        e2 = _StatEntryRecord(
            name="EntityShared", using="", explicit_fields={"DisplayName": uid2},
            pak_name="Shared.pak", internal_path="Public/Shared/FileB.txt", domain="D", priority=10, entry_index=0,
        )
        relations, audit_recs, counts = _materialize_stats_entities([e1, e2])
        self.assertEqual(counts["effective_entities"], 1)
        self.assertEqual(counts["multi_provider_entities"], 1)
        # Lexicographical tie-breaker: FileB > FileA
        effective_audit = [a for a in audit_recs if a.selectedAsEffective][0]
        self.assertEqual(effective_audit.internalPath, "Public/Shared/FileB.txt")

    def test_same_entity_in_different_packages(self) -> None:
        """Entity defined in Shared, Gustav, Patch selects Patch as effective."""
        uid_s = _uid(61)
        uid_g = _uid(62)
        uid_p = _uid(63)
        es = _StatEntryRecord(name="E", using="", explicit_fields={"DisplayName": uid_s}, pak_name="Shared.pak", internal_path="s.txt", domain="D", priority=10)
        eg = _StatEntryRecord(name="E", using="", explicit_fields={"DisplayName": uid_g}, pak_name="Gustav.pak", internal_path="g.txt", domain="D", priority=20)
        ep = _StatEntryRecord(name="E", using="", explicit_fields={"DisplayName": uid_p}, pak_name="Patch8_HotFix9.pak", internal_path="p.txt", domain="D", priority=40)

        relations, audit, counts = _materialize_stats_entities([es, eg, ep])
        self.assertEqual(counts["effective_entities"], 1)
        effective = [a for a in audit if a.selectedAsEffective][0]
        self.assertEqual(effective.provider, "Patch8_HotFix9.pak")
        self.assertEqual(effective.overrideReason, "HigherProviderPriority")

        superceded = [a for a in audit if not a.selectedAsEffective]
        self.assertEqual(len(superceded), 2)
        for s in superceded:
            self.assertEqual(s.overrideReason, "SupercededByHigherProviderPriority")

    def test_static_determinism_input_order(self) -> None:
        """Section 8: Static determinism test
        Run extraction twice with the same synthetic entity definitions in different input order.
        Expected: same effective entity graph, same inherited relations, same UID universe."""
        uid1 = _uid(71)
        uid2 = _uid(72)
        uid3 = _uid(73)
        uid4 = _uid(74)

        e1 = _StatEntryRecord(name="A", using="", explicit_fields={"DisplayName": uid1}, pak_name="Shared.pak", internal_path="a.txt", domain="D", priority=10, entry_index=0)
        e2 = _StatEntryRecord(name="A", using="", explicit_fields={"DisplayName": uid2}, pak_name="Patch8_HotFix9.pak", internal_path="a.txt", domain="D", priority=40, entry_index=0)
        e3 = _StatEntryRecord(name="B", using="A", explicit_fields={"Description": uid3}, pak_name="Gustav.pak", internal_path="b.txt", domain="D", priority=20, entry_index=0)
        e4 = _StatEntryRecord(name="C", using="B", explicit_fields={"Tooltip": uid4}, pak_name="GustavX.pak", internal_path="c.txt", domain="D", priority=30, entry_index=0)

        order1 = [e1, e2, e3, e4]
        order2 = [e4, e3, e2, e1]
        order3 = [e3, e1, e4, e2]

        rels1, audit1, counts1 = _materialize_stats_entities(order1)
        rels2, audit2, counts2 = _materialize_stats_entities(order2)
        rels3, audit3, counts3 = _materialize_stats_entities(order3)

        # 1. Same counts
        self.assertEqual(counts1, counts2)
        self.assertEqual(counts1, counts3)

        # 2. Same effective entity graph audit
        eff1 = [(a.entity, a.provider, a.priority, a.selectedAsEffective) for a in audit1]
        eff2 = [(a.entity, a.provider, a.priority, a.selectedAsEffective) for a in audit2]
        eff3 = [(a.entity, a.provider, a.priority, a.selectedAsEffective) for a in audit3]
        self.assertEqual(eff1, eff2)
        self.assertEqual(eff1, eff3)

        # 3. Same relations
        sig1 = [(r.contentUid, r.entity, r.field, r.inheritanceDepth, r.explicitOrInherited, r.definingProvider) for r in rels1]
        sig2 = [(r.contentUid, r.entity, r.field, r.inheritanceDepth, r.explicitOrInherited, r.definingProvider) for r in rels2]
        sig3 = [(r.contentUid, r.entity, r.field, r.inheritanceDepth, r.explicitOrInherited, r.definingProvider) for r in rels3]
        self.assertEqual(sig1, sig2)
        self.assertEqual(sig1, sig3)

        # 4. Same UID universe
        uids1 = set(r.contentUid for r in rels1)
        uids2 = set(r.contentUid for r in rels2)
        uids3 = set(r.contentUid for r in rels3)
        self.assertEqual(uids1, uids2)
        self.assertEqual(uids1, uids3)


# ---------------------------------------------------------------------------
# 12. Cross-Domain Coverage Expansion & Classification Tests
# ---------------------------------------------------------------------------

class TestRootTemplatesFieldExpansion(unittest.TestCase):
    """Test RootTemplates expanded semantic fields and GameMasterSpawnSubSection compatibility classification."""

    def setUp(self) -> None:
        self.rule = next(r for r in CROSS_DOMAIN_FAMILY_RULES if r.family == "RootTemplatesLSX")

    def test_expanded_semantic_fields_extracted_as_semantic_target(self) -> None:
        """OnUseDescription, DisplayNameAlchemy, TechnicalDescription, UnknownDescription, UnknownDisplayName
        must be extracted and classified as SemanticTarget."""
        u_disp = _uid(101)
        u_onuse = _uid(102)
        u_alchemy = _uid(103)
        u_tech = _uid(104)
        u_unk_desc = _uid(105)
        u_unk_name = _uid(106)
        u_unrelated = _uid(107)

        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
          <region id="Templates">
            <node id="GameObjects">
              <children>
                <node id="GameObjects">
                  <attribute id="DisplayName" type="TranslatedString" handle="{u_disp}" />
                  <attribute id="OnUseDescription" type="TranslatedString" handle="{u_onuse}" />
                  <attribute id="DisplayNameAlchemy" type="TranslatedString" handle="{u_alchemy}" />
                  <attribute id="TechnicalDescription" type="TranslatedString" handle="{u_tech}" />
                  <attribute id="UnknownDescription" type="TranslatedString" handle="{u_unk_desc}" />
                  <attribute id="UnknownDisplayName" type="TranslatedString" handle="{u_unk_name}" />
                  <attribute id="UnrelatedNonLocalized" type="TranslatedString" handle="{u_unrelated}" />
                </node>
              </children>
            </node>
          </region>
        </save>
        """
        rels = list(_extract_from_lsx_xml(
            xml,
            pak_name="Shared.pak",
            internal_path="Public/Shared/RootTemplates/_merged.lsf",
            domain=self.rule.domain,
            field_re=self.rule.field_re,
            classification=self.rule.classification,
        ))
        rel_map = {r.contentUid: r for r in rels}

        # All 6 semantic fields must be extracted
        for u in (u_disp, u_onuse, u_alchemy, u_tech, u_unk_desc, u_unk_name):
            self.assertIn(u, rel_map)
            self.assertEqual(rel_map[u].classification, "SemanticTarget")
            self.assertEqual(rel_map[u].domain, "GameObjectDescription")

        # Specific field names preserved
        self.assertEqual(rel_map[u_onuse].field, "OnUseDescription")
        self.assertEqual(rel_map[u_alchemy].field, "DisplayNameAlchemy")
        self.assertEqual(rel_map[u_tech].field, "TechnicalDescription")
        self.assertEqual(rel_map[u_unk_desc].field, "UnknownDescription")
        self.assertEqual(rel_map[u_unk_name].field, "UnknownDisplayName")

        # Unrelated attribute filtered out
        self.assertNotIn(u_unrelated, rel_map)

    def test_gamemaster_spawn_subsection_classified_as_historical_compatibility(self) -> None:
        """GameMasterSpawnSubSection must be extracted and explicitly classified as HistoricalCompatibilityReference."""
        u_gm = _uid(108)
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
          <region id="Templates">
            <node id="GameObjects">
              <children>
                <node id="GameObjects">
                  <children>
                    <node id="GameMaster">
                      <attribute id="GameMasterSpawnSubSection" type="TranslatedString" handle="{u_gm}" />
                    </node>
                  </children>
                </node>
              </children>
            </node>
          </region>
        </save>
        """
        rels = list(_extract_from_lsx_xml(
            xml,
            pak_name="Shared.pak",
            internal_path="Public/Shared/RootTemplates/_merged.lsf",
            domain=self.rule.domain,
            field_re=self.rule.field_re,
            classification=self.rule.classification,
        ))
        self.assertEqual(len(rels), 1)
        rel = rels[0]
        self.assertEqual(rel.contentUid, u_gm)
        self.assertEqual(rel.field, "GameMasterSpawnSubSection")
        self.assertEqual(rel.classification, "HistoricalCompatibilityReference")


class TestProgressionDescriptionsExtraction(unittest.TestCase):
    """Test dedicated ProgressionDescriptions family rule and extraction."""

    def test_progression_descriptions_rule_selection(self) -> None:
        r1 = ResearchScanResource(
            pakName="Gustav.pak",
            internalPath="Public/GustavDev/Localization/ProgressionDescriptions_Description.lsf",
            resourceFormat="LSF",
            sourceRole="LocalizationRegistry",
            size=1584,
        )
        r2 = ResearchScanResource(
            pakName="Gustav.pak",
            internalPath="Public/GustavDev/Localization/ProgressionDescriptions_DisplayName.lsf",
            resourceFormat="LSF",
            sourceRole="LocalizationRegistry",
            size=1584,
        )
        selected = select_cross_domain_resources([r1, r2])
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][0].family, "ProgressionDescriptionsLSX")
        self.assertEqual(selected[0][0].domain, "ProgressionUI")
        self.assertEqual(selected[0][0].classification, "SemanticTarget")
        self.assertEqual(selected[1][0].family, "ProgressionDescriptionsLSX")

    def test_progression_descriptions_content_extraction(self) -> None:
        rule = next(r for r in CROSS_DOMAIN_FAMILY_RULES if r.family == "ProgressionDescriptionsLSX")
        u1 = _uid(201)
        u2 = _uid(202)
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
          <region id="TranslatedStringKeys">
            <node id="TranslatedStringKeys">
              <children>
                <node id="TranslatedStringKey">
                  <attribute id="Content" type="TranslatedString" handle="{u1}" version="1" />
                  <attribute id="UUID" type="FixedString" value="Progression_01" />
                </node>
                <node id="TranslatedStringKey">
                  <attribute id="Content" type="TranslatedString" handle="{u2}" version="1" />
                  <attribute id="UUID" type="FixedString" value="Progression_02" />
                </node>
              </children>
            </node>
          </region>
        </save>
        """
        rels = list(_extract_from_lsx_xml(
            xml,
            pak_name="Gustav.pak",
            internal_path="Public/GustavDev/Localization/ProgressionDescriptions_Description.lsf",
            domain=rule.domain,
            field_re=rule.field_re,
            classification=rule.classification,
        ))
        self.assertEqual(len(rels), 2)
        for r in rels:
            self.assertEqual(r.classification, "SemanticTarget")
            self.assertEqual(r.domain, "ProgressionUI")
            self.assertEqual(r.field, "Content")
            self.assertEqual(r.entity, "TranslatedStringKey")
        uids = {r.contentUid for r in rels}
        self.assertEqual(uids, {u1, u2})


class TestGamePakUIXaml(unittest.TestCase):
    """Test Game.pak inclusion for UI XAML and exclusion for non-UI resources."""

    def test_game_pak_ui_xaml_included(self) -> None:
        r1 = ResearchScanResource(
            pakName="Game.pak",
            internalPath="Mods/MainUI/GUI/Pages/Options.xaml",
            resourceFormat="XAML",
            sourceRole="UiResource",
            size=1000,
        )
        r2 = ResearchScanResource(
            pakName="Game.pak",
            internalPath="Public/Game/GUI/Library/Tooltips.xaml",
            resourceFormat="XAML",
            sourceRole="UiResource",
            size=2000,
        )
        selected = select_cross_domain_resources([r1, r2])
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][0].family, "UIXaml")
        self.assertEqual(selected[0][0].domain, "UserInterface")
        self.assertEqual(selected[0][0].classification, "SemanticTarget")

    def test_game_pak_non_ui_excluded(self) -> None:
        """Non-UI resources in Game.pak must NOT be selected by any Cross-Domain rule."""
        non_ui_res = [
            ResearchScanResource(pakName="Game.pak", internalPath="Public/Game/Stats/Generated/Data/Stats.txt", resourceFormat="TXT", sourceRole="StatsResource", size=100),
            ResearchScanResource(pakName="Game.pak", internalPath="Mods/Game/Story/Dialogs/test.lsf", resourceFormat="LSF", sourceRole="DialogResource", size=100),
            ResearchScanResource(pakName="Game.pak", internalPath="Public/Game/RootTemplates/_merged.lsf", resourceFormat="LSF", sourceRole="RootTemplates", size=100),
        ]
        selected = select_cross_domain_resources(non_ui_res)
        self.assertEqual(selected, [])

    def test_game_pak_xaml_extraction(self) -> None:
        u_xaml = _uid(301)
        xaml_text = f"""<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
            <TextBlock Text="{u_xaml}" />
        </ResourceDictionary>"""
        rels = list(_extract_from_xaml(
            xaml_text,
            pak_name="Game.pak",
            internal_path="Mods/MainUI/GUI/Pages/AccessibilityOptions.xaml",
            domain="UserInterface",
            classification="SemanticTarget",
        ))
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].contentUid, u_xaml)
        self.assertEqual(rels[0].domain, "UserInterface")
        self.assertEqual(rels[0].classification, "SemanticTarget")
        self.assertEqual(rels[0].effectiveProvider, "Game.pak")


class TestDialogsBinaryHistorical(unittest.TestCase):
    """Test historical keyword-heuristic DialogsBinary selection and compatibility classification."""

    def test_dialogs_binary_historical_rule_selection(self) -> None:
        r1 = ResearchScanResource(
            pakName="Gustav.pak",
            internalPath="Mods/GustavDev/Story/DialogsBinary/Act2/Colony/COL_BrainReader_Memory_TutorialDark.lsf",
            resourceFormat="LSF",
            sourceRole="DialogsBinary",
            size=5727,
        )
        r2 = ResearchScanResource(
            pakName="Gustav.pak",
            internalPath="Mods/GustavDev/Story/DialogsBinary/Act2/Shar/SHA_VoiceOfShar_AD_ProgressionCommentary.lsf",
            resourceFormat="LSF",
            sourceRole="DialogsBinary",
            size=5125,
        )
        # Normal Act 1 or non-matching dialog should NOT be selected
        r3 = ResearchScanResource(
            pakName="Gustav.pak",
            internalPath="Mods/GustavDev/Story/DialogsBinary/Act1/NormalDialog.lsf",
            resourceFormat="LSF",
            sourceRole="DialogsBinary",
            size=4000,
        )
        selected = select_cross_domain_resources([r1, r2, r3])
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][0].family, "DialogsBinaryHistorical")
        self.assertEqual(selected[0][0].classification, "HistoricalCompatibilityReference")
        self.assertEqual(selected[1][0].family, "DialogsBinaryHistorical")
        self.assertEqual(selected[1][0].classification, "HistoricalCompatibilityReference")

    def test_dialogs_binary_tagtext_extraction(self) -> None:
        rule = next(r for r in CROSS_DOMAIN_FAMILY_RULES if r.family == "DialogsBinaryHistorical")
        u1 = _uid(401)
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
          <region id="dialog">
            <node id="dialog">
              <children>
                <node id="TaggedTexts">
                  <children>
                    <node id="TaggedText">
                      <attribute id="TagText" type="TranslatedString" handle="{u1}" />
                    </node>
                  </children>
                </node>
              </children>
            </node>
          </region>
        </save>
        """
        rels = list(_extract_from_lsx_xml(
            xml,
            pak_name="Gustav.pak",
            internal_path="Mods/GustavDev/Story/DialogsBinary/Act2/Colony/COL_BrainReader_Memory_TutorialDark.lsf",
            domain=rule.domain,
            field_re=rule.field_re,
            classification=rule.classification,
        ))
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].contentUid, u1)
        self.assertEqual(rels[0].classification, "HistoricalCompatibilityReference")
        self.assertEqual(rels[0].field, "TagText")


class TestSemanticVsCompatibilitySeparation(unittest.TestCase):
    """Test separate tracking of SemanticTarget vs HistoricalCompatibilityReference."""

    def test_properties_and_reproduction_universe_union(self) -> None:
        u_sem1 = _uid(501)
        u_sem2 = _uid(502)
        u_hist = _uid(503)

        t1 = CrossDomainTarget(contentUid=u_sem1, domain="D1", provider="P1", internalPath="I1", entity="E1", field="F1", classification="SemanticTarget")
        t2 = CrossDomainTarget(contentUid=u_sem2, domain="D2", provider="P2", internalPath="I2", entity="E2", field="F2", classification="SemanticTarget")
        t3 = CrossDomainTarget(contentUid=u_hist, domain="D3", provider="P3", internalPath="I3", entity="E3", field="F3", classification="HistoricalCompatibilityReference")

        res = CrossDomainExtractionResult(
            targets_by_uid={u_sem1: t1, u_sem2: t2, u_hist: t3}
        )
        self.assertEqual(res.semantic_target_uids, {u_sem1, u_sem2})
        self.assertEqual(res.historical_compatibility_uids, {u_hist})
        self.assertTrue(res.semantic_target_uids.isdisjoint(res.historical_compatibility_uids))
        self.assertEqual(res.reproduction_universe_uids, {u_sem1, u_sem2, u_hist})
        self.assertEqual(res.reproduction_universe_uids, res.semantic_target_uids | res.historical_compatibility_uids)
        self.assertEqual(res.unique_uids, res.reproduction_universe_uids)

    def test_cross_domain_derivation_with_reproduction_universe(self) -> None:
        from bg3loc.research.story import derive_cross_domain_references

        u_existing = _uid(601)
        u_sem_overlap = _uid(602)
        u_hist_overlap = _uid(603)
        u_story_only = _uid(604)
        u_cross_only = _uid(605)

        story_universe = {u_existing, u_sem_overlap, u_hist_overlap, u_story_only}
        existing_authority = {u_existing}

        t_sem = CrossDomainTarget(contentUid=u_sem_overlap, domain="D", provider="P", internalPath="I", entity="E", field="F", classification="SemanticTarget")
        t_hist = CrossDomainTarget(contentUid=u_hist_overlap, domain="D", provider="P", internalPath="I", entity="E", field="F", classification="HistoricalCompatibilityReference")
        t_other = CrossDomainTarget(contentUid=u_cross_only, domain="D", provider="P", internalPath="I", entity="E", field="F", classification="SemanticTarget")

        res = CrossDomainExtractionResult(
            targets_by_uid={u_sem_overlap: t_sem, u_hist_overlap: t_hist, u_cross_only: t_other}
        )

        cross_domain_reproduction = derive_cross_domain_references(
            story_universe,
            res.reproduction_universe_uids,
            existing_383_uids=existing_authority,
        )
        cross_domain_semantic = (story_universe & res.semantic_target_uids) - existing_authority
        cross_domain_historical = (story_universe & res.historical_compatibility_uids) - existing_authority

        self.assertEqual(cross_domain_semantic, {u_sem_overlap})
        self.assertEqual(cross_domain_historical, {u_hist_overlap})
        self.assertEqual(cross_domain_reproduction, {u_sem_overlap, u_hist_overlap})
        self.assertEqual(cross_domain_reproduction, cross_domain_semantic | cross_domain_historical)


if __name__ == "__main__":
    unittest.main()
