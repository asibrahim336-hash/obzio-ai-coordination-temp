import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.portability import scan_mapping


class PortabilityFixtureTests(unittest.TestCase):
    def test_planted_nonportable_path_classes_are_reported(self):
        blobs = {
            "packs/demo/config.txt": (
                b'posix="/tmp/packs/demo"\n'
                b'windows="C:\\\\Users\\\\demo\\\\pack.json"\n'
                b'unc="\\\\\\\\server\\\\share\\\\pack.json"\n'
                b'relative="../absent/config.json"\n'
            )
        }
        findings = scan_mapping(blobs)
        classes = {finding["class"] for finding in findings}
        self.assertIn("machine_specific_root", classes)
        self.assertIn("windows_drive_path", classes)
        self.assertIn("windows_unc_path", classes)
        self.assertIn("unresolvable_relative_reference", classes)

    def test_resolvable_relative_reference_is_not_reported(self):
        blobs = {
            "packs/demo/config.txt": b'relative="./present.json"\n',
            "packs/demo/present.json": b"{}\n",
        }
        findings = scan_mapping(blobs)
        unresolved = [
            finding
            for finding in findings
            if finding["class"] == "unresolvable_relative_reference"
        ]
        self.assertEqual(unresolved, [])


if __name__ == "__main__":
    unittest.main()
