#!/usr/bin/env python3
"""Tests that every G2 change is traceable, and that nothing untraceable slipped in.

The frozen acceptance for a8-u04 is falsified if G2 contains a change with no
traceable G1 failure or accepted lesson.  That is a property of the code, so it
is tested rather than reviewed: each change must name at least one cause, each
named case must exist in a frozen suite, G1 must actually fail it, G2 must
actually pass it, and each change must name a recurrence test that exists.
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

from successor.g1 import factory as g1
from successor.g2 import successor as g2
from successor.harness.runner import load_cases, run_suite

LINEAGE = PO03 / "successor" / "g2" / "lineage.json"
LESSONS = PO03 / "successor" / "lessons" / "lessons.json"
SUITES = (
    PO03 / "successor" / "suite" / "public" / "cases.json",
    PO03 / "successor" / "suite" / "holdout" / "cases.json",
)


def catalogue() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for path in SUITES:
        _, entries = load_cases(path)
        for case in entries:
            cases[case["id"]] = case
    return cases


class LineageDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lineage = json.loads(LINEAGE.read_text(encoding="utf-8"))
        cls.cases = catalogue()

    def test_lineage_document_matches_the_change_table_in_the_code(self):
        completed = subprocess.run(
            [sys.executable, "-I", "workstreams/po03/successor/g2/build_lineage.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_every_change_is_represented_exactly_once(self):
        self.assertEqual(
            [change["change_id"] for change in self.lineage["changes"]],
            [change["change_id"] for change in g2.CHANGES],
        )
        self.assertEqual(self.lineage["change_count"], len(g2.CHANGES))

    def test_no_change_exists_without_a_declared_cause(self):
        for change in self.lineage["changes"]:
            self.assertTrue(
                change["caused_by_failures"] or change["caused_by_lessons"],
                f"{change['change_id']} would falsify a8-u04",
            )

    def test_every_named_failure_exists_in_a_frozen_suite(self):
        for change in self.lineage["changes"]:
            self.assertEqual(change["unknown_case_ids"], [], change["change_id"])
            for case_id in change["caused_by_failures"]:
                self.assertIn(case_id, self.cases, f"{change['change_id']} names a case that is not frozen")

    def test_every_named_failure_is_one_g1_actually_fails(self):
        named = sorted({case_id for change in self.lineage["changes"] for case_id in change["caused_by_failures"]})
        selected = [self.cases[case_id] for case_id in named]
        outcomes = {record["case_id"]: record["passed"] for record in run_suite(g1.build, selected)}
        for case_id in named:
            self.assertFalse(outcomes[case_id], f"{case_id} is cited as a G1 failure but G1 passes it")

    def test_every_named_failure_is_one_g2_actually_fixes(self):
        named = sorted({case_id for change in self.lineage["changes"] for case_id in change["caused_by_failures"]})
        selected = [self.cases[case_id] for case_id in named]
        outcomes = {record["case_id"]: record["passed"] for record in run_suite(g2.build, selected)}
        for case_id in named:
            self.assertTrue(outcomes[case_id], f"{case_id} is cited as closed by G2 but G2 fails it")

    def test_every_change_reports_all_its_named_failures_closed(self):
        for change in self.lineage["changes"]:
            if change["caused_by_failures"]:
                self.assertIs(change["all_named_failures_closed"], True, change["change_id"])
            else:
                self.assertEqual(change["all_named_failures_closed"], "NOT_APPLICABLE", change["change_id"])

    def test_a_change_with_no_frozen_case_rests_on_an_independent_lesson(self):
        """The suites froze before the evaluators published, so later findings have no case.

        Such a change is still traceable, but only through a lesson. Allowing it
        without that requirement would reopen the untraceable-change hole that
        a8-u04's acceptance turns on, so the basis is asserted explicitly.
        """
        if not LESSONS.is_file():
            self.skipTest("lesson ledger lands with a8-u06")
        lessons = {
            lesson["lesson_id"]: lesson
            for lesson in json.loads(LESSONS.read_text(encoding="utf-8"))["lessons"]
        }
        for change in self.lineage["changes"]:
            if change["caused_by_failures"]:
                self.assertEqual(change["evidence_basis"], "frozen_suite_case", change["change_id"])
                continue
            self.assertEqual(change["evidence_basis"], "independently_supported_lesson", change["change_id"])
            self.assertTrue(change["caused_by_lessons"], change["change_id"])
            for lesson_id in change["caused_by_lessons"]:
                self.assertIn(lesson_id, lessons, change["change_id"])
                self.assertTrue(
                    lessons[lesson_id]["independently_supported"],
                    f"{change['change_id']} rests on {lesson_id}, which has no independent support",
                )

    def test_every_change_names_a_recurrence_test_that_runs(self):
        for change in self.lineage["changes"]:
            module_name, _, method = change["recurrence_test"].rpartition(".")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "workstreams/po03/tests",
                    "-p",
                    f"{module_name.split('.')[0]}.py",
                    "-k",
                    method,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, f"{change['change_id']}: {completed.stderr}")
            self.assertIn("Ran 1 test", completed.stderr, f"{change['change_id']} named test did not select exactly one test")

    def test_a_change_declined_for_lack_of_a_cause_is_recorded(self):
        self.assertTrue(self.lineage["not_changed_and_why"])
        for entry in self.lineage["not_changed_and_why"]:
            self.assertTrue(entry["candidate"].strip())
            self.assertTrue(entry["reason"].strip())

    def test_a_declined_candidate_later_adopted_keeps_its_original_record(self):
        """Superseding must add a disposition, not rewrite what was believed."""
        adopted = [
            entry for entry in self.lineage["not_changed_and_why"] if entry.get("superseded_by")
        ]
        change_ids = {change["change_id"] for change in self.lineage["changes"]}
        for entry in adopted:
            self.assertIn(entry["superseded_by"], change_ids)
            self.assertTrue(entry["disposition_basis"].strip())
            self.assertTrue(entry["reason"].strip(), "the original reasoning must survive the supersession")


class LessonCrossReferenceTests(unittest.TestCase):
    def test_every_lesson_cited_by_a_change_exists_in_the_lesson_ledger(self):
        if not LESSONS.is_file():
            self.skipTest("lesson ledger lands with a8-u06")
        lessons = json.loads(LESSONS.read_text(encoding="utf-8"))
        known = {lesson["lesson_id"] for lesson in lessons["lessons"]}
        cited = {lesson_id for change in g2.CHANGES for lesson_id in change["caused_by_lessons"]}
        self.assertTrue(cited)
        self.assertEqual(cited - known, set(), "a change cites a lesson that is not in the ledger")


class CoverageTests(unittest.TestCase):
    """Every G1 failure should be accounted for, not just the convenient ones."""

    def test_every_case_g1_fails_is_claimed_by_some_change(self):
        cases = catalogue()
        failing = {
            record["case_id"]
            for record in run_suite(g1.build, list(cases.values()))
            if not record["passed"]
        }
        claimed = {case_id for change in g2.CHANGES for case_id in change["caused_by_failures"]}
        self.assertEqual(
            failing - claimed,
            set(),
            "a measured G1 failure is not attributed to any change, so the lineage is incomplete",
        )

    def test_no_change_claims_a_case_g1_passes(self):
        cases = catalogue()
        passing = {
            record["case_id"] for record in run_suite(g1.build, list(cases.values())) if record["passed"]
        }
        claimed = {case_id for change in g2.CHANGES for case_id in change["caused_by_failures"]}
        self.assertEqual(claimed & passing, set())


if __name__ == "__main__":
    unittest.main()
