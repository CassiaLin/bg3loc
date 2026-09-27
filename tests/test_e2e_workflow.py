from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.e2e.config import load_project_config
from bg3loc.e2e.prepare import WorkflowPrepareError, run_prepare


class E2EWorkflowPrepareTests(unittest.TestCase):
    def make_project(self, root: Path, profile: str = "basic", strategy: str = "standard") -> Path:
        path = root / "bg3loc-project.json"
        path.write_text(json.dumps({
            "schemaVersion": "1.0",
            "project": {"name": "fixture"},
            "game": {"installDir": str(root / "game")},
            "locales": {"source": "English", "target": "French", "references": []},
            "workflow": {"evidenceProfile": profile, "translationStrategy": strategy},
            "reviews": {"structural": "profile-default"},
            "qa": {"ruleSets": []},
            "inputs": {"glossary": None},
            "material": {"format": "jsonl", "maxRowsPerFile": 100},
            "workspace": {"root": "workspace"},
        }), encoding="utf-8")
        return path

    def fake_extract(self, request):
        request.output.mkdir(parents=True, exist_ok=True)
        (request.output / "extract-manifest.json").write_text("{}", encoding="utf-8")
        return {}

    def fake_package(self, **kwargs):
        out = kwargs["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "translation-package-manifest.json").write_text("{}", encoding="utf-8")
        return {}

    def test_basic_prepare_checkpoints_and_reuses_completed_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            scan_manifest = {
                "game": {"installPath": str(root / "game")},
            }
            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest) as scan,
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract),
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package) as package,
            ):
                state = run_prepare(config)
                self.assertEqual(state["currentStage"], "translate")
                self.assertEqual(state["stages"]["package"]["status"], "completed")
                self.assertEqual(state["stages"]["translate"]["status"], "ready")
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(package.call_count, 1)

                again = run_prepare(config)
                self.assertEqual(again["currentStage"], "translate")
                # Prepare re-probes scan evidence to detect a changed game install,
                # but reuses downstream artifacts when the fingerprint is unchanged.
                self.assertEqual(scan.call_count, 2)
                self.assertEqual(package.call_count, 1)

    def test_context_prepare_uses_neighbor_context_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root, profile="context")
            config = load_project_config(project)
            scan_manifest = {"game": {"installPath": str(root / "game")}}

            def fake_context(_extract, output):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("", encoding="utf-8")
                return output

            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest),
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract),
                patch("bg3loc.e2e.prepare.build_neighbor_context", side_effect=fake_context) as context,
                patch("bg3loc.e2e.prepare.run_research_scan_request") as research_scan,
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package),
            ):
                state = run_prepare(config)
                self.assertEqual(state["currentStage"], "translate")
                context.assert_called_once()
                research_scan.assert_not_called()

    def test_full_prepare_runs_research_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root, profile="full", strategy="blind-first")
            config = load_project_config(project)
            scan_manifest = {"game": {"installPath": str(root / "game")}}

            def fake_research_scan(request):
                request.output.parent.mkdir(parents=True, exist_ok=True)
                request.output.write_text("{}", encoding="utf-8")
                return 0

            def fake_research_map(request):
                request.output_dir.mkdir(parents=True, exist_ok=True)
                (request.output_dir / "research-summary.json").write_text("{}", encoding="utf-8")
                (request.output_dir / "research-mappings.jsonl").write_text("", encoding="utf-8")
                return 0

            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest),
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract),
                patch("bg3loc.e2e.prepare.run_research_scan_request", side_effect=fake_research_scan) as rscan,
                patch("bg3loc.e2e.prepare.run_research_map_request", side_effect=fake_research_map) as rmap,
                patch("bg3loc.e2e.prepare.research_evidence_sidecars", return_value={}),
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package),
            ):
                state = run_prepare(config)
                self.assertEqual(state["currentStage"], "translate")
                rscan.assert_called_once()
                rmap.assert_called_once()

    def test_changed_config_invalidates_and_reprepares(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            scan_manifest = {"game": {"installPath": str(root / "game")}}

            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest),
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract) as extract,
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package) as package,
            ):
                first = run_prepare(config)
                self.assertEqual(first["stages"]["package"]["status"], "completed")

                data = json.loads(project.read_text(encoding="utf-8"))
                data["workflow"]["translationStrategy"] = "blind-first"
                project.write_text(json.dumps(data), encoding="utf-8")
                changed = load_project_config(project)

                second = run_prepare(changed)
                self.assertEqual(second["projectConfigSha256"], changed.sha256)
                self.assertEqual(second["translationStrategy"], "blind-first")
                self.assertEqual(second["stages"]["package"]["status"], "completed")
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(package.call_count, 2)

    def test_qa_only_config_change_reuses_scan_extract_evidence_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            scan_manifest = {"game": {"installPath": str(root / "game")}}
            rules = root / "rules.json"
            rules.write_text("{}", encoding="utf-8")

            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest) as scan,
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract) as extract,
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package) as package,
            ):
                run_prepare(config)

                data = json.loads(project.read_text(encoding="utf-8"))
                data["qa"] = {
                    "ruleSets": [{
                        "id": "usage",
                        "type": "taiwan-usage",
                        "path": "rules.json",
                    }]
                }
                project.write_text(json.dumps(data), encoding="utf-8")
                changed = load_project_config(project)

                second = run_prepare(changed)
                self.assertEqual(second["projectConfigSha256"], changed.sha256)
                self.assertEqual(second["currentStage"], "translate")
                self.assertEqual(scan.call_count, 2)
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(package.call_count, 1)
                self.assertEqual(
                    second["stages"]["language-qa"]["status"],
                    "invalidated",
                )

    def test_changed_scan_evidence_invalidates_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            first_scan = {
                "game": {"installPath": str(root / "game"), "buildId": "1"},
            }
            second_scan = {
                "game": {"installPath": str(root / "game"), "buildId": "2"},
            }

            with (
                patch("bg3loc.e2e.state.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch(
                    "bg3loc.e2e.prepare.build_manifest",
                    side_effect=[first_scan, second_scan],
                ),
                patch("bg3loc.e2e.prepare.run_extract", side_effect=self.fake_extract) as extract,
                patch("bg3loc.e2e.prepare.prepare_translation_package", side_effect=self.fake_package) as package,
            ):
                run_prepare(config)
                second = run_prepare(config)
                self.assertEqual(second["stages"]["package"]["status"], "completed")
                self.assertEqual(extract.call_count, 2)
                self.assertEqual(package.call_count, 2)


if __name__ == "__main__":
    unittest.main()
