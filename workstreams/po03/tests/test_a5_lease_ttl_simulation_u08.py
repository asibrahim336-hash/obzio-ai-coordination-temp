"""Unit tests for the a5-u08 lease-TTL discrete-event simulation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.lease_ttl_simulation_u08 import (  # noqa: E402
    Epoch,
    SimConfig,
    cost,
    evaluate_epoch,
    evaluate_fleet,
    generate_fleet_timeline,
    generate_worker_timeline,
)


class TestEvaluateEpoch(unittest.TestCase):
    def test_healthy_epoch_with_tiny_gaps_and_huge_ttl_is_none(self) -> None:
        epoch = Epoch(start=0.0, duration=100.0, heartbeats=[10.0, 20.0, 30.0, 100.0], crash_time=None)
        outcome, recovery = evaluate_epoch(epoch, ttl=1000.0)
        self.assertEqual(outcome, "none")
        self.assertIsNone(recovery)

    def test_healthy_epoch_with_gap_exceeding_tiny_ttl_is_false_eviction(self) -> None:
        epoch = Epoch(start=0.0, duration=100.0, heartbeats=[10.0, 20.0, 30.0, 100.0], crash_time=None)
        outcome, recovery = evaluate_epoch(epoch, ttl=1.0)
        self.assertEqual(outcome, "false_eviction")
        self.assertIsNone(recovery)

    def test_crashed_epoch_is_eventually_a_true_recovery_with_generous_ttl(self) -> None:
        epoch = Epoch(start=0.0, duration=100.0, heartbeats=[10.0, 20.0, 30.0, 100.0], crash_time=15.0)
        outcome, recovery = evaluate_epoch(epoch, ttl=1000.0)
        self.assertEqual(outcome, "true_recovery")
        # eviction happens at last successful heartbeat (10.0) + ttl; crash at 15.0
        self.assertAlmostEqual(recovery, 1000.0 + 10.0 - 15.0)

    def test_crash_before_any_heartbeat_detected_relative_to_epoch_start(self) -> None:
        epoch = Epoch(start=0.0, duration=100.0, heartbeats=[10.0, 100.0], crash_time=3.0)
        outcome, recovery = evaluate_epoch(epoch, ttl=5.0)
        self.assertEqual(outcome, "true_recovery")
        self.assertAlmostEqual(recovery, 5.0 - 3.0)

    def test_recovery_time_is_never_negative(self) -> None:
        for ttl in (1.0, 5.0, 10.0, 50.0, 500.0):
            for crash_time in (0.5, 5.0, 50.0, 99.0):
                epoch = Epoch(start=0.0, duration=100.0, heartbeats=[10.0, 20.0, 50.0, 100.0], crash_time=crash_time)
                outcome, recovery = evaluate_epoch(epoch, ttl=ttl)
                if outcome == "true_recovery":
                    self.assertGreaterEqual(recovery, 0.0)

    def test_every_crashed_epoch_resolves_never_falls_through_to_none(self) -> None:
        # Sentinel guarantee: an epoch with a crash_time must never return "none".
        for ttl in (0.5, 1.0, 3.3, 500.0):
            epoch = Epoch(start=0.0, duration=100.0, heartbeats=[7.0, 41.0, 100.0], crash_time=99.9)
            outcome, _ = evaluate_epoch(epoch, ttl=ttl)
            self.assertIn(outcome, {"true_recovery", "false_eviction"})


class TestFleetTimeline(unittest.TestCase):
    def test_same_seed_reproduces_identical_timeline(self) -> None:
        cfg = SimConfig(num_workers=5, epochs_per_worker=8)
        a = generate_fleet_timeline(seed=123, cfg=cfg)
        b = generate_fleet_timeline(seed=123, cfg=cfg)
        self.assertEqual(
            [[(e.start, e.duration, e.heartbeats, e.crash_time) for e in worker] for worker in a],
            [[(e.start, e.duration, e.heartbeats, e.crash_time) for e in worker] for worker in b],
        )

    def test_different_seeds_diverge(self) -> None:
        cfg = SimConfig(num_workers=5, epochs_per_worker=8)
        a = generate_fleet_timeline(seed=1, cfg=cfg)
        b = generate_fleet_timeline(seed=2, cfg=cfg)
        self.assertNotEqual(
            [e.crash_time for worker in a for e in worker],
            [e.crash_time for worker in b for e in worker],
        )

    def test_timeline_shape_matches_config(self) -> None:
        cfg = SimConfig(num_workers=4, epochs_per_worker=6)
        fleet = generate_fleet_timeline(seed=7, cfg=cfg)
        self.assertEqual(len(fleet), 4)
        for worker in fleet:
            self.assertEqual(len(worker), 6)

    def test_every_heartbeat_list_ends_with_a_sentinel_at_epoch_end(self) -> None:
        cfg = SimConfig(num_workers=3, epochs_per_worker=5)
        fleet = generate_fleet_timeline(seed=9, cfg=cfg)
        for worker in fleet:
            for epoch in worker:
                self.assertAlmostEqual(epoch.heartbeats[-1], epoch.start + epoch.duration)

    def test_crash_time_always_within_epoch_bounds(self) -> None:
        cfg = SimConfig(num_workers=6, epochs_per_worker=10, crash_prob=0.5)
        fleet = generate_fleet_timeline(seed=11, cfg=cfg)
        for worker in fleet:
            for epoch in worker:
                if epoch.crash_time is not None:
                    self.assertGreaterEqual(epoch.crash_time, epoch.start)
                    self.assertLess(epoch.crash_time, epoch.start + epoch.duration)


class TestEvaluateFleetAndCost(unittest.TestCase):
    def test_same_timeline_different_ttl_changes_the_split(self) -> None:
        cfg = SimConfig(num_workers=20, epochs_per_worker=30)
        fleet = generate_fleet_timeline(seed=42, cfg=cfg)
        tiny = evaluate_fleet(fleet, ttl=1.0)
        huge = evaluate_fleet(fleet, ttl=100000.0)
        self.assertGreater(tiny["false_eviction_rate"], huge["false_eviction_rate"])
        self.assertGreaterEqual(huge["mean_recovery_time"], tiny["mean_recovery_time"])

    def test_every_epoch_is_accounted_for_exactly_once(self) -> None:
        cfg = SimConfig(num_workers=10, epochs_per_worker=20)
        fleet = generate_fleet_timeline(seed=5, cfg=cfg)
        for ttl in (5.0, 50.0, 500.0):
            m = evaluate_fleet(fleet, ttl=ttl)
            self.assertEqual(m["total_epochs"], cfg.num_workers * cfg.epochs_per_worker)
            self.assertEqual(m["healthy_epochs"] + m["crashed_epochs"], m["total_epochs"])
            # A false eviction can fire on an epoch that would eventually
            # have crashed anyway, if the TTL is small enough to evict
            # before that later crash takes effect -- so false_evictions is
            # bounded by total_epochs, not by healthy_epochs alone.
            self.assertLessEqual(m["false_evictions"], m["total_epochs"])
            self.assertLessEqual(m["true_recoveries"], m["crashed_epochs"])
            self.assertLessEqual(m["false_evictions"] + m["true_recoveries"], m["total_epochs"])

    def test_extremely_small_ttl_can_evict_epochs_before_their_own_later_crash(self) -> None:
        # heartbeat_interval=10 > ttl=1, so the very first heartbeat check
        # always fails before any real heartbeat, regardless of whether
        # this epoch's crash_time (drawn from later in its duration) has
        # happened yet -- an epoch destined to crash later can still be
        # correctly counted as a false eviction because the eviction fired
        # for the wrong (premature) reason.
        cfg = SimConfig(num_workers=10, epochs_per_worker=20, crash_prob=0.5)
        fleet = generate_fleet_timeline(seed=13, cfg=cfg)
        m = evaluate_fleet(fleet, ttl=1.0)
        self.assertGreater(m["false_evictions"], m["healthy_epochs"])

    def test_cost_increases_with_false_eviction_weight_when_rate_is_positive(self) -> None:
        measurement = {"mean_recovery_time": 10.0, "false_eviction_rate": 0.2}
        self.assertLess(cost(measurement, 10.0), cost(measurement, 100.0))

    def test_cost_ignores_weight_when_false_eviction_rate_is_zero(self) -> None:
        measurement = {"mean_recovery_time": 10.0, "false_eviction_rate": 0.0}
        self.assertEqual(cost(measurement, 10.0), cost(measurement, 999.0))


if __name__ == "__main__":
    unittest.main()
