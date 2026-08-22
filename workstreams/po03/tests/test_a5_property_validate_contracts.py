"""Permanent property/metamorphic regression suite for validate_contracts.py.

This is a5-u06's live mechanism change: a new, permanent test asset added to
the standing gate (``python3 -I -m unittest discover -s workstreams/po03/tests``)
that checks three properties the existing example-based
``test_validate_contracts.py`` suite does not check at all:

1. any non-positive artifact byte count is rejected (not just the specific
   reconciliation mismatch the fixed examples happen to try);
2. any total_bytes / artifact-sum mismatch is rejected, for a swept range of
   offsets, not only the exact +1 example already in the fixed suite;
3. a terminal independent_acceptance decision is rejected for every
   non-COMPLETED state tried, not only the one RESULT_COMMITTED example.

a5-u06's reproduction (workstreams/po03/research/repro/run_u06_mutation_testing.py)
shows this suite kills real mutants of validate_contracts.py that the
existing example-based suite misses; running it here, against the real,
unmutated module, is the permanent regression protection those mutants
motivate.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.mutation_engine_u06 import load_real_module  # noqa: E402
from lib.property_harness_u06 import (  # noqa: E402
    property_nonpositive_bytes_always_rejected,
    property_terminal_review_requires_completed,
    property_total_bytes_mismatch_always_rejected,
)

import random

SEED = 20260822
TRIALS = 60


class TestValidateContractsProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_real_module()

    def test_nonpositive_artifact_bytes_always_rejected(self) -> None:
        rng = random.Random(SEED)
        violations = property_nonpositive_bytes_always_rejected(self.module.validate_result, rng, TRIALS)
        self.assertEqual(violations, [], f"non-positive byte counts must always be rejected: {violations}")

    def test_total_bytes_mismatch_always_rejected_across_offsets(self) -> None:
        rng = random.Random(SEED + 1)
        violations = property_total_bytes_mismatch_always_rejected(self.module.validate_result, rng, TRIALS)
        self.assertEqual(violations, [], f"every total_bytes mismatch must be rejected: {violations}")

    def test_terminal_review_requires_completed_across_states(self) -> None:
        rng = random.Random(SEED + 2)
        violations = property_terminal_review_requires_completed(self.module.validate_result, rng, TRIALS)
        self.assertEqual(violations, [], f"terminal review must require COMPLETED in every state tried: {violations}")


if __name__ == "__main__":
    unittest.main()
