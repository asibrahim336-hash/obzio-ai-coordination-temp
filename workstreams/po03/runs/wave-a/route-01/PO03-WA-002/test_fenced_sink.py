#!/usr/bin/env python3
"""Falsification suite for PO03-WA-002.

The hypothesis is falsified if a fence token below the sink's high-water mark
ever produces a staged or committed result, or mutates the sink at all beyond
its rejection audit log.  Coverage includes a real multi-process race so the
guarantee is not merely a single-threaded assertion.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("fenced_sink", Path(__file__).with_name("fenced_sink.py"))
assert SPEC is not None and SPEC.loader is not None
SINK = importlib.util.module_from_spec(SPEC)
sys.modules["fenced_sink"] = SINK
SPEC.loader.exec_module(SINK)

MODULE_PATH = str(Path(__file__).with_name("fenced_sink.py"))


def _worker_process(path_text: str, fence: int, worker: str, queue) -> None:
    """Run in a *separate process* to prove the guard is durable, not in-memory."""
    spec = importlib.util.spec_from_file_location("fenced_sink_child", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fenced_sink_child"] = module
    spec.loader.exec_module(module)
    sink = module.FencedResultSink(Path(path_text))
    try:
        sink.stage(fence, worker, f"payload-{worker}".encode())
    except Exception as error:  # noqa: BLE001
        queue.put((worker, "REFUSED", type(error).__name__))
    else:
        queue.put((worker, "ACCEPTED", None))


class TempSinkCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.path = Path(self._directory.name) / "sink.json"
        self.sink = SINK.FencedResultSink(self.path)

    def content_without_audit(self):
        state = self.sink.read()
        state.pop("rejections")
        return json.dumps(state, sort_keys=True)


class StaleFenceRejectionTests(TempSinkCase):
    def test_stale_fence_cannot_stage(self):
        self.sink.acquire(2, "worker-B")
        with self.assertRaises(SINK.StaleFenceError) as caught:
            self.sink.stage(1, "worker-A", b"stale")
        self.assertEqual(1, caught.exception.presented)
        self.assertEqual(2, caught.exception.high_water)
        self.assertIsNone(self.sink.read()["staged"])
        self.assertEqual("RESERVED", self.sink.read()["txn_state"])

    def test_stale_fence_cannot_commit(self):
        self.sink.stage(2, "worker-B", b"good")
        with self.assertRaises(SINK.StaleFenceError):
            self.sink.commit(1, "worker-A")
        self.assertEqual("STAGED", self.sink.read()["txn_state"])
        self.assertIsNone(self.sink.read()["committed"])

    def test_rejection_leaves_the_sink_byte_identical_apart_from_the_audit_log(self):
        self.sink.stage(3, "worker-B", b"good")
        self.sink.commit(3, "worker-B")
        before = self.content_without_audit()
        for fence in (1, 2):
            with self.assertRaises(SINK.StaleFenceError):
                self.sink.stage(fence, "worker-A", b"overwrite")
            with self.assertRaises(SINK.StaleFenceError):
                self.sink.commit(fence, "worker-A")
        self.assertEqual(before, self.content_without_audit())
        self.assertEqual(2, self.sink.read()["accepted_writes"], "no rejected call may count as a write")

    def test_every_lower_fence_is_rejected_for_every_operation(self):
        self.sink.acquire(5, "worker-B")
        for fence in range(1, 5):
            for operation, call in (
                ("acquire", lambda f=fence: self.sink.acquire(f, "worker-A")),
                ("stage", lambda f=fence: self.sink.stage(f, "worker-A", b"x")),
                ("commit", lambda f=fence: self.sink.commit(f, "worker-A")),
            ):
                with self.assertRaises(SINK.StaleFenceError, msg=f"{operation}@{fence}") as caught:
                    call()
                self.assertEqual(operation, caught.exception.operation)

    def test_rejection_is_audited_with_both_fences(self):
        self.sink.acquire(4, "worker-B")
        with self.assertRaises(SINK.StaleFenceError):
            self.sink.stage(2, "worker-A", b"x")
        entry = self.sink.read()["rejections"][-1]
        self.assertEqual("stage", entry["operation"])
        self.assertEqual(2, entry["presented_fence"])
        self.assertEqual(4, entry["high_water_fence"])
        self.assertEqual("StaleFenceError", entry["reason"])


class EqualAndHigherFenceTests(TempSinkCase):
    def test_equal_fence_is_the_current_holder_and_is_accepted(self):
        self.sink.acquire(3, "worker-B")
        self.sink.stage(3, "worker-B", b"payload")
        self.assertEqual("STAGED", self.sink.read()["txn_state"])

    def test_higher_fence_permanently_evicts_the_older_lease(self):
        self.sink.acquire(1, "worker-A")
        self.sink.acquire(2, "worker-B")
        self.assertEqual(2, self.sink.read()["high_water_fence"])
        with self.assertRaises(SINK.StaleFenceError):
            self.sink.acquire(1, "worker-A")
        # Eviction is permanent: A never regains the sink at its old fence.
        with self.assertRaises(SINK.StaleFenceError):
            self.sink.stage(1, "worker-A", b"x")

    def test_high_water_never_decreases(self):
        observed = []
        for fence, worker in ((1, "A"), (4, "B"), (9, "C")):
            self.sink.acquire(fence, worker)
            observed.append(self.sink.read()["high_water_fence"])
        self.assertEqual([1, 4, 9], observed)
        self.assertEqual(observed, sorted(observed))


class InvalidFenceTests(TempSinkCase):
    def test_non_positive_and_non_integer_fences_are_refused(self):
        for bad in (0, -1, "2", 2.0, None, True):
            with self.assertRaises(SINK.InvalidFenceError, msg=repr(bad)):
                self.sink.stage(bad, "worker-A", b"x")
        self.assertEqual(0, self.sink.read()["high_water_fence"])


class TransactionStateTests(TempSinkCase):
    def test_commit_requires_a_stage_first(self):
        with self.assertRaises(SINK.SinkStateError):
            self.sink.commit(1, "worker-A")

    def test_commit_must_use_the_fence_that_staged(self):
        self.sink.stage(1, "worker-A", b"x")
        with self.assertRaises(SINK.SinkStateError) as caught:
            self.sink.commit(2, "worker-B")
        self.assertIn("staged under fence 1", str(caught.exception))

    def test_committed_transaction_cannot_be_restaged_even_at_a_higher_fence(self):
        self.sink.stage(1, "worker-A", b"x")
        self.sink.commit(1, "worker-A")
        with self.assertRaises(SINK.SinkStateError):
            self.sink.stage(99, "worker-Z", b"overwrite")
        self.assertEqual("x", "x")
        self.assertEqual(SINK._digest(b"x"), self.sink.read()["committed"]["sha256"])


class ConcurrencyTests(TempSinkCase):
    def test_threaded_stale_writers_never_win(self):
        self.sink.acquire(10, "worker-B")
        outcomes: list[str] = []
        lock = threading.Lock()

        def attempt(fence: int):
            try:
                self.sink.stage(fence, f"worker-{fence}", b"x")
            except SINK.FenceError:
                with lock:
                    outcomes.append("REFUSED")
            else:
                with lock:
                    outcomes.append("ACCEPTED")

        threads = [threading.Thread(target=attempt, args=(fence,)) for fence in range(1, 10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(["REFUSED"] * 9, outcomes)
        self.assertIsNone(self.sink.read()["staged"])

    def test_separate_process_with_a_stale_fence_is_refused(self):
        """The guard must be durable, not an artifact of one process's memory."""
        self.sink.acquire(7, "worker-B")
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        stale = context.Process(target=_worker_process, args=(str(self.path), 3, "worker-A", queue))
        fresh = context.Process(target=_worker_process, args=(str(self.path), 7, "worker-B", queue))
        stale.start()
        stale.join(30)
        fresh.start()
        fresh.join(30)
        results = {worker: (outcome, error) for worker, outcome, error in (queue.get(), queue.get())}
        self.assertEqual(("REFUSED", "StaleFenceError"), results["worker-A"])
        self.assertEqual(("ACCEPTED", None), results["worker-B"])
        self.assertEqual("worker-B", self.sink.read()["staged"]["worker"])


class ReproductionTests(unittest.TestCase):
    def test_delayed_worker_reproduction_is_stopped_by_the_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = SINK.reproduce_delayed_worker(Path(directory))
        outcomes = [(item["step"], item["outcome"]) for item in report["timeline"]]
        self.assertEqual(
            [
                ("A acquires lease at fence 1", "ACCEPTED"),
                ("A stalls; coordinator re-leases to B at fence 2", "ACCEPTED"),
                ("B stages its result at fence 2", "ACCEPTED"),
                ("B commits at fence 2", "ACCEPTED"),
                ("A wakes and stages at stale fence 1", "REFUSED"),
                ("A retries commit at stale fence 1", "REFUSED"),
            ],
            outcomes,
        )
        self.assertEqual("worker-B", report["committed_by"])
        self.assertEqual(2, report["accepted_writes"])
        self.assertTrue(report["sink_bytes_unchanged_by_rejections"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
