"""Tests for the a5 hypothesis preregistration ledger.

These tests protect the preregistration guarantee itself: every one of the
twelve dispatched units must have a hypothesis row, the row's frozen fields
must match the immutable dispatch record byte-for-byte, and the four custody
states (source / frozen_hypothesis / registration) must never collapse into
one undifferentiated blob.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PO03_ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES_PATH = PO03_ROOT / "research" / "hypotheses.jsonl"
DISPATCH_DIR = PO03_ROOT / "control" / "dispatch"

EXPECTED_UNITS = [f"a5-u{i:02d}" for i in range(1, 13)]


def load_rows() -> list[dict]:
    rows = []
    for line in HYPOTHESES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


class TestHypothesisRegistration(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = load_rows()
        self.by_unit = {row["unit_id"]: row for row in self.rows}

    def test_ledger_file_exists(self) -> None:
        self.assertTrue(HYPOTHESES_PATH.exists())

    def test_all_twelve_units_registered(self) -> None:
        missing = [unit for unit in EXPECTED_UNITS if unit not in self.by_unit]
        self.assertEqual(missing, [], f"missing hypothesis registrations: {missing}")

    def test_at_least_twelve_rows(self) -> None:
        self.assertGreaterEqual(len(self.rows), 12)

    def test_states_are_distinct_fields(self) -> None:
        for unit_id, row in self.by_unit.items():
            with self.subTest(unit=unit_id):
                self.assertIn("source", row)
                self.assertIn("frozen_hypothesis", row)
                self.assertIn("registration", row)
                self.assertEqual(row["source"]["state"], "source")
                self.assertEqual(row["frozen_hypothesis"]["state"], "frozen_hypothesis")
                self.assertEqual(row["registration"]["state"], "registration")
                # A row must never claim to already be a reproduction or a
                # mechanism change; those states only exist in the separate
                # reproduction ledger, produced after this row is committed.
                self.assertNotIn("reproduction", row)
                self.assertNotIn("mechanism_change", row)

    def test_frozen_hypothesis_matches_dispatch_record_verbatim(self) -> None:
        for unit_id, row in self.by_unit.items():
            with self.subTest(unit=unit_id):
                dispatch = json.loads((DISPATCH_DIR / f"{unit_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(row["frozen_hypothesis"]["hypothesis_text"], dispatch["hypothesis"])
                self.assertEqual(
                    row["frozen_hypothesis"]["acceptance_assertion"], dispatch["acceptance"]["assertion"]
                )
                self.assertEqual(
                    row["frozen_hypothesis"]["falsified_if"], dispatch["acceptance"]["falsified_if"]
                )
                self.assertEqual(row["acceptance_contract_sha256"], dispatch["acceptance_contract_sha256"])

    def test_row_hash_is_self_consistent(self) -> None:
        import hashlib

        for row in self.rows:
            body = {k: v for k, v in row.items() if k != "row_sha256"}
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.assertEqual(row["row_sha256"], expected)

    def test_registered_before_reproduction_flag_is_true(self) -> None:
        for unit_id, row in self.by_unit.items():
            with self.subTest(unit=unit_id):
                self.assertTrue(row["registered_before_reproduction"])


if __name__ == "__main__":
    unittest.main()
