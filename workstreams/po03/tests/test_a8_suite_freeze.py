#!/usr/bin/env python3
"""Tests that the scoring suites are frozen and the holdout is independent.

A "frozen suite" and an "independent holdout" are the two claims that make a
lift number mean anything.  Both are checkable, so both are checked here rather
than described: the committed case files must match their generators and their
declared digests, the holdout must be byte-identical to the evaluator cohort's
own file, its author must differ from the generation author, and the lift metric
must have been preregistered with a no-regression clause before scoring.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.harness.runner import load_cases

SUITE_DIR = PO03 / "successor" / "suite"
MANIFEST = SUITE_DIR / "suite-manifest.json"
PREREGISTRATION = SUITE_DIR / "lift-preregistration.json"
PROVENANCE = SUITE_DIR / "holdout" / "provenance.json"
A6_SOURCE = SUITE_DIR / "holdout" / "a6-source-cases.json"

A6_CASE_FILE_SHA256 = "52ac6507f66086ff339c3659b681986f1337cea08411d099493b14b65c3d90ef"
A6_BRANCH = "cursor/po03-a6-independent-review-ed20"
A6_CASE_PATH = "workstreams/po03/review/luna/hidden-cases/cases.json"

GENERATION_OWNER = "po03-worker-a8"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


class GeneratorAgreementTests(unittest.TestCase):
    """A committed suite that no longer matches its generator is not frozen."""

    def test_public_suite_matches_its_generator(self):
        completed = run("workstreams/po03/successor/suite/build_public_suite.py", "--check")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("FROZEN", completed.stdout)

    def test_holdout_binding_matches_its_generator(self):
        completed = run("workstreams/po03/successor/suite/build_holdout_suite.py", "--check")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("FROZEN", completed.stdout)

    def test_manifest_digests_match_the_committed_files(self):
        completed = run("workstreams/po03/successor/suite/freeze_suites.py", "--check")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_every_declared_suite_exists_and_hashes_as_declared(self):
        self.assertTrue(self.manifest["suites"])
        for entry in self.manifest["suites"]:
            path = REPO_ROOT / entry["path"]
            self.assertTrue(path.is_file(), entry["path"])
            data = path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], entry["path"])
            self.assertEqual(len(data), entry["bytes"], entry["path"])

    def test_case_identifiers_are_unique_within_and_across_suites(self):
        seen: set[str] = set()
        for entry in self.manifest["suites"]:
            _, cases = load_cases(REPO_ROOT / entry["path"])
            ids = [case["id"] for case in cases]
            self.assertEqual(len(ids), len(set(ids)), f"duplicate id inside {entry['path']}")
            self.assertFalse(seen & set(ids), "a case id is shared between the public suite and the holdout")
            seen |= set(ids)

    def test_every_case_declares_what_it_is_for(self):
        for entry in self.manifest["suites"]:
            _, cases = load_cases(REPO_ROOT / entry["path"])
            for case in cases:
                self.assertTrue(case.get("intent", "").strip(), case["id"])
                self.assertTrue(case["steps"], case["id"])
                self.assertTrue(case["assert"], case["id"])
                self.assertTrue(case.get("criteria"), f"{case['id']} scores against no frozen criterion")


class HoldoutIndependenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        self.source = json.loads(A6_SOURCE.read_text(encoding="utf-8"))

    def test_holdout_author_differs_from_the_generation_author(self):
        authorship = self.provenance["authorship"]
        self.assertEqual(authorship["generations_authored_by"], GENERATION_OWNER)
        self.assertNotEqual(authorship["holdout_cases_authored_by"], GENERATION_OWNER)
        self.assertTrue(authorship["distinct_owners"])

    def test_vendored_copy_is_byte_identical_to_the_digest_a6_recorded(self):
        self.assertEqual(hashlib.sha256(A6_SOURCE.read_bytes()).hexdigest(), A6_CASE_FILE_SHA256)
        self.assertEqual(self.provenance["source"]["case_file_sha256"], A6_CASE_FILE_SHA256)
        self.assertEqual(self.source["authored_by"], "po03-worker-a6")
        self.assertTrue(self.source["authored_before_producer_read"])
        self.assertEqual(self.source["producer_test_hashes_seen_at_authoring"], [])

    def test_vendored_copy_still_matches_the_evaluator_branch_if_reachable(self):
        completed = subprocess.run(
            ["git", "cat-file", "blob", f"origin/{A6_BRANCH}:{A6_CASE_PATH}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.skipTest("evaluator branch not fetched in this clone")
        self.assertEqual(completed.stdout, A6_SOURCE.read_bytes(), "the vendored holdout drifted from a6's branch")

    def test_binding_covers_a6s_case_set_exactly_and_preserves_every_expectation(self):
        _, bound = load_cases(SUITE_DIR / "holdout" / "cases.json")
        self.assertEqual(
            sorted(case["id"] for case in bound),
            sorted(case["id"] for case in self.source["cases"]),
        )
        source_by_id = {case["id"]: case for case in self.source["cases"]}
        for case in bound:
            original = source_by_id[case["id"]]
            self.assertEqual(case["holdout_source"]["attack"], original["attack"])
            self.assertEqual(case["holdout_source"]["expected"], original["expected"])
            self.assertEqual(case["holdout_source"]["input_mutation"], original["input_mutation"])
            self.assertEqual(case["criteria"], original["criteria"])
            self.assertEqual(case["holdout_source"]["authored_by"], "po03-worker-a6")

    def test_the_encoding_boundary_is_recorded_rather_than_glossed(self):
        self.assertEqual(self.provenance["authorship"]["executable_binding_authored_by"], GENERATION_OWNER)
        self.assertTrue(self.provenance["limitations"])
        self.assertEqual(self.provenance["boundary_states"]["cross_family_holdout_available"], "NOT_YET")
        self.assertEqual(self.provenance["boundary_states"]["independent_acceptance_of_this_cohort"], "NOT_TESTED")


class PreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    def test_the_metric_of_record_is_the_holdout_not_the_self_authored_suite(self):
        self.assertEqual(self.prereg["primary_metric"]["metric_id"], "holdout_pass_rate")
        self.assertEqual(self.prereg["primary_metric"]["suite"], "holdout")
        self.assertEqual(self.prereg["primary_comparison"]["suite"], "holdout")

    def test_a_no_regression_clause_exists_and_covers_safety_and_per_case_outcomes(self):
        conditions = " ".join(self.prereg["lift_rule"]["conditions"])
        self.assertIn("no-false-completion", conditions)
        self.assertIn("no-safety-regression", conditions)
        self.assertIn("no-per-case-regression", conditions)
        self.assertIn("public-suite-not-worse", conditions)

    def test_the_threshold_is_positive_and_justified(self):
        self.assertGreater(self.prereg["lift_rule"]["minimum_lift"], 0)
        self.assertTrue(self.prereg["lift_rule"]["rationale"].strip())

    def test_compounding_from_the_self_authored_suite_alone_is_declared_unclaimable(self):
        text = " ".join(self.prereg["not_claimable"])
        self.assertIn("public suite alone", text)
        self.assertIn("guard metric regresses", text)

    def test_every_declared_comparison_is_scorable(self):
        for pair in self.prereg["comparisons"]:
            self.assertIn(pair["baseline"], {"G0", "G1", "G2"})
            self.assertIn(pair["candidate"], {"G0", "G1", "G2"})
            self.assertIn(pair["suite"], {"public", "holdout"})


if __name__ == "__main__":
    unittest.main()
