#!/usr/bin/env python3
"""Focused tests for the WA-018 threshold, frontier and falsifier harness.

The harness decides the outcome, so its arithmetic is pinned independently of
the simulation: materiality rules, the separation between relative penalty and
absolute level, frontier extraction, monotonicity and the deviation record.

Run: python3 -m unittest discover -s . -p 'test_*.py' -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import queue_verification_sim as sim  # noqa: E402
import threshold_cases as tc  # noqa: E402


def cell(**overrides: object) -> dict[str, object]:
    base = {
        "false_green_total": 0,
        "false_green_seed_fraction": 0.0,
        "escaped_defect_total": 0,
        "mean_p95_verification_wait_seconds": 400.0,
        "mean_time_to_detect_seconds": 1000.0,
        "recovery_rework_units_total": 0,
        "mean_verified_throughput_per_hour": 9.0,
        "mean_nominal_throughput_per_hour": 9.0,
        "mean_peak_staged_backlog": 3.0,
    }
    base.update(overrides)
    return base


class BalancedRatio(unittest.TestCase):
    def test_ladder_matches_the_preregistered_ladder(self) -> None:
        prereg = tc._prereg()
        ratio = prereg["parameters"]["balanced_ratio_R"]
        for entry in prereg["parameters"]["proportional_control_ladder"]:
            self.assertEqual(
                tc.balanced_concurrency(entry["verifiers"], ratio),
                entry["concurrency"],
            )

    def test_balanced_concurrency_is_never_below_one(self) -> None:
        self.assertEqual(tc.balanced_concurrency(1, 0.1), 1)


class MaterialityRules(unittest.TestCase):
    def test_relative_increase_handles_missing_and_zero_baselines(self) -> None:
        self.assertIsNone(tc._relative_increase(None, 10.0))
        self.assertIsNone(tc._relative_increase(10.0, None))
        self.assertIsNone(tc._relative_increase(10.0, 0.0))
        self.assertEqual(tc._relative_increase(12.5, 10.0), 0.25)

    def test_latency_materiality_fires_at_exactly_the_threshold(self) -> None:
        baseline = cell()
        observed = cell(mean_p95_verification_wait_seconds=500.0)
        self.assertTrue(tc._material(observed, baseline, 900)["latency_material"])

    def test_latency_materiality_does_not_fire_below_the_threshold(self) -> None:
        baseline = cell()
        observed = cell(mean_p95_verification_wait_seconds=499.0)
        self.assertFalse(tc._material(observed, baseline, 900)["latency_material"])

    def test_absolute_slo_breach_is_material_in_the_as_written_rule(self) -> None:
        baseline = cell(mean_p95_verification_wait_seconds=1000.0)
        observed = cell(mean_p95_verification_wait_seconds=1000.0)
        verdict = tc._material(observed, baseline, 900)
        self.assertTrue(verdict["latency_material"])
        self.assertTrue(verdict["p95_wait_over_slo"])

    def test_absolute_slo_breach_is_not_a_relative_penalty(self) -> None:
        """This separation is the substance of deviation D-018-01."""
        baseline = cell(mean_p95_verification_wait_seconds=1000.0)
        observed = cell(mean_p95_verification_wait_seconds=1000.0)
        penalty = tc._penalty_only(observed, baseline)
        self.assertFalse(penalty["latency_material"])
        self.assertFalse(penalty["any_channel_material"])

    def test_any_false_green_is_material_with_no_tolerance_band(self) -> None:
        verdict = tc._material(cell(false_green_total=1), cell(), 900)
        self.assertTrue(verdict["false_green_material"])
        self.assertTrue(verdict["any_channel_material"])

    def test_penalty_only_uses_excess_over_the_reference(self) -> None:
        penalty = tc._penalty_only(
            cell(false_green_total=3), cell(false_green_total=3)
        )
        self.assertEqual(penalty["false_green_excess_over_reference"], 0)
        self.assertFalse(penalty["false_green_material"])

    def test_one_extra_rework_unit_is_material(self) -> None:
        verdict = tc._material(cell(recovery_rework_units_total=1), cell(), 900)
        self.assertTrue(verdict["recovery_material"])

    def test_time_to_detect_growth_is_material(self) -> None:
        verdict = tc._material(cell(mean_time_to_detect_seconds=1250.0), cell(), 900)
        self.assertTrue(verdict["recovery_material"])


class FrontierExtraction(unittest.TestCase):
    def _cells(self, grid: list[int], false_greens: dict[int, int]) -> dict:
        return {
            f"C{c}_V1": cell(
                false_green_total=false_greens.get(c, 0),
                mean_p95_verification_wait_seconds=100.0 * c,
                mean_verified_throughput_per_hour=9.0,
            )
            for c in grid
        }

    def test_safety_frontier_is_the_largest_clean_concurrency(self) -> None:
        grid = [1, 2, 4, 8]
        frontiers = tc._frontiers(self._cells(grid, {8: 3}), grid, 1, 900)
        self.assertEqual(frontiers["safety_frontier_concurrency"], 4)
        self.assertFalse(frontiers["safety_frontier_is_grid_maximum"])

    def test_safety_frontier_reports_grid_maximum_when_never_breached(self) -> None:
        grid = [1, 2, 4, 8]
        frontiers = tc._frontiers(self._cells(grid, {}), grid, 1, 900)
        self.assertEqual(frontiers["safety_frontier_concurrency"], 8)
        self.assertTrue(frontiers["safety_frontier_is_grid_maximum"])

    def test_service_frontier_respects_the_slo(self) -> None:
        grid = [1, 2, 4, 8]
        frontiers = tc._frontiers(self._cells(grid, {}), grid, 1, 450)
        self.assertEqual(frontiers["service_frontier_concurrency"], 4)

    def test_saturation_frontier_uses_the_two_percent_rule(self) -> None:
        grid = [1, 2, 4]
        cells = {
            "C1_V1": cell(mean_verified_throughput_per_hour=5.0),
            "C2_V1": cell(mean_verified_throughput_per_hour=9.0),
            "C4_V1": cell(mean_verified_throughput_per_hour=9.1),
        }
        frontiers = tc._frontiers(cells, grid, 1, 10_000)
        self.assertEqual(frontiers["saturation_frontier_concurrency"], 2)

    def test_monotonicity_detects_a_decreasing_series(self) -> None:
        frontiers = {
            "V1": {"safety_frontier_concurrency": 4, "service_frontier_concurrency": 8, "saturation_frontier_concurrency": 2},
            "V2": {"safety_frontier_concurrency": 8, "service_frontier_concurrency": 4, "saturation_frontier_concurrency": 4},
        }
        report = tc._monotonicity(frontiers, [1, 2])
        self.assertTrue(report["safety_frontier_concurrency"]["monotone_non_decreasing"])
        self.assertFalse(report["service_frontier_concurrency"]["monotone_non_decreasing"])

    def test_monotonicity_ignores_missing_values(self) -> None:
        frontiers = {
            "V1": {"safety_frontier_concurrency": None, "service_frontier_concurrency": 1, "saturation_frontier_concurrency": 1},
            "V2": {"safety_frontier_concurrency": 4, "service_frontier_concurrency": 2, "saturation_frontier_concurrency": 2},
        }
        report = tc._monotonicity(frontiers, [1, 2])
        self.assertTrue(report["safety_frontier_concurrency"]["monotone_non_decreasing"])


class CaseVerdicts(unittest.TestCase):
    def _observation(self, **aggregate: object) -> dict[str, object]:
        agg = cell(**aggregate)
        return {
            "policy": sim.BLOCKING_GATE,
            "concurrency": 8,
            "verifiers": 1,
            "balanced_concurrency": 3,
            "above_balanced_ratio": True,
            "aggregate": agg,
            "materiality": tc._material(agg, cell(), 900),
        }

    def test_no_penalty_expectation_fails_when_a_channel_is_material(self) -> None:
        spec = {"expected": "NO_PENALTY"}
        verdict = tc._case_verdict(spec, [self._observation(false_green_total=1)])
        self.assertFalse(verdict["expectation_met"])

    def test_false_green_expectation_requires_a_false_green(self) -> None:
        spec = {"expected": "FALSE_GREEN_PENALTY"}
        self.assertFalse(
            tc._case_verdict(spec, [self._observation()])["expectation_met"]
        )
        self.assertTrue(
            tc._case_verdict(spec, [self._observation(false_green_total=2)])[
                "expectation_met"
            ]
        )

    def test_latency_without_false_green_expectation_is_exclusive(self) -> None:
        spec = {"expected": "LATENCY_PENALTY_WITHOUT_FALSE_GREEN"}
        both = self._observation(
            mean_p95_verification_wait_seconds=5000.0, false_green_total=1
        )
        self.assertFalse(tc._case_verdict(spec, [both])["expectation_met"])
        latency_only = self._observation(mean_p95_verification_wait_seconds=5000.0)
        self.assertTrue(tc._case_verdict(spec, [latency_only])["expectation_met"])

    def test_no_escape_expectation_rejects_any_escape(self) -> None:
        spec = {"expected": "NO_ESCAPE_POSSIBLE"}
        self.assertFalse(
            tc._case_verdict(spec, [self._observation(escaped_defect_total=1)])[
                "expectation_met"
            ]
        )

    def test_proportional_slots_insufficient_needs_escape_without_false_green(self) -> None:
        spec = {"expected": "PROPORTIONAL_SLOTS_INSUFFICIENT"}
        self.assertTrue(
            tc._case_verdict(spec, [self._observation(escaped_defect_total=4)])[
                "expectation_met"
            ]
        )
        self.assertFalse(
            tc._case_verdict(
                spec, [self._observation(escaped_defect_total=4, false_green_total=1)]
            )["expectation_met"]
        )

    def test_unknown_expectation_is_refused(self) -> None:
        with self.assertRaises(AssertionError):
            tc._case_verdict({"expected": "SOMETHING_ELSE"}, [self._observation()])

    def test_every_case_spec_declares_a_supported_expectation(self) -> None:
        supported = {
            "NO_PENALTY",
            "LATENCY_PENALTY_WITHOUT_FALSE_GREEN",
            "FALSE_GREEN_PENALTY",
            "FALSE_GREEN_PENALTY_WITHOUT_BACKLOG",
            "ABOVE_BALANCED_RATIO",
            "PROPORTIONAL_SLOTS_INSUFFICIENT",
            "SEED_FRACTION_AT_OR_ABOVE_MARGIN",
            "PENALTY_PERSISTS",
            "NO_ESCAPE_POSSIBLE",
        }
        for spec in tc.CASE_SPECS:
            self.assertIn(spec["expected"], supported)
            self.assertIn("question", spec)
            self.assertIn("sub_hypothesis", spec)


class DeviationRecord(unittest.TestCase):
    def test_each_deviation_records_both_verdicts_and_a_cost(self) -> None:
        self.assertTrue(tc.DEVIATIONS)
        for deviation in tc.DEVIATIONS:
            for field in ("id", "preregistered_rule", "problem", "handling", "counted_as"):
                self.assertIn(field, deviation)
            self.assertTrue(
                any(key.startswith("verdict_") for key in deviation),
                "a deviation must record the verdict it changes",
            )

    def test_deviation_ids_are_unique(self) -> None:
        ids = [deviation["id"] for deviation in tc.DEVIATIONS]
        self.assertEqual(len(ids), len(set(ids)))


class PreregistrationBinding(unittest.TestCase):
    def test_harness_thresholds_match_the_preregistered_values(self) -> None:
        prereg = tc._prereg()
        text = json.dumps(prereg["comparison_thresholds"])
        self.assertIn("25 percent", text)
        self.assertIn("2 percent", text)
        self.assertIn("90 percent", text)
        self.assertEqual(tc.RELATIVE_MATERIALITY, 0.25)
        self.assertEqual(tc.SATURATION_TOLERANCE, 0.02)
        self.assertEqual(tc.SEED_SEPARATION_MARGIN, 0.90)

    def test_base_config_is_built_from_the_preregistration(self) -> None:
        prereg = tc._prereg()
        params = prereg["parameters"]
        base = tc._base_config(prereg)
        self.assertEqual(base.units, params["units_per_wave"])
        self.assertEqual(
            base.latent_defect_probability,
            params["latent_defect_probability"]["primary"],
        )
        self.assertEqual(base.queue_cap, params["queue_cap"]["primary"])
        self.assertEqual(
            base.bypass_deadline_seconds,
            params["bypass_deadline_seconds"]["primary"],
        )

    def test_every_preregistered_falsifier_is_evaluated(self) -> None:
        prereg = tc._prereg()
        declared = {item["id"] for item in prereg["falsifiers"]}
        results = json.loads(
            (HERE / "threshold-case-results.json").read_text(encoding="utf-8")
        )
        evaluated = {item["id"] for item in results["falsifiers"]}
        self.assertEqual(declared, evaluated)

    def test_every_preregistered_sub_hypothesis_has_a_case(self) -> None:
        prereg = tc._prereg()
        declared = {item["id"] for item in prereg["sub_hypotheses"]}
        covered = {spec["sub_hypothesis"] for spec in tc.CASE_SPECS}
        self.assertTrue(declared.issubset(covered | {"H-018-6"}))

    def test_recorded_results_carry_every_case_and_no_missing_verdict(self) -> None:
        results = json.loads(
            (HERE / "threshold-case-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(results["cases"]), len(tc.CASE_SPECS))
        for case in results["cases"]:
            self.assertIn("expectation_met", case["verdict"])
            self.assertIn("expected_before_execution", case)


class RecordedOutcomeIntegrity(unittest.TestCase):
    def test_frontier_results_cover_the_full_preregistered_grid(self) -> None:
        prereg = tc._prereg()
        params = prereg["parameters"]
        grid = json.loads((HERE / "frontier-results.json").read_text(encoding="utf-8"))
        self.assertEqual(grid["seeds"], params["seeds"]["count"])
        for policy in params["policies"]:
            for verifiers in params["verifier_grid"]:
                for concurrency in params["concurrency_grid"]:
                    self.assertIn(
                        f"C{concurrency}_V{verifiers}", grid["cells"][policy]
                    )

    def test_verified_throughput_never_exceeds_nominal_throughput(self) -> None:
        grid = json.loads((HERE / "frontier-results.json").read_text(encoding="utf-8"))
        for policy, cells in grid["cells"].items():
            for key, values in cells.items():
                self.assertLessEqual(
                    values["mean_verified_throughput_per_hour"],
                    values["mean_nominal_throughput_per_hour"] + 1e-6,
                    f"{policy} {key}",
                )

    def test_blocking_gate_records_no_false_green_anywhere(self) -> None:
        grid = json.loads((HERE / "frontier-results.json").read_text(encoding="utf-8"))
        for key, values in grid["cells"]["BLOCKING_GATE"].items():
            self.assertEqual(values["false_green_total"], 0, key)

    def test_usable_cap_never_exceeds_either_frontier(self) -> None:
        grid = json.loads((HERE / "frontier-results.json").read_text(encoding="utf-8"))
        for policy, per_v in grid["operating_recommendation"].items():
            for key, values in per_v.items():
                self.assertLessEqual(
                    values["usable_concurrency_cap"],
                    values["safety_frontier_concurrency"],
                    f"{policy} {key}",
                )
                self.assertLessEqual(
                    values["usable_concurrency_cap"],
                    values["saturation_frontier_concurrency"],
                    f"{policy} {key}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
