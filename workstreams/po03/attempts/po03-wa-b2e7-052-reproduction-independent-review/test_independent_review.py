#!/usr/bin/env python3
"""Tests for the independent-review fallback reproduction."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("experiment.py")
SPEC = importlib.util.spec_from_file_location("review_experiment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class IndependentReviewTests(unittest.TestCase):
    def test_reviewers_are_blind_to_defect_labels(self) -> None:
        fixture = experiment.fixtures(52052, 1)[0]
        self.assertNotIn("defect", fixture["payload"])

    def test_fallback_never_claims_cross_family_support(self) -> None:
        root = Path(__file__).resolve().parent
        result = experiment.run(
            json.loads((root / "preregister.json").read_text()),
            json.loads((root / "provider_attempt.json").read_text()),
        )
        self.assertEqual("NOT_SUPPORTED", result["verdict"])
        self.assertFalse(result["different_family_identity_verified"])
        self.assertTrue(all(arm["model_family"] == "NOT_SUPPORTED" for arm in result["arms"].values()))

    def test_complementary_profiles_detect_all_seeded_defect_types(self) -> None:
        for fixture in experiment.fixtures(52052, 120):
            detected = (
                experiment.structural_reviewer(fixture["payload"])
                or experiment.adversarial_reviewer(fixture["payload"])
            )
            self.assertTrue(detected, fixture["defect"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
