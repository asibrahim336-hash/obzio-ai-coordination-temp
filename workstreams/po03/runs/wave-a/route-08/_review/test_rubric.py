#!/usr/bin/env python3

import importlib.util
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("route08_rubric", HERE / "rubric.py")
assert SPEC and SPEC.loader
RUBRIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUBRIC)


class RubricFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.held_out = json.loads(
            (HERE / "held-out-cases.json").read_text(encoding="utf-8")
        )

    def report(self, case_id, status="PASS", passed=True):
        return {
            "tests": [
                {
                    "command": "python3 independent_test.py",
                    "exit_code": 0 if passed else 1,
                    "passed": passed,
                    "critical": True,
                    "observed": "synthetic rubric unit test",
                }
            ],
            "hidden_cases": [
                {"case_id": case_id, "status": status, "evidence": "synthetic"}
            ],
            "defects": [],
            "limitations": [],
        }

    def test_one_unique_case_per_target(self):
        cases = self.held_out["cases"]
        ids = [case["case_id"] for case in cases]
        tasks = [case["task_id"] for case in cases]
        self.assertEqual(32, len(cases))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(tasks), len(set(tasks)))

    def test_accept_requires_test_and_held_out_pass(self):
        outcome, rejects, retests = RUBRIC.score_report(
            "PO03-WA-001", self.report("H001-skip-and-reverse"), self.held_out
        )
        self.assertEqual("RECOMMEND_ACCEPT", outcome)
        self.assertEqual([], rejects)
        self.assertEqual([], retests)

    def test_critical_failure_rejects(self):
        outcome, rejects, _ = RUBRIC.score_report(
            "PO03-WA-001",
            self.report("H001-skip-and-reverse", status="FAIL", passed=False),
            self.held_out,
        )
        self.assertEqual("RECOMMEND_REJECT", outcome)
        self.assertTrue(rejects)

    def test_unavailable_case_retests(self):
        outcome, rejects, retests = RUBRIC.score_report(
            "PO03-WA-001",
            self.report("H001-skip-and-reverse", status="NOT_SUPPORTED"),
            self.held_out,
        )
        self.assertEqual("RETEST", outcome)
        self.assertEqual([], rejects)
        self.assertTrue(retests)


if __name__ == "__main__":
    unittest.main()
