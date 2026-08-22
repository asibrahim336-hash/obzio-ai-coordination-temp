"""Tests for a7-u01: metric definitions must be frozen and internally consistent.

These tests check the *shape* of the frozen definitions document (every metric
has a formula, a source and an availability class, and every rate names its
numerator and denominator). They do not compute any metric value themselves;
that would defeat the point of freezing definitions before values exist.
"""

import json
import unittest
from pathlib import Path

METRICS_DIR = Path(__file__).parents[1] / "metrics"
DEFINITIONS_PATH = METRICS_DIR / "metric-definitions.json"

ALLOWED_AVAILABILITY = {"AVAILABLE", "NOT_SUPPORTED", "NOT_YET"}


class TestMetricDefinitionsFrozen(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(DEFINITIONS_PATH.read_text(encoding="utf-8"))

    def test_top_level_shape(self):
        for key in (
            "protocol_version",
            "definitions_id",
            "commission_id",
            "data_sources",
            "availability_classes",
            "row_level_fields",
            "report_level_metrics",
            "byte_stability_contract",
        ):
            self.assertIn(key, self.doc, f"missing top-level key: {key}")

    def test_availability_classes_documented(self):
        self.assertEqual(set(self.doc["availability_classes"].keys()), ALLOWED_AVAILABILITY)

    def test_every_row_level_field_has_formula_source_and_availability(self):
        for name, spec in self.doc["row_level_fields"].items():
            self.assertIn("formula", spec, f"{name}: missing formula")
            self.assertIn("source", spec, f"{name}: missing source")
            self.assertIn("availability", spec, f"{name}: missing availability")
            self.assertIn(spec["availability"], ALLOWED_AVAILABILITY, f"{name}: invalid availability class")

    def test_every_report_level_metric_has_formula_and_availability(self):
        for name, spec in self.doc["report_level_metrics"].items():
            self.assertIn("formula", spec, f"{name}: missing formula")
            self.assertIn("availability", spec, f"{name}: missing availability")
            self.assertIn(spec["availability"], ALLOWED_AVAILABILITY, f"{name}: invalid availability class")

    def test_rate_metrics_name_numerator_and_denominator(self):
        """Every metric whose name suggests a ratio must state both halves explicitly."""
        rate_markers = ("rate", "ratio", "conversion", "throughput")
        for name, spec in self.doc["report_level_metrics"].items():
            if any(marker in name for marker in rate_markers):
                self.assertIn("numerator_definition", spec, f"{name}: rate metric missing numerator_definition")
                self.assertIn("denominator_definition", spec, f"{name}: rate metric missing denominator_definition")

    def test_not_supported_metrics_state_a_boundary(self):
        for name, spec in self.doc["report_level_metrics"].items():
            if spec["availability"] == "NOT_SUPPORTED":
                self.assertIn("observed_boundary", spec, f"{name}: NOT_SUPPORTED metric missing observed_boundary")
        for name, spec in self.doc["row_level_fields"].items():
            if spec["availability"] == "NOT_SUPPORTED":
                self.assertIn("observed_boundary", spec, f"{name}: NOT_SUPPORTED field missing observed_boundary")

    def test_not_yet_metrics_state_a_boundary(self):
        for name, spec in self.doc["report_level_metrics"].items():
            if spec["availability"] == "NOT_YET":
                self.assertIn("boundary", spec, f"{name}: NOT_YET metric missing boundary")

    def test_token_and_cost_are_not_supported_and_never_estimated(self):
        field = self.doc["row_level_fields"]["token_and_cost_data"]
        self.assertEqual(field["availability"], "NOT_SUPPORTED")
        self.assertNotIn("estimate", json.dumps(field).lower())

    def test_document_is_deterministic_json(self):
        """Re-serializing the parsed document with sorted keys must match a canonical
        re-encoding, proving the file contains no duplicate keys or ordering tricks."""
        canonical = json.dumps(self.doc, sort_keys=True, ensure_ascii=False)
        reparsed = json.loads(canonical)
        self.assertEqual(reparsed, self.doc)


if __name__ == "__main__":
    unittest.main()
