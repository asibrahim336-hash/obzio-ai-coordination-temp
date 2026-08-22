"""Unit tests for the a5-u02 message-passing vs content-addressed comparison."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.custody_designs_u02 import (  # noqa: E402
    ContentAddressedCustody,
    MessagePassingReturn,
    run_callback_loss_trial,
)


class TestCustodyDesigns(unittest.TestCase):
    def test_message_passing_loses_result_when_callback_dropped(self) -> None:
        mp = MessagePassingReturn()
        mp.worker_finishes("u1", "payload", callback_dropped=True)
        self.assertIsNone(mp.parent_recover("u1"))

    def test_message_passing_recovers_when_callback_delivered(self) -> None:
        mp = MessagePassingReturn()
        mp.worker_finishes("u1", "payload", callback_dropped=False)
        self.assertEqual(mp.parent_recover("u1"), "payload")

    def test_content_addressed_recovers_even_when_callback_dropped(self) -> None:
        ca = ContentAddressedCustody()
        ca.worker_finishes("u1", "payload", callback_dropped=True)
        self.assertEqual(ca.parent_recover("u1"), "payload")
        self.assertFalse(ca.notifications_delivered["u1"])

    def test_both_arms_actually_execute_in_run_callback_loss_trial(self) -> None:
        unit_ids = [f"u{i}" for i in range(10)]
        drops = [i % 2 == 0 for i in range(10)]
        result = run_callback_loss_trial(unit_ids, drops)
        self.assertEqual(result["trials"], 10)
        self.assertEqual(result["callback_drop_count"], 5)
        self.assertEqual(result["message_passing_recovered"], 5)
        self.assertEqual(result["content_addressed_recovered"], 10)

    def test_content_addressed_strictly_dominates_across_random_seeds(self) -> None:
        rng = random.Random(20260822)
        for trial in range(20):
            n = rng.randint(5, 50)
            p_drop = rng.random()
            unit_ids = [f"trial{trial}-u{i}" for i in range(n)]
            drops = [rng.random() < p_drop for _ in range(n)]
            result = run_callback_loss_trial(unit_ids, drops)
            with self.subTest(trial=trial, n=n, p_drop=p_drop):
                self.assertEqual(result["content_addressed_recovery_rate"], 1.0)
                self.assertLessEqual(
                    result["message_passing_recovery_rate"], result["content_addressed_recovery_rate"]
                )


if __name__ == "__main__":
    unittest.main()
