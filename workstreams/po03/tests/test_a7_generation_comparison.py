"""Tests for workstreams/po03/metrics/generate_comparison.py.

generation-comparison.json is a required durable output owned by po03-worker-a7
(workstreams/po03/metrics/). The G0/G1/G2 measurements themselves are owned by
po03-worker-a8 on cursor/po03-a8-successor-generations-ed20; this cohort's job
is only to define the schema those measurements must land in and to compute,
independently, from a8's raw per-suite and per-case data, the comparison the
frozen commission wording requires -- never to copy a8's own verdict fields,
never to invent a score.
"""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "generate_comparison.py"
SPEC = importlib.util.spec_from_file_location("generate_comparison", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/generation-comparison.json"

# The exact commit on a8's branch this cohort's committed report was measured
# against -- see this report's own measured_against.successor_commit_sha, and
# the coordinator's follow-up naming this same commit explicitly.
# workstreams/po03/evidence/snapshot-coupling.json documents why the live
# remote-tracking ref must never be used for a reproduction assertion: a8
# keeps landing more of that branch (this pin itself already superseded two
# earlier ones -- 347b0a9710596215f05e0c7b8bef062de1430add when G2's public
# transcript first landed, then 4c29dc315a597f586f07eb94f58f6905f7f0c0d4
# before holdout existed for any generation), so the ref itself is a moving
# target and "recomputed == committed" would fail as ordinary wave progress,
# not as a regression. compute()'s successor_pin parameter exists so this
# test can resolve the immutable commit directly instead.
PIN_SUCCESSOR_COMMIT = "01dfb05ccd267929abf8c54307c335dddf690adc"


class TestGenerationComparison(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_pin_matches_the_committed_measured_against(self):
        """PIN_SUCCESSOR_COMMIT must actually be the commit this report
        claims to be measured against, or the pinned reproduction below
        would silently be checking the wrong thing."""
        self.assertEqual(self.report["measured_against"]["successor_commit_sha"], PIN_SUCCESSOR_COMMIT)

    def test_recomputation_matches_committed_report_at_the_recorded_pin(self):
        """Never assert reproduction against the live a8 remote-tracking ref
        (workstreams/po03/evidence/snapshot-coupling.json): a8 keeps landing
        more of that branch, so the ref itself moves. Assert against the
        explicit immutable commit this report was actually measured against.

        The committed report was produced by a live-ref resolution (an
        operator ran the tool with no --successor-pin, right after fetching),
        so its measured_against.resolution_boundary reads "resolved <ref> ->
        <sha>"; recomputing here with an explicit successor_pin instead
        produces the semantically equivalent "pinned to explicit immutable
        commit <sha> -> <sha>". Both resolve to the identical sha (asserted
        explicitly below) by two different, equally valid code paths, so
        that one descriptive string is normalised out of the exact-equality
        check; every other field, including every independently computed
        condition, every agreement check and every verdict, must match
        byte-for-byte."""
        recomputed = MODULE.compute(REPO_ROOT, successor_pin=PIN_SUCCESSOR_COMMIT)
        self.assertEqual(
            recomputed["measured_against"]["successor_commit_sha"],
            self.report["measured_against"]["successor_commit_sha"],
        )
        recomputed_normalized = json.loads(json.dumps(recomputed))
        committed_normalized = json.loads(json.dumps(self.report))
        recomputed_normalized["measured_against"].pop("resolution_boundary")
        committed_normalized["measured_against"].pop("resolution_boundary")
        self.assertEqual(recomputed_normalized, committed_normalized)

    def test_pinned_reproduction_would_catch_a_mutated_report(self):
        """Prove the pinned assertion is not a tautology from the report's
        side: a deliberately corrupted copy of the report must not match."""
        recomputed = MODULE.compute(REPO_ROOT, successor_pin=PIN_SUCCESSOR_COMMIT)
        mutated_report = json.loads(json.dumps(self.report))
        mutated_report["overall_result"] = "PASS" if mutated_report["overall_result"] != "PASS" else "NOT_YET"
        self.assertNotEqual(recomputed, mutated_report)

    def test_pinned_reproduction_would_catch_a_generator_regression(self):
        """Prove the pinned assertion is not a tautology from the
        generator's side: a monkeypatched independent_conditions() must make
        the pinned recomputation disagree with the committed report."""
        original = MODULE.independent_conditions
        try:
            MODULE.independent_conditions = lambda *a, **k: {
                "baseline": "X",
                "candidate": "Y",
                "suite": "public",
                "baseline_pass_rate": 0,
                "candidate_pass_rate": 0,
                "lift": 0,
                "conditions": {},
                "unmet_conditions": ["TAMPERED"],
                "verdict": "TAMPERED",
            }
            tampered = MODULE.compute(REPO_ROOT, successor_pin=PIN_SUCCESSOR_COMMIT)
        finally:
            MODULE.independent_conditions = original
        self.assertNotEqual(tampered, self.report)

    def test_pinned_reproduction_would_catch_the_wrong_pin(self):
        """Prove the pinned assertion is not a tautology from the pin's
        side: resolving against the a8 branch's own root commit (a
        different, earlier immutable commit that predates every score)
        must not reproduce this report."""
        code, root_sha, _ = MODULE.run_git(REPO_ROOT, ["rev-list", "--max-parents=0", PIN_SUCCESSOR_COMMIT])
        self.assertEqual(code, 0)
        self.assertTrue(root_sha)
        older = MODULE.compute(REPO_ROOT, successor_pin=root_sha)
        self.assertNotEqual(older["measured_against"]["successor_commit_sha"], PIN_SUCCESSOR_COMMIT)
        self.assertNotEqual(older, self.report)

    def test_schema_declares_the_source_paths(self):
        schema = self.report["schema"]
        self.assertEqual(schema["prereg_path"], "workstreams/po03/successor/suite/lift-preregistration.json")
        self.assertEqual(schema["scores_path"], "workstreams/po03/successor/scores/generation-comparison.json")

    def test_all_three_generations_reported_at_the_pin(self):
        for gen in ("G0", "G1", "G2"):
            entry = self.report["generations"][gen]
            self.assertEqual(entry["generation"], gen)
            self.assertEqual(entry["status"], "REPORTED")
            for suite in ("public", "holdout"):
                suite_entry = entry["suites"][suite]
                self.assertEqual(suite_entry["status"], "REPORTED")
                self.assertIn("pass_rate", suite_entry)
                self.assertIn("failed_case_ids", suite_entry)
                self.assertIn("passed_case_ids", suite_entry)

    def test_overall_result_is_the_primary_preregistered_verdict_not_a_collapse(self):
        """overall_result must equal the primary preregistered comparison's
        verdict (G1 vs G2, holdout, per lift-preregistration.json), and must
        never be derived by collapsing it together with g0_vs_g1: the two
        verdicts stay observably distinct fields in the same report."""
        self.assertEqual(self.report["overall_result"], self.report["primary_preregistered_verdict"]["value"])
        self.assertIn("g0_vs_g1", self.report["lift"])
        self.assertIn("g1_vs_g2", self.report["lift"])

    def test_g0_vs_g1_and_g1_vs_g2_verdicts_are_kept_separate_and_may_differ(self):
        g0_vs_g1_public = self.report["lift"]["g0_vs_g1"]["public"]["verdict"]
        g1_vs_g2_public = self.report["lift"]["g1_vs_g2"]["public"]["verdict"]
        # As of this measurement these differ (NOT_YET vs PASS); the point of
        # this test is that the schema can express that difference at all,
        # not that it must always hold for any future landed data.
        self.assertIn(g0_vs_g1_public, ("PASS", "NOT_YET"))
        self.assertIn(g1_vs_g2_public, ("PASS", "NOT_YET"))

    def test_independent_computation_agrees_with_a8_headline_at_the_pin(self):
        """As of the pinned commit, this cohort's independent recomputation
        of all six preregistered conditions, from a8's raw per-suite and
        per-case data alone (never from a8's own conditions/verdict fields),
        agrees with a8's own committed verdict on both comparisons and both
        suites, and finds zero disagreements. If a future pin ever disagrees,
        this test must be updated to say so explicitly with the arithmetic,
        never silently loosened."""
        self.assertFalse(self.report["disagreements_found"])
        for pair_key in ("g0_vs_g1", "g1_vs_g2"):
            for suite in ("public", "holdout"):
                agreement = self.report["agreement_with_a8"][pair_key][suite]
                self.assertTrue(agreement["a8_comparison_found"])
                self.assertTrue(agreement["verdict_agrees"])
                self.assertEqual(agreement["disagreements"], [])

    def test_g0_vs_g1_fails_l2_and_l6_on_both_suites_with_l4_holding_only_on_holdout(self):
        """The precise, independently-derived nuance this cohort's arithmetic
        adds beyond a8's own summary: on the holdout suite, L4 (no per-case
        regression) actually HOLDS for G0-vs-G1, because G0 passed zero
        holdout cases to begin with, so there is nothing to regress from. On
        the public suite, where G0 passed 3 of 31 cases, L4 fails because
        P05-pinned-input-drift-detected regresses. Both suites still fail
        overall (L2 and L6 fail on both), so the verdict is NOT_YET either
        way, but the reason differs."""
        holdout = self.report["independent_conditions"]["g0_vs_g1"]["holdout"]
        public = self.report["independent_conditions"]["g0_vs_g1"]["public"]
        self.assertEqual(
            set(holdout["unmet_conditions"]),
            {"L2-no-false-completion", "L6-critical-correctness-complete"},
        )
        self.assertEqual(
            set(public["unmet_conditions"]),
            {"L2-no-false-completion", "L4-no-per-case-regression", "L6-critical-correctness-complete"},
        )
        self.assertEqual(holdout["conditions"]["L4-no-per-case-regression"]["held"], True)
        self.assertEqual(public["conditions"]["L4-no-per-case-regression"]["held"], False)
        self.assertEqual(
            public["conditions"]["L4-no-per-case-regression"]["observed"],
            ["P05-pinned-input-drift-detected"],
        )

    def test_g1_vs_g2_holds_every_condition_on_both_suites(self):
        for suite in ("public", "holdout"):
            result = self.report["independent_conditions"]["g1_vs_g2"][suite]
            self.assertEqual(result["unmet_conditions"], [])
            self.assertEqual(result["verdict"], "PASS")

    def test_primary_preregistered_verdict_matches_lift_preregistration_primary_comparison(self):
        primary = self.report["preregistration"]["primary_comparison"]
        self.assertEqual(primary, {"baseline": "G1", "candidate": "G2", "suite": "holdout"})
        pv = self.report["primary_preregistered_verdict"]
        self.assertEqual(pv["baseline"], "G1")
        self.assertEqual(pv["candidate"], "G2")
        self.assertEqual(pv["suite"], "holdout")
        self.assertEqual(pv["value"], "PASS")
        self.assertTrue(pv["agrees_with_a8_headline"])

    def test_compounding_claim_across_all_three_generations_is_not_sustained(self):
        """Per a8's own lift-preregistration.json not_claimable rule,
        compounding may not be claimed if any guard metric regresses even
        when the primary metric improves. Because g0_vs_g1 does not meet the
        guards on either suite, the full G0-through-G2 compounding claim
        must be reported as NOT_SUSTAINED even though overall_result (the
        primary G1-vs-G2 metric alone) is PASS."""
        self.assertEqual(self.report["compounding_claim_g0_through_g2"]["value"], "NOT_SUSTAINED")
        self.assertEqual(self.report["overall_result"], "PASS")

    def test_independence_boundaries_are_reflected_not_resolved(self):
        boundaries = self.report["independence_boundaries"]
        self.assertIn("g2_is_proposal_not_deployment", boundaries)
        self.assertIn("a8_recurrence_tests_self_authored", boundaries)
        self.assertIn("no_a8_unit_independently_accepted", boundaries)
        self.assertIn("holdout_independence_is_provisional", boundaries)
        for key in (
            "g2_is_proposal_not_deployment",
            "a8_recurrence_tests_self_authored",
            "no_a8_unit_independently_accepted",
            "holdout_independence_is_provisional",
        ):
            self.assertTrue(boundaries[key])

    def test_measured_against_records_the_exact_resolution_attempt(self):
        measured = self.report["measured_against"]
        self.assertEqual(measured["successor_remote_ref"], "origin/cursor/po03-a8-successor-generations-ed20")
        if measured["successor_commit_sha"] is None:
            self.assertTrue(measured["resolution_boundary"])

    def test_independent_conditions_function_computes_l4_regression_correctly(self):
        """Direct unit check of independent_conditions() against a small,
        hand-built fixture independent of any landed a8 data, so this
        function's L4 logic is verified even if a8's own data ever changes
        shape."""
        generations = {
            "A": {
                "suites": {
                    "public": {"pass_rate": 0.5, "critical_pass_rate": 1.0, "false_completion_count": 0,
                               "passed_case_ids": ["c1", "c2"], "failed_case_ids": ["c3"]},
                    "holdout": {"pass_rate": 0.0, "critical_pass_rate": 0.0, "false_completion_count": 1,
                                "passed_case_ids": [], "failed_case_ids": ["h1"]},
                }
            },
            "B": {
                "suites": {
                    "public": {"pass_rate": 0.5, "critical_pass_rate": 1.0, "false_completion_count": 0,
                               "passed_case_ids": ["c1", "c3"], "failed_case_ids": ["c2"]},
                    "holdout": {"pass_rate": 1.0, "critical_pass_rate": 1.0, "false_completion_count": 0,
                                "passed_case_ids": ["h1"], "failed_case_ids": []},
                }
            },
        }
        result = MODULE.independent_conditions(generations, "A", "B", "public", 0.1)
        # c2 passed under A, fails under B: L4 must be violated.
        self.assertEqual(result["conditions"]["L4-no-per-case-regression"]["held"], False)
        self.assertEqual(result["conditions"]["L4-no-per-case-regression"]["observed"], ["c2"])
        # public lift is 0.0 (0.5 - 0.5), below the 0.1 minimum: L1 fails.
        self.assertEqual(result["conditions"]["L1-minimum-lift"]["held"], False)

    def test_independent_conditions_l5_always_checks_public_suite(self):
        """L5 cross-checks the public suite regardless of which suite this
        comparison targets, matching a8's own preregistration wording
        ('public suite not worse') rather than the suite under test."""
        generations = {
            "A": {
                "suites": {
                    "public": {"pass_rate": 0.9, "critical_pass_rate": 1.0, "false_completion_count": 0,
                               "passed_case_ids": [], "failed_case_ids": []},
                    "holdout": {"pass_rate": 0.1, "critical_pass_rate": 0.0, "false_completion_count": 1,
                                "passed_case_ids": [], "failed_case_ids": []},
                }
            },
            "B": {
                "suites": {
                    "public": {"pass_rate": 0.2, "critical_pass_rate": 1.0, "false_completion_count": 0,
                               "passed_case_ids": [], "failed_case_ids": []},
                    "holdout": {"pass_rate": 0.9, "critical_pass_rate": 1.0, "false_completion_count": 0,
                                "passed_case_ids": [], "failed_case_ids": []},
                }
            },
        }
        result = MODULE.independent_conditions(generations, "A", "B", "holdout", 0.1)
        # holdout pass_rate improved (0.1 -> 0.9) but public regressed
        # (0.9 -> 0.2): L5 must fail even though we are scoring the holdout row.
        self.assertEqual(result["conditions"]["L5-public-suite-not-worse"]["held"], False)


if __name__ == "__main__":
    unittest.main()
