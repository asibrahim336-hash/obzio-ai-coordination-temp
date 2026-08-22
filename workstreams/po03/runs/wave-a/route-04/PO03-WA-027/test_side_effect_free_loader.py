import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("side_effect_free_loader.py")
SPEC = importlib.util.spec_from_file_location("wa027_loader", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SideEffectFreeLoaderTests(unittest.TestCase):
    def test_package_initializer_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "hostile_package"
            package.mkdir()
            marker = root / "side-effect.txt"
            (package / "__init__.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            (package / "component.py").write_text(
                "def verify(value):\n    return value == 7\n",
                encoding="utf-8",
            )
            sys.path.insert(0, str(root))
            try:
                report = MODULE.qualify(root, "hostile_package/component.py", "verify")
            finally:
                sys.path.remove(str(root))
            self.assertEqual("PASS", report["disposition"])
            self.assertFalse(marker.exists())
            self.assertNotIn("hostile_package", sys.modules)

    def test_hidden_main_block_does_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "main-ran"
            (root / "source.py").write_text(
                "def verify():\n    return True\n"
                f"if __name__ == '__main__':\n    open({str(marker)!r}, 'w').close()\n",
                encoding="utf-8",
            )
            report = MODULE.qualify(root, "source.py", "verify")
            self.assertEqual("PASS", report["disposition"])
            self.assertFalse(marker.exists())

    def test_escape_and_missing_symbol_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
            self.assertEqual(
                "FAIL", MODULE.qualify(root, "../outside.py", "verify")["disposition"]
            )
            report = MODULE.qualify(root, "source.py", "verify")
            self.assertEqual(["REQUIRED_CALLABLE_MISSING:verify"], report["defects"])


if __name__ == "__main__":
    unittest.main()
