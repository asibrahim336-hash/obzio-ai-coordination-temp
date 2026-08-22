import os
import tempfile
import unittest
from pathlib import Path
from mechanism import baseline_identity, portable_identity


class MetamorphicPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="obzio path ")
        self.root = Path(self.tmp.name)
        (self.root / "pack").mkdir()
        (self.root / "pack/data.json").write_text('{"fixture":"sanitized"}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_example_only_identity_misses_equivalence(self):
        variants = ["pack/data.json", "./pack/data.json", "pack/../pack/data.json"]
        self.assertEqual(3, len({baseline_identity(path) for path in variants}))

    def test_equivalent_variants_have_one_portable_identity(self):
        variants = ["pack/data.json", "./pack/data.json", "pack/../pack/data.json"]
        rows = [portable_identity(self.root, path) for path in variants]
        self.assertEqual(1, len({row["identity"] for row in rows}))
        self.assertEqual({"pack/data.json"}, {row["relative_path"] for row in rows})

    def test_absolute_and_escape_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            portable_identity(self.root, str((self.root / "pack/data.json").resolve()))
        outside = self.root.parent / "outside.json"
        outside.write_text("{}")
        try:
            with self.assertRaises(ValueError):
                portable_identity(self.root, "../outside.json")
        finally:
            outside.unlink()

    def test_symlink_escape_is_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        outside = self.root.parent / "outside-symlink.json"
        outside.write_text("{}")
        try:
            os.symlink(outside, self.root / "pack/link.json")
            with self.assertRaises(ValueError):
                portable_identity(self.root, "pack/link.json")
        finally:
            outside.unlink()


if __name__ == "__main__":
    unittest.main()
