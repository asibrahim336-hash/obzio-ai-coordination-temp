"""Reproduction for partial-write and commit-boundary faults.

Hypothesis under test: a partial write, a pre-commit failure and a post-commit
failure each leave a recoverable state and never a false completion.

Every crash here is a real SIGKILL of a child worker process, so the mechanism
gets no opportunity to unwind.  Assertions describe the observed behaviour of
the unmodified mechanism; none of them is relaxed to obtain a pass.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_043_kit", "fault_kit.py")
injector = _load("po03_c6_043_injector", "commit_boundary_injector.py")


class InjectionTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class PartialWriteTests(InjectionTestCase):
    def test_kill_before_atomic_link_leaves_no_half_written_immutable_file(self):
        result = injector.inject_partial_write(self.root)
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertEqual(-9, result["crash"]["returncode"])
        self.assertFalse(result["observed"]["half_written_immutable_file_visible"])
        self.assertEqual(
            ["000001-created.json", "000002-leased.json", "000003-running.json"],
            result["observed"]["durable_event_files"],
        )
        self.assertEqual("PASS", result["verdict"])

    def test_stray_temporary_file_after_a_crash_is_not_read_as_state(self):
        result = injector.inject_partial_write(self.root)
        self.assertTrue(result["observed"]["stray_temporary_entries"])
        self.assertTrue(result["observed"]["stray_entries_ignored_by_mechanism"])
        self.assertEqual([], result["observed"]["event_chain_errors"])

    def test_kill_after_link_before_directory_fsync_leaves_exact_bytes(self):
        result = injector.inject_link_without_fsync(self.root)
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertTrue(result["observed"]["checkpoint_file_present"])
        self.assertTrue(result["observed"]["checkpoint_content_self_consistent"])
        self.assertEqual([], result["observed"]["event_chain_errors"])

    def test_crash_mid_replacement_keeps_the_previous_generation(self):
        result = injector.inject_replace_atomic_crash(self.root)
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertTrue(result["observed"]["previous_generation_intact"])
        self.assertEqual(1, result["observed"]["observed_generation"])
        self.assertTrue(result["observed"]["target_is_valid_json"])

    def test_crash_between_events_keeps_the_chain_verifiable(self):
        result = injector.inject_mid_event_chain(self.root)
        self.assertEqual([], result["observed"]["event_chain_errors"])
        self.assertEqual("CHECKPOINTED", result["observed"]["last_state"])
        self.assertTrue(result["observed"]["next_event_sequence_is_contiguous"])

    def test_immutable_file_cannot_be_rewritten_with_different_bytes(self):
        result = injector.inject_immutable_overwrite(self.root)
        self.assertTrue(result["observed"]["differing_payload_refused"])
        self.assertTrue(result["observed"]["identical_payload_is_a_noop"])
        self.assertTrue(result["observed"]["bytes_unchanged"])


class CommitBoundaryTests(InjectionTestCase):
    def test_pre_commit_failure_is_refused_at_ingestion(self):
        result = injector.inject_pre_commit_failure(self.root)
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertEqual([], result["observed"]["bytes_present_in_commit"])
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["ingestion_state"])
        self.assertTrue(
            any("read-back failed" in error for error in result["observed"]["ingestion_errors"])
        )
        self.assertEqual(
            "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT", result["observed"]["recovery_action"]
        )

    def test_post_commit_failure_leaves_durable_readable_bytes(self):
        result = injector.inject_post_commit_failure(self.root)
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertGreater(result["observed"]["committed_result_bytes_readable"], 0)
        self.assertTrue(result["state_is_recoverable"])
        self.assertTrue(result["observed"]["immutable_input_available_for_rerun"])

    def test_post_commit_failure_is_not_automatically_replayed(self):
        result = injector.inject_post_commit_failure(self.root)
        self.assertFalse(result["automatic_recovery_by_live_scanner"])
        self.assertEqual(0, result["observed"]["ingestion_records"])
        self.assertIn("DEF-PO03-C6-042", result["cross_reference"])

    def test_no_fault_class_produces_a_false_completion(self):
        report = injector.inject_all(self.root)
        self.assertEqual(0, report["false_completions_observed"])
        for item in report["results"]:
            with self.subTest(fault_class=item["fault_class"]):
                self.assertEqual(0, item["observed"].get("false_completion_count", 0) or 0)

    def test_every_fault_class_passes_its_own_classification(self):
        report = injector.inject_all(self.root)
        self.assertEqual(7, report["fault_classes"])
        self.assertEqual("PASS", report["verdict"])
        verdicts = {item["fault_class"]: item["verdict"] for item in report["results"]}
        self.assertEqual({"PASS"}, set(verdicts.values()), verdicts)

    def test_report_is_json_serialisable_for_the_fault_matrix(self):
        report = injector.inject_all(self.root)
        rows = json.loads(json.dumps(report))["results"]
        for row in rows:
            with self.subTest(fault_class=row["fault_class"]):
                self.assertIn("injected_at_state_transition", row)
                self.assertIn("verdict", row)


if __name__ == "__main__":
    unittest.main()
