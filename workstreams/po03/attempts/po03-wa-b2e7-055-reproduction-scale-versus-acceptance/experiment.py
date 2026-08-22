#!/usr/bin/env python3
"""Sweep attempt concurrency against fixed acceptance and recovery capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def defect_probability(concurrency: int, acceptance_capacity: int) -> float:
    return min(0.80, 0.04 + 0.025 * max(0, concurrency - acceptance_capacity))


def detection_probability(concurrency: int, acceptance_capacity: int) -> float:
    return max(0.25, 0.98 - 0.02 * max(0, concurrency - acceptance_capacity))


def simulate_level(
    seed: int,
    slots: int,
    concurrency: int,
    acceptance_capacity: int,
    recovery_capacity: int,
) -> dict[str, object]:
    rng = random.Random(seed + concurrency)
    acceptance_queue: deque[dict[str, object]] = deque()
    recovery_queue: deque[dict[str, object]] = deque()
    defect_chance = defect_probability(concurrency, acceptance_capacity)
    detection_chance = detection_probability(concurrency, acceptance_capacity)
    produced = reviewed = accepted_good = escaped = detected = recovered = 0
    raw_slots = []
    task = 0
    for slot in range(slots):
        for _ in range(concurrency):
            acceptance_queue.append({"task": task, "defective": rng.random() < defect_chance})
            task += 1
            produced += 1
        slot_good = slot_escaped = slot_detected = slot_recovered = 0
        for _ in range(min(acceptance_capacity, len(acceptance_queue))):
            candidate = acceptance_queue.popleft()
            reviewed += 1
            if not candidate["defective"]:
                accepted_good += 1
                slot_good += 1
            elif rng.random() < detection_chance:
                detected += 1
                slot_detected += 1
                recovery_queue.append(candidate)
            else:
                escaped += 1
                slot_escaped += 1
        for _ in range(min(recovery_capacity, len(recovery_queue))):
            candidate = recovery_queue.popleft()
            candidate["defective"] = False
            acceptance_queue.append(candidate)
            recovered += 1
            slot_recovered += 1
        raw_slots.append(
            {
                "slot": slot,
                "accepted_good": slot_good,
                "escaped_defects": slot_escaped,
                "detected_defects": slot_detected,
                "recovered_to_acceptance_queue": slot_recovered,
                "acceptance_queue_depth": len(acceptance_queue),
                "recovery_queue_depth": len(recovery_queue),
            }
        )
    accepted_total = accepted_good + escaped
    return {
        "concurrency": concurrency,
        "defect_probability": defect_chance,
        "review_detection_probability": detection_chance,
        "produced": produced,
        "reviewed": reviewed,
        "accepted_good": accepted_good,
        "escaped_defects": escaped,
        "detected_defects": detected,
        "recovered_to_acceptance_queue": recovered,
        "final_acceptance_queue_depth": len(acceptance_queue),
        "final_recovery_queue_depth": len(recovery_queue),
        "independently_accepted_good_results_per_slot": accepted_good / slots,
        "escaped_defect_fraction_of_accepted": escaped / accepted_total if accepted_total else 0.0,
        "raw_slots": raw_slots,
    }


def run(preregister: dict[str, object]) -> dict[str, object]:
    levels = [
        simulate_level(
            int(preregister["seed"]),
            int(preregister["sample_size_slots_per_level"]),
            int(concurrency),
            int(preregister["acceptance_capacity_per_slot"]),
            int(preregister["recovery_capacity_per_slot"]),
        )
        for concurrency in preregister["concurrency_levels"]
    ]
    by_level = {str(item["concurrency"]): item for item in levels}
    baseline = by_level["4"]
    high = by_level["32"]
    throughput_delta = (
        high["independently_accepted_good_results_per_slot"]
        - baseline["independently_accepted_good_results_per_slot"]
    )
    escape_delta = (
        high["escaped_defect_fraction_of_accepted"]
        - baseline["escaped_defect_fraction_of_accepted"]
    )
    accepted = throughput_delta < 0 and escape_delta > 0
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size_slots_per_level": preregister["sample_size_slots_per_level"],
        "acceptance_capacity_per_slot": preregister["acceptance_capacity_per_slot"],
        "recovery_capacity_per_slot": preregister["recovery_capacity_per_slot"],
        "levels": levels,
        "concurrency_32_minus_4_good_throughput": throughput_delta,
        "concurrency_32_minus_4_escaped_defect_fraction": escape_delta,
        "verdict": "PASS" if accepted else "FAIL",
        "refutation_triggered": not accepted,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    result = run(json.loads((ROOT / "preregister.json").read_text()))
    args.output.write_bytes(canonical(result))
    summary = dict(result)
    summary["levels"] = [
        {key: value for key, value in item.items() if key != "raw_slots"} for item in result["levels"]
    ]
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
