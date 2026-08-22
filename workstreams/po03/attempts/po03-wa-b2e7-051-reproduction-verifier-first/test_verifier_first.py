#!/usr/bin/env python3
"""Tests for the verifier-first reproduction."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("experiment.py")
SPEC = importlib.util.spec_from_file_location("verifier_experiment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class VerifierFirstTests(unittest.TestCase):
    def test_seeded_defects_are_rejected_by_frozen_contract(self) -> None:
        for fixture in experiment.fixtures(51051, 200):
            self.assertFalse(experiment.frozen_acceptance(fixture["result"]))

    def test_frozen_arm_reduces_false_greens(self) -> None:
        preregister = json.loads(Path(__file__).with_name("preregister.json").read_text())
        result = experiment.run(preregister)
        self.assertEqual("PASS", result["verdict"])
        self.assertGreaterEqual(result["false_green_rate_reduction"], 0.20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
