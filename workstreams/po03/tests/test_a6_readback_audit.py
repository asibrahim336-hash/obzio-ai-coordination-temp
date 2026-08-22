import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "workstreams" / "po03" / "review" / "luna" / "readback_audit.py"
SPEC = importlib.util.spec_from_file_location("readback_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)


class ReadbackAuditTests(unittest.TestCase):
    def test_a7_artifacts_match_but_declared_result_commit_lacks_record(self):
        result = AUDIT.audit_target(
            "origin/cursor/po03-a7-os-metrics-ed20:"
            "workstreams/po03/control/units/a7/a7-u01.json"
        )
        self.assertEqual("AUDITED", result["status"])
        self.assertEqual(2, result["artifacts_checked"])
        self.assertTrue(all(check["hash_match"] for check in result["checks"]))
        self.assertTrue(all(check["bytes_match"] for check in result["checks"]))
        self.assertFalse(result["record_present_at_declared_result_commit"])
        self.assertEqual(1, result["discrepancy_count"])

    def test_missing_result_is_not_invented(self):
        result = AUDIT.audit_target(
            "origin/cursor/po03-a1-custody-engine-ed20:"
            "workstreams/po03/control/units/a1/a1-u01.json"
        )
        self.assertEqual("UNAVAILABLE", result["status"])
        self.assertEqual(0, result["artifacts_checked"])


if __name__ == "__main__":
    unittest.main()
