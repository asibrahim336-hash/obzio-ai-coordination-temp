#!/usr/bin/env python3
"""Falsification suite for PO03-WA-004.

The hypothesis is falsified if a callback that the channel drops fails to reach
the parent after relay recovery, or if recovery re-delivers as a second
ingested effect.  The suite sweeps every drop schedule up to length five rather
than testing one hand-picked loss pattern, and pins the unsafe control to show
the loss is genuinely unrecoverable without the outbox.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("outbox_relay", Path(__file__).with_name("outbox_relay.py"))
assert SPEC is not None and SPEC.loader is not None
OB = importlib.util.module_from_spec(SPEC)
sys.modules["outbox_relay"] = OB
SPEC.loader.exec_module(OB)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.directory = Path(self._directory.name)


class AtomicityTests(TempCase):
    def test_result_and_outbox_row_become_durable_together(self):
        store = OB.WorkerStore(self.directory / "w.json")
        store.commit_and_enqueue("T1", {"v": 1})
        state = store.read()
        self.assertIn("T1", state["results"])
        self.assertEqual(1, len(state["outbox"]))
        self.assertEqual("T1", state["outbox"][0]["task_id"])
        self.assertEqual("PENDING", state["outbox"][0]["status"])

    def test_no_committed_result_ever_lacks_an_outbox_row(self):
        store = OB.WorkerStore(self.directory / "w.json")
        for index in range(5):
            store.commit_and_enqueue(f"T{index}", {"v": index})
        state = store.read()
        outbox_tasks = {row["task_id"] for row in state["outbox"]}
        self.assertEqual(set(state["results"]), outbox_tasks)

    def test_state_survives_a_fresh_store_object(self):
        path = self.directory / "w.json"
        OB.WorkerStore(path).commit_and_enqueue("T1", {"v": 1})
        reopened = OB.WorkerStore(path)
        self.assertEqual(1, len(reopened.pending()))


class LostCallbackRecoveryTests(TempCase):
    def test_first_callback_lost_then_recovered(self):
        report = OB.reproduce_lost_callback(self.directory)
        self.assertEqual(1, report["pending_after_commit"])
        self.assertEqual(0, report["pending_after_drain"], "recovery must drain the outbox")
        self.assertEqual(1, report["parent_ingested"], "the lost result must arrive exactly once")
        self.assertEqual(3, report["channel_attempts"], "two drops then one success")
        self.assertEqual(1, report["channel_deliveries"])
        self.assertEqual(["ACKNOWLEDGED"], [row["status"] for row in report["outbox_final"]])
        self.assertEqual(3, report["outbox_final"][0]["attempts"])

    def test_every_drop_schedule_up_to_length_five_recovers(self):
        """Sweep, rather than pick, the loss pattern."""
        failures = []
        for length in range(1, 6):
            for schedule in itertools.product([True, False], repeat=length):
                # Guarantee the channel eventually succeeds.
                schedule = list(schedule) + [False]
                with tempfile.TemporaryDirectory() as directory:
                    report = OB.reproduce_lost_callback(Path(directory), schedule)
                if report["pending_after_drain"] != 0 or report["parent_ingested"] != 1:
                    failures.append((schedule, report["pending_after_drain"], report["parent_ingested"]))
        self.assertEqual([], failures, "every drop schedule must recover to exactly one ingestion")

    def test_a_totally_dead_channel_leaves_the_row_pending_not_lost(self):
        store = OB.WorkerStore(self.directory / "w.json")
        store.commit_and_enqueue("T1", {"v": 1})
        channel = OB.UnreliableChannel([True] * 50)
        relay = OB.OutboxRelay(store, channel, OB.ParentCoordinator())
        relay.drain(max_scans=5)
        pending = store.pending()
        self.assertEqual(1, len(pending), "an undeliverable row stays recoverable, never discarded")
        self.assertEqual(5, pending[0]["attempts"])
        self.assertEqual("PENDING", pending[0]["status"])

    def test_relay_is_safe_to_rerun_after_success(self):
        store = OB.WorkerStore(self.directory / "w.json")
        store.commit_and_enqueue("T1", {"v": 1})
        parent = OB.ParentCoordinator()
        relay = OB.OutboxRelay(store, OB.UnreliableChannel([]), parent)
        relay.drain()
        for _ in range(4):
            report = relay.scan_once()
            self.assertEqual([], report["outcomes"], "an acknowledged row must not be re-sent")
        self.assertEqual(1, parent.ingested.__len__())


class ExactlyOnceEffectTests(TempCase):
    def test_at_least_once_delivery_yields_exactly_one_ingestion(self):
        """Force a genuine double delivery and prove the effect stays single."""
        store = OB.WorkerStore(self.directory / "w.json")
        store.commit_and_enqueue("T1", {"v": 1})
        parent = OB.ParentCoordinator()
        channel = OB.UnreliableChannel([])
        relay = OB.OutboxRelay(store, channel, parent)
        relay.scan_once()
        # Simulate an acknowledgement that was itself lost: the row is put back
        # to PENDING even though the parent already received the message.
        row = store.read()["outbox"][0]
        store.mark(row["outbox_id"], "PENDING", row["attempts"])
        relay.scan_once()

        self.assertEqual(2, parent.deliveries, "the parent genuinely saw two deliveries")
        self.assertEqual(1, len(parent.ingested), "but only one ingested effect")
        self.assertEqual(2, len(channel.delivered))

    def test_idempotency_key_is_stable_across_redeliveries(self):
        store = OB.WorkerStore(self.directory / "w.json")
        store.commit_and_enqueue("T1", {"v": 1})
        channel = OB.UnreliableChannel([True, False])
        relay = OB.OutboxRelay(store, channel, OB.ParentCoordinator())
        relay.drain()
        self.assertEqual(1, len({message["idempotency_key"] for message in channel.delivered}))


class UnsafeControlTests(TempCase):
    """Without the outbox the same loss is unrecoverable -- the PO-02 shape."""

    def test_loss_without_outbox_is_unrecoverable(self):
        report = OB.reproduce_unrecoverable_loss(self.directory)
        self.assertTrue(report["result_committed"], "the work really was done")
        self.assertTrue(report["callback_lost"])
        self.assertEqual(0, report["recoverable_rows_after_restart"], "nothing durable to retry from")
        self.assertEqual([], report["recovery_outcomes"])
        self.assertEqual(0, report["parent_ingested"], "the parent never learns the result exists")
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", report["classification"])

    def test_control_and_guarded_paths_differ_only_in_the_outbox(self):
        with_outbox = OB.reproduce_lost_callback(self.directory)
        without = OB.reproduce_unrecoverable_loss(self.directory)
        self.assertEqual(1, with_outbox["parent_ingested"])
        self.assertEqual(0, without["parent_ingested"])


class SerialisationTests(TempCase):
    def test_reports_are_json_serialisable_for_evidence_capture(self):
        report = OB.reproduce_lost_callback(self.directory)
        self.assertIsInstance(json.dumps(report, sort_keys=True), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
