"""Falsification tests for PO03-WA-053 NOT_SUPPORTED preservation.

The hypothesis fails if any aggregation turns an unknown into a number, or lets a
caller read a value without its coverage.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metric_aggregator import (  # noqa: E402
    NOT_SUPPORTED,
    Aggregate,
    MetricCoercionError,
    aggregate_count,
    aggregate_mean,
    aggregate_percentile,
    aggregate_rate,
    aggregate_sum,
    is_unknown,
    numeric,
    roll_up,
)


class UnknownDetectionTests(unittest.TestCase):
    def test_every_sentinel_reads_as_unknown(self):
        for value in (None, NOT_SUPPORTED, "", "null", "NULL", "N/A", "n/a", "unknown", float("nan")):
            with self.subTest(value=value):
                self.assertTrue(is_unknown(value))

    def test_real_values_including_zero_are_known(self):
        for value in (0, 0.0, -1, 1e9, False, True):
            with self.subTest(value=value):
                self.assertFalse(is_unknown(value))

    def test_zero_is_not_confused_with_unknown(self):
        self.assertFalse(is_unknown(0))
        self.assertEqual(0, numeric(0))

    def test_coercing_an_unknown_raises(self):
        for value in (None, NOT_SUPPORTED, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(MetricCoercionError):
                    numeric(value)

    def test_non_numeric_known_values_are_refused(self):
        with self.assertRaises(MetricCoercionError):
            numeric("12")
        with self.assertRaises(MetricCoercionError):
            numeric([1])


class PreservationTests(unittest.TestCase):
    def test_sum_of_all_unknown_is_not_supported(self):
        agg = aggregate_sum("cost", [NOT_SUPPORTED, None, NOT_SUPPORTED])
        self.assertEqual(NOT_SUPPORTED, agg.value)
        self.assertFalse(agg.supported)
        self.assertEqual(3, agg.unknown_count)
        self.assertEqual(0.0, agg.coverage)

    def test_sum_ignores_unknowns_without_treating_them_as_zero(self):
        agg = aggregate_sum("cost", [2, NOT_SUPPORTED, 3])
        self.assertEqual(5, agg.value)
        self.assertEqual(2, agg.known_count)
        self.assertEqual(1, agg.unknown_count)
        self.assertAlmostEqual(2 / 3, agg.coverage)

    def test_mean_is_over_known_values_only(self):
        agg = aggregate_mean("wall_seconds", [10, NOT_SUPPORTED, 20])
        self.assertEqual(15, agg.value)
        # A zero-coercing implementation would have produced 10.
        self.assertNotEqual(10, agg.value)

    def test_mean_of_all_unknown_is_not_supported(self):
        self.assertEqual(NOT_SUPPORTED, aggregate_mean("cost", [None, None]).value)

    def test_rate_with_unknown_denominator_is_not_supported(self):
        agg = aggregate_rate("false_green_rate", [1, 2], [NOT_SUPPORTED, None])
        self.assertEqual(NOT_SUPPORTED, agg.value)
        self.assertIn("unknown", agg.boundary)

    def test_rate_with_zero_denominator_is_not_supported(self):
        agg = aggregate_rate("false_green_rate", [0, 0], [0, 0])
        self.assertEqual(NOT_SUPPORTED, agg.value)
        self.assertIn("zero", agg.boundary)

    def test_rate_computes_when_both_sides_have_known_values(self):
        agg = aggregate_rate("first_pass_acceptance", [3, NOT_SUPPORTED], [4, 4])
        self.assertAlmostEqual(3 / 8, agg.value)

    def test_rate_requires_aligned_populations(self):
        with self.assertRaises(ValueError):
            aggregate_rate("x", [1], [1, 2])

    def test_percentile_of_all_unknown_is_not_supported(self):
        self.assertEqual(NOT_SUPPORTED, aggregate_percentile("cycle_time", [None], 0.95).value)

    def test_percentile_ignores_unknowns(self):
        agg = aggregate_percentile("cycle_time", [1, NOT_SUPPORTED, 5, 9], 0.5)
        self.assertIn(agg.value, (5, 1))
        self.assertEqual(3, agg.known_count)

    def test_percentile_rejects_an_out_of_range_quantile(self):
        with self.assertRaises(ValueError):
            aggregate_percentile("cycle_time", [1], 1.5)

    def test_count_never_scores_an_unknown_as_a_non_match(self):
        agg = aggregate_count("provider_block", [True, NOT_SUPPORTED, False])
        self.assertEqual(1, agg.value)
        self.assertEqual(2, agg.known_count)
        self.assertEqual(1, agg.unknown_count)

    def test_count_of_all_unknown_is_not_supported(self):
        self.assertEqual(NOT_SUPPORTED, aggregate_count("provider_block", [None, None]).value)


class CoverageTests(unittest.TestCase):
    def test_coverage_of_an_empty_population_is_not_supported(self):
        agg = aggregate_sum("cost", [])
        self.assertEqual(NOT_SUPPORTED, agg.value)
        self.assertEqual(NOT_SUPPORTED, agg.coverage)

    def test_every_aggregate_row_carries_its_coverage_and_boundary(self):
        row = aggregate_sum("cost", [1, NOT_SUPPORTED]).as_row()
        for key in ("metric", "value", "known_count", "unknown_count", "population", "coverage", "observed_boundary"):
            self.assertIn(key, row)

    def test_a_not_supported_aggregate_records_an_observed_boundary(self):
        self.assertTrue(aggregate_sum("cost", [None]).boundary)
        self.assertTrue(aggregate_mean("cost", [None]).boundary)
        self.assertTrue(aggregate_rate("r", [None], [None]).boundary)


class RollUpTests(unittest.TestCase):
    def test_roll_up_propagates_per_metric_unknowns(self):
        rows = [
            {"cost": 1.0, "wall_seconds": 30, "context_waste": NOT_SUPPORTED},
            {"cost": NOT_SUPPORTED, "wall_seconds": 50, "context_waste": NOT_SUPPORTED},
        ]
        out = roll_up(rows, {"cost": "sum", "wall_seconds": "mean", "context_waste": "sum"})
        self.assertEqual(1.0, out["cost"]["value"])
        self.assertEqual(40, out["wall_seconds"]["value"])
        self.assertEqual(NOT_SUPPORTED, out["context_waste"]["value"])
        self.assertEqual(0.0, out["context_waste"]["coverage"])

    def test_a_missing_column_reads_as_unknown_not_zero(self):
        out = roll_up([{"cost": 2}], {"founder_interventions": "sum"})
        self.assertEqual(NOT_SUPPORTED, out["founder_interventions"]["value"])

    def test_unknown_aggregation_name_is_refused(self):
        with self.assertRaises(ValueError):
            roll_up([{"cost": 1}], {"cost": "median"})

    def test_aggregate_is_an_immutable_value_object(self):
        agg = aggregate_sum("cost", [1])
        self.assertIsInstance(agg, Aggregate)
        with self.assertRaises(Exception):
            agg.value = 99


class NanHygieneTests(unittest.TestCase):
    def test_nan_never_leaks_into_an_aggregate(self):
        agg = aggregate_mean("cost", [float("nan"), 4])
        self.assertEqual(4, agg.value)
        self.assertFalse(isinstance(agg.value, float) and math.isnan(agg.value))


if __name__ == "__main__":
    unittest.main()
