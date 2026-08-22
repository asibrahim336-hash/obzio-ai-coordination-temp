#!/usr/bin/env python3
"""Focused tests for the WA-018 queue/verification simulation and calibrator.

These tests carry the preregistered invalidating falsifiers (F-018-3, F-018-4,
F-018-8) plus analytic checks that pin the model against closed-form results,
so a simulator defect surfaces as a test failure rather than as a conclusion.

Run: python3 -m unittest discover -s . -p 'test_*.py' -v
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import calibrate_from_repository as calib  # noqa: E402
import queue_verification_sim as sim  # noqa: E402

BASE = sim.Config(concurrency=8, verifiers=1)
SEEDS = sim.seed_list(20260822, 8)


class CommonRandomNumbers(unittest.TestCase):
    def test_addressed_draws_are_stable_and_in_range(self) -> None:
        for index in range(64):
            value = sim.u01(20260822, index, "produce")
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 1.0)
            self.assertEqual(value, sim.u01(20260822, index, "produce"))

    def test_streams_are_independent(self) -> None:
        produce = [sim.u01(1, i, "produce") for i in range(64)]
        defect = [sim.u01(1, i, "defect") for i in range(64)]
        self.assertNotEqual(produce, defect)

    def test_unit_attributes_are_invariant_across_configurations(self) -> None:
        """The whole comparison rests on this: changing C or V must not change a unit."""
        reference = None
        for concurrency in (1, 8, 32):
            for verifiers in (1, 4):
                for policy in sim.POLICIES:
                    run = sim.Simulation(
                        replace(
                            BASE,
                            concurrency=concurrency,
                            verifiers=verifiers,
                            policy=policy,
                        )
                    )
                    run.run()
                    signature = [
                        (
                            unit.index,
                            unit.produce_seconds,
                            unit.nominal_verify_seconds,
                            unit.latent_defect,
                        )
                        for unit in run.units.values()
                        if not unit.is_rework
                    ]
                    if reference is None:
                        reference = signature
                    else:
                        self.assertEqual(reference, signature)

    def test_repeated_runs_are_byte_identical(self) -> None:
        first = json.dumps(sim.run_single(BASE), sort_keys=True)
        second = json.dumps(sim.run_single(BASE), sort_keys=True)
        self.assertEqual(first, second)


class DetectionPower(unittest.TestCase):
    def test_zero_work_has_exactly_zero_power(self) -> None:
        self.assertEqual(sim.detection_power(0.0, 300.0, 1.0, 3.0), 0.0)

    def test_nominal_work_has_exactly_full_power(self) -> None:
        self.assertEqual(sim.detection_power(300.0, 300.0, 0.9, 3.0), 0.9)

    def test_power_is_monotone_and_concave(self) -> None:
        values = [sim.detection_power(w, 100.0, 1.0, 3.0) for w in range(0, 101, 10)]
        for earlier, later in zip(values, values[1:]):
            self.assertLessEqual(earlier, later)
        second_differences = [
            values[i + 2] - 2 * values[i + 1] + values[i]
            for i in range(len(values) - 2)
        ]
        for value in second_differences:
            self.assertLessEqual(value, 1e-12)

    def test_power_never_exceeds_full(self) -> None:
        self.assertLessEqual(sim.detection_power(1e6, 300.0, 0.9, 3.0), 0.9)


class ConservationInvariants(unittest.TestCase):
    def test_conservation_holds_across_the_grid(self) -> None:
        for concurrency in (1, 4, 8, 16, 32):
            for verifiers in (1, 2, 8):
                for policy in sim.POLICIES:
                    metrics = sim.run_single(
                        replace(
                            BASE,
                            concurrency=concurrency,
                            verifiers=verifiers,
                            policy=policy,
                        )
                    )
                    self.assertEqual(
                        metrics["promoted_count"],
                        metrics["wave_units"] + metrics["recovery_rework_units"],
                    )
                    self.assertEqual(
                        metrics["fully_verified_count"]
                        + metrics["partially_verified_count"]
                        + metrics["unverified_promotion_count"],
                        metrics["promoted_count"],
                    )
                    self.assertEqual(
                        metrics["detected_defect_count"]
                        + metrics["escaped_defect_count"],
                        metrics["latent_defect_count"],
                    )

    def test_conservation_assertion_actually_fires(self) -> None:
        """A guard that cannot fail is not a guard."""
        with self.assertRaises(AssertionError):
            sim._assert_conservation(
                {
                    "wave_units": 64,
                    "recovery_rework_units": 0,
                    "promoted_count": 63,
                    "fully_verified_count": 63,
                    "partially_verified_count": 0,
                    "unverified_promotion_count": 0,
                    "false_green_count": 0,
                    "escaped_defect_count": 0,
                    "detected_defect_count": 0,
                    "latent_defect_count": 0,
                }
            )

    def test_partition_assertion_actually_fires(self) -> None:
        with self.assertRaises(AssertionError):
            sim._assert_conservation(
                {
                    "wave_units": 64,
                    "recovery_rework_units": 0,
                    "promoted_count": 64,
                    "fully_verified_count": 60,
                    "partially_verified_count": 0,
                    "unverified_promotion_count": 0,
                    "false_green_count": 0,
                    "escaped_defect_count": 0,
                    "detected_defect_count": 0,
                    "latent_defect_count": 0,
                }
            )


class PreregisteredFalsifiers(unittest.TestCase):
    def test_f018_3_blocking_gate_with_full_power_has_no_escape(self) -> None:
        """F-018-3: a structurally impossible failure must be impossible."""
        for concurrency in (1, 8, 32):
            for verifiers in (1, 4):
                metrics = sim.run_single(
                    replace(
                        BASE,
                        concurrency=concurrency,
                        verifiers=verifiers,
                        policy=sim.BLOCKING_GATE,
                        detect_power_full=1.0,
                    )
                )
                self.assertEqual(metrics["false_green_count"], 0)
                self.assertEqual(metrics["escaped_defect_count"], 0)
                self.assertEqual(metrics["unverified_promotion_count"], 0)

    def test_f018_3_blocking_gate_never_produces_capacity_false_greens(self) -> None:
        for concurrency in (1, 8, 32):
            metrics = sim.run_single(
                replace(BASE, concurrency=concurrency, policy=sim.BLOCKING_GATE)
            )
            self.assertEqual(metrics["false_green_count"], 0)
            self.assertEqual(metrics["partially_verified_count"], 0)

    def test_f018_4_zero_defect_probability_yields_no_escapes(self) -> None:
        for policy in sim.POLICIES:
            for concurrency in (1, 32):
                metrics = sim.run_single(
                    replace(
                        BASE,
                        concurrency=concurrency,
                        policy=policy,
                        latent_defect_probability=0.0,
                    )
                )
                self.assertEqual(metrics["latent_defect_count"], 0)
                self.assertEqual(metrics["false_green_count"], 0)
                self.assertEqual(metrics["escaped_defect_count"], 0)
                self.assertEqual(metrics["recovery_rework_units"], 0)

    def test_certain_defects_are_all_caught_by_full_blocking_verification(self) -> None:
        metrics = sim.run_single(
            replace(
                BASE,
                policy=sim.BLOCKING_GATE,
                latent_defect_probability=1.0,
                detect_power_full=1.0,
            )
        )
        self.assertEqual(metrics["latent_defect_count"], 64)
        self.assertEqual(metrics["detected_defect_count"], 64)
        self.assertEqual(metrics["escaped_defect_count"], 0)


class PolicyBehaviour(unittest.TestCase):
    def test_deadline_bypass_promotes_no_earlier_than_the_deadline(self) -> None:
        run = sim.Simulation(
            replace(BASE, concurrency=32, verifiers=1, policy=sim.DEADLINE_BYPASS)
        )
        run.run()
        bypassed = [unit for unit in run.units.values() if unit.work_applied == 0.0]
        self.assertTrue(bypassed)
        for unit in bypassed:
            self.assertEqual(
                unit.promoted_at - unit.staged_at, BASE.bypass_deadline_seconds
            )

    def test_sampled_verification_respects_the_queue_cap(self) -> None:
        metrics = sim.run_single(
            replace(
                BASE,
                concurrency=32,
                verifiers=1,
                policy=sim.SAMPLED_VERIFICATION,
                queue_cap=4,
            )
        )
        self.assertLessEqual(metrics["peak_staged_backlog"], 4 + 1)
        self.assertGreater(metrics["unverified_promotion_count"], 0)

    def test_truncated_verification_never_leaves_a_result_unverified(self) -> None:
        metrics = sim.run_single(
            replace(BASE, concurrency=32, verifiers=1, policy=sim.TRUNCATED_VERIFICATION)
        )
        self.assertEqual(metrics["unverified_promotion_count"], 0)
        self.assertGreater(metrics["partially_verified_count"], 0)
        self.assertLess(metrics["verification_work_applied_fraction"], 1.0)

    def test_blocking_gate_applies_complete_work_to_every_result(self) -> None:
        metrics = sim.run_single(replace(BASE, concurrency=32, verifiers=1))
        self.assertEqual(metrics["verification_work_applied_fraction"], 1.0)
        self.assertEqual(metrics["fully_verified_count"], metrics["promoted_count"])

    def test_abundant_verification_matches_blocking_gate_exactly(self) -> None:
        """With verifiers at least the wave size, no policy can degrade."""
        reference = sim.run_single(
            replace(BASE, concurrency=8, verifiers=64, policy=sim.BLOCKING_GATE)
        )
        for policy in sim.POLICIES:
            metrics = sim.run_single(replace(BASE, concurrency=8, verifiers=64, policy=policy))
            self.assertEqual(metrics["fully_verified_count"], reference["fully_verified_count"])
            self.assertEqual(metrics["false_green_count"], 0)


class QueueingLaws(unittest.TestCase):
    def test_tandem_pipeline_makespan_matches_lindley_recursion(self) -> None:
        """C=1, V=1 with a blocking gate is a two-stage tandem queue.

        The producer slot is released at staging, exactly as a real producer
        pushes its branch and returns before the controller verifies, so
        production of unit k+1 overlaps verification of unit k. The closed form
        is therefore the Lindley recursion and not the serial sum.
        """
        cfg = replace(
            BASE,
            concurrency=1,
            verifiers=1,
            policy=sim.BLOCKING_GATE,
            latent_defect_probability=0.0,
        )
        run = sim.Simulation(cfg)
        metrics = run.run()
        units = [run.units[index] for index in range(cfg.units)]
        produced_at = 0
        finished_at = 0
        for unit in units:
            produced_at += unit.produce_seconds
            finished_at = max(produced_at, finished_at) + unit.nominal_verify_seconds
        self.assertEqual(metrics["makespan_seconds"], finished_at)
        self.assertLess(
            finished_at,
            sum(unit.produce_seconds + unit.nominal_verify_seconds for unit in units),
            "a tandem pipeline must beat the serial sum",
        )

    def test_full_concurrency_makespan_matches_single_verifier_closed_form(self) -> None:
        """With C at the wave size, verification alone sets the makespan."""
        cfg = replace(
            BASE,
            concurrency=64,
            verifiers=1,
            policy=sim.BLOCKING_GATE,
            latent_defect_probability=0.0,
        )
        run = sim.Simulation(cfg)
        metrics = run.run()
        units = [run.units[index] for index in range(cfg.units)]
        staged = sorted(unit.produce_seconds for unit in units)
        verify_by_stage_order = [
            unit.nominal_verify_seconds
            for unit in sorted(units, key=lambda item: (item.produce_seconds, item.index))
        ]
        finished_at = 0
        for staged_at, service in zip(staged, verify_by_stage_order):
            finished_at = max(staged_at, finished_at) + service
        self.assertEqual(metrics["makespan_seconds"], finished_at)

    def test_producer_slot_is_released_at_staging(self) -> None:
        """Pipelining is a modelling claim, so it is pinned rather than assumed."""
        cfg = replace(BASE, concurrency=1, verifiers=1, latent_defect_probability=0.0)
        run = sim.Simulation(cfg)
        run.run()
        first = run.units[0]
        second = run.units[1]
        self.assertEqual(second.dispatched_at, first.staged_at)
        self.assertLess(second.dispatched_at, first.promoted_at)

    def test_verified_throughput_is_bounded_by_verification_capacity(self) -> None:
        """No configuration can verify faster than V slots allow."""
        for verifiers in (1, 2, 4):
            for concurrency in (1, 8, 32):
                run = sim.Simulation(
                    replace(
                        BASE,
                        concurrency=concurrency,
                        verifiers=verifiers,
                        policy=sim.BLOCKING_GATE,
                    )
                )
                metrics = run.run()
                mean_verify = sum(
                    unit.nominal_verify_seconds for unit in run.units.values()
                ) / len(run.units)
                ceiling = 3600.0 * verifiers / mean_verify
                self.assertLessEqual(
                    metrics["verified_throughput_per_hour"], ceiling + 1e-6
                )

    def test_raising_concurrency_cannot_reduce_backlog(self) -> None:
        previous = 0
        for concurrency in (1, 2, 4, 8, 16, 32):
            metrics = sim.run_single(
                replace(BASE, concurrency=concurrency, verifiers=1)
            )
            self.assertGreaterEqual(metrics["peak_staged_backlog"], previous)
            previous = metrics["peak_staged_backlog"]

    def test_p95_uses_nearest_rank(self) -> None:
        self.assertEqual(sim._p95(list(range(1, 101))), 95)
        self.assertEqual(sim._p95([5]), 5)
        self.assertEqual(sim._p95([]), 0)

    def test_peak_backlog_never_exceeds_the_wave(self) -> None:
        metrics = sim.run_single(replace(BASE, concurrency=32, verifiers=1))
        self.assertLessEqual(metrics["peak_staged_backlog"], 64 + 8)


class Validation(unittest.TestCase):
    def test_invalid_configurations_are_refused(self) -> None:
        for bad in (
            {"concurrency": 0},
            {"verifiers": 0},
            {"units": 0},
            {"latent_defect_probability": 1.5},
            {"detect_power_full": -0.1},
            {"policy": "NOT_A_POLICY"},
        ):
            with self.assertRaises(ValueError):
                sim.Simulation(replace(BASE, **bad))


class EnsembleAggregation(unittest.TestCase):
    def test_ensemble_reports_seed_fractions(self) -> None:
        aggregate = sim.run_ensemble(
            replace(BASE, concurrency=32, verifiers=1, policy=sim.DEADLINE_BYPASS),
            SEEDS,
        )
        self.assertEqual(aggregate["seeds"], len(SEEDS))
        self.assertGreaterEqual(aggregate["false_green_seed_fraction"], 0.0)
        self.assertLessEqual(aggregate["false_green_seed_fraction"], 1.0)
        self.assertNotIn("seed", aggregate["config"])

    def test_ensemble_is_reproducible(self) -> None:
        cfg = replace(BASE, concurrency=16, verifiers=2, policy=sim.SAMPLED_VERIFICATION)
        first = json.dumps(sim.run_ensemble(cfg, SEEDS), sort_keys=True)
        second = json.dumps(sim.run_ensemble(cfg, SEEDS), sort_keys=True)
        self.assertEqual(first, second)


class CalibratorContract(unittest.TestCase):
    def test_timeline_keeps_earliest_running_and_latest_terminal(self) -> None:
        events = [
            {"task_id": "T", "to_state": "RUNNING", "at": "2026-08-22T08:22:00Z"},
            {"task_id": "T", "to_state": "RUNNING", "at": "2026-08-22T08:21:00Z"},
            {"task_id": "T", "to_state": "ACCEPTED", "at": "2026-08-22T09:00:00Z"},
            {"task_id": "T", "to_state": "ACCEPTED", "at": "2026-08-22T09:04:00Z"},
        ]
        timeline = calib._unit_timeline(events)
        self.assertEqual(timeline["T"]["RUNNING"], "2026-08-22T08:22:00Z")
        self.assertEqual(timeline["T"]["ACCEPTED"], "2026-08-22T09:04:00Z")

    def test_events_without_a_task_or_timestamp_are_ignored(self) -> None:
        self.assertEqual(calib._unit_timeline([{"to_state": "RUNNING"}]), {})

    def test_numeric_extraction_handles_documented_shapes(self) -> None:
        self.assertEqual(calib._numeric(3), 3)
        self.assertEqual(calib._numeric({"value": 5}), 5)
        self.assertEqual(calib._numeric({"cycles": 3}), 3)
        self.assertIsNone(calib._numeric("NOT_SUPPORTED"))
        self.assertIsNone(calib._numeric(True))

    def test_seconds_handles_both_recorded_offset_forms(self) -> None:
        self.assertEqual(
            calib._seconds("2026-08-22T08:57:41+00:00", "2026-08-22T09:04:32Z"), 411
        )

    def test_material_prefix_excludes_canaries(self) -> None:
        self.assertTrue(calib._is_material("PO03-WA-008"))
        self.assertFalse(calib._is_material("PO03-WA-CANARY-000"))

    def test_capsule_carries_no_prohibited_field(self) -> None:
        capsule = json.loads((HERE / "calibration-capsule.json").read_text())
        text = json.dumps(capsule)
        for prohibited in ("claude", "gpt-5", "gemini", "composer", "bc-b195", "http"):
            self.assertNotIn(prohibited, text.lower())

    def test_capsule_distributions_match_recorded_sample_counts(self) -> None:
        capsule = json.loads((HERE / "calibration-capsule.json").read_text())
        for key in (
            "producer_produce_seconds",
            "verifier_commit_to_ingest_seconds",
        ):
            block = capsule["distributions"][key]
            self.assertEqual(block["n"], len(block["samples"]))
            self.assertEqual(block["min"], min(block["samples"]))
            self.assertEqual(block["max"], max(block["samples"]))

    def test_simulation_populations_match_the_capsule(self) -> None:
        """The default populations must be the frozen repository evidence."""
        capsule = json.loads((HERE / "calibration-capsule.json").read_text())
        self.assertEqual(
            sorted(BASE.produce_population),
            sorted(capsule["distributions"]["producer_produce_seconds"]["samples"]),
        )
        self.assertEqual(
            sorted(BASE.verify_population),
            sorted(
                capsule["distributions"]["verifier_commit_to_ingest_seconds"]["samples"]
            ),
        )


class CommandLine(unittest.TestCase):
    def test_single_run_cli_emits_parseable_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(HERE / "queue_verification_sim.py"),
                "--concurrency",
                "8",
                "--verifiers",
                "1",
                "--policy",
                "DEADLINE_BYPASS",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["sim_version"], sim.SIM_VERSION)
        self.assertIn("makespan_seconds", payload["run"])

    def test_ensemble_cli_emits_parseable_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(HERE / "queue_verification_sim.py"),
                "--concurrency",
                "16",
                "--verifiers",
                "1",
                "--seeds",
                "4",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["ensemble"]["seeds"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
