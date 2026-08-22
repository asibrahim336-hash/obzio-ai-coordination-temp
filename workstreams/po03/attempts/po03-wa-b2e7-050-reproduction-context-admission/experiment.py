#!/usr/bin/env python3
"""Matched context-admission reproduction on synthetic Obzio-shaped tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED = ("task_id", "commission_id", "fence_token", "acceptance_hash", "owned_path", "return_route")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def make_workload(seed: int, count: int) -> list[list[tuple[str, str]]]:
    rng = random.Random(seed)
    workloads = []
    for trial in range(count):
        fields = [(key, f"{key}-value-{trial}") for key in REQUIRED]
        fields.extend((f"irrelevant_{number:03d}", f"noise-{trial}-{number}") for number in range(64))
        rng.shuffle(fields)
        workloads.append(fields)
    return workloads


def full_dump(fields: list[tuple[str, str]], budget: int) -> dict[str, str]:
    return dict(fields[:budget])


def bounded_capsule(fields: list[tuple[str, str]], budget: int) -> tuple[dict[str, str], str]:
    admitted = {key: value for key, value in fields if key in REQUIRED}
    if len(admitted) > budget:
        raise ValueError("required context exceeds admission budget")
    return admitted, hashlib.sha256(canonical(admitted)).hexdigest()


def run(preregister: dict[str, object]) -> dict[str, object]:
    workloads = make_workload(int(preregister["seed"]), int(preregister["sample_size"]))
    budget = int(preregister["admission_budget_fields"])
    trials = []
    mismatches = 0
    for number, fields in enumerate(workloads):
        dump = full_dump(fields, budget)
        bounded, digest = bounded_capsule(fields, budget)
        if hashlib.sha256(canonical(bounded)).hexdigest() != digest:
            mismatches += 1
        bounded_recovered = sum(key in bounded for key in REQUIRED)
        dump_recovered = sum(key in dump for key in REQUIRED)
        trials.append(
            {
                "trial": number,
                "bounded_required_recovered": bounded_recovered,
                "dump_required_recovered": dump_recovered,
                "bounded_admitted_fields": len(bounded),
                "dump_admitted_fields": len(dump),
            }
        )
    denominator = len(trials) * len(REQUIRED)
    bounded_rate = sum(item["bounded_required_recovered"] for item in trials) / denominator
    dump_rate = sum(item["dump_required_recovered"] for item in trials) / denominator
    delta = bounded_rate - dump_rate
    accepted = delta >= 0.20 and mismatches == 0
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size": len(trials),
        "arms": {
            "bounded_hashed_capsule": {"mean_required_field_recovery": bounded_rate},
            "indiscriminate_full_dump": {"mean_required_field_recovery": dump_rate},
        },
        "bounded_minus_dump_recovery": delta,
        "bounded_hash_mismatches": mismatches,
        "verdict": "PASS" if accepted else "FAIL",
        "refutation_triggered": not accepted,
        "raw_trials": trials,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    preregister = json.loads((ROOT / "preregister.json").read_text())
    result = run(preregister)
    args.output.write_bytes(canonical(result))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
