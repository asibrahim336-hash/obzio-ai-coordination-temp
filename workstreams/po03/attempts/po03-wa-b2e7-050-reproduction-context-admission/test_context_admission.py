#!/usr/bin/env python3
"""Tests for the context-admission reproduction."""

import hashlib
import json
import unittest
from pathlib import Path

import experiment


class ContextAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preregister = json.loads(Path(__file__).with_name("preregister.json").read_text())

    def test_matched_reproduction_meets_frozen_threshold(self) -> None:
        result = experiment.run(self.preregister)
        self.assertEqual("PASS", result["verdict"])
        self.assertGreaterEqual(result["bounded_minus_dump_recovery"], 0.20)
        self.assertEqual(0, result["bounded_hash_mismatches"])

    def test_capsule_hash_detects_mutation(self) -> None:
        fields = [(key, "value") for key in experiment.REQUIRED]
        capsule, digest = experiment.bounded_capsule(fields, 12)
        capsule["task_id"] = "tampered"
        self.assertNotEqual(digest, hashlib.sha256(experiment.canonical(capsule)).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
