#!/usr/bin/env python3
"""Inject return loss and compare report-only against durable outbox read-back."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def commit_outbox(directory: Path, record: dict[str, object]) -> tuple[Path, str]:
    body = canonical(record)
    digest = hashlib.sha256(body).hexdigest()
    final = directory / f"{record['task_id']}.json"
    temporary = directory / f".{record['task_id']}.tmp"
    with temporary.open("wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, final)
    return final, digest


def verified_readback(path: Path, expected_sha256: str) -> dict[str, object]:
    body = path.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"outbox hash mismatch: expected {expected_sha256}, got {actual}")
    return json.loads(body)


def run(preregister: dict[str, object], scratch: Path) -> dict[str, object]:
    rng = random.Random(int(preregister["seed"]))
    sample_size = int(preregister["sample_size"])
    loss_probability = float(preregister["injected_return_loss_probability"])
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    raw = []
    mismatches = 0
    try:
        for number in range(sample_size):
            loss = rng.random() < loss_probability
            record = {"task_id": f"synthetic-result-{number:04d}", "value": number, "state": "COMMITTED"}
            report_recovered = not loss
            path, digest = commit_outbox(scratch, record)
            try:
                readback = verified_readback(path, digest)
                outbox_recovered = (not loss and readback == record) or (loss and readback == record)
            except ValueError:
                mismatches += 1
                outbox_recovered = False
            raw.append(
                {
                    "trial": number,
                    "return_loss_injected": loss,
                    "report_only_recovered": report_recovered,
                    "outbox_readback_recovered": outbox_recovered,
                    "outbox_sha256": digest,
                }
            )
    finally:
        shutil.rmtree(scratch)
    report_fraction = sum(item["report_only_recovered"] for item in raw) / sample_size
    outbox_fraction = sum(item["outbox_readback_recovered"] for item in raw) / sample_size
    accepted = outbox_fraction == 1.0 and report_fraction < 1.0 and mismatches == 0
    return {
        "protocol": preregister["protocol"],
        "hypothesis_id": preregister["hypothesis_id"],
        "preregister_sha256": hashlib.sha256(canonical(preregister)).hexdigest(),
        "seed": preregister["seed"],
        "sample_size": sample_size,
        "losses_injected": sum(item["return_loss_injected"] for item in raw),
        "arms": {
            "report_only": {"recovered_result_fraction": report_fraction},
            "transactional_outbox_with_readback": {
                "recovered_result_fraction": outbox_fraction,
                "hash_mismatches": mismatches,
            },
        },
        "verdict": "PASS" if accepted else "FAIL",
        "refutation_triggered": not accepted,
        "raw_trials": raw,
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "measurement.json")
    args = parser.parse_args()
    result = run(json.loads((ROOT / "preregister.json").read_text()), ROOT / ".scratch")
    args.output.write_bytes(canonical(result))
    print(json.dumps({key: value for key, value in result.items() if key != "raw_trials"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
