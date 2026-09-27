from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.cli import main
from bg3loc.e2e.config import ProjectConfigError, load_project_config, resolved_structural_reviews
from bg3loc.e2e.state import new_state, state_path


class E2EProjectConfigTests(unittest.TestCase):
    def write_project(self, root: Path, data: dict) -> Path:
        path = root / "bg3loc-project.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def base_project(self) -> dict:
        return {
            "schemaVersion": "1.0",
            "project": {"name": "fixture"},
            "locales": {"source": "English", "target": "French"},
            "workflow": {"evidenceProfile": "basic", "translationStrategy": "standard"},
        }

    def test_defaults_and_relative_paths_resolve_from_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_project(root, self.base_project())
            config = load_project_config(path)
            self.assertEqual(config.effective["locales"]["references"], [])
            self.assertEqual(config.effective["material"]["format"], "xlsx")
            self.assertIsNone(config.effective["scope"]["contentUids"])
            self.assertEqual(
                Path(config.resolved["workspace"]["root"]),
                (root / "workspace").resolve(strict=False),
            )
            self.assertEqual(resolved_structural_reviews(config), [])

    def test_source_target_and_reference_semantics_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            same = self.base_project()
            same["locales"]["target"] = "english"
            path = self.write_project(root, same)
            with self.assertRaises(ProjectConfigError):
                load_project_config(path)

            refs = self.base_project()
            refs["locales"]["references"] = ["French"]
            path.write_text(json.dumps(refs), encoding="utf-8")
            with self.assertRaises(ProjectConfigError):
                load_project_config(path)

    def test_full_profile_default_reviews_and_typed_qa_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.base_project()
            data["workflow"]["evidenceProfile"] = "full"
            data["qa"] = {
                "ruleSets": [
                    {"id": "terminology", "type": "taiwan-usage", "path": "rules/a.json"},
                    {"id": "style", "type": "taiwan-usage", "path": "rules/b.json"},
                ]
            }
            path = self.write_project(root, data)
            config = load_project_config(path)
            self.assertEqual(
                resolved_structural_reviews(config),
                ["bark", "quest", "ui-skill", "multilingual"],
            )
            self.assertEqual(
                Path(config.resolved["qa"]["ruleSets"][0]["path"]),
                (root / "rules" / "a.json").resolve(strict=False),
            )

    def test_non_full_explicit_structural_reviews_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.base_project()
            data["reviews"] = {"structural": ["bark"]}
            path = self.write_project(root, data)
            with self.assertRaises(ProjectConfigError):
                load_project_config(path)

    def test_state_initialization_binds_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_project(root, self.base_project())
            config = load_project_config(path)
            state = new_state(config)
            self.assertEqual(state["stages"]["config"]["status"], "completed")
            self.assertEqual(state["stages"]["scan"]["status"], "ready")
            self.assertEqual(state["projectConfigSha256"], config.sha256)
            self.assertEqual(state_path(config), root / "workspace" / "e2e" / "workflow-state.json")

    def test_project_init_check_and_status_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.json"
            self.assertEqual(main([
                "project", "init",
                "--name", "fixture-project",
                "--source", "English",
                "--target", "French",
                "--output", str(project),
            ]), 0)
            self.assertTrue(project.is_file())
            self.assertEqual(main(["project", "check", "--project", str(project)]), 0)
            self.assertEqual(main(["workflow", "status", "--project", str(project)]), 0)

    def test_project_init_supports_references_and_material_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.json"
            self.assertEqual(main([
                "project", "init",
                "--name", "fixture-project",
                "--source", "English",
                "--target", "French",
                "--reference", "German",
                "--evidence-profile", "context",
                "--translation-strategy", "blind-first",
                "--format", "jsonl",
                "--workspace", "private-workspace",
                "--output", str(project),
            ]), 0)
            config = load_project_config(project)
            self.assertEqual(config.effective["locales"]["references"], ["German"])
            self.assertEqual(config.effective["workflow"]["evidenceProfile"], "context")
            self.assertEqual(config.effective["workflow"]["translationStrategy"], "blind-first")
            self.assertEqual(config.effective["material"]["format"], "jsonl")
            self.assertEqual(
                Path(config.resolved["workspace"]["root"]),
                (root / "private-workspace").resolve(strict=False),
            )

    def test_project_init_supports_content_uid_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.json"
            uid = "h11111111g2222g3333g4444g555555555555"
            self.assertEqual(main([
                "project", "init",
                "--name", "fixture-project",
                "--source", "English",
                "--target", "French",
                "--content-uid", uid,
                "--output", str(project),
            ]), 0)
            config = load_project_config(project)
            self.assertEqual(config.effective["scope"]["contentUids"], [uid])

    def test_full_profile_rejects_content_uid_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = self.base_project()
            data["workflow"]["evidenceProfile"] = "full"
            data["scope"] = {
                "contentUids": ["h11111111g2222g3333g4444g555555555555"]
            }
            path = self.write_project(root, data)
            with self.assertRaises(ProjectConfigError):
                load_project_config(path)

    def test_project_init_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(main([
                "project", "init",
                "--name", "fixture-project",
                "--source", "English",
                "--target", "French",
                "--output", str(path),
            ]), 71)


if __name__ == "__main__":
    unittest.main()
