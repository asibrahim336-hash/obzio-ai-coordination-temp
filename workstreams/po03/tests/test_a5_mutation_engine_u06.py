"""Unit tests for the a5-u06 text-level mutation engine itself."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.mutation_engine_u06 import (  # noqa: E402
    MUTANTS,
    apply_mutant,
    load_module_from_source,
    load_real_module,
    read_real_source,
    run_existing_suite_against_module,
    VALIDATE_CONTRACTS_PATH,
)


class TestMutationEngine(unittest.TestCase):
    def test_real_source_file_is_never_written(self) -> None:
        before = VALIDATE_CONTRACTS_PATH.read_bytes()
        for mutant in MUTANTS:
            source = read_real_source()
            mutated = apply_mutant(source, mutant)
            load_module_from_source(mutated, f"probe-{mutant['id']}")
        after = VALIDATE_CONTRACTS_PATH.read_bytes()
        self.assertEqual(before, after)

    def test_every_mutant_anchor_text_is_unique_in_real_source(self) -> None:
        source = read_real_source()
        for mutant in MUTANTS:
            with self.subTest(mutant=mutant["id"]):
                self.assertEqual(source.count(mutant["find"]), 1)

    def test_every_mutant_actually_changes_the_module_behaviourally(self) -> None:
        real_source = read_real_source()
        real_module = load_module_from_source(real_source, "real-for-diff")
        for mutant in MUTANTS:
            with self.subTest(mutant=mutant["id"]):
                mutated_source = apply_mutant(real_source, mutant)
                self.assertNotEqual(mutated_source, real_source)
                mutant_module = load_module_from_source(mutated_source, f"diff-{mutant['id']}")
                self.assertIsNot(mutant_module, real_module)

    def test_existing_suite_passes_against_the_real_unmutated_module(self) -> None:
        real_module = load_real_module()
        result = run_existing_suite_against_module(real_module)
        self.assertGreater(result["tests_run"], 0)
        self.assertFalse(result["killed"], f"existing suite must pass clean: {result['failures']}")

    def test_control_mutants_are_killed_by_the_existing_suite(self) -> None:
        control_ids = {"M4_duplicate_artifact_check_disabled", "M5_self_accept_check_disabled"}
        real_source = read_real_source()
        for mutant in MUTANTS:
            if mutant["id"] not in control_ids:
                continue
            with self.subTest(mutant=mutant["id"]):
                mutated_source = apply_mutant(real_source, mutant)
                module = load_module_from_source(mutated_source, f"control-{mutant['id']}")
                result = run_existing_suite_against_module(module)
                self.assertTrue(result["killed"], f"{mutant['id']} should be killed by the existing suite")


if __name__ == "__main__":
    unittest.main()
