from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import bg3loc


class VersionConsistencyTests(unittest.TestCase):
    def test_project_and_runtime_versions_match(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        with (repository_root / "pyproject.toml").open("rb") as stream:
            project_version = tomllib.load(stream)["project"]["version"]

        self.assertEqual(project_version, bg3loc.__version__)


if __name__ == "__main__":
    unittest.main()
