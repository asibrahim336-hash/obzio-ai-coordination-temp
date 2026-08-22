"""Unit tests for the a5-u03 cross-methodology blind review comparison."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.review_corpus_u03 import (  # noqa: E402
    DYNAMIC_ONLY_DEFECTS,
    DYNAMIC_REFERENCES,
    STATIC_ONLY_DEFECTS,
    generate_dynamic_inputs,
)
from lib.reviewers_u03 import PropertyBasedReviewer, StaticPatternReviewer  # noqa: E402


class TestCrossMethodologyReview(unittest.TestCase):
    def setUp(self) -> None:
        self.static_reviewer = StaticPatternReviewer()
        self.dynamic_reviewer = PropertyBasedReviewer(seed=20260822)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)

    def test_static_reviewer_catches_all_four_static_only_defects(self) -> None:
        for defect_class, fn in STATIC_ONLY_DEFECTS.items():
            with self.subTest(defect=defect_class):
                findings = self.static_reviewer.review(fn)
                self.assertIn(defect_class, findings)

    def test_static_reviewer_is_silent_on_dynamic_only_defects(self) -> None:
        for defect_class, fn in DYNAMIC_ONLY_DEFECTS.items():
            with self.subTest(defect=defect_class):
                findings = self.static_reviewer.review(fn)
                self.assertEqual(findings, set(), f"static reviewer should find nothing in {defect_class}")

    def test_dynamic_reviewer_catches_all_four_dynamic_only_defects(self) -> None:
        for defect_class, fn in DYNAMIC_ONLY_DEFECTS.items():
            with self.subTest(defect=defect_class):
                inputs = generate_dynamic_inputs(defect_class, self.dynamic_reviewer.rng)
                found = self.dynamic_reviewer.review_dynamic(defect_class, fn, DYNAMIC_REFERENCES[defect_class], inputs)
                self.assertTrue(found, f"dynamic reviewer should catch {defect_class}")

    def test_dynamic_reviewer_is_silent_on_static_only_defects(self) -> None:
        for defect_class, fn in STATIC_ONLY_DEFECTS.items():
            with self.subTest(defect=defect_class):
                found = self.dynamic_reviewer.review_static_only_snippet(defect_class, fn, self.tmp_dir)
                self.assertFalse(found, f"dynamic reviewer's scoped property should not fire on {defect_class}")

    def test_defect_sets_are_non_identical_and_pooling_beats_either_alone(self) -> None:
        static_catches = {
            name for name, fn in {**STATIC_ONLY_DEFECTS, **DYNAMIC_ONLY_DEFECTS}.items()
            if self.static_reviewer.review(fn)
        }
        dynamic_catches = set()
        for name, fn in DYNAMIC_ONLY_DEFECTS.items():
            inputs = generate_dynamic_inputs(name, self.dynamic_reviewer.rng)
            if self.dynamic_reviewer.review_dynamic(name, fn, DYNAMIC_REFERENCES[name], inputs):
                dynamic_catches.add(name)
        for name, fn in STATIC_ONLY_DEFECTS.items():
            if self.dynamic_reviewer.review_static_only_snippet(name, fn, self.tmp_dir):
                dynamic_catches.add(name)

        self.assertNotEqual(static_catches, dynamic_catches)
        self.assertFalse(static_catches <= dynamic_catches)
        self.assertFalse(dynamic_catches <= static_catches)
        pooled = static_catches | dynamic_catches
        self.assertEqual(len(pooled), 8)
        self.assertGreater(len(pooled), len(static_catches))
        self.assertGreater(len(pooled), len(dynamic_catches))


if __name__ == "__main__":
    unittest.main()
