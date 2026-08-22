#!/usr/bin/env python3
"""Apply frozen standing, chronology, and identifier precedence deterministically."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any


STANDING_RANK = {"QUARANTINED": 0, "SUPERSEDED": 1, "RETAINED": 2, "CURRENT": 3}


def timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def precedence(records: list[dict[str, str]]) -> dict[str, Any]:
    if not records:
        raise ValueError("NO_CANDIDATES")
    for record in records:
        if record.get("standing") not in STANDING_RANK:
            raise ValueError("UNKNOWN_STANDING")
        timestamp(record["effective_at"])
        if not record.get("source_id"):
            raise ValueError("SOURCE_ID_REQUIRED")
    ordered = sorted(
        records,
        key=lambda item: (
            -STANDING_RANK[item["standing"]],
            -timestamp(item["effective_at"]),
            item["source_id"],
        ),
    )
    normalized = [
        {
            "effective_at": item["effective_at"],
            "source_id": item["source_id"],
            "standing": item["standing"],
            "standing_rank": STANDING_RANK[item["standing"]],
        }
        for item in ordered
    ]
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True).encode()
    return {
        "ordered_candidates": normalized,
        "precedence_digest": hashlib.sha256(encoded).hexdigest(),
        "rule": ["standing_desc", "chronology_desc", "source_id_asc"],
        "selected_source_id": normalized[0]["source_id"],
    }


class DeterministicPrecedenceTests(unittest.TestCase):
    def candidates(self) -> list[dict[str, str]]:
        return [
            {"source_id": "CURRENT-OLD", "standing": "CURRENT", "effective_at": "2026-08-19T00:00:00Z"},
            {"source_id": "SUPERSEDED-NEW", "standing": "SUPERSEDED", "effective_at": "2026-08-22T00:00:00Z"},
            {"source_id": "CURRENT-NEW-B", "standing": "CURRENT", "effective_at": "2026-08-20T00:00:00Z"},
            {"source_id": "CURRENT-NEW-A", "standing": "CURRENT", "effective_at": "2026-08-20T00:00:00Z"},
        ]

    def test_all_input_permutations_produce_same_winner_and_digest(self) -> None:
        outcomes = {
            (precedence(list(order))["selected_source_id"], precedence(list(order))["precedence_digest"])
            for order in itertools.permutations(self.candidates())
        }
        self.assertEqual(1, len(outcomes))
        selected, _ = outcomes.pop()
        self.assertEqual("CURRENT-NEW-A", selected)

    def test_standing_outranks_newer_superseded_chronology(self) -> None:
        result = precedence(self.candidates()[:2])
        self.assertEqual("CURRENT-OLD", result["selected_source_id"])


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DeterministicPrecedenceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    demonstration = precedence(DeterministicPrecedenceTests().candidates())
    print(json.dumps({"disposition": "PASS" if result.wasSuccessful() else "FAIL", "precedence_digest": demonstration["precedence_digest"], "selected": demonstration["selected_source_id"], "tests_run": result.testsRun}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("test", "select"))
    parser.add_argument("--records", type=Path)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    if args.records is None:
        parser.error("select requires --records")
    records = json.loads(args.records.read_text(encoding="utf-8"))
    print(json.dumps(precedence(records), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
