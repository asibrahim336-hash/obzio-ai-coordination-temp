import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mechanism import baseline_load, hermetic_load


class HermeticTests(unittest.TestCase):
    def test_warm_hidden_state_masks_missing_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "local-state.json").write_text('{"token":"warm"}')
            self.assertEqual("warm", baseline_load(root))
            (root / "local-state.json").unlink()
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(FileNotFoundError):
                    baseline_load(root)

    def test_declared_input_is_stable_against_ambient_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inputs").mkdir()
            (root / "inputs/config.json").write_text(json.dumps({"token": "declared"}))
            (root / "local-state.json").write_text(json.dumps({"token": "hidden"}))
            with patch.dict(os.environ, {"PACK_TOKEN": "ambient"}, clear=True):
                self.assertEqual("declared", hermetic_load(root, "inputs/config.json"))

    def test_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                hermetic_load(tmp, "../outside.json")


if __name__ == "__main__":
    unittest.main()
