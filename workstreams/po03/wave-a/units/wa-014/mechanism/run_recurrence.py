#!/usr/bin/env python3
"""Repeat the stale-worker fixture and fail on any fence regression."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_concurrency_fixture import _write_output, run_fixture  # noqa: E402


def run_recurrence(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    stale_attempts = 0
    blocked_attempts = 0
    observed_token_sequences: set[tuple[int, int]] = set()

    for _ in range(iterations):
        report = run_fixture()
        observed = report["observed"]
        stale_attempts += 1
        blocked_attempts += int(not observed["stale_commit_accepted"])
        observed_token_sequences.add(
            (
                observed["initial_fence_token"],
                observed["transfer_fence_token"],
            )
        )
        if report["hypothesis_outcome"] != "SUPPORTED":
            raise AssertionError("fixture did not support the frozen hypothesis")
        if observed["durable_commit_count"] != 1:
            raise AssertionError("fixture produced a non-singleton commit")
        if observed["committed_fence_token"] != 2:
            raise AssertionError("successor did not commit with fence 2")

    if blocked_attempts != stale_attempts:
        raise AssertionError("one or more stale commits escaped fencing")
    if observed_token_sequences != {(1, 2)}:
        raise AssertionError(
            f"non-monotonic token sequence: {sorted(observed_token_sequences)!r}"
        )

    return {
        "protocol_version": "PO03-WA-014-RECURRENCE-v1",
        "task_id": "PO03-WA-014",
        "hypothesis_id": "H-PO03-WA-014",
        "iterations": iterations,
        "stale_commit_attempts": stale_attempts,
        "stale_commit_attempts_blocked": blocked_attempts,
        "false_acceptances": 0,
        "durable_commits_per_iteration": 1,
        "observed_token_sequences": [[1, 2]],
        "outcome": "PASS",
        "external_effects": [],
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=64)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_recurrence(args.iterations)
    if args.output is not None:
        _write_output(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
