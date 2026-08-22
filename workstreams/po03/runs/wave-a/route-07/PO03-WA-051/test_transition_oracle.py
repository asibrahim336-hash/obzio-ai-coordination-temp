"""Falsification tests for the PO03-WA-051 hidden transition-case oracle.

The hypothesis fails if any ordered state pair escapes classification, if a
prohibited skip is reported legal, or if the oracle cannot detect a deliberately
permissive custody implementation.
"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transition_oracle import (  # noqa: E402
    ALL_STATES,
    FAULT_STATES,
    HAPPY_PATH,
    REPEATABLE_STATES,
    TERMINAL_STATES,
    Verdict,
    classify_pair,
    enumerate_cases,
    enumerate_paths,
    falsify,
    legal_cases,
    prohibited_cases,
)


class CoverageTests(unittest.TestCase):
    def test_every_ordered_pair_is_classified_exactly_once(self):
        cases = enumerate_cases()
        self.assertEqual(len(ALL_STATES) ** 2, len(cases))
        seen = {(c.source, c.target) for c in cases}
        self.assertEqual(len(cases), len(seen))
        self.assertEqual(set(itertools.product(ALL_STATES, repeat=2)), seen)

    def test_legal_and_prohibited_partition_the_space(self):
        total = len(enumerate_cases())
        self.assertEqual(total, len(legal_cases()) + len(prohibited_cases()))
        self.assertEqual(
            set(),
            {(c.source, c.target) for c in legal_cases()}
            & {(c.source, c.target) for c in prohibited_cases()},
        )

    def test_every_happy_path_edge_is_legal(self):
        for a, b in zip(HAPPY_PATH, HAPPY_PATH[1:]):
            with self.subTest(edge=f"{a}->{b}"):
                self.assertIs(Verdict.LEGAL, classify_pair(a, b).verdict)

    def test_every_verdict_is_exercised_by_the_case_set(self):
        produced = {c.verdict for c in enumerate_cases()}
        self.assertEqual(set(Verdict), produced)


class ProhibitionTests(unittest.TestCase):
    def test_every_skip_over_the_happy_path_is_prohibited(self):
        for i, source in enumerate(HAPPY_PATH):
            for target in HAPPY_PATH[i + 2 :]:
                with self.subTest(edge=f"{source}->{target}"):
                    case = classify_pair(source, target)
                    self.assertIs(Verdict.SKIP, case.verdict)
                    self.assertFalse(case.must_be_accepted)

    def test_the_staging_bypass_is_named_explicitly(self):
        case = classify_pair("RUNNING", "RESULT_COMMITTED")
        self.assertIs(Verdict.SKIP, case.verdict)
        self.assertIn("RESULT_STAGED", case.reason)
        self.assertIn("RESULT_VERIFIED", case.reason)

    def test_every_backwards_edge_is_prohibited(self):
        """Terminal sources are UNREACHABLE first; every other rewind is REVERSAL."""
        for i, source in enumerate(HAPPY_PATH):
            for target in HAPPY_PATH[:i]:
                with self.subTest(edge=f"{source}->{target}"):
                    case = classify_pair(source, target)
                    self.assertFalse(case.must_be_accepted)
                    expected = (
                        Verdict.UNREACHABLE if source in TERMINAL_STATES else Verdict.REVERSAL
                    )
                    self.assertIs(expected, case.verdict)

    def test_terminal_states_have_no_outgoing_edge(self):
        for terminal in sorted(TERMINAL_STATES):
            for target in ALL_STATES:
                if target == terminal:
                    continue
                with self.subTest(edge=f"{terminal}->{target}"):
                    self.assertFalse(classify_pair(terminal, target).must_be_accepted)

    def test_only_checkpointed_may_repeat(self):
        for state in ALL_STATES:
            case = classify_pair(state, state)
            with self.subTest(state=state):
                if state in REPEATABLE_STATES:
                    self.assertIs(Verdict.LEGAL, case.verdict)
                else:
                    self.assertIs(Verdict.SELF, case.verdict)

    def test_recovery_cannot_resume_mid_pipeline(self):
        for fault in FAULT_STATES:
            for target in ("RESULT_STAGED", "RESULT_VERIFIED", "RESULT_COMMITTED", "COMPLETED"):
                with self.subTest(edge=f"{fault}->{target}"):
                    self.assertFalse(classify_pair(fault, target).must_be_accepted)

    def test_unknown_states_are_rejected(self):
        with self.assertRaises(ValueError):
            classify_pair("CREATED", "DONE")
        with self.assertRaises(ValueError):
            classify_pair("DONE", "CREATED")


class FalsificationTests(unittest.TestCase):
    def test_oracle_flags_a_permissive_implementation(self):
        report = falsify(lambda a, b: True)
        self.assertFalse(report["sound"])
        self.assertEqual(len(prohibited_cases()), len(report["false_accepts"]))
        self.assertEqual([], report["false_rejects"])

    def test_oracle_flags_a_refusing_implementation(self):
        report = falsify(lambda a, b: False)
        self.assertFalse(report["sound"])
        self.assertEqual(len(legal_cases()), len(report["false_rejects"]))

    def test_oracle_accepts_a_faithful_implementation(self):
        legal = {(c.source, c.target) for c in legal_cases()}
        report = falsify(lambda a, b: (a, b) in legal)
        self.assertTrue(report["sound"], report)

    def test_oracle_catches_a_single_smuggled_skip(self):
        legal = {(c.source, c.target) for c in legal_cases()}
        legal.add(("RUNNING", "RESULT_COMMITTED"))
        report = falsify(lambda a, b: (a, b) in legal)
        self.assertFalse(report["sound"])
        self.assertEqual(1, len(report["false_accepts"]))
        self.assertEqual(("RUNNING", "RESULT_COMMITTED"),
                         (report["false_accepts"][0].source, report["false_accepts"][0].target))

    def test_an_exception_from_the_implementation_counts_as_refusal(self):
        def explode(a, b):
            raise RuntimeError("boom")

        report = falsify(explode)
        self.assertEqual([], report["false_accepts"])
        self.assertEqual(len(legal_cases()), len(report["false_rejects"]))


class PathTests(unittest.TestCase):
    def test_bounded_paths_include_a_fully_legal_prefix(self):
        paths = enumerate_paths(max_length=4)
        legal = [p["path"] for p in paths if p["all_edges_legal"]]
        self.assertIn(("CREATED", "LEASED", "RUNNING"), legal)
        self.assertIn(("CREATED", "LEASED", "RUNNING", "CHECKPOINTED"), legal)

    def test_bounded_paths_reject_a_skip_prefix(self):
        paths = {p["path"]: p["all_edges_legal"] for p in enumerate_paths(max_length=3)}
        self.assertFalse(paths[("CREATED", "RUNNING")])
        self.assertFalse(paths[("CREATED", "COMPLETED")])

    def test_no_legal_path_reaches_completed_within_three_steps(self):
        for entry in enumerate_paths(max_length=4):
            if entry["all_edges_legal"]:
                with self.subTest(path=entry["path"]):
                    self.assertNotIn("COMPLETED", entry["path"])


if __name__ == "__main__":
    unittest.main()
