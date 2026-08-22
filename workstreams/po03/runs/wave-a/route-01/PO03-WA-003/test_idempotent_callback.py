#!/usr/bin/env python3
"""Falsification suite for PO03-WA-003.

The hypothesis is falsified if N duplicate deliveries of one callback ever
produce more than one result transaction.  The suite includes a negative
control: a deliberately naive receiver with the same interface but a
check-then-act split, which must be shown to *fail* the same assertion.  A
guard that passes only because the race never fires would be worthless, so the
control proves the test can actually detect the defect.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "idempotent_callback", Path(__file__).with_name("idempotent_callback.py")
)
assert SPEC is not None and SPEC.loader is not None
CB = importlib.util.module_from_spec(SPEC)
sys.modules["idempotent_callback"] = CB
SPEC.loader.exec_module(CB)


class NaiveReceiver:
    """Negative control: correct-looking dedupe with a check-then-act split.

    This is what a receiver looks like when the lookup and the allocation are
    not in one critical section.  It is here to prove the concurrency test can
    detect the defect, not as a candidate implementation.
    """

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}
        self.allocations = 0
        self._barrier = threading.Barrier(2)

    def receive(self, key: str, body: dict) -> dict:
        existing = self.seen.get(key)
        try:
            # Widen the check-then-act window deterministically instead of
            # relying on the scheduler to lose the race for us.
            self._barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        if existing is not None:
            return {"outcome": "DUPLICATE_IGNORED", "result_txn_id": existing}
        self.allocations += 1
        txn = f"rtxn-{self.allocations}"
        self.seen[key] = txn
        return {"outcome": "CREATED", "result_txn_id": txn}


class TempReceiverCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.receiver = CB.IdempotentCallbackReceiver(Path(self._directory.name))
        self.key = "wave:task:attempt-1"
        self.body = {"task_id": "t", "sha256": "b" * 64}


class SequentialDuplicateTests(TempReceiverCase):
    def test_first_delivery_creates_exactly_one_transaction(self):
        result = self.receiver.receive(self.key, self.body)
        self.assertEqual("CREATED", result["outcome"])
        self.assertEqual(1, len(self.receiver.transactions()))
        self.assertEqual(1, self.receiver.created_count())

    def test_repeat_deliveries_return_the_same_transaction_id(self):
        first = self.receiver.receive(self.key, self.body)
        ids = {first["result_txn_id"]}
        for _ in range(20):
            repeat = self.receiver.receive(self.key, self.body)
            self.assertEqual("DUPLICATE_IGNORED", repeat["outcome"])
            ids.add(repeat["result_txn_id"])
        self.assertEqual(1, len(ids), "duplicates must not mint new transaction ids")
        self.assertEqual(1, self.receiver.created_count())
        self.assertEqual(1, self.receiver.allocations())

    def test_duplicate_does_not_mutate_the_stored_result(self):
        self.receiver.receive(self.key, self.body)
        stored = json.dumps(self.receiver.transactions()[self.key]["body"], sort_keys=True)
        for _ in range(5):
            self.receiver.receive(self.key, self.body)
        after = json.dumps(self.receiver.transactions()[self.key]["body"], sort_keys=True)
        self.assertEqual(stored, after)

    def test_delivery_count_is_observable(self):
        self.receiver.receive(self.key, self.body)
        for expected in range(2, 6):
            result = self.receiver.receive(self.key, self.body)
            self.assertEqual(expected, result["delivery_count"])

    def test_key_ordering_and_whitespace_do_not_defeat_dedupe(self):
        self.receiver.receive(self.key, {"a": 1, "b": 2})
        repeat = self.receiver.receive(self.key, {"b": 2, "a": 1})
        self.assertEqual("DUPLICATE_IGNORED", repeat["outcome"])

    def test_distinct_keys_create_distinct_transactions(self):
        ids = {self.receiver.receive(f"key-{index}", self.body)["result_txn_id"] for index in range(8)}
        self.assertEqual(8, len(ids))
        self.assertEqual(8, self.receiver.created_count())


class ConflictTests(TempReceiverCase):
    def test_same_key_different_body_is_a_conflict_not_a_duplicate(self):
        self.receiver.receive(self.key, {"result": "A"})
        with self.assertRaises(CB.IdempotencyConflict) as caught:
            self.receiver.receive(self.key, {"result": "B"})
        self.assertEqual(self.key, caught.exception.key)
        self.assertNotEqual(caught.exception.stored_digest, caught.exception.presented_digest)

    def test_conflict_does_not_overwrite_the_stored_result(self):
        self.receiver.receive(self.key, {"result": "A"})
        with self.assertRaises(CB.IdempotencyConflict):
            self.receiver.receive(self.key, {"result": "B"})
        self.assertEqual({"result": "A"}, self.receiver.transactions()[self.key]["body"])
        self.assertEqual(1, self.receiver.created_count())

    def test_empty_key_is_refused(self):
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                self.receiver.receive(bad, self.body)


class ConcurrentDuplicateTests(unittest.TestCase):
    def test_concurrent_duplicate_storm_creates_exactly_one_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            report = CB.reproduce_duplicate_storm(Path(directory), deliveries=32, threads=16)
        self.assertEqual(1, report["created"], report)
        self.assertEqual(report["deliveries"] - 1, report["duplicates_ignored"], report)
        self.assertEqual(1, len(report["distinct_result_txn_ids"]), report)
        self.assertEqual(1, report["transactions_in_store"], report)
        self.assertEqual(1, report["ledger_created_events"], report)
        self.assertEqual(1, report["allocations"], report)

    def test_ledger_records_every_delivery_but_only_one_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            receiver = CB.IdempotentCallbackReceiver(Path(directory))
            for _ in range(10):
                receiver.receive("k", {"v": 1})
            ledger = receiver.ledger()
        self.assertEqual(10, len(ledger), "at-least-once delivery must remain visible")
        self.assertEqual(1, sum(1 for record in ledger if record["event"] == "CREATED"))
        self.assertEqual(9, sum(1 for record in ledger if record["event"] == "DUPLICATE_IGNORED"))


class NegativeControlTests(unittest.TestCase):
    """The test must be capable of detecting a check-then-act receiver."""

    def test_naive_receiver_creates_two_transactions_under_the_same_race(self):
        naive = NaiveReceiver()
        results: list[dict] = []
        lock = threading.Lock()

        def deliver():
            outcome = naive.receive("k", {"v": 1})
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=deliver) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(
            2,
            naive.allocations,
            "the negative control failed to reproduce the defect, so the assertion proves nothing",
        )
        self.assertEqual(2, len({item["result_txn_id"] for item in results}))

    def test_guarded_receiver_survives_the_identical_race(self):
        with tempfile.TemporaryDirectory() as directory:
            receiver = CB.IdempotentCallbackReceiver(Path(directory))
            barrier = threading.Barrier(2)
            results: list[dict] = []
            lock = threading.Lock()

            def deliver():
                barrier.wait(timeout=5)
                outcome = receiver.receive("k", {"v": 1})
                with lock:
                    results.append(outcome)

            threads = [threading.Thread(target=deliver) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(1, receiver.allocations())
            self.assertEqual(1, len({item["result_txn_id"] for item in results}))
            self.assertEqual(
                sorted(["CREATED", "DUPLICATE_IGNORED"]),
                sorted(item["outcome"] for item in results),
            )


class DurabilityTests(unittest.TestCase):
    def test_dedupe_survives_receiver_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            first = CB.IdempotentCallbackReceiver(Path(directory))
            original = first.receive("k", {"v": 1})["result_txn_id"]
            del first
            # A brand new receiver object over the same durable directory.
            second = CB.IdempotentCallbackReceiver(Path(directory))
            repeat = second.receive("k", {"v": 1})
            self.assertEqual("DUPLICATE_IGNORED", repeat["outcome"])
            self.assertEqual(original, repeat["result_txn_id"])
            self.assertEqual(0, second.allocations(), "a restart must not allocate a second transaction")


if __name__ == "__main__":
    unittest.main(verbosity=2)
