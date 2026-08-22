#!/usr/bin/env python3
"""Measure rework across checkpoint granularities under matched failures."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def rework_for_failure(completed_before_failure: int, granularity: int, total_steps: int) -> int:
    if granularity >= total_steps:
        persisted = 0
    else:
        persisted = (completed_before_failure // granularity) * granularity
    return completed_before_failure - persisted


def run(preregister: dict[str, object]) -> dict[str, object]:
    rng = random.Random(int(preregister["seed"]))
    count = int(preregister["sample_size"])
    steps = int(preregister["steps_per_attempt"])
    granularities = [int(value) for value in preregister["checkpoint_granularities"]]
    failures = [rng.randint(1, steps - 1) for _ in range(count)]
    raw = []
    for trial, failure in enumerate(failures):
        raw.append(
            {
                "trial": trial,
                "completed_steps_before_failure": failure,
                "reworked_steps": {
                    str(granularity): rework_for_failure(failure, granularity, steps)
                    for granularity in granularities
                },
            }
        )
    arms = {}
    for granularity in granularities:
        values = [item["reworked_steps"][str(granularity)] for item in raw]
        arms[str(granularity)] = {
            "checkpoint_every_steps": granularity,
            "mean_reworked_steps": sum(values) / count,
            "total_reworked_steps": sum(values),
        }
    every_step = arms["1"]["mean_reworked_steps"]
    all_or_nothing = arms[str(steps)]["mean_reworked_steps"]
    reduction = (all_or_nothing - every_step) / all_or_nothing
    accepted = every_step < all_or_nothing and reduction >= 0.50
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size": count,
        "steps_per_attempt": steps,
        "arms": arms,
        "granularity_1_rework_reduction_fraction": reduction,
        "verdict": "PASS" if accepted else "FAIL",
        "refutation_triggered": not accepted,
        "raw_trials": raw,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    result = run(json.loads((ROOT / "preregister.json").read_text()))
    args.output.write_bytes(canonical(result))
    print(json.dumps({key: value for key, value in result.items() if key != "raw_trials"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
