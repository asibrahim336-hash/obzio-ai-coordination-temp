#!/usr/bin/env python3
"""Tests for the lesson register, and the recurrence tests two lessons name.

The frozen acceptance for a8-u06 is falsified if fewer than three lessons reach
a live tested change, so that is asserted as a property of the register rather
than claimed in its prose. The register is also where this cohort could most
easily flatter itself, so the tests attack that directly: independence is
checked against the owner field rather than the wording, every mechanism must
resolve to something that exists, every recurrence test must actually run and
select exactly one test, and a lesson that names no live mechanism must not be
counted toward the threshold.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g2 import successor as g2
from successor.lessons.lessons import DISPOSITIONS, EVIDENCE, LESSONS, OWNER

REGISTER = PO03 / "successor" / "lessons" / "lessons.json"
BUILDER = "workstreams/po03/successor/lessons/build_lessons.py"
HYGIENE = "workstreams/po03/successor/check_custody_hygiene.py"
AUDITOR = "workstreams/po03/successor/audit_own_records.py"
SNAPSHOT = PO03 / "successor" / "self-readback-audit.json"
FINDING_CLASSES = {
    "ABSENT_AT_DECLARED_COMMIT",
    "STALE_AT_DECLARED_COMMIT",
    "RESOLVES_TO_THIS_RECORD",
}


def register() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


class RegisterIntegrityTests(unittest.TestCase):
    def test_document_matches_the_register_in_the_code(self):
        completed = subprocess.run(
            [sys.executable, "-I", BUILDER, "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_lesson_identifiers_are_unique(self):
        ids = [lesson["lesson_id"] for lesson in LESSONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_disposition_is_from_the_declared_vocabulary(self):
        for lesson in LESSONS:
            self.assertIn(lesson["disposition"], DISPOSITIONS, lesson["lesson_id"])

    def test_every_cited_evidence_record_exists(self):
        for lesson in LESSONS:
            for item in lesson["support"]:
                self.assertIn(item["evidence"], EVIDENCE, lesson["lesson_id"])

    def test_every_lesson_carries_a_basis_and_a_lineage_field(self):
        for lesson in LESSONS:
            self.assertTrue(lesson["disposition_basis"].strip(), lesson["lesson_id"])
            for key in ("derived_from", "supersedes", "superseded_by"):
                self.assertIn(key, lesson["lineage"], lesson["lesson_id"])


class IndependenceTests(unittest.TestCase):
    def test_independence_is_decided_by_owner_not_by_wording(self):
        for record in register()["lessons"]:
            owners = {item["owner"] for item in record["support"]}
            self.assertEqual(
                record["independently_supported"],
                bool(owners - {OWNER}),
                f"{record['lesson_id']} claims independence inconsistent with its cited owners",
            )

    def test_a_lesson_supported_only_by_this_cohort_is_not_called_independent(self):
        """The case that matters: L-05 is this cohort's own measurement."""
        records = {record["lesson_id"]: record for record in register()["lessons"]}
        self.assertFalse(records["L-05"]["independently_supported"])
        self.assertIn("independent support", records["L-05"]["disposition_basis"])

    def test_at_least_two_distinct_evaluator_owners_are_cited(self):
        owners = {record["owner"] for record in EVIDENCE.values()} - {OWNER}
        self.assertGreaterEqual(len(owners), 2, f"only {owners} cited")

    def test_recurrence_test_authorship_boundary_is_stated_not_glossed(self):
        """The acceptance asks for a test by another owner; this cohort wrote them."""
        document = register()
        boundary = document["recurrence_test_authorship_boundary"]
        self.assertIn("NOT_YET", boundary)
        for record in document["lessons"]:
            self.assertEqual(record["recurrence_test_author"], OWNER)


class AcceptanceThresholdTests(unittest.TestCase):
    def test_at_least_three_lessons_have_independent_support_and_a_live_mechanism(self):
        document = register()
        qualifying = [
            record["lesson_id"]
            for record in document["lessons"]
            if record["independently_supported"] and record["mechanism_is_live"]
        ]
        self.assertEqual(sorted(qualifying), document["lessons_with_live_mechanism_and_independent_support"])
        self.assertGreaterEqual(len(qualifying), 3, "a8-u06 is falsified below three")
        self.assertTrue(document["acceptance_met"])

    def test_a_lesson_with_no_mechanism_is_excluded_from_the_count(self):
        document = register()
        counted = set(document["lessons_with_live_mechanism_and_independent_support"])
        for record in document["lessons"]:
            if not record["mechanism_is_live"]:
                self.assertNotIn(record["lesson_id"], counted, record["lesson_id"])
                self.assertEqual(record["mechanism"]["kind"], "none")
                self.assertTrue(record["mechanism"]["reason"].strip())

    def test_every_g2_change_mechanism_names_a_change_that_exists(self):
        known = {change["change_id"] for change in g2.CHANGES}
        for lesson in LESSONS:
            if lesson["mechanism"]["kind"] != "g2_change":
                continue
            self.assertIn(lesson["mechanism"]["change_id"], known, lesson["lesson_id"])
            for also in lesson["mechanism"].get("also", []):
                self.assertIn(also, known, lesson["lesson_id"])

    def test_every_repository_mechanism_names_a_file_that_exists(self):
        for lesson in LESSONS:
            if lesson["mechanism"]["kind"] != "repository_mechanism":
                continue
            self.assertTrue((REPO_ROOT / lesson["mechanism"]["path"]).is_file(), lesson["lesson_id"])

    def test_every_g2_change_is_traced_to_a_lesson_in_this_register(self):
        self.assertEqual(register()["g2_changes_not_traced_to_a_lesson_here"], [])


class RecurrenceTestTests(unittest.TestCase):
    def test_every_lesson_names_a_recurrence_test_that_runs_and_selects_one_test(self):
        for lesson in LESSONS:
            module, _, method = lesson["recurrence_test"].rpartition(".")
            completed = subprocess.run(
                [
                    sys.executable, "-I", "-m", "unittest", "discover",
                    "-s", "workstreams/po03/tests",
                    "-p", f"{module.split('.')[0]}.py",
                    "-k", method,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, f"{lesson['lesson_id']}: {completed.stderr}")
            self.assertIn(
                "Ran 1 test",
                completed.stderr,
                f"{lesson['lesson_id']} names a test that does not select exactly one test",
            )

    def test_retained_and_retested_lessons_all_have_a_recurrence_test(self):
        for lesson in LESSONS:
            self.assertTrue(lesson["recurrence_test"].strip(), lesson["lesson_id"])

    def test_a_retest_disposition_names_its_residual(self):
        for lesson in LESSONS:
            if lesson["disposition"] == "RETEST":
                self.assertTrue(lesson["residual_boundary"], lesson["lesson_id"])


class HygieneMechanismTests(unittest.TestCase):
    """The live mechanism for L-13, and evidence for its RETEST disposition."""

    def test_no_derived_bytecode_is_tracked_under_owned_paths(self):
        completed = subprocess.run(
            [sys.executable, "-I", HYGIENE],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("CLEAN", completed.stdout)

    def test_the_mechanism_refuses_a_derived_file_when_one_is_present(self):
        """A check that cannot fail is not a mechanism.

        Rather than staging bytecode to prove it, the classifier is exercised
        directly on the shapes a6 found.
        """
        sys.path.insert(0, str(PO03 / "successor"))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "check_custody_hygiene", REPO_ROOT / HYGIENE
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for derived in (
            "workstreams/po03/tests/__pycache__/test_validate_contracts.cpython-312.pyc",
            "workstreams/po03/successor/g2/__pycache__/successor.cpython-312.pyc",
            "workstreams/po03/successor/harness/runner.pyc",
        ):
            self.assertTrue(module.is_derived(derived), derived)
        for evidence in (
            "workstreams/po03/successor/g2/successor.py",
            "workstreams/po03/successor/scores/generation-comparison.json",
        ):
            self.assertFalse(module.is_derived(evidence), evidence)

    def test_the_residual_boundary_is_still_true(self):
        """L-13 stays RETEST only while coordinator-owned paths remain unclean.

        If the named files are cleaned by their owner, this test fails and the
        disposition must be revisited. That is the retest, made automatic rather
        than left to memory.
        """
        record = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-13"]
        self.assertEqual(record["disposition"], "RETEST")
        completed = subprocess.run(
            ["git", "ls-files", "--", "workstreams/po03/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        tracked_derived = [
            line for line in completed.stdout.splitlines() if "__pycache__" in line or line.endswith(".pyc")
        ]
        self.assertTrue(
            tracked_derived,
            "no derived file is tracked anywhere any more, so L-13 should move from RETEST to RETAIN",
        )
        for path in tracked_derived:
            self.assertNotIn("successor/", path, "an owned path regressed")


class WithdrawnBeliefTests(unittest.TestCase):
    """Evidence for L-14's DELETE: the belief is withdrawn on the evaluator's own record."""

    def test_the_rejection_of_this_cohort_was_an_availability_boundary(self):
        record = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-14"]
        self.assertEqual(record["disposition"], "DELETE")
        self.assertFalse(record["mechanism_is_live"], "a withdrawn belief must not have changed a mechanism")
        self.assertIn("a6-correction", record["lineage"]["superseded_by"])

        commit = EVIDENCE["a6-correction"]["commit"]
        path = EVIDENCE["a6-correction"]["path"]
        blob = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            self.skipTest(f"evaluator ref {commit[:7]} not present in this clone")
        correction = json.loads(blob.stdout)
        unavailable = correction["availability_reclassification"]["unavailable_units"]
        self.assertIn("a8-u01..a8-u06", unavailable)
        quality = correction["availability_reclassification"]["quality_relevant_units_detail"]
        self.assertEqual(
            [unit for unit in quality if unit.startswith("a8")],
            [],
            "a8 appears among the quality-relevant units, so the belief was not withdrawn",
        )

    def test_no_acceptance_of_this_cohort_is_claimed(self):
        """Absence of an adverse finding is not acceptance."""
        record = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-14"]
        self.assertIn("not acceptance", record["residual_boundary"])


class SelfReadbackTests(unittest.TestCase):
    """L-08's internal reproduction: the lesson applied to this cohort's own records.

    The load-bearing test here reads backwards - it asserts that a defect is
    still present. L-08 claims a8's own result records do not resolve at the
    locators they declare, and a claim of that kind must not be allowed to
    survive the condition that made it true. If the coordinator-owned tool is
    repaired, this fails and says what to do about it.
    """

    def snapshot(self) -> dict:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    def test_no_record_of_this_cohort_resolves_at_its_declared_commit(self):
        completed = subprocess.run(
            [sys.executable, "-I", AUDITOR, "--verify-invariant"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "the read-back invariant no longer holds; if this says REVISIT, make_result.py was "
            f"repaired and L-08 must be revisited:\n{completed.stdout}{completed.stderr}",
        )
        self.assertIn("INVARIANT HOLDS", completed.stdout)

    def test_every_artifact_claim_read_back_byte_exact(self):
        """The half of the protocol that does work, and the reason nothing is lost."""
        snapshot = self.snapshot()
        self.assertEqual(snapshot["aggregate"]["artifact_verification_failures"], 0)
        self.assertGreater(snapshot["aggregate"]["artifact_claims_audited"], 0)
        for unit in snapshot["units"]:
            self.assertEqual(
                unit["artifacts_verified"],
                unit["artifact_count"],
                f"{unit['unit_id']} has an artifact that does not read back at its declared commit",
            )

    def test_the_snapshot_states_the_commit_it_observed(self):
        """A point-in-time observation has to say which point in time."""
        commit = self.snapshot()["observed_at_commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        resolved = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        self.assertEqual(resolved.returncode, 0, f"observed_at_commit {commit[:7]} is not a commit here")

    def test_the_findings_account_for_every_record_audited(self):
        aggregate = self.snapshot()["aggregate"]
        self.assertEqual(aggregate["records_resolving_to_themselves"], 0)
        self.assertEqual(
            aggregate["records_absent_at_declared_commit"] + aggregate["records_stale_at_declared_commit"],
            aggregate["records_audited"],
        )
        self.assertEqual(aggregate["result"], "DISCREPANCY_FOUND")
        for unit in self.snapshot()["units"]:
            self.assertIn(unit["record_finding"], FINDING_CLASSES, unit["unit_id"])

    def test_the_stale_case_is_distinguished_from_the_absent_case(self):
        """They are not equally bad, and collapsing them would hide the worse one."""
        snapshot = self.snapshot()
        stale = [
            unit["unit_id"] for unit in snapshot["units"]
            if unit["record_finding"] == "STALE_AT_DECLARED_COMMIT"
        ]
        absent = [
            unit["unit_id"] for unit in snapshot["units"]
            if unit["record_finding"] == "ABSENT_AT_DECLARED_COMMIT"
        ]
        self.assertTrue(stale, "no stale case observed, so the distinction is untested here")
        self.assertTrue(absent)
        self.assertEqual(sorted(snapshot["findings_by_class"]["STALE_AT_DECLARED_COMMIT"]), sorted(stale))

        reproduction = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-08"][
            "internal_reproduction"
        ]
        self.assertIn(
            "existence check",
            reproduction["significance"],
            "the reproduction must say why a resolving-but-stale locator is the worse case",
        )

    def test_the_classifier_reaches_all_three_outcomes(self):
        """Including the one that does not occur today, which is the fixed case."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("audit_own_records", REPO_ROOT / AUDITOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        current = b'{"unit_id": "a8-u01"}\n'
        self.assertEqual(module.classify(None, current), "ABSENT_AT_DECLARED_COMMIT")
        self.assertEqual(module.classify(current, current), "RESOLVES_TO_THIS_RECORD")
        self.assertEqual(module.classify(b'{"unit_id": "a8-u01", "older": true}\n', current), "STALE_AT_DECLARED_COMMIT")

    def test_l08_records_the_reproduction_without_counting_it_as_independent(self):
        record = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-08"]
        reproduction = record["internal_reproduction"]
        self.assertIsNotNone(reproduction, "L-08 no longer carries its internal reproduction")
        self.assertTrue((REPO_ROOT / reproduction["document"]).is_file())
        self.assertEqual(
            reproduction["recurrence_test"],
            f"test_a8_lessons.SelfReadbackTests.{self.test_no_record_of_this_cohort_resolves_at_its_declared_commit.__name__}",
        )
        self.assertNotIn(OWNER, record["support_owners"], "the reproduction leaked into the support list")
        self.assertTrue(record["independently_supported"])
        self.assertIn(OWNER, reproduction["not_independent_support"])

    def test_the_residual_names_how_a_parent_must_resolve_these_records(self):
        """A defect this cohort cannot fix must at least be actionable downstream."""
        record = {lesson["lesson_id"]: lesson for lesson in register()["lessons"]}["L-08"]
        self.assertIn("branch head", record["residual_boundary"])


class SupportVerificationTests(unittest.TestCase):
    def test_every_citation_matches_the_git_object_it_names(self):
        completed = subprocess.run(
            [sys.executable, "-I", BUILDER, "--verify-support"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("FAIL", completed.stdout)


if __name__ == "__main__":
    unittest.main()
