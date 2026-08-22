#!/usr/bin/env python3
"""Matched acceptance-timing experiment over seeded defective results."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFECTS = ("missing_artifact_count", "zero_artifacts", "bad_hash", "wrong_state", "false_tests")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fixtures(seed: int, count: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    results = []
    for index in range(count):
        result: dict[str, object] = {
            "task_id": f"po03-synthetic-{index:04d}",
            "state": "COMMITTED",
            "artifact_count": 2,
            "artifact_sha256": hashlib.sha256(f"artifact-{index}".encode()).hexdigest(),
            "tests_passed": True,
            "decision_changed": [],
        }
        defect = rng.choice(DEFECTS)
        if defect == "missing_artifact_count":
            del result["artifact_count"]
        elif defect == "zero_artifacts":
            result["artifact_count"] = 0
        elif defect == "bad_hash":
            result["artifact_sha256"] = "producer-reported-ok"
        elif defect == "wrong_state":
            result["state"] = "RUNNING"
        elif defect == "false_tests":
            result["tests_passed"] = False
        results.append({"fixture": index, "defect": defect, "result": result})
    return results


def frozen_acceptance(result: dict[str, object]) -> bool:
    return (
        set(result) == {"task_id", "state", "artifact_count", "artifact_sha256", "tests_passed", "decision_changed"}
        and isinstance(result["task_id"], str)
        and result["task_id"].startswith("po03-synthetic-")
        and result["state"] == "COMMITTED"
        and isinstance(result["artifact_count"], int)
        and not isinstance(result["artifact_count"], bool)
        and result["artifact_count"] > 0
        and isinstance(result["artifact_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", result["artifact_sha256"]) is not None
        and result["tests_passed"] is True
        and result["decision_changed"] == []
    )


def adapted_after_acceptance(result: dict[str, object]) -> bool:
    """Model a verifier derived from the observed shape, not the prior contract."""
    inferred_types = {
        key: (int if isinstance(value, int) and not isinstance(value, bool) else type(value))
        for key, value in result.items()
    }
    return all(
        (isinstance(value, expected) and not (expected is int and isinstance(value, bool)))
        for key, expected in inferred_types.items()
        for value in (result[key],)
    )


def run(preregister: dict[str, object]) -> dict[str, object]:
    seeded = fixtures(int(preregister["seed"]), int(preregister["sample_size"]))
    raw = []
    for item in seeded:
        result = item["result"]
        frozen_green = frozen_acceptance(result)
        adapted_green = adapted_after_acceptance(result)
        raw.append(
            {
                "fixture": item["fixture"],
                "defect": item["defect"],
                "frozen_false_green": frozen_green,
                "adapted_false_green": adapted_green,
            }
        )
    frozen_rate = sum(item["frozen_false_green"] for item in raw) / len(raw)
    adapted_rate = sum(item["adapted_false_green"] for item in raw) / len(raw)
    reduction = adapted_rate - frozen_rate
    passed = reduction >= 0.20
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size": len(raw),
        "defect_counts": dict(sorted(Counter(item["defect"] for item in raw).items())),
        "arms": {
            "criteria_frozen_before_output": {"false_green_rate": frozen_rate},
            "criteria_adapted_after_output": {"false_green_rate": adapted_rate},
        },
        "false_green_rate_reduction": reduction,
        "verdict": "PASS" if passed else "FAIL",
        "refutation_triggered": not passed,
        "raw_trials": raw,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    result = run(json.loads((ROOT / "preregister.json").read_text()))
    args.output.write_bytes(canonical(result))
    summary = {key: value for key, value in result.items() if key != "raw_trials"}
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
