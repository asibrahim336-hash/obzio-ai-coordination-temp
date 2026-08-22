import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("canonical_path_auditor.py")
SPEC = importlib.util.spec_from_file_location("wa026_paths", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CanonicalPathAuditorTests(unittest.TestCase):
    def test_dot_and_separator_aliases_are_duplicates(self):
        report = MODULE.audit_paths(["pack/item.py", "pack/./item.py", "pack\\item.py"])
        codes = [defect["code"] for defect in report["defects"]]
        self.assertEqual(2, codes.count("CANONICAL_ALIAS_DUPLICATE"))

    def test_unicode_compatibility_and_slash_aliases_are_duplicates(self):
        report = MODULE.audit_paths(["pack/K.py", "pack/\u212a.py", "pack\u2215K.py"])
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(
            2,
            sum(d["code"] == "CANONICAL_ALIAS_DUPLICATE" for d in report["defects"]),
        )

    def test_hidden_encoded_and_parent_escapes_are_rejected(self):
        for hostile in ("../outside", "%2e%2e/outside", "/absolute", "C:\\outside", "\x00x"):
            with self.subTest(hostile=hostile):
                report = MODULE.audit_paths([hostile])
                self.assertEqual("UNSAFE_PATH", report["defects"][0]["code"])

    def test_omission_and_undeclared_files_are_not_masked_by_aliases(self):
        report = MODULE.audit_paths(
            ["pack/a.py", "pack/b.py"],
            ["pack/./a.py", "pack/c.py"],
        )
        self.assertEqual(["pack/b.py"], report["omissions"])
        self.assertEqual(["pack/c.py"], report["undeclared"])

    def test_distinct_canonical_paths_pass(self):
        report = MODULE.audit_paths(["pack/a.py", "pack/b.py"])
        self.assertEqual("PASS", report["disposition"])


if __name__ == "__main__":
    unittest.main()
