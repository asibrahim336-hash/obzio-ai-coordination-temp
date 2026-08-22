import hashlib
import tempfile
import unittest
from pathlib import Path

from successor_reproducer import verify


class SuccessorReproducerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "artifact").write_bytes(b"bytes")
        self.manifest = {
            "generation_id": "G2",
            "founder_relay_required": False,
            "artifacts": [
                {
                    "path": "artifact",
                    "sha256": hashlib.sha256(b"bytes").hexdigest(),
                    "bytes": 5,
                }
            ],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_manifest_reproduces(self):
        self.assertEqual(verify(self.root, self.manifest)["disposition"], "PASS")

    def test_same_size_corruption_fails(self):
        (self.root / "artifact").write_bytes(b"wrong")
        self.assertEqual(verify(self.root, self.manifest)["disposition"], "FAIL")

    def test_founder_relay_is_refused(self):
        self.manifest["founder_relay_required"] = True
        report = verify(self.root, self.manifest)
        self.assertIn("founder_relay_not_zero", report["defects"])


if __name__ == "__main__":
    unittest.main()
