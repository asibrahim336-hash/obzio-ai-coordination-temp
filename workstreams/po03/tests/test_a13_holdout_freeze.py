"""Structural and mutation checks for the evaluator-held a13 holdout."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOLDOUT = ROOT / "workstreams" / "po03" / "holdout"
CASES_PATH = HOLDOUT / "cases" / "cases.json"
SCORER_PATH = HOLDOUT / "score_holdout.py"


def load_scorer():
    spec = importlib.util.spec_from_file_location("a13_score_holdout", SCORER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load holdout scorer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class A13HoldoutFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scorer = load_scorer()
        cls.suite = cls.scorer.load_suite(CASES_PATH)

    def test_suite_has_32_unique_executable_cases(self) -> None:
        cases = self.suite["cases"]
        self.assertEqual(32, len(cases))
        self.assertEqual(32, len({case["id"] for case in cases}))
        for case in cases:
            with self.subTest(case=case["id"]):
                operations = case["input"].get("operations")
                self.assertIsInstance(operations, list)
                self.assertTrue(operations)
                self.assertTrue(case["assertions"])

    def test_each_case_cites_a_commission_requirement_and_novelty(self) -> None:
        for case in self.suite["cases"]:
            requirement = case["requirement"]
            with self.subTest(case=case["id"]):
                self.assertTrue(requirement["commission_section"])
                self.assertTrue(requirement["quote"])
                self.assertTrue(requirement["novelty"])
                self.assertIsInstance(requirement["source_defects"], list)

    def test_every_case_has_a_false_completion_oracle(self) -> None:
        expected_path = "/observation/counts/false_completions"
        for case in self.suite["cases"]:
            paths = {assertion["path"] for assertion in case["assertions"]}
            with self.subTest(case=case["id"]):
                self.assertIn(expected_path, paths)

    def test_oracles_are_not_part_of_candidate_request(self) -> None:
        for case in self.suite["cases"]:
            request = {
                "protocol_version": self.scorer.REQUEST_VERSION,
                "case_id": case["id"],
                "input": case["input"],
            }
            encoded = self.scorer.canonical_json_bytes(request)
            decoded = json.loads(encoded)
            with self.subTest(case=case["id"]):
                self.assertNotIn("assertions", decoded)
                self.assertNotIn("requirement", decoded)
                self.assertEqual(case["input"], decoded["input"])

    def test_each_case_can_fail_against_an_empty_broken_observation(self) -> None:
        broken_response = {
            "protocol_version": self.scorer.RESPONSE_VERSION,
            "case_id": "placeholder",
            "status": "EXECUTED",
            "boundary": None,
            "observation": {},
        }
        for case in self.suite["cases"]:
            broken_response["case_id"] = case["id"]
            results = [
                self.scorer.evaluate_assertion(broken_response, assertion)
                for assertion in case["assertions"]
            ]
            with self.subTest(case=case["id"]):
                self.assertTrue(any(not result["passed"] for result in results))

    def test_first_equality_oracle_in_each_case_rejects_a_mutation(self) -> None:
        for case in self.suite["cases"]:
            equality = next(
                assertion
                for assertion in case["assertions"]
                if assertion["op"] == "eq"
            )
            mutated = dict(equality)
            expected = equality["value"]
            if isinstance(expected, bool):
                mutated_actual = not expected
            elif isinstance(expected, int):
                mutated_actual = expected + 1
            elif isinstance(expected, str):
                mutated_actual = expected + "-MUTATED"
            elif isinstance(expected, list):
                mutated_actual = [*expected, "MUTATED"]
            else:
                mutated_actual = {"mutated": True}
            response = {
                "protocol_version": self.scorer.RESPONSE_VERSION,
                "case_id": case["id"],
                "status": "EXECUTED",
                "boundary": None,
                "observation": {},
            }
            tokens = equality["path"][1:].split("/")
            cursor = response
            for token in tokens[:-1]:
                token = token.replace("~1", "/").replace("~0", "~")
                cursor = cursor.setdefault(token, {})
            cursor[tokens[-1]] = mutated_actual
            with self.subTest(case=case["id"]):
                result = self.scorer.evaluate_assertion(response, mutated)
                self.assertFalse(result["passed"])

    def test_not_supported_requires_an_exact_boundary(self) -> None:
        valid = {
            "protocol_version": self.scorer.RESPONSE_VERSION,
            "case_id": "H01",
            "status": "NOT_SUPPORTED",
            "boundary": "generation exposes no durable-remote lookup operation",
        }
        self.assertEqual(valid, self.scorer.validate_response(valid, "H01"))
        invalid = dict(valid, boundary="")
        with self.assertRaises(self.scorer.ContractError):
            self.scorer.validate_response(invalid, "H01")

    def test_snapshot_coupling_rule_is_respected(self) -> None:
        serialized = CASES_PATH.read_text(encoding="utf-8")
        self.assertNotIn("current repository defect must exist", serialized)
        self.assertNotIn("recompute live state equals", serialized)
        for case in self.suite["cases"]:
            with self.subTest(case=case["id"]):
                self.assertIn("logical_clock", case["input"])


if __name__ == "__main__":
    unittest.main()
