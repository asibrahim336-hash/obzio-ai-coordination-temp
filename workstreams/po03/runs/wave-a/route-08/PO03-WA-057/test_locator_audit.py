import json
import tempfile
import unittest
from pathlib import Path

from locator_audit import audit_rows


class LocatorAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "results").mkdir()
        self.result = {
            "obzio_state": "COMPLETED",
            "independent_acceptance": {"state": "PENDING"},
            "result_transaction": {"result_commit_id": "abc"},
        }
        self.path = self.root / "results/T.json"
        self.path.write_text(json.dumps(self.result))
        import hashlib

        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.registry = [{"task_id": "T", "obzio_state": "COMPLETED"}]
        self.locator = {
            "task_id": "T",
            "result_uri": "results/T.json",
            "result_commit_id": "abc",
            "completed_receipt_sha256": self.sha,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_immutable_locator_passes(self):
        report = audit_rows(self.registry, [self.locator], self.root)
        self.assertEqual(report["disposition"], "PASS")

    def test_duplicate_locator_fails(self):
        report = audit_rows(self.registry, [self.locator, self.locator], self.root)
        self.assertEqual(report["disposition"], "FAIL")

    def test_illegal_disposition_fails(self):
        self.result["obzio_state"] = "RESULT_STAGED"
        self.path.write_text(json.dumps(self.result))
        locator = dict(self.locator)
        import hashlib

        locator["completed_receipt_sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = audit_rows(self.registry, [locator], self.root)
        self.assertIn("illegal_result_disposition", report["findings"][0]["defects"])


if __name__ == "__main__":
    unittest.main()
