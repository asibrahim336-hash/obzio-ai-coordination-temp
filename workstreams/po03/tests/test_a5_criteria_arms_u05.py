"""Unit tests for the a5-u05 preregistered vs post-hoc criteria comparison."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.criteria_arms_u05 import (  # noqa: E402
    BOUNDARY_INPUT_FOR_DEFECT,
    CANDIDATE_IMPLEMENTATIONS,
    generate_post_hoc_suite,
    run_post_hoc_suite_against_spec,
    run_preregistered_suite,
    spec_reference,
)


class TestCriteriaArms(unittest.TestCase):
    def test_every_candidate_actually_deviates_from_spec_at_its_boundary(self) -> None:
        for name, fn in CANDIDATE_IMPLEMENTATIONS.items():
            boundary = BOUNDARY_INPUT_FOR_DEFECT[name]
            with self.subTest(candidate=name):
                self.assertNotEqual(fn(boundary), spec_reference(boundary), f"{name} should disagree with spec at its boundary")

    def test_preregistered_suite_catches_every_candidate_defect(self) -> None:
        for name, fn in CANDIDATE_IMPLEMENTATIONS.items():
            with self.subTest(candidate=name):
                failures = run_preregistered_suite(fn)
                self.assertGreater(len(failures), 0, f"preregistered suite should catch {name}")
                self.assertIn(BOUNDARY_INPUT_FOR_DEFECT[name], failures)

    def test_post_hoc_suite_escapes_every_candidate_defect(self) -> None:
        for name, fn in CANDIDATE_IMPLEMENTATIONS.items():
            with self.subTest(candidate=name):
                oracle = generate_post_hoc_suite(fn)
                failures = run_post_hoc_suite_against_spec(oracle)
                self.assertEqual(failures, [], f"post-hoc suite should NOT catch {name} (that is the finding)")

    def test_both_arms_are_actually_run_not_asserted(self) -> None:
        prereg_escaped = 0
        posthoc_escaped = 0
        for name, fn in CANDIDATE_IMPLEMENTATIONS.items():
            if not run_preregistered_suite(fn):
                prereg_escaped += 1
            oracle = generate_post_hoc_suite(fn)
            if not run_post_hoc_suite_against_spec(oracle):
                posthoc_escaped += 1
        self.assertEqual(prereg_escaped, 0)
        self.assertEqual(posthoc_escaped, len(CANDIDATE_IMPLEMENTATIONS))


if __name__ == "__main__":
    unittest.main()
