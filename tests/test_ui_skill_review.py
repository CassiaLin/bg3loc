from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.review.ui_skill import (
    PASS1_COLUMNS,
    candidates_from_universe,
    prepare_ui_skill_review,
    validate_ui_skill_review,
)


def relation(
    uid: str,
    *,
    domain: str,
    entity: str,
    field: str = "Description",
    parent_name: str = "",
    depth: int = 0,
    explicit: str = "explicit",
    status: str = "Eligible",
    workstream: str = "UserInterface",
    provider: str = "Synthetic.pak::Synthetic/path.txt",
) -> dict[str, str]:
    return {
        "ContentUid": uid,
        "Status": status,
        "Workstream": workstream,
        "Provider": provider,
        "Package": provider.split("::", 1)[0],
        "InternalPath": f"Synthetic/{domain}.txt",
        "SourceFamilies": "UI/GUI definitions",
        "Domains": domain,
        "EntityType": "SyntheticEntity",
        "EntityName": entity,
        "FieldName": field,
        "ParentName": parent_name,
        "InheritanceDepth": str(depth),
        "ExplicitOrInherited": explicit,
        "CommentOnly": "false",
    }


class UiSkillReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = {
            "synthetic-skill": "Skill {Player} %s",
            "synthetic-ui": "UI <LSTag Type=\"X\">label</LSTag>",
            "synthetic-existing": "Already translated",
            "synthetic-held": "Held evidence",
        }
        self.target = {"synthetic-existing": "Existing target"}
        self.rows = [
            relation("synthetic-skill", domain="Ability.Unknown", entity="Child", workstream="AbilitySkill"),
            relation(
                "synthetic-skill", domain="Ability.Unknown", entity="Child", workstream="AbilitySkill",
                field="DisplayName", parent_name="Parent", depth=1, explicit="inherited",
            ),
            relation("synthetic-ui", domain="UI.Unknown", entity="Progression"),
            relation("synthetic-existing", domain="UI.Unknown", entity="Existing"),
            relation(
                "synthetic-ui", domain="UI.Tutorial", entity="Historical", status="Hold",
            ),
            relation("synthetic-held", domain="UI.Unknown", entity="Held", status="Hold"),
        ]

    def test_candidates_use_complete_universe_and_preserve_relations(self) -> None:
        candidates = candidates_from_universe(self.rows, source_text=self.source)
        self.assertEqual(len(candidates), 3)
        by_uid = {item.content_uid: item for item in candidates}
        self.assertEqual(by_uid["synthetic-skill"].relation_count, 2)
        self.assertEqual(
            {rel.explicit_or_inherited for rel in by_uid["synthetic-skill"].relations},
            {"explicit", "inherited"},
        )
        self.assertEqual(by_uid["synthetic-ui"].workstreams, ("UserInterface",))
        self.assertIn("synthetic-existing", by_uid)
        self.assertNotIn("synthetic-held", by_uid)
        self.assertEqual(by_uid["synthetic-skill"].workstreams, ("AbilitySkill",))

    def test_candidate_identity_is_stable_across_relation_order(self) -> None:
        left = candidates_from_universe(self.rows, source_text=self.source)
        right = candidates_from_universe(reversed(self.rows), source_text=self.source)
        self.assertEqual(
            [(item.content_uid, item.candidate_id) for item in left],
            [(item.content_uid, item.candidate_id) for item in right],
        )

    @staticmethod
    def _write_materialization(path: Path, rows: list[dict[str, str]]) -> None:
        columns = [
            "ContentUid", "Status", "Workstream", "Provider", "Package", "InternalPath",
            "SourceFamilies", "Domains", "EntityType", "EntityName", "FieldName",
            "ParentName", "InheritanceDepth", "ExplicitOrInherited", "CommentOnly",
        ]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _package(self, root: Path, include_pass2: bool = True) -> tuple[Path, Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        universe = root / "ui-skill-universe.csv"
        self._write_materialization(universe, self.rows)
        locale_paths: dict[str, Path] = {}
        for locale, records in {
            "English": self.source,
            "SyntheticTarget": self.target,
            "SyntheticReference": {"synthetic-skill": "reference {Player} %s"},
        }.items():
            path = root / f"{locale}.jsonl"
            path.write_text(
                "".join(json.dumps({"contentUid": uid, "text": text}) + "\n" for uid, text in records.items()),
                encoding="utf-8",
            )
            locale_paths[locale] = path
        extract = root / "extract-manifest.json"
        extract.write_text(json.dumps({
            "sourceLocale": "English",
            "targetLocale": "SyntheticTarget",
            "referenceLocales": ["SyntheticReference"],
            "locales": [
                {"localeId": locale, "normalized": str(path)}
                for locale, path in locale_paths.items()
            ],
        }), encoding="utf-8")
        output = root / "review"
        prepare_ui_skill_review(
            universe_path=universe,
            extract_manifest=extract,
            output_dir=output,
            include_pass2=include_pass2,
        )
        return (
            output / "ui-skill-review-pass1.csv",
            output / "ui-skill-review-pass2.csv",
            output / "ui-skill-review-manifest.json",
        )

    @staticmethod
    def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            return list(reader.fieldnames or []), list(reader)

    @staticmethod
    def _write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_pass1_is_blind_and_pass2_contains_configured_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pass1, pass2, _manifest = self._package(Path(tmp))
            headers1, _rows1 = self._read(pass1)
            headers2, rows2 = self._read(pass2)
            self.assertEqual(headers1, list(PASS1_COLUMNS))
            self.assertNotIn("OfficialTarget", headers1)
            self.assertNotIn("ReferenceComparison", headers1)
            self.assertIn("OfficialTarget", headers2)
            skill = next(row for row in rows2 if row["ContentUid"] == "synthetic-skill")
            self.assertEqual(skill["OfficialTarget"], "")
            self.assertIn("SyntheticReference", skill["ReferenceComparison"])

    def test_valid_review_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            skill = next(row for row in rows if row["ContentUid"] == "synthetic-skill")
            skill["ReviewerDecision"] = "Approved"
            skill["EvidenceSufficient"] = "true"
            skill["DraftText"] = "Draft {Player} %s"
            skill["FinalDecision"] = "Approved"
            skill["FinalText"] = "Final {Player} %s"
            skill["ApprovedAuthority"] = "ReferenceLocale:SyntheticReference"
            self._write(pass2, columns, rows)
            result = validate_ui_skill_review(
                input_path=pass2, manifest_path=manifest, output_dir=root / "validated"
            )
            self.assertEqual(result["status"], "passed")

    def test_relation_mutation_duplicate_and_token_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            skill = next(row for row in rows if row["ContentUid"] == "synthetic-skill")
            skill["Relations"] = "[]"
            skill["RelationCount"] = "0"
            skill["FinalText"] = "Dropped protected tokens"
            rows.append(dict(rows[0]))
            self._write(pass2, columns, rows)
            result = validate_ui_skill_review(
                input_path=pass2, manifest_path=manifest, output_dir=root / "validated"
            )
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"UIS001", "UIS002", "UIS009", "UIS012"} <= codes)

    def test_invalid_status_authority_and_pass1_leakage_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pass1, _pass2, manifest = self._package(root)
            columns, rows = self._read(pass1)
            columns.append("OfficialTarget")
            rows[0]["OfficialTarget"] = "leak"
            rows[0]["ReviewerDecision"] = "Maybe"
            self._write(pass1, columns, rows)
            result = validate_ui_skill_review(
                input_path=pass1, manifest_path=manifest, output_dir=root / "validated"
            )
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"UIS006", "UIS007"} <= codes)

            _p1, pass2, manifest2 = self._package(root / "second")
            columns2, rows2 = self._read(pass2)
            rows2[0]["ApprovedAuthority"] = "HistoricalWorkbook"
            self._write(pass2, columns2, rows2)
            result2 = validate_ui_skill_review(
                input_path=pass2, manifest_path=manifest2, output_dir=root / "validated2"
            )
            self.assertIn("UIS010", {item["code"] for item in result2["findings"]})


if __name__ == "__main__":
    unittest.main()
