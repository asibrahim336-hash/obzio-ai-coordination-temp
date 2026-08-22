#!/usr/bin/env python3
"""Blind seeded-defect review with an explicitly limited local fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFECTS = ("missing_hash", "bad_hash", "path_escape", "running_state", "self_acceptance", "strategy_binding")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fixtures(seed: int, count: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    output = []
    for number in range(count):
        payload: dict[str, object] = {
            "task_id": f"po03-blind-{number:04d}",
            "state": "COMMITTED",
            "artifact_path": f"workstreams/po03/attempts/synthetic/{number}.json",
            "artifact_sha256": hashlib.sha256(str(number).encode()).hexdigest(),
            "completion_actor": None,
            "decision_changed": [],
        }
        defect = rng.choice(DEFECTS)
        if defect == "missing_hash":
            del payload["artifact_sha256"]
        elif defect == "bad_hash":
            payload["artifact_sha256"] = "looks-good"
        elif defect == "path_escape":
            payload["artifact_path"] = "../../state/forbidden.json"
        elif defect == "running_state":
            payload["state"] = "RUNNING"
        elif defect == "self_acceptance":
            payload["completion_actor"] = "producer"
        elif defect == "strategy_binding":
            payload["decision_changed"] = ["bind strategy"]
        output.append({"fixture": number, "defect": defect, "payload": payload})
    return output


def structural_reviewer(payload: dict[str, object]) -> bool:
    """Blind profile A: detect malformed or out-of-bound artifact structures."""
    digest = payload.get("artifact_sha256")
    path = payload.get("artifact_path")
    return (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(path, str)
        or not path.startswith("workstreams/po03/attempts/")
        or ".." in Path(path).parts
    )


def adversarial_reviewer(payload: dict[str, object]) -> bool:
    """Blind profile B: detect authority and transaction-semantic violations."""
    return (
        payload.get("state") != "COMMITTED"
        or payload.get("completion_actor") is not None
        or payload.get("decision_changed") != []
    )


def run(preregister: dict[str, object], provider: dict[str, object]) -> dict[str, object]:
    seeded = fixtures(int(preregister["seed"]), int(preregister["sample_size"]))
    raw = []
    for item in seeded:
        first = structural_reviewer(item["payload"])
        second = adversarial_reviewer(item["payload"])
        raw.append(
            {
                "fixture": item["fixture"],
                "defect": item["defect"],
                "structural_detected": first,
                "adversarial_detected": second,
                "disagreed": first != second,
            }
        )
    count = len(raw)
    first_rate = sum(item["structural_detected"] for item in raw) / count
    second_rate = sum(item["adversarial_detected"] for item in raw) / count
    disagreement = sum(item["disagreed"] for item in raw) / count
    incremental = sum(item["adversarial_detected"] and not item["structural_detected"] for item in raw) / count
    family_verified = provider["status"] == "SUPPORTED"
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "provider_attempt_sha256": hashlib.sha256(canonical(provider)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size": count,
        "defect_counts": dict(sorted(Counter(item["defect"] for item in raw).items())),
        "arms": {
            "structural_blind_profile": {
                "model_family": "NOT_SUPPORTED",
                "detection_rate": first_rate,
                "execution": "single-runtime deterministic fallback",
            },
            "adversarial_blind_profile": {
                "model_family": "NOT_SUPPORTED",
                "detection_rate": second_rate,
                "execution": "single-runtime deterministic fallback",
            },
        },
        "reviewer_disagreement_rate": disagreement,
        "incremental_detection_rate_of_adversarial_profile": incremental,
        "different_family_identity_verified": family_verified,
        "verdict": "NOT_SUPPORTED",
        "refutation_triggered": False,
        "limitation": provider["verbatim_boundary"],
        "raw_trials": raw,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    preregister = json.loads((ROOT / "preregister.json").read_text())
    provider = json.loads((ROOT / "provider_attempt.json").read_text())
    result = run(preregister, provider)
    args.output.write_bytes(canonical(result))
    summary = {key: value for key, value in result.items() if key != "raw_trials"}
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
