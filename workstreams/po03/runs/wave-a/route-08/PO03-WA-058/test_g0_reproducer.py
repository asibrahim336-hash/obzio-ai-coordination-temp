import hashlib
import tempfile
import unittest
from pathlib import Path

from g0_reproducer import recover


class G0RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.payloads = {"a": b"alpha", "nested/b": b"beta"}
        self.entries = [
            {"path": path, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            for path, payload in self.payloads.items()
        ]

    def test_every_crash_point_recovers_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for point in range(len(self.entries) + 1):
                row = recover(
                    self.entries,
                    self.payloads.__getitem__,
                    Path(tmp) / str(point),
                    point,
                )
                self.assertEqual(row["defects"], [])

    def test_corrupt_immutable_source_is_detected(self):
        payloads = dict(self.payloads)
        payloads["a"] = b"wrong"
        with tempfile.TemporaryDirectory() as tmp:
            row = recover(self.entries, payloads.__getitem__, Path(tmp), 0)
        self.assertIn("sha256:a", row["defects"])


if __name__ == "__main__":
    unittest.main()
