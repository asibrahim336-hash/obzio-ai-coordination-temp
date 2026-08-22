#!/usr/bin/env python3
"""Tests for checkpoint-granularity reproduction."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("experiment.py")
SPEC = importlib.util.spec_from_file_location("checkpoint_experiment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class CheckpointGranularityTests(unittest.TestCase):
    def test_known_failure_rework(self) -> None:
        self.assertEqual(0, experiment.rework_for_failure(13, 1, 20))
        self.assertEqual(3, experiment.rework_for_failure(13, 5, 20))
        self.assertEqual(13, experiment.rework_for_failure(13, 20, 20))

    def test_fine_checkpointing_reduces_rework(self) -> None:
        preregister = json.loads(Path(__file__).with_name("preregister.json").read_text())
        result = experiment.run(preregister)
        self.assertEqual("PASS", result["verdict"])
        means = [result["arms"][str(value)]["mean_reworked_steps"] for value in (1, 2, 5, 10, 20)]
        self.assertEqual(sorted(means), means)
        self.assertGreaterEqual(result["granularity_1_rework_reduction_fraction"], 0.50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
