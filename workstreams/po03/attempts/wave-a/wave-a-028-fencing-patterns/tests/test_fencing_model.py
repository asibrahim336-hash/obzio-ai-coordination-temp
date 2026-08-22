from __future__ import annotations

import sys
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UNIT_ROOT))

from fencing_model import (  # noqa: E402
    FenceRegression,
    FencedLedger,
    HighestSeenFenceSink,
    IdempotencyConflict,
    LedgerSequenceMismatch,
    OwnershipSnapshot,
    StaleOwnership,
)
from run_fixtures import execute_fixtures  # noqa: E402


class FencedLedgerTests(unittest.TestCase):
    def test_stale_owner_is_rejected_even_with_exact_next_sequence(self) -> None:
        ledger = FencedLedger("owner-a")
        ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="one",
            payload="one",
        )
        current = ledger.transfer("owner-b")

        with self.assertRaises(StaleOwnership):
            ledger.commit(
                owner_id="owner-a",
                fence_token=1,
                expected_sequence=2,
                operation_id="stale",
                payload="stale",
            )

        entry = ledger.commit(
            owner_id="owner-b",
            fence_token=current.fence_token,
            expected_sequence=2,
            operation_id="current",
            payload="current",
        )
        self.assertEqual(2, entry.sequence)

    def test_current_snapshot_does_not_replace_sequence_validation(self) -> None:
        ledger = FencedLedger("owner-a")
        ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="one",
            payload="one",
        )
        ledger.validate_snapshot(OwnershipSnapshot("owner-a", 1))

        with self.assertRaises(LedgerSequenceMismatch):
            ledger.commit(
                owner_id="owner-a",
                fence_token=1,
                expected_sequence=1,
                operation_id="two",
                payload="two",
            )

    def test_split_snapshot_validation_reproduces_stale_write(self) -> None:
        ledger = FencedLedger("owner-a")
        captured = ledger.snapshot
        ledger.validate_snapshot(captured)
        ledger.transfer("owner-b")

        entry = ledger.unsafe_append_after_prior_validation(
            prior_snapshot=captured,
            expected_sequence=1,
            operation_id="stale",
            payload="stale",
        )
        self.assertEqual("owner-a", entry.owner_id)
        self.assertEqual(1, entry.fence_token)

        with self.assertRaises(StaleOwnership):
            ledger.commit(
                owner_id="owner-a",
                fence_token=1,
                expected_sequence=2,
                operation_id="safe-path",
                payload="stale",
            )

    def test_transfer_rejects_equal_and_lower_fences(self) -> None:
        ledger = FencedLedger("owner-a", initial_fence=10)
        with self.assertRaises(FenceRegression):
            ledger.transfer("owner-b", requested_fence=10)
        with self.assertRaises(FenceRegression):
            ledger.transfer("owner-b", requested_fence=9)
        self.assertEqual(14, ledger.transfer("owner-b", requested_fence=14).fence_token)

    def test_exact_replay_after_transfer_has_no_new_effect(self) -> None:
        ledger = FencedLedger("owner-a")
        first = ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="one",
            payload="one",
        )
        ledger.transfer("owner-b")
        replay = ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="one",
            payload="one",
        )
        self.assertIs(first, replay)
        self.assertEqual(1, len(ledger.entries))

        with self.assertRaises(IdempotencyConflict):
            ledger.commit(
                owner_id="owner-a",
                fence_token=1,
                expected_sequence=1,
                operation_id="one",
                payload="changed",
            )


class HighestSeenSinkTests(unittest.TestCase):
    def test_old_equal_token_is_admitted_until_new_token_is_seen(self) -> None:
        sink = HighestSeenFenceSink()
        self.assertTrue(
            sink.write(fence_token=1, operation_id="one", payload="one")
        )
        self.assertTrue(
            sink.write(fence_token=1, operation_id="gap", payload="gap")
        )
        self.assertTrue(
            sink.write(fence_token=2, operation_id="two", payload="two")
        )
        with self.assertRaises(StaleOwnership):
            sink.write(fence_token=1, operation_id="late", payload="late")


class FixtureContractTests(unittest.TestCase):
    def test_every_frozen_fixture_matches_observed_output(self) -> None:
        report = execute_fixtures()
        self.assertEqual(6, report["summary"]["total"])
        self.assertEqual(6, report["summary"]["passed"])
        self.assertEqual(0, report["summary"]["failed"])


if __name__ == "__main__":
    unittest.main()
