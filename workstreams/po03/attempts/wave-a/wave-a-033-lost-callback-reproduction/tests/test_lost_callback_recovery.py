#!/usr/bin/env python3
"""Assertions for the lost-provider-callback reproduction.

The suite tests what the frozen predictions claimed, including the predictions
this reproduction refutes. A refuted prediction is asserted in its observed
direction and named as a refutation, so the suite stays green while the recorded
result reports the negative outcome honestly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenarios import (  # noqa: E402
    scenario_duplicate_callback_replay,
    scenario_escalation_probe,
    scenario_false_completion_ladder,
    scenario_pre_provider_reservation_loss,
    scenario_running_provider_callback_loss,
)


class PreProviderReservationLoss(unittest.TestCase):
    """P1-P4: a callback lost before any provider worker ran."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = scenario_pre_provider_reservation_loss()

    def test_p1_reservation_is_not_mistaken_for_a_running_provider(self) -> None:
        classification = self.observed["classification_lease_valid"]
        self.assertEqual(classification["obzio_state"], "LEASED")
        self.assertEqual(classification["provider_state"], "NOT_DISPATCHED")
        self.assertEqual(
            classification["recovery_action"], "AWAIT_PROVIDER_ADMISSION_OR_LEASE_EXPIRY"
        )
        self.assertFalse(classification["provider_execution_evidence"])
        self.assertTrue(classification["visible_in_recovery_scan"])
        self.assertEqual(classification["chain_errors"], [])

    def test_p2_still_valid_lease_is_not_preempted(self) -> None:
        attempt = self.observed["recover_while_lease_valid"]
        self.assertEqual(attempt["outcome"], "REJECTED")
        self.assertIn("still-valid reservation lease", attempt["error_message"])
        self.assertEqual(self.observed["events_after_rejected_recovery"], 2)

    def test_p3_expired_reservation_schedules_a_retry(self) -> None:
        attempt = self.observed["recover_after_lease_expiry"]
        self.assertEqual(attempt["outcome"], "ACCEPTED")
        self.assertEqual(attempt["value"]["status"], "RETRY_SCHEDULED")
        classification = self.observed["classification_after_recovery"]
        self.assertEqual(classification["obzio_state"], "RETRY_SCHEDULED")
        self.assertEqual(classification["provider_state"], "NOT_DISPATCHED")
        self.assertEqual(classification["recovery_action"], "RERUN_OR_RECONCILE")

    def test_p4_duplicate_recovery_callback_is_harmless(self) -> None:
        attempt = self.observed["duplicate_recovery_callback"]
        self.assertEqual(attempt["outcome"], "ACCEPTED")
        self.assertEqual(attempt["value"]["status"], "ALREADY_RETRY_SCHEDULED")
        self.assertEqual(self.observed["duplicate_recovery_new_events"], 0)

    def test_p10_stale_worker_cannot_act_after_ownership_transfer(self) -> None:
        self.assertEqual(self.observed["release_after_recovery"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["classification_after_release"]["fence_token"], 2)
        attempt = self.observed["stale_worker_after_transfer"]
        self.assertEqual(attempt["outcome"], "REJECTED")
        self.assertIn("stale fence token", attempt["error_message"])


class RunningProviderCallbackLoss(unittest.TestCase):
    """P5-P7: a genuinely running provider whose return message was lost."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = scenario_running_provider_callback_loss()

    def test_p5_running_provider_is_distinguished_from_a_reservation(self) -> None:
        classification = self.observed["classification_callback_lost"]
        self.assertEqual(classification["obzio_state"], "RUNNING")
        self.assertEqual(classification["provider_state"], "RUNNING")
        self.assertEqual(classification["recovery_action"], "MONITOR")
        self.assertTrue(classification["provider_execution_evidence"])
        self.assertTrue(classification["visible_in_recovery_scan"])

    def test_p6_live_worker_is_never_preempted_as_a_reservation(self) -> None:
        attempt = self.observed["recover_as_undispatched_after_provider_ran"]
        self.assertEqual(attempt["outcome"], "REJECTED")
        self.assertIn("provider execution evidence", attempt["error_message"])
        # The guard must hold even though the lease has already expired.
        self.assertEqual(
            self.observed["classification_after_lease_expiry"]["provider_state"], "RUNNING"
        )
        self.assertEqual(self.observed["events_after_rejected_recovery"], 3)

    def test_p7_provider_completion_without_a_commit_is_not_obzio_completion(self) -> None:
        self.assertEqual(self.observed["provider_completed_uncommitted"]["outcome"], "ACCEPTED")
        classification = self.observed["classification_provider_completed_uncommitted"]
        self.assertEqual(classification["obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED")
        self.assertEqual(classification["provider_state"], "COMPLETED")
        self.assertEqual(classification["recovery_action"], "RERUN_OR_RECONCILE")
        self.assertIsNone(classification["result_commit_id"])

    def test_p8_uncommitted_provider_completion_cannot_shortcut_to_completed(self) -> None:
        attempt = self.observed["false_completion_from_uncommitted"]
        self.assertEqual(attempt["outcome"], "REJECTED")
        self.assertIn("invalid transition", attempt["error_message"])

    def test_lost_unit_returns_to_execution_under_a_higher_fence(self) -> None:
        self.assertEqual(self.observed["reconcile_to_recovery_required"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["retry_scheduled"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["release_at_higher_fence"]["outcome"], "ACCEPTED")
        self.assertEqual(
            self.observed["classification_after_ownership_transfer"]["fence_token"], 2
        )

    def test_provider_completion_evidence_survives_recovery(self) -> None:
        """Provider state must not be rewritten to hide that a provider ran."""
        self.assertEqual(
            self.observed["classification_after_ownership_transfer"]["provider_state"],
            "COMPLETED",
        )
        self.assertTrue(
            self.observed["classification_after_ownership_transfer"][
                "provider_execution_evidence"
            ]
        )

    def test_lost_worker_cannot_commit_after_transfer(self) -> None:
        for key in ("stale_worker_commit_after_transfer", "non_owner_at_current_fence"):
            with self.subTest(attempt=key):
                self.assertEqual(self.observed[key]["outcome"], "REJECTED")

    def test_refutation_fence_guard_is_not_the_first_line_of_defence(self) -> None:
        """Observed: the transition check runs before the fence check.

        The stale worker was rejected, but for an ordering reason rather than a
        fence reason, so the fence guard was never reached on this path.
        """
        message = self.observed["stale_worker_commit_after_transfer"]["error_message"]
        self.assertIn("invalid transition", message)
        self.assertNotIn("stale fence token", message)


class FalseCompletionLadder(unittest.TestCase):
    """P9 and the deliberately incorrect completion path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = scenario_false_completion_ladder()

    def test_no_false_completion_is_reachable(self) -> None:
        self.assertFalse(self.observed["reached_completed"])
        self.assertNotEqual(self.observed["classification_final"]["obzio_state"], "COMPLETED")

    def test_illegal_shortcuts_are_rejected(self) -> None:
        for key in (
            "running_to_completed_shortcut",
            "running_to_parent_ingested_shortcut",
            "producer_self_completion",
        ):
            with self.subTest(attempt=key):
                self.assertEqual(self.observed[key]["outcome"], "REJECTED")
                self.assertIn("invalid transition", self.observed[key]["error_message"])

    def test_staging_evidence_requirements_are_enforced(self) -> None:
        self.assertEqual(
            self.observed["result_staged_missing_manifest_hash"]["outcome"], "REJECTED"
        )
        self.assertEqual(
            self.observed["result_verified_without_readback"]["outcome"], "REJECTED"
        )

    def test_forged_commit_cannot_reach_parent_ingested_or_completed(self) -> None:
        self.assertEqual(self.observed["parent_ingested_on_forged_commit"]["outcome"], "REJECTED")
        self.assertEqual(
            self.observed["ingest_forged_commit_through_controller"]["outcome"], "REJECTED"
        )

    def test_refutation_p9_forged_result_commit_is_accepted_into_the_ledger(self) -> None:
        """Observed refutation of P9's stronger reading.

        The RESULT_COMMITTED guard checks only the shape of the identifier, so a
        well-formed but nonexistent commit is recorded and then surfaced by the
        recovery projection as ``result_commit_id``. Terminal completion still
        fails closed, so the blast radius is a misleading intermediate record
        rather than a false completion.
        """
        self.assertEqual(self.observed["result_committed_with_forged_commit"]["outcome"], "ACCEPTED")
        classification = self.observed["classification_after_forged_commit"]
        self.assertEqual(classification["obzio_state"], "RESULT_COMMITTED")
        self.assertEqual(classification["result_commit_id"], "0" * 39 + "1")

    def test_strand_on_forged_commit_remains_recoverable(self) -> None:
        """Fail-closed must not mean fail-stuck."""
        self.assertEqual(self.observed["strand_recovery_required"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["strand_retry_scheduled"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["strand_released_at_higher_fence"]["outcome"], "ACCEPTED")
        self.assertEqual(
            self.observed["classification_after_strand_recovery"]["fence_token"], 2
        )


class DuplicateCallbackReplay(unittest.TestCase):
    """P11: a retried callback must not corrupt immutable custody."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = scenario_duplicate_callback_replay()

    def test_p11_identical_replay_is_idempotent(self) -> None:
        self.assertEqual(self.observed["identical_replay"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["identical_replay_new_events"], 0)
        self.assertTrue(self.observed["identical_replay_bytes_unchanged"])

    def test_p11_conflicting_replay_is_rejected_without_mutation(self) -> None:
        self.assertEqual(self.observed["conflicting_replay"]["outcome"], "REJECTED")
        self.assertTrue(self.observed["conflicting_replay_bytes_unchanged"])

    def test_capsule_replay_is_idempotent(self) -> None:
        self.assertEqual(self.observed["capsule_replay"]["outcome"], "ACCEPTED")
        self.assertEqual(self.observed["classification_after_replays"]["chain_errors"], [])

    def test_refutation_duplicate_logical_callback_is_rejected_not_absorbed(self) -> None:
        """Observed refutation of the documented idempotency-key tolerance.

        ``_advance_task_locked`` documents that a replay naming the same target
        state and payload is harmless, but it never consults an idempotency key.
        A redelivered RUNNING callback is rejected as an invalid transition
        instead of being recognised as the same logical callback.
        """
        attempt = self.observed["repeated_running_callback"]
        self.assertEqual(attempt["outcome"], "REJECTED")
        self.assertIn("invalid transition: RUNNING -> RUNNING", attempt["error_message"])
        self.assertFalse(self.observed["idempotency_key_consulted_in_transition"])

    def test_result_commit_is_not_resolved_in_git_at_transition_time(self) -> None:
        self.assertFalse(self.observed["result_commit_verified_at_transition"])


class EscalationProbe(unittest.TestCase):
    """P12: the escalation half of the hypothesis, which is refuted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = scenario_escalation_probe()

    def test_classification_survives_from_immutable_state_alone(self) -> None:
        self.assertEqual(self.observed["projection_verification_errors"], [])
        unit = self.observed["rebuilt_projection_unit"]
        self.assertEqual(unit["obzio_state"], "RUNNING")
        self.assertEqual(unit["provider_state"], "RUNNING")
        self.assertEqual(unit["recovery_action"], "MONITOR")
        self.assertEqual(len(self.observed["recovery_scan_after_expiry"]), 1)

    def test_refutation_p12_no_automatic_time_bounded_escalation(self) -> None:
        """Observed refutation: lease expiry changes nothing for a live worker.

        A permanently lost callback from a genuinely running provider stays
        RUNNING/MONITOR indefinitely. No exposed command escalates it, the lease
        duration is never consulted on the dispatched path, and no heartbeat is
        ever recorded, so recovery needs a controller decision rather than an
        automatic route.
        """
        self.assertFalse(self.observed["classification_changed_on_lease_expiry"])
        self.assertFalse(self.observed["escalation_route_available"])
        self.assertEqual(
            self.observed["recover_undispatched_available"]["outcome"], "REJECTED"
        )
        self.assertFalse(self.observed["heartbeat_written_nonnull_anywhere"])
        self.assertNotIn(
            "_recovery_action",
            self.observed["lease_expiry_consulted_outside_undispatched_recovery"],
        )
        self.assertEqual(self.observed["events_after_all_automatic_routes"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
