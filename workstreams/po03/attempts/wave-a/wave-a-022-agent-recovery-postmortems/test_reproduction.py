#!/usr/bin/env python3
"""Tests for the sanitized result-loss reproductions."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from reproduce import (
    HERE,
    build_observed_results,
    controlled_checkpoint_trial,
    run_process_exit_trials,
)


class CheckpointRaceTests(unittest.TestCase):
    def test_stale_snapshot_schedule_loses_all_but_last_write(self) -> None:
        observed = controlled_checkpoint_trial(workers=8, protected=False)
        self.assertEqual(observed["retained_writes"], 1)
        self.assertEqual(observed["lost_writes"], 7)
        self.assertEqual(observed["retained_task_ids"], ["task-7"])

    def test_locked_critical_section_preserves_every_write(self) -> None:
        observed = controlled_checkpoint_trial(workers=8, protected=True)
        self.assertEqual(observed["retained_writes"], 8)
        self.assertEqual(observed["lost_writes"], 0)
        self.assertEqual(
            observed["retained_task_ids"],
            [f"task-{index}" for index in range(8)],
        )


class ProcessExitTests(unittest.TestCase):
    def test_completion_receipt_does_not_preserve_memory_only_result(self) -> None:
        observed = run_process_exit_trials(trials=3, mode="ephemeral")
        self.assertEqual(observed["provider_completed_receipts"], 3)
        self.assertEqual(observed["durable_readbacks"], 0)
        self.assertEqual(observed["hash_verified_readbacks"], 0)
        self.assertEqual(observed["false_green_if_receipt_were_sufficient"], 3)

    def test_atomic_file_survives_worker_exit_and_hash_verifies(self) -> None:
        observed = run_process_exit_trials(trials=3, mode="durable")
        self.assertEqual(observed["provider_completed_receipts"], 3)
        self.assertEqual(observed["durable_readbacks"], 3)
        self.assertEqual(observed["hash_verified_readbacks"], 3)
        self.assertEqual(observed["false_green_if_receipt_were_sufficient"], 0)

    def test_temporary_reproduction_directories_are_cleaned(self) -> None:
        before = set(HERE.glob(".result-loss-*"))
        run_process_exit_trials(trials=1, mode="durable")
        after = set(HERE.glob(".result-loss-*"))
        self.assertEqual(after, before)


class ResultContractTests(unittest.TestCase):
    def test_full_result_satisfies_every_preregistered_assertion(self) -> None:
        observed = build_observed_results()
        self.assertEqual(observed["outcome"], "PASS")
        self.assertTrue(all(observed["assertions"].values()))

    def test_source_cards_are_proposition_level_and_complete(self) -> None:
        required = {
            "accessed_at",
            "card_id",
            "claim",
            "direct_evidence",
            "incentives",
            "published_or_updated_at",
            "reproducibility",
            "rights",
            "source",
            "source_types",
            "validity_horizon",
        }
        source_cards = Path(__file__).with_name("source-cards.jsonl")
        cards = [
            json.loads(line)
            for line in source_cards.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(cards), 6)
        self.assertEqual(len(cards), len({card["card_id"] for card in cards}))
        for card in cards:
            self.assertTrue(required.issubset(card), card["card_id"])
            self.assertIsInstance(card["claim"], str)
            self.assertIsInstance(card["direct_evidence"], str)
            self.assertTrue(card["claim"])
            self.assertTrue(card["direct_evidence"])


if __name__ == "__main__":
    unittest.main()
