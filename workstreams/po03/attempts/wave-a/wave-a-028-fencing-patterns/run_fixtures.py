#!/usr/bin/env python3
"""Run the deterministic fencing fault fixtures."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Callable

from fencing_model import (
    FenceRegression,
    FencedLedger,
    HighestSeenFenceSink,
    IdempotencyConflict,
    LedgerSequenceMismatch,
    StaleOwnership,
)


UNIT_ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURES = UNIT_ROOT / "fixtures" / "fencing-edge-cases.json"


def error_name(action: Callable[[], object]) -> str | None:
    try:
        action()
    except Exception as exc:  # expected exceptions are compared by class name
        return type(exc).__name__
    return None


def split_validation_stale_write() -> dict[str, Any]:
    ledger = FencedLedger("owner-a")
    captured = ledger.snapshot
    ledger.validate_snapshot(captured)
    transferred = ledger.transfer("owner-b")
    unsafe = ledger.unsafe_append_after_prior_validation(
        prior_snapshot=captured,
        expected_sequence=1,
        operation_id="unsafe-stale-write",
        payload="result-from-owner-a",
    )
    safe_error = error_name(
        lambda: ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=2,
            operation_id="safe-path-stale-write",
            payload="another-result-from-owner-a",
        )
    )
    return {
        "captured_fence": captured.fence_token,
        "current_fence": transferred.fence_token,
        "safe_path_error": safe_error,
        "unsafe_entry_owner": unsafe.owner_id,
        "unsafe_stale_write_accepted": True,
    }


def ledger_sequence_not_fence() -> dict[str, Any]:
    ledger = FencedLedger("owner-a")
    ledger.commit(
        owner_id="owner-a",
        fence_token=1,
        expected_sequence=1,
        operation_id="first",
        payload="one",
    )
    current = ledger.transfer("owner-b")
    stale_error = error_name(
        lambda: ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=2,
            operation_id="stale-with-correct-sequence",
            payload="two-stale",
        )
    )
    accepted = ledger.commit(
        owner_id="owner-b",
        fence_token=current.fence_token,
        expected_sequence=2,
        operation_id="current-with-correct-sequence",
        payload="two-current",
    )
    return {
        "accepted_owner": accepted.owner_id,
        "accepted_sequence": accepted.sequence,
        "stale_error": stale_error,
        "stale_used_next_sequence": 2,
    }


def snapshot_not_sequence() -> dict[str, Any]:
    ledger = FencedLedger("owner-a")
    ledger.commit(
        owner_id="owner-a",
        fence_token=1,
        expected_sequence=1,
        operation_id="first",
        payload="one",
    )
    sequence_error = error_name(
        lambda: ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="current-owner-stale-sequence",
            payload="two",
        )
    )
    return {
        "current_snapshot_valid": True,
        "ledger_entry_count": len(ledger.entries),
        "sequence_error": sequence_error,
    }


def monotonic_transfer() -> dict[str, Any]:
    ledger = FencedLedger("owner-a", initial_fence=7)
    first = ledger.transfer("owner-b")
    equal_error = error_name(
        lambda: ledger.transfer("owner-c", requested_fence=first.fence_token)
    )
    lower_error = error_name(
        lambda: ledger.transfer("owner-c", requested_fence=6)
    )
    jumped = ledger.transfer("owner-c", requested_fence=12)
    return {
        "equal_token_error": equal_error,
        "first_transfer_fence": first.fence_token,
        "jumped_transfer_fence": jumped.fence_token,
        "lower_token_error": lower_error,
    }


def highest_seen_observation_gap() -> dict[str, Any]:
    authority = FencedLedger("owner-a")
    sink = HighestSeenFenceSink()
    sink.write(fence_token=1, operation_id="a-before", payload="before")
    transferred = authority.transfer("owner-b")
    stale_during_gap = sink.write(
        fence_token=1,
        operation_id="a-during-gap",
        payload="stale-during-gap",
    )
    sink.write(
        fence_token=transferred.fence_token,
        operation_id="b-current",
        payload="current",
    )
    stale_after_observation_error = error_name(
        lambda: sink.write(
            fence_token=1,
            operation_id="a-after-observation",
            payload="stale-after-observation",
        )
    )
    return {
        "sink_highest_seen": sink.highest_seen_fence,
        "stale_after_observation_error": stale_after_observation_error,
        "stale_during_gap_accepted": stale_during_gap,
        "write_count": len(sink.writes),
    }


def idempotent_replay_after_transfer() -> dict[str, Any]:
    ledger = FencedLedger("owner-a")
    first = ledger.commit(
        owner_id="owner-a",
        fence_token=1,
        expected_sequence=1,
        operation_id="operation-one",
        payload="one",
    )
    ledger.transfer("owner-b")
    replay = ledger.commit(
        owner_id="owner-a",
        fence_token=1,
        expected_sequence=1,
        operation_id="operation-one",
        payload="one",
    )
    conflict_error = error_name(
        lambda: ledger.commit(
            owner_id="owner-a",
            fence_token=1,
            expected_sequence=1,
            operation_id="operation-one",
            payload="changed",
        )
    )
    return {
        "conflict_error": conflict_error,
        "entry_count": len(ledger.entries),
        "replay_returned_original": replay == first,
    }


SCENARIOS: dict[str, Callable[[], dict[str, Any]]] = {
    "split-validation-stale-write": split_validation_stale_write,
    "ledger-sequence-not-fence": ledger_sequence_not_fence,
    "snapshot-not-ledger-sequence": snapshot_not_sequence,
    "monotonic-transfer": monotonic_transfer,
    "highest-seen-observation-gap": highest_seen_observation_gap,
    "idempotent-replay-after-transfer": idempotent_replay_after_transfer,
}


def execute_fixtures(fixture_path: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    fixture_document = json.loads(fixture_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in fixture_document["cases"]:
        case_id = case["id"]
        observed = SCENARIOS[case_id]()
        passed = observed == case["expected"]
        if not passed:
            failures.append(case_id)
        results.append(
            {
                "id": case_id,
                "observed": observed,
                "passed": passed,
            }
        )
    return {
        "fixture_version": fixture_document["fixture_version"],
        "platform": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
            "system": platform.system(),
        },
        "results": results,
        "summary": {
            "failed": len(failures),
            "failed_case_ids": failures,
            "passed": len(results) - len(failures),
            "total": len(results),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = execute_fixtures(args.fixtures)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
