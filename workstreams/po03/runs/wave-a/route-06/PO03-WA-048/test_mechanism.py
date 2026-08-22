import tempfile
import unittest
from pathlib import Path
from mechanism import differential, portable_evaluate


class DifferentialRuntimeTests(unittest.TestCase):
    def make_warm(self):
        tmp = tempfile.TemporaryDirectory(prefix="obzio warm ")
        root = Path(tmp.name)
        (root / "tracked").mkdir()
        (root / "tracked/config.json").write_text('{"mode":"portable","version":1}\n')
        (root / "local-default.json").write_text('{"mode":"warm-only","version":1}\n')
        return tmp, root

    def test_differential_detects_untracked_local_override(self):
        tmp, root = self.make_warm()
        try:
            result = differential(root)
            self.assertNotEqual(result["baseline_warm"], result["baseline_clean"])
        finally:
            tmp.cleanup()

    def test_portable_mechanism_matches_in_fresh_subprocesses(self):
        tmp, root = self.make_warm()
        try:
            result = differential(root)
            self.assertEqual(result["portable_warm"], result["portable_clean"])
        finally:
            tmp.cleanup()

    def test_missing_declared_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                portable_evaluate(tmp)


if __name__ == "__main__":
    unittest.main()
