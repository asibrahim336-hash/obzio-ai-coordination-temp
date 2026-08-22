#!/usr/bin/env python3
"""Tests for the frozen hypothesis register and falsifiability validator."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import build_register
import validate_hypotheses


class HypothesisRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build_register.main()
        cls.path = Path(__file__).with_name("hypotheses.jsonl")
        cls.entries = [json.loads(line) for line in cls.path.read_text().splitlines()]

    def test_register_has_at_least_twelve_valid_entries(self) -> None:
        self.assertGreaterEqual(len(self.entries), 12)
        self.assertEqual([], validate_hypotheses.validate_file(self.path))

    def test_validator_refuses_non_falsifiable_entry(self) -> None:
        bad = copy.deepcopy(self.entries[0])
        bad["refutation_condition"]["threshold"] = "material"
        errors = validate_hypotheses.validate_entry(bad)
        self.assertIn("numeric refutation threshold is required", errors)

    def test_validator_refuses_tampered_source(self) -> None:
        bad = copy.deepcopy(self.entries[0])
        bad["source_identity"]["text"] += " unverified addition"
        errors = validate_hypotheses.validate_entry(bad)
        self.assertIn("relied source text hash mismatch", errors)

    def test_strategy_interlock_is_empty(self) -> None:
        self.assertTrue(all(entry["decision_changed"] == [] for entry in self.entries))


if __name__ == "__main__":
    unittest.main(verbosity=2)
