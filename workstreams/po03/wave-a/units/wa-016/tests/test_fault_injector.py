"""The fault schedule fires where it is aimed, and nowhere else."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.fault_injector import (
    ENVIRONMENT_KINDS,
    FAULT_KINDS,
    FAULT_POINTS,
    Fault,
    FaultInjector,
    LOSS_KINDS,
    ProcessLoss,
    quiet,
    random_schedule,
    single,
)


class ScheduleValidationTests(unittest.TestCase):
    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            Fault(kind="NOT_A_KIND", point="pre_journal_append")

    def test_unknown_point_is_rejected(self):
        with self.assertRaises(ValueError):
            Fault(kind="PROCESS_LOSS", point="not_a_point")

    def test_environment_is_an_accepted_pseudo_point(self):
        self.assertEqual("environment", Fault(kind="STALE_LEASE", point="environment").point)

    def test_occurrence_must_be_positive(self):
        with self.assertRaises(ValueError):
            Fault(kind="PROCESS_LOSS", point="pre_journal_append", occurrence=0)

    def test_arriving_at_an_unknown_point_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            quiet().arrive("not_a_point")

    def test_every_loss_and_environment_kind_is_a_declared_kind(self):
        self.assertTrue(LOSS_KINDS <= set(FAULT_KINDS))
        self.assertTrue(ENVIRONMENT_KINDS <= set(FAULT_KINDS))


class FiringTests(unittest.TestCase):
    def test_quiet_injector_never_fires(self):
        injector = quiet()
        for point in FAULT_POINTS:
            self.assertIsNone(injector.arrive(point))
        self.assertEqual([], injector.fired)

    def test_a_fault_fires_once_and_is_consumed(self):
        injector = single("PROCESS_LOSS", "post_journal_append")
        self.assertIsNotNone(injector.arrive("post_journal_append"))
        self.assertIsNone(injector.arrive("post_journal_append"))
        self.assertEqual([], injector.armed)

    def test_occurrence_selects_which_arrival_fires(self):
        injector = single("PROCESS_LOSS", "pre_journal_append", occurrence=3)
        self.assertIsNone(injector.arrive("pre_journal_append"))
        self.assertIsNone(injector.arrive("pre_journal_append"))
        self.assertIsNotNone(injector.arrive("pre_journal_append"))

    def test_arrivals_at_other_points_do_not_advance_the_count(self):
        injector = single("PROCESS_LOSS", "pre_journal_append", occurrence=2)
        injector.arrive("pre_journal_append")
        for _ in range(5):
            injector.arrive("post_journal_append")
        self.assertIsNotNone(injector.arrive("pre_journal_append"))

    def test_loss_kinds_raise_and_other_kinds_are_returned(self):
        with self.assertRaises(ProcessLoss) as raised:
            single("PROCESS_LOSS", "pre_readback").crash_if("pre_readback")
        self.assertEqual("pre_readback", raised.exception.point)
        fault = single("CALLBACK_LOSS", "pre_callback_send").crash_if("pre_callback_send")
        self.assertIsNotNone(fault)
        self.assertEqual("CALLBACK_LOSS", fault.kind)


class ArmingTests(unittest.TestCase):
    def test_an_inactive_injector_records_arrivals_without_firing(self):
        injector = FaultInjector([Fault(kind="PROCESS_LOSS", point="pre_journal_append")])
        self.assertIsNone(injector.arrive("pre_journal_append"))
        self.assertEqual(1, injector.arrivals("pre_journal_append"))
        self.assertEqual([], injector.fired)

    def test_arming_restarts_occurrence_counting(self):
        """Setup must not consume the occurrence the cell aims at."""
        injector = FaultInjector([Fault(kind="PROCESS_LOSS", point="pre_journal_append")])
        for _ in range(4):
            injector.arrive("pre_journal_append")
        injector.arm()
        with self.assertRaises(ProcessLoss):
            injector.crash_if("pre_journal_append")


class DeterminismTests(unittest.TestCase):
    def test_the_same_arrival_sequence_digests_identically(self):
        def run() -> str:
            injector = single("PROCESS_LOSS", "post_readback")
            injector.arrive("pre_journal_append", rel="journal.jsonl")
            injector.arrive("pre_snapshot_write", rel="state.json")
            return injector.trace_digest()

        self.assertEqual(run(), run())

    def test_a_different_arrival_sequence_digests_differently(self):
        first = single("PROCESS_LOSS", "post_readback")
        first.arrive("pre_journal_append")
        second = single("PROCESS_LOSS", "post_readback")
        second.arrive("pre_snapshot_write")
        self.assertNotEqual(first.trace_digest(), second.trace_digest())

    def test_a_seeded_random_schedule_is_reproducible(self):
        left = [f.cell_id for f in random_schedule(4242).faults]
        right = [f.cell_id for f in random_schedule(4242).faults]
        self.assertEqual(left, right)

    def test_environment_kinds_are_scheduled_at_the_environment_point(self):
        for seed in range(60):
            for fault in random_schedule(seed).faults:
                if fault.kind in ENVIRONMENT_KINDS:
                    self.assertEqual("environment", fault.point)


if __name__ == "__main__":
    unittest.main()
