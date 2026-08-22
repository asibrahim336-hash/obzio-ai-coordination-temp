#!/usr/bin/env python3
"""Tests for the scale-versus-acceptance reproduction."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("experiment.py")
SPEC = importlib.util.spec_from_file_location("scale_experiment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


class ScaleAcceptanceTests(unittest.TestCase):
    def test_pressure_formulas_are_monotonic(self) -> None:
        defect_rates = [experiment.defect_probability(level, 4) for level in (2, 4, 8, 16, 32)]
        detection_rates = [experiment.detection_probability(level, 4) for level in (2, 4, 8, 16, 32)]
        self.assertEqual(sorted(defect_rates), defect_rates)
        self.assertEqual(sorted(detection_rates, reverse=True), detection_rates)

    def test_unbalanced_scale_degrades_accepted_good_throughput(self) -> None:
        preregister = json.loads(Path(__file__).with_name("preregister.json").read_text())
        result = experiment.run(preregister)
        self.assertEqual("PASS", result["verdict"])
        self.assertLess(result["concurrency_32_minus_4_good_throughput"], 0)
        self.assertGreater(result["concurrency_32_minus_4_escaped_defect_fraction"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
