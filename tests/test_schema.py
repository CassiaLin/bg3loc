from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.schema import SchemaStore, default_schema_root


class SchemaStoreTests(unittest.TestCase):
    def test_default_schema_root_is_not_cwd_dependent_in_source_tree(self) -> None:
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {}, clear=False):
                    root = default_schema_root()
                self.assertTrue((root / "scan.schema.json").is_file())
                self.assertTrue((root / "extract-manifest.schema.json").is_file())
                SchemaStore(root).load("extract-manifest.schema.json")
            finally:
                os.chdir(previous)

    def test_environment_override_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"BG3LOC_SCHEMA_DIR": str(root)}, clear=False):
                self.assertEqual(default_schema_root(), root.resolve())


if __name__ == "__main__":
    unittest.main()
