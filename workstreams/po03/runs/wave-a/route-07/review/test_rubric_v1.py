"""Self-test proving the frozen review rubric resists false PASS.

Runs the pre-registered hidden adversarial cases through rubric_v1 and asserts
that every case reaches its pre-registered recommendation. This test is part of
the rubric freeze: it is hashed before any producer conclusion is read.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hidden_cases_v1 as hc  # noqa: E402
import rubric_v1 as rb  # noqa: E402


def _cohort_for(root: Path, case: str) -> dict:
    if case != "duplicate_unit":
        return {}
    golden = root / hc.OWNED_PREFIX / "golden"
    return {
        "GOLDEN": {
            p.name: p.read_text(encoding="utf-8")
            for p in golden.glob("*.py")
        }
    }


class HiddenCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.expectations = hc.build_all(cls.root)
        cls.results = {}
        for exp in cls.expectations:
            review = rb.review_slot(
                repo_root=cls.root,
                slot_rel=exp["slot"],
                task_id=hc.TASK_ID,
                hypothesis=hc.HYPOTHESIS,
                acceptance_sha=hc.ACCEPTANCE_SHA,
                manifest_sha=hc.MANIFEST_SHA,
                owned_prefix=hc.OWNED_PREFIX,
                cohort=_cohort_for(cls.root, exp["case"]),
            )
            cls.results[exp["case"]] = review

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_case_reaches_registered_recommendation(self):
        for exp in self.expectations:
            with self.subTest(case=exp["case"]):
                got = self.results[exp["case"]].recommendation
                self.assertEqual(
                    exp["expected_recommendation"],
                    got,
                    f"{exp['case']}: expected {exp['expected_recommendation']} got {got}; "
                    f"defects={self.results[exp['case']].defects}",
                )

    def test_registered_dimensions_actually_fail(self):
        for exp in self.expectations:
            failed = {
                d.dimension for d in self.results[exp["case"]].dimensions if d.verdict == "FAIL"
            }
            with self.subTest(case=exp["case"]):
                self.assertTrue(
                    set(exp["expected_failed_dimensions"]).issubset(failed),
                    f"{exp['case']}: expected {exp['expected_failed_dimensions']} within {sorted(failed)}",
                )

    def test_golden_case_has_no_failed_dimension(self):
        golden = self.results["golden"]
        failed = [d.dimension for d in golden.dimensions if d.verdict == "FAIL"]
        self.assertEqual([], failed, f"golden slot must be clean, got {failed}")

    def test_no_corrupt_manifest_case_is_accepted(self):
        corrupt = [
            "manifest_omission",
            "manifest_hash_corrupt",
            "manifest_bytes_corrupt",
            "unmanifested_extra",
        ]
        for case in corrupt:
            with self.subTest(case=case):
                self.assertEqual("RECOMMEND_REJECT", self.results[case].recommendation)

    def test_missing_slot_is_rejected(self):
        review = rb.review_slot(
            repo_root=self.root,
            slot_rel=f"{hc.OWNED_PREFIX}/does-not-exist",
            task_id=hc.TASK_ID,
            hypothesis=hc.HYPOTHESIS,
            acceptance_sha=hc.ACCEPTANCE_SHA,
            manifest_sha=hc.MANIFEST_SHA,
            owned_prefix=hc.OWNED_PREFIX,
        )
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)

    def test_recommendation_enum_never_claims_terminal_acceptance(self):
        for review in self.results.values():
            self.assertIn(
                review.recommendation,
                ("RECOMMEND_ACCEPT", "RECOMMEND_REJECT", "RETEST"),
            )
            self.assertNotIn(review.recommendation, ("ACCEPTED", "COMPLETED", "PASS"))


if __name__ == "__main__":
    unittest.main()
