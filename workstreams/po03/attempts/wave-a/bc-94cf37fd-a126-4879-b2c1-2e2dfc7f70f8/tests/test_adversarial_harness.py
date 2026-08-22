import importlib.util
import unittest
from pathlib import Path


HARNESS_PATH = Path(__file__).parents[1] / "adversarial_harness.py"
SPEC = importlib.util.spec_from_file_location("po03_adversarial_harness", HARNESS_PATH)
HARNESS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HARNESS)
REPOSITORY = HARNESS_PATH.parents[5]


class AdversarialHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = HARNESS.run(REPOSITORY)
        cls.by_id = {
            attempt["task_id"]: attempt for attempt in cls.result["attempts"]
        }

    def test_all_eight_attempts_leave_executable_evidence(self):
        self.assertEqual(8, self.result["attempt_count"])
        self.assertEqual(8, self.result["attempts_with_executable_evidence"])
        self.assertEqual(
            {f"po03-wa-adv-{number:03d}" for number in range(1, 9)},
            set(self.by_id),
        )
        self.assertTrue(all(attempt["assertion"] for attempt in self.by_id.values()))

    def test_schema_validator_drift_is_reproduced(self):
        observed = self.by_id["po03-wa-adv-001"]["observations"]
        self.assertTrue(observed["schema_rejects_unknown_root_property"])
        self.assertEqual([], observed["validator_unknown_property_errors"])
        self.assertEqual([], observed["validator_invalid_provider_state_errors"])

    def test_source_lock_uses_dirty_bytes_with_pinned_blob(self):
        observed = self.by_id["po03-wa-adv-002"]["observations"]
        self.assertEqual(
            observed["recorded_sha256"], observed["dirty_worktree_sha256"]
        )
        self.assertNotEqual(
            observed["recorded_sha256"], observed["committed_sha256"]
        )

    def test_concurrent_event_writers_collide(self):
        observed = self.by_id["po03-wa-adv-003"]["observations"]
        self.assertEqual(8, observed["writers"])
        self.assertEqual(1, observed["committed"])
        self.assertEqual(7, observed["failed"])
        self.assertIn("FileExistsError", observed["error_types"])

    def test_directory_fsync_failure_is_not_repaired_on_retry(self):
        observed = self.by_id["po03-wa-adv-004"]["observations"]
        self.assertTrue(observed["directory_fsync_failure_raised"])
        self.assertTrue(observed["destination_survived_failed_directory_fsync"])
        self.assertTrue(observed["retry_returned_without_repair_evidence"])

    def test_ci_reachability_gap_is_distinct_from_direct_path_rejection(self):
        observed = self.by_id["po03-wa-adv-005"]["observations"]
        self.assertEqual(
            observed["direct_escape_fixture_count"],
            len(observed["direct_rejections"]),
        )
        self.assertTrue(observed["out_of_scope_only_pull_request_can_skip_guard"])
        self.assertTrue(observed["subordinate_cursor_branch_push_can_skip_guard"])

    def test_local_task_verification_has_no_remote_commit_evidence(self):
        observed = self.by_id["po03-wa-adv-006"]["observations"]
        self.assertEqual(0, observed["local_verify_return_code"])
        self.assertIsNone(observed["result_commit_id"])
        self.assertEqual(0, observed["remote_readback_evidence_count"])

    def test_stale_fence_completed_event_passes_integrity_only_check(self):
        observed = self.by_id["po03-wa-adv-007"]["observations"]
        self.assertTrue(observed["stale_worker_completed_event_admitted"])
        self.assertEqual([], observed["semantic_chain_errors"])
        self.assertFalse(observed["fence_token_checked_by_event_writer"])

    def test_provider_loss_is_classified_but_not_replayable(self):
        observed = self.by_id["po03-wa-adv-008"]["observations"]
        self.assertEqual(
            [], observed["provider_completed_uncommitted_classification_errors"]
        )
        self.assertIsNotNone(observed["same_idempotency_key_replay_error"])
        self.assertFalse(observed["has_executable_recovery_command"])


if __name__ == "__main__":
    unittest.main()
