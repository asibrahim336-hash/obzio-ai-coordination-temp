"""Assertions over the sanitized pre-commit prevention reproduction."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

from reproduce_overlap_prevention import (  # noqa: E402
    A_CONTENT,
    SHARED_PATH,
    run_reproduction,
)


@unittest.skipIf(shutil.which("git") is None, "git is not available")
class PreventionReproductionTest(unittest.TestCase):
    record = None

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.record = run_reproduction(Path(tmp))

    def step(self, prefix):
        matches = [step for step in self.record["steps"] if step["step"].startswith(prefix)]
        self.assertEqual(len(matches), 1, f"expected exactly one {prefix} step")
        return matches[0]

    def test_overlap_is_detected_while_the_repository_is_still_empty(self):
        observed = self.step("R1")["observed"]
        self.assertEqual(observed["overlap_count"], 1)
        self.assertEqual(observed["witness_paths"], [SHARED_PATH])
        self.assertEqual(observed["witness_paths_present_in_tree"], [])
        self.assertEqual(observed["repository_file_count"], 0)

    def test_repairing_the_registry_removes_the_overlap(self):
        self.assertEqual(self.step("R2")["observed"]["overlap_count"], 0)

    def test_the_owner_can_commit_inside_its_grant(self):
        observed = self.step("R3")["observed"]
        self.assertTrue(observed["committed"])
        self.assertTrue(observed["head_moved"])
        self.assertEqual(observed["committed_bytes"], A_CONTENT)

    def test_the_overlapping_write_is_stopped_before_a_commit_exists(self):
        observed = self.step("R4")["observed"]
        self.assertFalse(observed["committed"])
        self.assertNotEqual(observed["commit_exit_code"], 0)
        self.assertFalse(observed["head_moved"])
        self.assertTrue(observed["bytes_preserved"])
        self.assertEqual(observed["gate_reasons"], {"DENY_FOREIGN_OWNER": 1})

    def test_the_refused_writer_keeps_its_own_subtree(self):
        self.assertTrue(self.step("R5")["observed"]["committed"])

    def test_a_stale_fence_token_cannot_commit(self):
        observed = self.step("R6")["observed"]
        self.assertFalse(observed["committed"])
        self.assertFalse(observed["head_moved"])
        self.assertIn("DENY_STALE_FENCE", observed["gate_reasons"])

    def test_a_rename_cannot_carry_a_foreign_file_away(self):
        observed = self.step("R7")["observed"]
        self.assertFalse(observed["committed"])
        self.assertTrue(observed["owner_bytes_intact"])
        self.assertIn("DENY_RENAME_SOURCE_NOT_OWNED", observed["gate_reasons"])

    def test_a_deny_glob_stops_a_shared_state_write(self):
        observed = self.step("R8")["observed"]
        self.assertFalse(observed["committed"])
        self.assertEqual(observed["gate_reasons"], {"DENY_PROHIBITED_PATH": 1})

    def test_the_negative_control_shows_the_refusals_come_from_the_engine(self):
        observed = self.step("R9")["observed"]
        self.assertTrue(observed["committed"])
        self.assertTrue(observed["head_moved"])

    def test_the_summary_supports_the_hypothesis(self):
        summary = self.record["summary"]
        self.assertTrue(summary["prevented_before_commit"])
        self.assertTrue(summary["owner_writes_admitted"])
        self.assertTrue(summary["negative_control_confirms_attribution"])
        self.assertTrue(summary["static_overlap_detected_before_any_write"])

    def test_the_reproduction_records_no_external_effect(self):
        self.assertEqual(
            self.record["external_effects"],
            "none: temporary local repository, no network, no secrets",
        )


if __name__ == "__main__":
    unittest.main()
