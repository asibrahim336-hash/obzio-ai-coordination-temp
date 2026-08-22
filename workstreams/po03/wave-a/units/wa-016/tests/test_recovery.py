"""What the recovery scanner does with each kind of surviving evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness import fixtures
from harness.custody_machine import Clock, Coordinator, CustodyStore, ExternalWorld
from harness.fault_injector import ExternalUnavailable, ProcessLoss, quiet, single
from harness.recovery import MAX_SCAN_PASSES, UNRECOVERABLE_READBACK_FAILURES, RecoveryScanner

TASK = fixtures.TASK_ID


class ScannerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="po03-wa016-recovery-")
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.injector = quiet()
        self.clock = Clock()
        self.world = ExternalWorld(self.injector)
        self.store = CustodyStore(self.root, self.injector, self.clock)
        self.coordinator = Coordinator(self.store)
        self.input = fixtures.immutable_input_stub()
        self.store.create(TASK, self.input)

    def arm(self, injector):
        self.injector = injector
        self.store.injector = injector
        self.store.io.injector = injector
        self.world.injector = injector
        return injector

    def reopen(self, injector=None) -> CustodyStore:
        self.injector = injector or self.injector
        self.store = CustodyStore(self.root, self.injector, self.clock)
        self.world.injector = self.injector
        self.coordinator = Coordinator(self.store)
        self.coordinator.restart()
        return self.store

    def scan(self):
        return RecoveryScanner(self.store, self.world, self.coordinator).scan({TASK: self.input})

    def lease_and_run(self, fence: int = 1) -> None:
        self.store.lease(TASK, self.input["attempt_id"], fence, self.input["idempotency_key"], self.input["lease_id"])
        self.store.start(TASK, fence)

    def stage_and_verify(self, fence: int = 1) -> None:
        self.store.begin_staging(TASK, fence)
        self.store.stage_artifacts(TASK, fence, fixtures.default_payload())
        self.store.verify_staged(TASK, fence)


class ClassificationTests(ScannerCase):
    def test_a_provider_claim_without_a_commit_is_scheduled_for_retry(self):
        self.lease_and_run()
        self.store.observe_provider(TASK, "COMPLETED")
        report = self.scan()
        self.assertIn("SCHEDULE_RETRY_FROM_IMMUTABLE_INPUT", report.kinds())
        self.assertEqual("RETRY_SCHEDULED", self.store.state(TASK).obzio_state)

    def test_the_retry_carries_the_frozen_idempotency_key(self):
        self.lease_and_run()
        self.store.observe_provider(TASK, "COMPLETED")
        action = next(a for a in self.scan().actions if a["action"] == "SCHEDULE_RETRY_FROM_IMMUTABLE_INPUT")
        self.assertTrue(action["immutable_input_present"])
        self.assertEqual(fixtures.IDEMPOTENCY_KEY, action["idempotency_key"])

    def test_work_in_flight_is_resumed_in_place(self):
        self.lease_and_run()
        self.stage_and_verify()
        report = self.scan()
        self.assertIn("RESUME_IN_PLACE", report.kinds())
        self.assertEqual("RESULT_VERIFIED", self.store.state(TASK).obzio_state)

    def test_an_expired_lease_moves_the_task_out_of_the_old_owners_hands(self):
        self.lease_and_run()
        self.store.expire_lease(TASK)
        report = self.scan()
        self.assertIn("FENCE_EXPIRED_LEASE", report.kinds())
        self.assertIn(self.store.state(TASK).obzio_state, {"RECOVERY_REQUIRED", "RETRY_SCHEDULED"})

    def test_a_committed_result_is_never_reclassified_for_retry(self):
        self.lease_and_run()
        self.stage_and_verify()
        commit = self.store.commit_result(TASK, 1, self.world)
        self.store.expire_lease(TASK)
        self.scan()
        self.assertEqual(commit, self.store.state(TASK).result_commit_id)
        self.assertNotIn("RETRY_SCHEDULED", self.store.state(TASK).history)

    def test_a_healthy_terminal_state_produces_no_action(self):
        self.lease_and_run()
        self.stage_and_verify()
        self.store.commit_result(TASK, 1, self.world)
        self.store.verify_readback(TASK, self.world)
        self.store.relay(TASK, self.coordinator)
        self.coordinator.complete(TASK, self.world)
        report = self.scan()
        self.assertEqual([], report.kinds())
        self.assertFalse(report.exhausted)


class SurvivingDamageTests(ScannerCase):
    def test_a_torn_journal_tail_is_healed_and_reported(self):
        self.lease_and_run()
        self.arm(single("PARTIAL_WRITE", "journal_append_partial"))
        with self.assertRaises(ProcessLoss):
            self.store.checkpoint(TASK, 1, 1)
        self.reopen(quiet())
        report = self.scan()
        self.assertIn("HEAL_TORN_JOURNAL", report.kinds())
        healed = next(a for a in report.actions if a["action"] == "HEAL_TORN_JOURNAL")
        self.assertGreater(healed["torn_bytes_discarded"], 0)

    def test_an_orphan_temp_file_is_swept(self):
        self.lease_and_run()
        self.arm(single("SNAPSHOT_ROLLBACK", "post_snapshot_tmp_write"))
        with self.assertRaises(ProcessLoss):
            self.store.checkpoint(TASK, 1, 1)
        self.reopen(quiet())
        self.assertEqual(["state.json.tmp"], self.store.io.orphan_temp_files())
        report = self.scan()
        self.assertIn("SWEEP_ORPHAN_TEMP_FILES", report.kinds())
        self.assertEqual([], self.store.io.orphan_temp_files())


class UnacknowledgedCommitTests(ScannerCase):
    def _lose_the_acknowledgement(self) -> None:
        self.lease_and_run()
        self.stage_and_verify()
        self.arm(single("NETWORK_INTERRUPTION", "post_external_effect"))
        with self.assertRaises(ExternalUnavailable):
            self.store.commit_result(TASK, 1, self.world)
        self.arm(quiet())

    def test_a_landed_effect_is_adopted_rather_than_repeated(self):
        self._lose_the_acknowledgement()
        self.assertIsNone(self.store.state(TASK).result_commit_id)
        report = self.scan()
        self.assertIn("ADOPT_UNACKNOWLEDGED_COMMIT", report.kinds())
        state = self.store.state(TASK)
        self.assertEqual(self.world.lookup(self.store.result_ref(TASK)), state.result_commit_id)
        self.assertEqual(1, self.world.distinct_effect_count)
        self.assertEqual(1, len(self.world.attempts))

    def test_the_adopted_commit_is_carried_through_to_one_ingestion(self):
        self._lose_the_acknowledgement()
        report = self.scan()
        self.assertEqual(["ADOPT_UNACKNOWLEDGED_COMMIT", "REPLAY_LOST_CALLBACK"], report.kinds())
        state = self.store.state(TASK)
        self.assertEqual([], self.store.pending_callbacks(TASK))
        self.assertEqual(1, state.history.count("PARENT_INGESTED"))
        self.assertEqual(state.result_commit_id, state.outbox[0]["result_commit_id"])

    def test_a_diverged_remote_commit_is_reported_and_not_adopted(self):
        self._lose_the_acknowledgement()
        commit = self.world.lookup(self.store.result_ref(TASK))
        self.world.corrupt(commit, "artifact-manifest.json")
        report = self.scan()
        self.assertIn("REMOTE_COMMIT_DIVERGED", report.kinds())
        self.assertNotIn("ADOPT_UNACKNOWLEDGED_COMMIT", report.kinds())
        self.assertIsNone(self.store.state(TASK).result_commit_id)


class LostCallbackTests(ScannerCase):
    def test_a_lost_callback_is_replayed_from_the_surviving_outbox(self):
        self.lease_and_run()
        self.stage_and_verify()
        self.store.commit_result(TASK, 1, self.world)
        self.arm(single("CALLBACK_LOSS", "pre_callback_send"))
        self.store.relay(TASK, self.coordinator)
        self.assertEqual("RESULT_COMMITTED", self.store.state(TASK).obzio_state)
        self.arm(quiet())
        report = self.scan()
        self.assertIn("REPLAY_LOST_CALLBACK", report.kinds())
        self.assertEqual(1, self.store.state(TASK).history.count("PARENT_INGESTED"))

    def test_ingestion_is_replayed_when_even_the_outbox_was_delivered(self):
        self.lease_and_run()
        self.stage_and_verify()
        self.store.commit_result(TASK, 1, self.world)
        # Mark the entry delivered without the parent having ingested it: the
        # relay crashed after sending and before the parent recorded anything.
        entry = self.store.state(TASK).outbox[0]
        self.store.record_event("CALLBACK_DELIVERED", TASK, outbox_id=entry["outbox_id"], at=self.clock.now())
        report = self.scan()
        self.assertIn("REPLAY_PARENT_INGEST", report.kinds())
        self.assertEqual("PARENT_INGESTED", self.store.state(TASK).obzio_state)


class BoundedTerminationTests(ScannerCase):
    def test_repeated_remote_damage_is_classified_terminally(self):
        """Recurrence test for M4: unrecoverable damage must not retry forever.

        Damage to an already published commit cannot be repaired by the
        producer, so the retry loop has to stop instead of circling.
        """
        self.lease_and_run()
        self.stage_and_verify()
        commit = self.store.commit_result(TASK, 1, self.world)
        self.world.remove(commit, "canary.txt")

        fence = 1
        report = None
        for _ in range(UNRECOVERABLE_READBACK_FAILURES):
            self.assertTrue(self.store.verify_readback(TASK, self.world))
            self.assertEqual("RECOVERY_REQUIRED", self.store.state(TASK).obzio_state)
            report = self.scan()
            if self.store.state(TASK).obzio_state == "RETRY_SCHEDULED":
                fence += 1
                self.store.lease(
                    TASK, self.input["attempt_id"], fence, self.input["idempotency_key"], self.input["lease_id"]
                )

        self.assertIn("CLASSIFY_UNRECOVERABLE_REMOTE_DAMAGE", report.kinds())
        state = self.store.state(TASK)
        self.assertEqual("FAILED_TERMINAL", state.obzio_state)
        self.assertNotIn("COMPLETED", state.history)
        # Terminal means terminal: a further scan proposes nothing.
        self.assertEqual([], self.scan().kinds())

    def test_the_scanner_terminates_within_its_pass_budget(self):
        self.lease_and_run()
        self.store.observe_provider(TASK, "COMPLETED")
        report = self.scan()
        self.assertFalse(report.exhausted)
        self.assertLessEqual(report.passes, MAX_SCAN_PASSES)

    def test_a_second_scan_of_a_settled_task_is_a_no_op(self):
        self.lease_and_run()
        self.store.observe_provider(TASK, "COMPLETED")
        self.scan()
        self.assertEqual([], self.scan().kinds())


if __name__ == "__main__":
    unittest.main()
