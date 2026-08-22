#!/usr/bin/env python3
"""Tests for the PO-03 metric collection harness and its fabrication refusal."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"po03_057_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = load("collect_metrics")
validate_rows = load("validate_rows")

DEFINITIONS = json.loads((REPO / collect.DEFINITIONS_PATH).read_text(encoding="utf-8"))
REQUIRED = list(DEFINITIONS["required_fields"])
UNSUPPORTED = DEFINITIONS["unsupported_value"]


class CollectedCorpus:
    """One real collection run shared by the tests that read it."""

    payload = None

    @classmethod
    def get(cls):
        if cls.payload is None:
            cls.payload = collect.build_rows(REPO, REQUIRED)
        return cls.payload


class TestFrozenDefinitionsAlignment(unittest.TestCase):
    def test_harness_registry_covers_exactly_the_frozen_fields(self):
        self.assertEqual(sorted(collect.FIELD_SOURCES), sorted(REQUIRED))

    def test_unsupported_sentinel_matches_the_frozen_definitions(self):
        self.assertEqual(collect.UNSUPPORTED, UNSUPPORTED)

    def test_every_registry_entry_declares_a_source_kind(self):
        for field, spec in collect.FIELD_SOURCES.items():
            self.assertIn(
                spec["kind"], {"MEASURED", "PROVIDER_UNSUPPORTED", "OBSERVED_OR_ABSENT"}, field
            )
            self.assertTrue(spec["operational_definition"].strip(), field)
            self.assertTrue(spec["durable_source"].strip(), field)


class TestRealCollection(unittest.TestCase):
    def setUp(self):
        self.payload = CollectedCorpus.get()
        self.rows = self.payload["rows"]

    def test_one_row_per_counted_unit(self):
        expected = validate_rows.counted_task_ids(REPO)
        self.assertEqual(len(expected), 64)
        self.assertEqual([row["task_id"] for row in self.rows], expected)

    def test_rows_carry_exactly_the_frozen_field_set(self):
        for row in self.rows:
            self.assertEqual(list(row), REQUIRED, row["task_id"])

    def test_provider_unsupported_fields_are_never_valued(self):
        unsupported_fields = [
            field for field, spec in collect.FIELD_SOURCES.items() if spec["kind"] == "PROVIDER_UNSUPPORTED"
        ]
        self.assertTrue(unsupported_fields)
        for row in self.rows:
            for field in unsupported_fields:
                self.assertEqual(row[field], UNSUPPORTED, f"{row['task_id']}.{field}")

    def test_every_unsupported_cell_resolves_to_an_exact_boundary(self):
        field_level, row_level = validate_rows._boundary_index(self.payload["boundaries"])
        for row in self.rows:
            for field in REQUIRED:
                if row[field] != UNSUPPORTED:
                    continue
                boundary = row_level.get((row["task_id"], field)) or field_level.get(field, "")
                self.assertGreaterEqual(
                    len(boundary.strip()),
                    validate_rows.MIN_BOUNDARY_CHARS,
                    f"{row['task_id']}.{field} boundary too thin: {boundary!r}",
                )

    def test_key_census_is_executed_not_asserted(self):
        census = self.payload["boundaries"]["key_census"]
        self.assertGreater(census["documents_scanned"]["capsule_documents"], 0)
        self.assertGreater(census["documents_scanned"]["event_documents"], 0)
        self.assertGreater(census["distinct_key_names"], 0)
        for field in collect.PROBES:
            self.assertIn(field, census["matches"])

    def test_real_rows_pass_the_validator(self):
        errors = validate_rows.validate(
            self.rows,
            DEFINITIONS,
            self.payload["boundaries"],
            self.payload["field_source_registry"],
            validate_rows.counted_task_ids(REPO),
        )
        self.assertEqual(errors, [])


class TestFabricationRefusal(unittest.TestCase):
    def setUp(self):
        self.payload = CollectedCorpus.get()
        self.rows = [dict(row) for row in self.payload["rows"]]
        self.boundaries = self.payload["boundaries"]
        self.registry = self.payload["field_source_registry"]
        self.expected = validate_rows.counted_task_ids(REPO)

    def run_validator(self, rows):
        return validate_rows.validate(rows, DEFINITIONS, self.boundaries, self.registry, self.expected)

    def test_rejects_invented_token_count(self):
        self.rows[0]["available_tokens"] = 128000
        errors = self.run_validator(self.rows)
        self.assertTrue(any("available_tokens" in error and "invented" in error for error in errors), errors)

    def test_rejects_zero_cost_substituted_for_missing_data(self):
        self.rows[1]["available_cost"] = 0
        errors = self.run_validator(self.rows)
        self.assertTrue(any("available_cost" in error for error in errors), errors)

    def test_rejects_placeholder_string(self):
        self.rows[2]["exact_model"] = "unknown"
        errors = self.run_validator(self.rows)
        self.assertTrue(any("placeholder" in error for error in errors), errors)

    def test_rejects_negative_sentinel(self):
        self.rows[3]["defect_count"] = -1
        errors = self.run_validator(self.rows)
        self.assertTrue(any("defect_count" in error for error in errors), errors)

    def test_rejects_non_sha256_hash(self):
        self.rows[4]["prompt_sha256"] = "deadbeef"
        errors = self.run_validator(self.rows)
        self.assertTrue(any("prompt_sha256" in error for error in errors), errors)

    def test_rejects_fabricated_commit_id(self):
        self.rows[5]["result_commit_id"] = "not-a-commit"
        errors = self.run_validator(self.rows)
        self.assertTrue(any("result_commit_id" in error for error in errors), errors)

    def test_rejects_verified_readback_without_a_commit(self):
        row = self.rows[6]
        row["readback_state"] = "VERIFIED"
        row["result_commit_id"] = UNSUPPORTED
        errors = self.run_validator(self.rows)
        self.assertTrue(
            any("readback_state VERIFIED without an observed result_commit_id" in error for error in errors),
            errors,
        )

    def test_rejects_unsupported_without_a_boundary(self):
        stripped = {
            "boundaries_version": "PO03-METRIC-BOUNDARIES-v1",
            "field_level": [],
            "row_level": [],
        }
        errors = validate_rows.validate(self.rows, DEFINITIONS, stripped, self.registry, self.expected)
        self.assertTrue(any("without an observed boundary" in error for error in errors), errors)

    def test_rejects_thin_boundary_text(self):
        thin = {
            "boundaries_version": "PO03-METRIC-BOUNDARIES-v1",
            "field_level": [{"field": field, "boundary": "not supported"} for field in REQUIRED],
            "row_level": [],
        }
        errors = validate_rows.validate(self.rows, DEFINITIONS, thin, self.registry, self.expected)
        self.assertTrue(any("not an exact observation" in error for error in errors), errors)

    def test_rejects_missing_row_for_a_counted_unit(self):
        errors = self.run_validator(self.rows[:-1])
        self.assertTrue(any("has no metric row" in error for error in errors), errors)

    def test_rejects_duplicate_row(self):
        errors = self.run_validator(self.rows + [dict(self.rows[0])])
        self.assertTrue(any("duplicate row" in error for error in errors), errors)

    def test_rejects_extra_field(self):
        self.rows[7]["invented_field"] = 1
        errors = self.run_validator(self.rows)
        self.assertTrue(any("does not match frozen definitions" in error for error in errors), errors)

    def test_rejects_unobserved_unit_carrying_downstream_values(self):
        row = next((row for row in self.rows if row["readback_state"] == "NO_RESULT_OBSERVED"), None)
        if row is None:
            self.skipTest("every counted unit had an observed result at collection time")
        row["first_pass_outcome"] = "PASS"
        errors = self.run_validator(self.rows)
        self.assertTrue(any("cannot have been measured" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
