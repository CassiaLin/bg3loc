from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.e2e.config import load_project_config
from bg3loc.e2e.install import WorkflowInstallError, run_workflow_install
from bg3loc.e2e.package import prepare_translation_package, read_jsonl, sha256_file
from bg3loc.e2e.rebuild import run_workflow_rebuild
from bg3loc.e2e.prepare import _initialize_returns
from bg3loc.e2e.review import (
    _apply_manual_resolutions,
    _reconcile,
    integrate_reviews,
    prepare_reviews,
)
from bg3loc.e2e.state import new_state, state_path, write_state
from bg3loc.e2e.validate import WorkflowValidateError, _validate_final_target, run_validate


class E2EFlowTests(unittest.TestCase):
    UID = "h11111111g2222g3333g4444g555555555555"

    def make_extract(self, root: Path, *, reference: bool = True) -> Path:
        normalized = root / "normalized"
        normalized.mkdir(parents=True, exist_ok=True)
        (normalized / "English.jsonl").write_text(
            json.dumps({"contentUid": self.UID, "text": "Hello {name}", "version": 1}) + "\n",
            encoding="utf-8",
        )
        (normalized / "French.jsonl").write_text(
            json.dumps({"contentUid": self.UID, "text": "Bonjour {name}", "version": 2}) + "\n",
            encoding="utf-8",
        )
        if reference:
            (normalized / "German.jsonl").write_text(
                json.dumps({"contentUid": self.UID, "text": "Hallo {name}", "version": 3}) + "\n",
                encoding="utf-8",
            )

        locales = {
            "English": {"text": "Hello {name}", "version": 1},
            "French": {"text": "Bonjour {name}", "version": 2},
        }
        if reference:
            locales["German"] = {"text": "Hallo {name}", "version": 3}
        aligned = root / "aligned.jsonl"
        aligned.write_text(
            json.dumps({"contentUid": self.UID, "locales": locales}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        locale_entries = []
        for locale in locales:
            locale_entries.append({
                "localeId": locale,
                "packageFile": str(root / f"{locale}.pak"),
                "locaEntry": f"Localization/{locale}/{locale}.loca",
                "sourceLoca": str(root / f"{locale}.loca"),
                "sourceXml": str(root / f"{locale}.xml"),
                "normalized": str(normalized / f"{locale}.jsonl"),
                "nodeCount": 1,
            })

        manifest = {
            "schemaVersion": "1.0",
            "scanManifest": str(root / "scan-manifest.json"),
            "sourceLocale": "English",
            "targetLocale": "French",
            "referenceLocales": ["German"] if reference else [],
            "backend": {"id": "fixture"},
            "locales": locale_entries,
            "aligned": str(aligned),
            "roundtripValidation": str(root / "roundtrip.json"),
        }
        path = root / "extract-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def make_project(
        self,
        root: Path,
        *,
        profile: str = "basic",
        strategy: str = "standard",
        qa: list[dict] | None = None,
    ) -> Path:
        path = root / "bg3loc-project.json"
        path.write_text(json.dumps({
            "schemaVersion": "1.0",
            "project": {"name": "fixture"},
            "locales": {
                "source": "English",
                "target": "French",
                "references": [],
            },
            "workflow": {
                "evidenceProfile": profile,
                "translationStrategy": strategy,
            },
            "reviews": {"structural": "profile-default"},
            "qa": {"ruleSets": qa or []},
            "inputs": {"glossary": None},
            "material": {"format": "jsonl", "maxRowsPerFile": 100},
            "workspace": {"root": "workspace"},
        }), encoding="utf-8")
        return path

    def prepare_fixture_package(
        self,
        root: Path,
        *,
        strategy: str = "standard",
        reference: bool = True,
    ) -> tuple[Path, Path]:
        extract = self.make_extract(root, reference=reference)
        package_root = root / "package"
        prepare_translation_package(
            extract_manifest=extract,
            project_config_sha256="0" * 64,
            evidence_profile="basic",
            translation_strategy=strategy,
            material_format="jsonl",
            max_rows=100,
            output_dir=package_root,
        )
        return extract, package_root

    def test_blind_first_delivery_tree_contains_no_comparison_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, package_root = self.prepare_fixture_package(root, strategy="blind-first")
            row = read_jsonl(package_root / "delivery" / "materials" / "001.jsonl")[0]
            self.assertNotIn("ExistingTargetText", row)
            self.assertNotIn("ReferenceTexts", row)
            for path in (package_root / "delivery").rglob("*"):
                if path.is_file():
                    raw = path.read_bytes()
                    self.assertNotIn("Bonjour".encode("utf-8"), raw)
                    self.assertNotIn("Hallo".encode("utf-8"), raw)
            internal = (package_root / "internal" / "comparison" / "comparison.jsonl").read_text(encoding="utf-8")
            self.assertIn("Bonjour", internal)
            self.assertIn("Hallo", internal)

    def test_reprepare_replaces_entire_delivery_tree_for_blind_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract = self.make_extract(root / "extract", reference=True)
            package_root = root / "package"
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="0" * 64,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="csv",
                max_rows=100,
                output_dir=package_root,
            )
            self.assertTrue((package_root / "delivery" / "materials" / "001.csv").is_file())

            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="1" * 64,
                evidence_profile="basic",
                translation_strategy="blind-first",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
            )

            self.assertFalse((package_root / "delivery" / "materials" / "001.csv").exists())
            for path in (package_root / "delivery").rglob("*"):
                if path.is_file():
                    raw = path.read_bytes()
                    self.assertNotIn("Bonjour".encode("utf-8"), raw)
                    self.assertNotIn("Hallo".encode("utf-8"), raw)

    def test_qa_package_regenerates_when_translator_text_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "rules.json"
            rules.write_text(json.dumps({
                "schemaVersion": "1.0",
                "rules": [{
                    "ruleId": "SYN-001",
                    "kind": "literal",
                    "pattern": "bad",
                    "category": "Synthetic",
                    "rationale": "fixture",
                }],
            }), encoding="utf-8")
            project = self.make_project(
                root,
                qa=[{"id": "usage", "type": "taiwan-usage", "path": "rules.json"}],
            )
            config = load_project_config(project)
            extract = self.make_extract(root / "extract", reference=False)
            package_root = Path(config.resolved["workspace"]["root"]) / "e2e" / "package"
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256=config.sha256,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
            )
            package_manifest = package_root / "translation-package-manifest.json"
            returns = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
            _initialize_returns(package_manifest, package_root, returns)
            material = next(returns.glob("*.jsonl"))
            row = read_jsonl(material)[0]
            row["ProposedTargetText"] = "bad {name}"
            row["TranslationStatus"] = "translated"
            material.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            state = new_state(config)
            state["stages"]["package"].update({
                "status": "completed",
                "artifact": str(package_manifest),
                "sha256": sha256_file(package_manifest),
            })
            state["stages"]["translate"]["status"] = "ready"
            state["artifacts"]["translationPackage"] = str(package_manifest)
            state["artifacts"]["extractManifest"] = str(extract)
            state["bindings"]["translationPackageSha256"] = sha256_file(package_manifest)
            write_state(state_path(config), state)

            first = prepare_reviews(config, str(material))
            first_manifest = Path(first["path"]) / "usage" / "e2e-qa-manifest.json"
            first_data = json.loads(first_manifest.read_text(encoding="utf-8"))

            row["ProposedTargetText"] = "new bad {name}"
            material.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            second = prepare_reviews(config, str(material))
            second_manifest = Path(second["path"]) / "usage" / "e2e-qa-manifest.json"
            second_data = json.loads(second_manifest.read_text(encoding="utf-8"))

            self.assertNotEqual(first_data["baseTargetSha256"], second_data["baseTargetSha256"])
            review_csv = Path(second["path"]) / "usage" / "taiwan-usage-review.csv"
            with review_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["TargetText"], "new bad {name}")

    def test_scoped_package_contains_only_selected_content_uids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract = self.make_extract(root / "extract", reference=False)
            aligned = Path(json.loads(extract.read_text(encoding="utf-8"))["aligned"])
            second_uid = "h99999999g8888g7777g6666g555555555555"
            with aligned.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "contentUid": second_uid,
                    "locales": {
                        "English": {"text": "Second source", "version": 1},
                        "French": {"text": "Deuxième", "version": 1},
                    },
                }, ensure_ascii=False) + "\n")

            package_root = root / "package"
            manifest = prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="0" * 64,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
                scope_content_uids={self.UID},
            )

            rows = read_jsonl(package_root / "delivery" / "materials" / "001.jsonl")
            self.assertEqual([row["ContentUid"] for row in rows], [self.UID])
            self.assertEqual(manifest["counts"]["rows"], 1)
            self.assertEqual(manifest["counts"]["translationRequired"], 1)
            self.assertEqual(manifest["scope"]["type"], "content-uids")
            self.assertEqual(manifest["scope"]["contentUidCount"], 1)

    def test_scoped_package_filters_delivery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract = self.make_extract(root / "extract", reference=False)
            second_uid = "h99999999g8888g7777g6666g555555555555"
            evidence = root / "context.jsonl"
            evidence.write_text(
                json.dumps({
                    "contentUid": self.UID,
                    "evidenceType": "context",
                    "summary": "Scoped",
                    "payload": {},
                }) + "\n" +
                json.dumps({
                    "contentUid": second_uid,
                    "evidenceType": "context",
                    "summary": "Outside",
                    "payload": {},
                }) + "\n",
                encoding="utf-8",
            )

            package_root = root / "package"
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="0" * 64,
                evidence_profile="context",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
                evidence_files={"context": evidence},
                scope_content_uids={self.UID},
            )

            delivered = read_jsonl(package_root / "delivery" / "evidence" / "context.jsonl")
            self.assertEqual([item["contentUid"] for item in delivered], [self.UID])

    def test_scoped_package_rejects_unknown_content_uid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extract = self.make_extract(root / "extract", reference=False)
            with self.assertRaises(ValueError):
                prepare_translation_package(
                    extract_manifest=extract,
                    project_config_sha256="0" * 64,
                    evidence_profile="basic",
                    translation_strategy="standard",
                    material_format="jsonl",
                    max_rows=100,
                    output_dir=root / "package",
                    scope_content_uids={"h-does-not-exist"},
                )

    def test_scoped_validation_requires_only_scoped_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            data = json.loads(project.read_text(encoding="utf-8"))
            data["scope"] = {"contentUids": [self.UID]}
            project.write_text(json.dumps(data), encoding="utf-8")
            config = load_project_config(project)
            extract = self.make_extract(root / "extract", reference=False)

            aligned = Path(json.loads(extract.read_text(encoding="utf-8"))["aligned"])
            second_uid = "h99999999g8888g7777g6666g555555555555"
            with aligned.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "contentUid": second_uid,
                    "locales": {
                        "English": {"text": "Second source", "version": 1},
                        "French": {"text": "Deuxième", "version": 1},
                    },
                }, ensure_ascii=False) + "\n")

            package_root = Path(config.resolved["workspace"]["root"]) / "e2e" / "package"
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256=config.sha256,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
                scope_content_uids={self.UID},
            )
            package_manifest = package_root / "translation-package-manifest.json"
            returns = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
            _initialize_returns(package_manifest, package_root, returns)
            material = next(returns.glob("*.jsonl"))
            row = read_jsonl(material)[0]
            row["ProposedTargetText"] = "Salut {name}"
            row["TranslationStatus"] = "translated"
            material.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            state = new_state(config)
            state["stages"]["package"].update({
                "status": "completed",
                "artifact": str(package_manifest),
                "sha256": sha256_file(package_manifest),
            })
            state["stages"]["translate"]["status"] = "ready"
            state["artifacts"]["translationPackage"] = str(package_manifest)
            state["artifacts"]["extractManifest"] = str(extract)
            state["bindings"]["translationPackageSha256"] = sha256_file(package_manifest)
            write_state(state_path(config), state)

            result = run_validate(config, str(material))
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["acceptedRecordCount"], 1)

    def test_standard_package_exposes_comparison_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, package_root = self.prepare_fixture_package(root, strategy="standard")
            row = read_jsonl(package_root / "delivery" / "materials" / "001.jsonl")[0]
            self.assertEqual(row["ExistingTargetText"], "Bonjour {name}")
            self.assertEqual(row["ReferenceTexts"]["German"], "Hallo {name}")

    def test_basic_e2e_validate_produces_core_compatible_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            extract = self.make_extract(root / "extract", reference=False)
            package_root = Path(config.resolved["workspace"]["root"]) / "e2e" / "package"
            manifest = prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256=config.sha256,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
            )
            package_manifest = package_root / "translation-package-manifest.json"
            returns = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
            _initialize_returns(package_manifest, package_root, returns)
            material = next(returns.glob("*.jsonl"))
            row = read_jsonl(material)[0]
            row["ProposedTargetText"] = "Salut {name}"
            row["TranslationStatus"] = "translated"
            material.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            state = new_state(config)
            state["stages"]["package"].update({
                "status": "completed",
                "artifact": str(package_manifest),
                "sha256": sha256_file(package_manifest),
            })
            state["stages"]["translate"]["status"] = "ready"
            state["artifacts"]["translationPackage"] = str(package_manifest)
            state["artifacts"]["extractManifest"] = str(extract)
            state["bindings"]["translationPackageSha256"] = sha256_file(package_manifest)
            write_state(state_path(config), state)

            result = run_validate(config, str(material))
            self.assertEqual(result["status"], "pass")
            validate_manifest = json.loads(Path(result["validateManifest"]).read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest["summary"]["status"], "pass")
            accepted = read_jsonl(Path(validate_manifest["accepted"]["path"]))
            self.assertEqual(accepted[0]["text"], "Salut {name}")

    def test_review_reconciliation_conflicting_revisions_fail_closed(self) -> None:
        canonical = {
            self.UID: {
                "contentUid": self.UID,
                "localeId": "French",
                "text": "Base",
                "version": 1,
            }
        }
        base_hash = "0" * 64
        results = [
            {
                "ContentUid": self.UID,
                "Protocol": "bark",
                "ReviewInstanceId": "bark",
                "ReviewClass": "structural",
                "Decision": "revision-required",
                "BaseTextSha256": base_hash,
                "CandidateId": "A",
                "SourceValidationSha256": base_hash,
                "ProposedText": "Revision A",
            },
            {
                "ContentUid": self.UID,
                "Protocol": "quest",
                "ReviewInstanceId": "quest",
                "ReviewClass": "structural",
                "Decision": "revision-required",
                "BaseTextSha256": base_hash,
                "CandidateId": "B",
                "SourceValidationSha256": base_hash,
                "ProposedText": "Revision B",
            },
        ]
        reconciliation, target, conflicts = _reconcile(canonical, results)
        self.assertEqual(conflicts, 1)
        self.assertEqual(reconciliation[0]["Resolution"], "conflict")
        self.assertEqual(target[0]["text"], "Base")

    def test_qa_revision_generates_fresh_round_before_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "rules.json"
            rules.write_text(json.dumps({
                "schemaVersion": "1.0",
                "rules": [{
                    "ruleId": "SYN-001",
                    "kind": "literal",
                    "pattern": "bad",
                    "category": "Synthetic",
                    "rationale": "fixture",
                }],
            }), encoding="utf-8")
            project = self.make_project(
                root,
                qa=[{"id": "usage", "type": "taiwan-usage", "path": "rules.json"}],
            )
            config = load_project_config(project)
            extract = self.make_extract(root / "extract", reference=False)
            package_root = Path(config.resolved["workspace"]["root"]) / "e2e" / "package"
            manifest = prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256=config.sha256,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
            )
            package_manifest = package_root / "translation-package-manifest.json"
            returns = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
            _initialize_returns(package_manifest, package_root, returns)
            material = next(returns.glob("*.jsonl"))
            row = read_jsonl(material)[0]
            row["ProposedTargetText"] = "bad {name}"
            row["TranslationStatus"] = "translated"
            material.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            state = new_state(config)
            state["stages"]["package"].update({
                "status": "completed",
                "artifact": str(package_manifest),
                "sha256": sha256_file(package_manifest),
            })
            state["stages"]["translate"]["status"] = "ready"
            state["artifacts"]["translationPackage"] = str(package_manifest)
            state["artifacts"]["extractManifest"] = str(extract)
            state["bindings"]["translationPackageSha256"] = sha256_file(package_manifest)
            write_state(state_path(config), state)

            prepared = prepare_reviews(config, str(material))
            self.assertEqual(prepared["stage"], "language-qa")
            review_csv = Path(prepared["path"]) / "usage" / "taiwan-usage-review.csv"
            with review_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                fields = list(reader.fieldnames or [])
            self.assertEqual(len(rows), 1)
            rows[0]["ReviewerDecision"] = "Revise"
            rows[0]["ProposedText"] = "good {name}"
            with review_csv.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            first = integrate_reviews(config)
            self.assertEqual(first["status"], "blocked")
            self.assertEqual(first["stage"], "language-qa")
            second_csv = Path(first["path"]) / "usage" / "taiwan-usage-review.csv"
            with second_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                second_rows = list(csv.DictReader(stream))
            self.assertEqual(second_rows, [])

            second = integrate_reviews(config)
            self.assertEqual(second["status"], "passed")
            final_target = read_jsonl(Path(second["finalTarget"]))
            self.assertEqual(final_target[0]["text"], "good {name}")

    def test_manual_conflict_resolution_updates_only_current_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            canonical = {
                self.UID: {
                    "contentUid": self.UID,
                    "localeId": "French",
                    "text": "Base {name}",
                    "version": 1,
                }
            }
            base_hash = hashlib.sha256("Base {name}".encode("utf-8")).hexdigest()
            source_hash = "0" * 64
            results = [
                {
                    "ContentUid": self.UID,
                    "Protocol": "bark",
                    "ReviewInstanceId": "bark",
                    "ReviewClass": "structural",
                    "Decision": "revision-required",
                    "BaseTextSha256": base_hash,
                    "CandidateId": "A",
                    "SourceValidationSha256": source_hash,
                    "ProposedText": "A {name}",
                },
                {
                    "ContentUid": self.UID,
                    "Protocol": "quest",
                    "ReviewInstanceId": "quest",
                    "ReviewClass": "structural",
                    "Decision": "revision-required",
                    "BaseTextSha256": base_hash,
                    "CandidateId": "B",
                    "SourceValidationSha256": source_hash,
                    "ProposedText": "B {name}",
                },
            ]
            reconciliation, target, conflicts = _reconcile(canonical, results)
            self.assertEqual(conflicts, 1)

            manual = workspace / "review" / "manual-resolutions" / "structural.jsonl"
            manual.parent.mkdir(parents=True, exist_ok=True)
            resolved = "Final {name}"
            manual.write_text(json.dumps({
                "ReviewStage": "structural",
                "ContentUid": self.UID,
                "BaseTextSha256": base_hash,
                "ResolvedText": resolved,
                "ResolvedTextSha256": hashlib.sha256(resolved.encode("utf-8")).hexdigest(),
            }) + "\n", encoding="utf-8")

            reconciliation, target, conflicts = _apply_manual_resolutions(
                workspace,
                "structural",
                reconciliation,
                target,
            )
            self.assertEqual(conflicts, 0)
            self.assertEqual(reconciliation[0]["Resolution"], "manual-conflict-resolution")
            self.assertEqual(target[0]["text"], resolved)

    def test_final_target_revalidates_protected_syntax(self) -> None:
        baseline = {
            self.UID: {
                "ContentUid": self.UID,
                "SourceText": "Hello {name}",
                "TargetLocale": "French",
                "PresenceStatus": "source+target",
                "TranslationRequired": True,
                "ProtectedTokens": ["{name}"],
            }
        }
        errors = _validate_final_target(
            [{
                "contentUid": self.UID,
                "localeId": "French",
                "text": "Bonjour",
                "translationStatus": "translated",
            }],
            baseline,
        )
        self.assertTrue(any("PROTECTED_SYNTAX_MISSING" in message for _uid, message in errors))

    def test_default_validate_rejects_stale_returns_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            extract = self.make_extract(root / "extract", reference=False)
            package_root = Path(config.resolved["workspace"]["root"]) / "e2e" / "package"
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256=config.sha256,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_root,
            )
            package_manifest = package_root / "translation-package-manifest.json"

            state = new_state(config)
            state["stages"]["package"].update({
                "status": "completed",
                "artifact": str(package_manifest),
                "sha256": sha256_file(package_manifest),
            })
            state["artifacts"]["translationPackage"] = str(package_manifest)
            state["artifacts"]["extractManifest"] = str(extract)
            state["bindings"]["translationPackageSha256"] = sha256_file(package_manifest)
            write_state(state_path(config), state)

            returns = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
            returns.mkdir(parents=True, exist_ok=True)
            (returns / "returns-manifest.json").write_text(json.dumps({
                "schemaVersion": "1.0",
                "sourceTranslationPackageSha256": "0" * 64,
                "materials": [],
            }), encoding="utf-8")

            with self.assertRaises(WorkflowValidateError):
                run_validate(config)

    def test_prepare_does_not_overwrite_edited_returns_from_old_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_a = root / "package-a"
            package_b = root / "package-b"
            extract = self.make_extract(root / "extract", reference=False)
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="1" * 64,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_a,
            )
            prepare_translation_package(
                extract_manifest=extract,
                project_config_sha256="2" * 64,
                evidence_profile="basic",
                translation_strategy="standard",
                material_format="jsonl",
                max_rows=100,
                output_dir=package_b,
            )

            from bg3loc.e2e.prepare import _initialize_returns

            returns = root / "returns"
            _initialize_returns(
                package_a / "translation-package-manifest.json",
                package_a,
                returns,
            )
            material = next(returns.glob("*.jsonl"))
            material.write_text(material.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                _initialize_returns(
                    package_b / "translation-package-manifest.json",
                    package_b,
                    returns,
                )

    def test_rebuild_and_install_require_stage_bindings_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            config = load_project_config(project)
            workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
            workspace.mkdir(parents=True, exist_ok=True)
            validate_manifest = workspace / "validation" / "validate-manifest.json"
            accepted_target = workspace / "validation" / "accepted" / "normalized-target.jsonl"
            extract_manifest = workspace / "extract" / "extract-manifest.json"
            scan_manifest = workspace / "scan" / "scan-manifest.json"
            validate_manifest.parent.mkdir(parents=True, exist_ok=True)
            accepted_target.parent.mkdir(parents=True, exist_ok=True)
            extract_manifest.parent.mkdir(parents=True, exist_ok=True)
            scan_manifest.parent.mkdir(parents=True, exist_ok=True)
            scan_manifest.write_text("{}", encoding="utf-8")
            accepted_target.write_text(
                json.dumps({
                    "contentUid": self.UID,
                    "localeId": "French",
                    "text": "Salut {name}",
                    "version": 1,
                }) + "\n",
                encoding="utf-8",
            )
            validate_manifest.write_text(json.dumps({
                "accepted": {
                    "path": str(accepted_target),
                    "recordCount": 1,
                }
            }), encoding="utf-8")
            extract_manifest.write_text("{}", encoding="utf-8")

            state = new_state(config)
            state["stages"]["validate"]["status"] = "completed"
            state["artifacts"]["validateManifest"] = str(validate_manifest)
            state["artifacts"]["extractManifest"] = str(extract_manifest)
            state["artifacts"]["scanManifest"] = str(scan_manifest)
            state["bindings"]["scanManifestSha256"] = sha256_file(scan_manifest)
            state["bindings"]["validationManifestSha256"] = sha256_file(validate_manifest)
            state["bindings"]["validationAcceptedSha256"] = sha256_file(accepted_target)
            write_state(state_path(config), state)

            def fake_rebuild(request):
                request.output.mkdir(parents=True, exist_ok=True)
                manifest = request.output / "rebuild-manifest.json"
                manifest.write_text("{}", encoding="utf-8")
                return {"artifacts": [{"path": "fixture.pak"}]}

            with patch("bg3loc.e2e.rebuild.run_rebuild", side_effect=fake_rebuild) as rebuild:
                run_workflow_rebuild(config)
                run_workflow_rebuild(config)
                self.assertEqual(rebuild.call_count, 1)

            with self.assertRaises(WorkflowInstallError):
                run_workflow_install(config, apply=True)

            with patch(
                "bg3loc.e2e.install.run_install",
                return_value={"status": "dry-run-pass", "preflight": {"destination": "fixture.pak"}},
            ) as install:
                dry = run_workflow_install(config, apply=False)
                self.assertEqual(dry["status"], "dry-run-pass")
                dry_again = run_workflow_install(config, apply=False)
                self.assertEqual(dry_again["status"], "dry-run-pass")
                self.assertEqual(install.call_count, 1)

            fake_install_manifest = workspace / "backups" / "install-manifest.json"
            fake_install_manifest.parent.mkdir(parents=True, exist_ok=True)
            fake_install_manifest.write_text("{}", encoding="utf-8")
            with patch(
                "bg3loc.e2e.install.run_install",
                return_value={
                    "deployment": [{"destination": "fixture.pak"}],
                    "manifestPath": str(fake_install_manifest),
                },
            ):
                applied = run_workflow_install(config, apply=True)
                self.assertEqual(applied["deployment"][0]["destination"], "fixture.pak")


if __name__ == "__main__":
    unittest.main()
