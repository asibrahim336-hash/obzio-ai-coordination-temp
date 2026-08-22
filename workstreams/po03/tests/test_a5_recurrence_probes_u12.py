"""Unit tests for the a5-u12 recurrence probes and helpers.

These tests verify the probes are side-effect-free (never touch the
already-committed reproduction-ledger.jsonl or output/a5-u0{6,7}-result.json)
and that subprocess-based recurrence testing actually works end to end.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.recurrence_testing_u12 import (  # noqa: E402
    VALID_DISPOSITIONS,
    determine_disposition,
    run_permanent_test_subprocess,
    run_probe_subprocess,
)

U06_PROBE = RESEARCH_ROOT / "repro" / "recurrence_probe_u06.py"
U07_PROBE = RESEARCH_ROOT / "repro" / "recurrence_probe_u07.py"
LEDGER_PATH = RESEARCH_ROOT / "reproduction-ledger.jsonl"
U06_OUTPUT = RESEARCH_ROOT / "output" / "a5-u06-result.json"
U07_OUTPUT = RESEARCH_ROOT / "output" / "a5-u07-result.json"


class TestProbesAreSideEffectFree(unittest.TestCase):
    def test_u06_probe_does_not_modify_the_committed_ledger_or_output(self) -> None:
        ledger_before = LEDGER_PATH.read_bytes()
        output_before = U06_OUTPUT.read_bytes()
        run_probe_subprocess(U06_PROBE, seed=1)
        self.assertEqual(LEDGER_PATH.read_bytes(), ledger_before)
        self.assertEqual(U06_OUTPUT.read_bytes(), output_before)

    def test_u07_probe_does_not_modify_the_committed_ledger_or_output(self) -> None:
        ledger_before = LEDGER_PATH.read_bytes()
        output_before = U07_OUTPUT.read_bytes()
        run_probe_subprocess(U07_PROBE, seed=1, extra_args=["--sample-size", "20"])
        self.assertEqual(LEDGER_PATH.read_bytes(), ledger_before)
        self.assertEqual(U07_OUTPUT.read_bytes(), output_before)


class TestU06ProbeQualitativeStability(unittest.TestCase):
    def test_default_seed_finds_the_same_missed_mutants_as_the_original(self) -> None:
        measurement = run_probe_subprocess(U06_PROBE, seed=20260822)
        self.assertEqual(measurement["existing_missed_property_caught_count"], 2)

    def test_different_seed_still_finds_at_least_one_missed_mutant(self) -> None:
        measurement = run_probe_subprocess(U06_PROBE, seed=999999)
        self.assertGreaterEqual(measurement["existing_missed_property_caught_count"], 1)


class TestU07ProbeQualitativeStability(unittest.TestCase):
    def test_sequential_never_finds_a_violation_regardless_of_seed(self) -> None:
        measurement = run_probe_subprocess(U07_PROBE, seed=42, extra_args=["--sample-size", "50"])
        self.assertEqual(measurement["sequential_violations_found"], 0)

    def test_dst_finds_at_least_one_violation_with_a_different_seed(self) -> None:
        measurement = run_probe_subprocess(U07_PROBE, seed=777, extra_args=["--sample-size", "50"])
        self.assertGreater(measurement["dst_violations_found"], 0)


class TestRunPermanentTestSubprocess(unittest.TestCase):
    def test_u06_permanent_property_test_passes_under_independent_subprocess(self) -> None:
        result = run_permanent_test_subprocess("test_a5_property_validate_contracts.py")
        self.assertTrue(result["passed"], result["stderr_tail"])

    def test_u07_permanent_sentinel_test_passes_under_independent_subprocess(self) -> None:
        result = run_permanent_test_subprocess("test_a5_lease_race_sentinel_u07.py")
        self.assertTrue(result["passed"], result["stderr_tail"])


class TestDetermineDisposition(unittest.TestCase):
    def test_pass_and_match_is_retain(self) -> None:
        self.assertEqual(determine_disposition(True, True), "RETAIN")

    def test_pass_but_no_match_is_retest(self) -> None:
        self.assertEqual(determine_disposition(True, False), "RETEST")

    def test_test_failure_is_reject_regardless_of_qualitative_match(self) -> None:
        self.assertEqual(determine_disposition(False, True), "REJECT")
        self.assertEqual(determine_disposition(False, False), "REJECT")

    def test_all_returned_dispositions_are_in_the_valid_set(self) -> None:
        for a in (True, False):
            for b in (True, False):
                self.assertIn(determine_disposition(a, b), VALID_DISPOSITIONS)


if __name__ == "__main__":
    unittest.main()
