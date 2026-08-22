"""Unit tests for the a5-u09 rule-based causal-defect coder."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.causal_defect_coder_u09 import (  # noqa: E402
    DEFECT_CATEGORIES,
    code_causal_defect_list,
    code_evidence_rulings,
    code_ledger_rows,
    code_text,
    summarize,
)


class TestCodeText(unittest.TestCase):
    def test_producer_reported_triggers_producer_self_certification(self) -> None:
        self.assertIn("producer_self_certification", code_text("PRODUCER_REPORTED_REPRODUCTION_BYTES_NOT_PRESENT"))

    def test_uncommitted_triggers_discretionary_persistence(self) -> None:
        self.assertIn("discretionary_persistence", code_text("PROVIDER_COMPLETED_UNCOMMITTED"))

    def test_live_conflict_triggers_provider_route_as_custody(self) -> None:
        self.assertIn("provider_route_as_custody", code_text("COMPLETION_REPORTED_OR_LIVE_CONFLICT"))

    def test_unrecovered_after_four_routes_triggers_no_custody_invariants(self) -> None:
        self.assertIn("no_custody_invariants", code_text("UNRECOVERED_AFTER_FOUR_FOUNDER_REPORTED_ROUTES"))

    def test_exact_worker_denominator_triggers_scale_outpaced_capacity(self) -> None:
        self.assertIn("scale_outpaced_capacity", code_text("exact_worker_denominator NOT_YET_RECONCILED"))

    def test_unrelated_text_matches_nothing(self) -> None:
        self.assertEqual(code_text("this sentence is about gardening and has no relation to custody"), [])

    def test_a_string_can_match_multiple_categories(self) -> None:
        matches = code_text("PRODUCER_REPORTED completion but result was UNCOMMITTED")
        self.assertIn("producer_self_certification", matches)
        self.assertIn("discretionary_persistence", matches)


class TestCodeCausalDefectList(unittest.TestCase):
    def test_every_named_causal_defect_matches_its_own_category_at_least_once(self) -> None:
        causal_defects = [spec["causal_defect_text"] for spec in DEFECT_CATEGORIES.values()]
        coded = code_causal_defect_list(causal_defects)
        for i, category_id in enumerate(DEFECT_CATEGORIES):
            with self.subTest(category=category_id):
                self.assertIn(category_id, coded[f"causal_defect_{i}"])


class TestCodeEvidenceRulings(unittest.TestCase):
    def test_real_so02_style_rulings_are_coded_with_expected_categories(self) -> None:
        rulings = {
            "cohort_launch_reconciler_36_of_36": "PRODUCER_REPORTED_REPRODUCTION_BYTES_NOT_PRESENT",
            "code2_provider_state": "COMPLETION_REPORTED_OR_LIVE_CONFLICT",
            "code2_obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
            "code2_result_state": "UNRECOVERED_AFTER_FOUR_FOUNDER_REPORTED_ROUTES",
            "exact_worker_denominator": "NOT_YET_RECONCILED",
            "personal_memory_exclusion": "NOT_YET_END_TO_END",
        }
        coded = code_evidence_rulings(rulings)
        self.assertIn("producer_self_certification", coded["cohort_launch_reconciler_36_of_36"])
        self.assertIn("provider_route_as_custody", coded["code2_provider_state"])
        self.assertIn("discretionary_persistence", coded["code2_obzio_state"])
        self.assertIn("no_custody_invariants", coded["code2_result_state"])
        self.assertIn("scale_outpaced_capacity", coded["exact_worker_denominator"])
        self.assertEqual(coded["personal_memory_exclusion"], [])


class TestCodeLedgerRows(unittest.TestCase):
    def test_created_and_leased_rows_are_marked_structurally_ineligible(self) -> None:
        rows = [
            {"unit_id": "x-u01", "seq": 1, "event": "CREATED", "payload": {}},
            {"unit_id": "x-u01", "seq": 2, "event": "LEASED", "payload": {"worker_id": "w1"}},
        ]
        coded = code_ledger_rows(rows)
        self.assertIsNone(coded["x-u01#1"])
        self.assertIsNone(coded["x-u01#2"])

    def test_result_committed_row_is_eligible_and_coded(self) -> None:
        rows = [
            {
                "unit_id": "x-u01",
                "seq": 3,
                "event": "RESULT_COMMITTED",
                "payload": {"note": "PROVIDER_COMPLETED_UNCOMMITTED at time of report"},
            }
        ]
        coded = code_ledger_rows(rows)
        self.assertIsNotNone(coded["x-u01#3"])
        self.assertIn("discretionary_persistence", coded["x-u01#3"])

    def test_clean_result_committed_row_with_no_trigger_text_matches_nothing(self) -> None:
        rows = [
            {
                "unit_id": "x-u01",
                "seq": 3,
                "event": "RESULT_COMMITTED",
                "payload": {"result_commit_id": "abc123", "artifact_count": 2},
            }
        ]
        coded = code_ledger_rows(rows)
        self.assertEqual(coded["x-u01#3"], [])


class TestSummarize(unittest.TestCase):
    def test_counts_ineligible_eligible_and_matched_correctly(self) -> None:
        coded = {
            "a": None,
            "b": None,
            "c": [],
            "d": ["producer_self_certification"],
            "e": ["producer_self_certification", "discretionary_persistence"],
        }
        summary = summarize(coded)
        self.assertEqual(summary["total_records"], 5)
        self.assertEqual(summary["ineligible_records"], 2)
        self.assertEqual(summary["eligible_records"], 3)
        self.assertEqual(summary["matched_records"], 2)
        self.assertEqual(summary["category_counts"]["producer_self_certification"], 2)
        self.assertEqual(summary["category_counts"]["discretionary_persistence"], 1)
        self.assertEqual(summary["category_counts"]["schema_allowed_nulls"], 0)

    def test_all_categories_always_present_in_output_even_at_zero(self) -> None:
        summary = summarize({})
        self.assertEqual(set(summary["category_counts"]), set(DEFECT_CATEGORIES))


if __name__ == "__main__":
    unittest.main()
