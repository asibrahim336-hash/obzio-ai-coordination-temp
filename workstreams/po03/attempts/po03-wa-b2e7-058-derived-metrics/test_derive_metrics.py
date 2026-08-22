#!/usr/bin/env python3
"""Tests for the PO-03 derived-metrics computation.

The synthetic fixtures have hand-computed values, so a wrong arithmetic change
is caught by an exact equality rather than by a tolerance.  The refusal tests
prove that an absent input is refused instead of imputed.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
ROWS_057 = REPO / "workstreams/po03/attempts/po03-wa-b2e7-057-metric-collection-harness/work-unit-runs.jsonl"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"po03_058_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


derive_metrics = load("derive_metrics")
UNSUPPORTED = derive_metrics.UNSUPPORTED
DEFINITIONS = json.loads(
    (REPO / "workstreams/po03/metrics/metric-definitions.json").read_text(encoding="utf-8")
)
REQUIRED = list(DEFINITIONS["required_fields"])


def row(**overrides):
    """Build a synthetic row carrying exactly the frozen field set."""
    base = {field: UNSUPPORTED for field in REQUIRED}
    base.update(
        {
            "task_id": overrides.pop("task_id", "synthetic-unit"),
            "parent_id": "synthetic-parent",
            "function": "synthetic-function",
            "runtime": "synthetic-runtime",
            "exact_model": "synthetic-model",
            "reasoning": "high",
            "prompt_sha256": "0" * 64,
            "source_sha256": "1" * 64,
            "context_sha256": "2" * 64,
            "retry_count": 0,
            "readback_state": "NO_RESULT_OBSERVED",
            "defect_count": 0,
            "rework_count": 0,
            "founder_action_count": 0,
            "provider_block": "NONE_OBSERVED",
            "collision_count": 0,
            "recovery_events": 0,
        }
    )
    base.update(overrides)
    return base


class TestKnownValueFixtures(unittest.TestCase):
    def test_false_green_rate_is_exactly_one_quarter(self):
        rows = [
            row(task_id=f"pass-verified-{index}", first_pass_outcome="PASS", readback_state="VERIFIED")
            for index in range(3)
        ]
        rows.append(row(task_id="pass-mismatch", first_pass_outcome="PASS", readback_state="MISMATCH"))
        rows.append(row(task_id="fail-verified", first_pass_outcome="FAIL", readback_state="VERIFIED"))
        record = derive_metrics.false_green_rate(rows)
        self.assertEqual(record["denominator"], 4)
        self.assertEqual(record["numerator"], 1)
        self.assertEqual(record["value"], 0.25)

    def test_first_pass_acceptance_rate_is_exactly_one_half(self):
        rows = [
            row(task_id="a", independent_disposition="ACCEPTED", rework_count=0),
            row(task_id="b", independent_disposition="ACCEPTED", rework_count=1),
            row(task_id="c", independent_disposition="REJECTED", rework_count=0),
            row(task_id="d", independent_disposition="ACCEPTED", rework_count=0),
            row(task_id="e", independent_disposition="NOT_TESTED", rework_count=0),
        ]
        record = derive_metrics.first_pass_acceptance_rate(rows)
        self.assertEqual(record["denominator"], 4)
        self.assertEqual(record["numerator"], 2)
        self.assertEqual(record["value"], 0.5)

    def test_recovery_rate_is_exactly_two_thirds(self):
        rows = [
            row(task_id="r1", recovery_events=1, readback_state="VERIFIED"),
            row(task_id="r2", recovery_events=2, readback_state="VERIFIED"),
            row(task_id="r3", recovery_events=1, readback_state="MISMATCH"),
            row(task_id="r4", recovery_events=0, readback_state="VERIFIED"),
        ]
        record = derive_metrics.recovery_rate(rows)
        self.assertEqual((record["numerator"], record["denominator"]), (2, 3))
        self.assertEqual(record["value"], 2 / 3)

    def test_research_conversion_is_exactly_three_quarters(self):
        rows = [
            row(task_id=f"res-{index}", function="research-fn", readback_state="VERIFIED")
            for index in range(3)
        ]
        rows.append(row(task_id="res-3", function="research-fn", readback_state="NO_RESULT_OBSERVED"))
        rows.append(row(task_id="other", function="other-fn", readback_state="VERIFIED"))
        record = derive_metrics.research_to_reproduction_conversion(rows, "research-fn")
        self.assertEqual((record["numerator"], record["denominator"]), (3, 4))
        self.assertEqual(record["value"], 0.75)

    def test_throughput_is_exact_when_a_window_is_supplied(self):
        rows = [
            row(task_id=f"acc-{index}", independent_disposition="ACCEPTED", readback_state="VERIFIED")
            for index in range(6)
        ]
        record = derive_metrics.independently_accepted_throughput(rows, 3.0)
        self.assertEqual(record["numerator"], 6)
        self.assertEqual(record["value"], 2.0)

    def test_lesson_conversion_is_exact_when_lineage_is_supplied(self):
        lineage = {
            "accepted_lessons": [{"lesson_id": "L1"}, {"lesson_id": "L2"}, {"lesson_id": "L3"}, {"lesson_id": "L4"}],
            "live_mechanism_changes": [{"lesson_id": "L1"}, {"lesson_id": "L3"}],
        }
        record = derive_metrics.lesson_to_live_change_conversion([], lineage)
        self.assertEqual(record["value"], 0.5)

    def test_successor_lift_is_passed_through_without_reinterpretation(self):
        record = derive_metrics.successor_lift([], {"successor_lift": -0.125, "source": "unit-064"})
        self.assertEqual(record["value"], -0.125)


class TestRefusals(unittest.TestCase):
    def test_empty_population_is_refused_not_zeroed(self):
        rows = [row(task_id="only", first_pass_outcome="FAIL", readback_state="VERIFIED")]
        record = derive_metrics.false_green_rate(rows)
        self.assertEqual(record["value"], UNSUPPORTED)
        self.assertTrue(any("matched 0 of 1 recorded rows" in text for text in record["missing_inputs"]))

    def test_unsupported_input_cell_excludes_the_row(self):
        rows = [
            row(task_id="observed", first_pass_outcome="PASS", readback_state="VERIFIED"),
            row(task_id="unobserved", first_pass_outcome=UNSUPPORTED, readback_state="NO_RESULT_OBSERVED"),
        ]
        record = derive_metrics.false_green_rate(rows)
        self.assertEqual(record["denominator"], 1)
        self.assertEqual(record["rows_excluded_for_unsupported_inputs"], ["unobserved"])

    def test_throughput_without_a_time_base_is_refused(self):
        rows = [row(task_id="a", independent_disposition="ACCEPTED", readback_state="VERIFIED")]
        record = derive_metrics.independently_accepted_throughput(rows, None)
        self.assertEqual(record["value"], UNSUPPORTED)
        self.assertTrue(any("no absolute attempt start" in text for text in record["missing_inputs"]))

    def test_lesson_conversion_without_lineage_is_refused(self):
        record = derive_metrics.lesson_to_live_change_conversion([row()], None)
        self.assertEqual(record["value"], UNSUPPORTED)
        self.assertEqual(len(record["missing_inputs"]), 2)

    def test_successor_lift_without_comparison_is_refused(self):
        record = derive_metrics.successor_lift([row()], None)
        self.assertEqual(record["value"], UNSUPPORTED)
        self.assertTrue(any("generation comparison unit (064)" in text for text in record["missing_inputs"]))

    def test_successor_lift_refuses_a_non_numeric_claim(self):
        record = derive_metrics.successor_lift([], {"successor_lift": "positive"})
        self.assertEqual(record["value"], UNSUPPORTED)

    def test_missing_schema_field_is_named_rather_than_defaulted(self):
        stripped = [{key: value for key, value in row().items() if key != "readback_state"}]
        record = derive_metrics.false_green_rate(stripped)
        self.assertEqual(record["value"], UNSUPPORTED)
        self.assertIn("readback_state (absent from the recorded row schema)", record["missing_inputs"])

    def test_derive_refuses_a_metric_set_that_drifts_from_the_frozen_list(self):
        with self.assertRaises(ValueError):
            derive_metrics.derive(
                [row()],
                definitions={"metrics_version": "x", "derived_metrics": ["only_one_metric"]},
            )


class TestRealRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ROWS_057.is_file():
            raise unittest.SkipTest("unit 057 rows are not present in this checkout")
        cls.rows = derive_metrics.load_rows(ROWS_057)
        cls.payload = derive_metrics.derive(cls.rows, definitions=DEFINITIONS)

    def test_all_seven_frozen_derived_metrics_are_addressed(self):
        self.assertEqual(sorted(self.payload["derived_metrics"]), sorted(DEFINITIONS["derived_metrics"]))

    def test_false_green_rate_is_computed_from_real_rows(self):
        record = self.payload["derived_metrics"]["false_green_rate"]
        self.assertNotEqual(record["value"], UNSUPPORTED)
        passes = [item for item in self.rows if item["first_pass_outcome"] == "PASS"]
        self.assertEqual(record["denominator"], len(passes))
        self.assertEqual(
            record["numerator"], sum(1 for item in passes if item["readback_state"] != "VERIFIED")
        )

    def test_refused_metrics_name_their_missing_inputs(self):
        for name, record in self.payload["derived_metrics"].items():
            if record["value"] == UNSUPPORTED:
                self.assertTrue(record["missing_inputs"], name)

    def test_hypothesis_probe_reaches_an_explicit_verdict(self):
        probe = self.payload["hypothesis_probe"]
        self.assertIn(probe["verdict"], {"PASS", "NOT_YET", "REFUTED"})
        self.assertEqual(len(probe["quantities"]), 5)


if __name__ == "__main__":
    unittest.main()
