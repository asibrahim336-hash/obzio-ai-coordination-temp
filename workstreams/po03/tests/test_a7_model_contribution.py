"""Tests for a7-u06: per-model contribution and cross-family disagreement,
computed per exact model slug from committed dispositions, with no
attribution to Auto. Frozen acceptance (workstreams/po03/control/dispatch/a7-u06.json):
"Contribution and disagreement are computed per exact model slug from
committed dispositions, with counts and no attribution to Auto."
Falsified if any unit lacks an exact model slug attribution.
"""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "model_contribution.py"
SPEC = importlib.util.spec_from_file_location("model_contribution", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/model-contribution-report.json"
RUNS_PATH = REPO_ROOT / "workstreams/po03/metrics/work-unit-runs.jsonl"
REGISTER_PATH = REPO_ROOT / "workstreams/po03/control/model-capability-register.json"


def load_unit_runs():
    return [
        json.loads(line)
        for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("record_type") == "unit_run"
    ]


class TestModelContribution(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_recomputation_matches_committed_report(self):
        recomputed = MODULE.compute(REPO_ROOT)
        self.assertEqual(recomputed, self.report)

    def test_every_dispatched_unit_is_attributed_to_exactly_one_model_bucket_or_excluded(self):
        runs = load_unit_runs()
        attributed_unit_ids = set()
        for bucket in self.report["per_model_contribution"].values():
            attributed_unit_ids.update(bucket["unit_ids"])
        excluded_unit_ids = {row["unit_id"] for row in self.report["excluded_not_exact_slug"]}
        self.assertEqual(attributed_unit_ids | excluded_unit_ids, {r["unit_id"] for r in runs})
        self.assertEqual(set(), attributed_unit_ids & excluded_unit_ids)

    def test_no_bucket_key_or_slug_is_auto_or_inherit(self):
        """The acceptance is falsified if any unit's model attribution is
        collapsed to a non-exact placeholder such as Auto or inherit."""
        forbidden = {"auto", "inherit"}
        for slug in self.report["per_model_contribution"]:
            self.assertNotIn(slug.lower(), forbidden)
            self.assertEqual(self.report["per_model_contribution"][slug]["model_slug"], slug)

    def test_auto_attribution_count_matches_excluded_list_length(self):
        self.assertEqual(
            self.report["auto_attribution_count"], len(self.report["excluded_not_exact_slug"])
        )

    def test_dispatched_counts_sum_to_total_attributed_units(self):
        total_dispatched = sum(
            bucket["dispatched_count"] for bucket in self.report["per_model_contribution"].values()
        )
        runs = load_unit_runs()
        self.assertEqual(total_dispatched, len(runs) - self.report["auto_attribution_count"])

    def test_result_committed_count_never_exceeds_dispatched_count(self):
        for bucket in self.report["per_model_contribution"].values():
            self.assertLessEqual(bucket["result_committed_count"], bucket["dispatched_count"])
            self.assertLessEqual(bucket["accepted_count"] + bucket["rejected_count"], bucket["dispatched_count"])

    def test_rate_fields_are_explicit_numerator_over_denominator_or_undefined(self):
        for bucket in self.report["per_model_contribution"].values():
            for rate_field in ("result_commit_rate", "acceptance_rate"):
                rate = bucket[rate_field]
                if rate["denominator"] == 0:
                    self.assertEqual(rate["value"], "UNDEFINED_0_OF_0")
                else:
                    self.assertAlmostEqual(rate["value"], rate["numerator"] / rate["denominator"])

    def test_disagreement_pairs_never_pair_a_family_with_itself(self):
        """cross_family_review_matrix rule: a reviewer must not share a model
        family with the producer it judges."""
        for pair in self.report["per_model_disagreement"].values():
            self.assertNotEqual(pair["producer_family"], pair["reviewer_family"])

    def test_disagreement_rate_is_explicit_numerator_over_denominator_or_undefined(self):
        for pair in self.report["per_model_disagreement"].values():
            rate = pair["disagreement_rate"]
            total = pair["rejected_count"] + pair["accepted_count"]
            self.assertEqual(rate["denominator"], total)
            if total == 0:
                self.assertEqual(rate["value"], "UNDEFINED_0_OF_0")
            else:
                self.assertAlmostEqual(rate["value"], pair["rejected_count"] / total)

    def test_family_resolution_never_silently_guesses_beyond_register_or_suffix_rule(self):
        register = json.loads(REGISTER_PATH.read_text(encoding="utf-8"))
        slug_to_family = {
            entry["slug"]: entry["family"] for entry in register.get("delegation_models_exposed", [])
        }
        for slug, bucket in self.report["per_model_contribution"].items():
            self.assertEqual(bucket["family"], MODULE.resolve_family(slug, slug_to_family))

    def test_measured_against_matches_work_unit_runs_metadata(self):
        meta = next(
            json.loads(line)
            for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("record_type") == "generation_metadata"
        )
        self.assertEqual(self.report["measured_against"]["ledger_head_sha256"], meta["ledger_head_sha256"])
        self.assertEqual(self.report["measured_against"]["ledger_rows"], meta["ledger_rows"])


if __name__ == "__main__":
    unittest.main()
