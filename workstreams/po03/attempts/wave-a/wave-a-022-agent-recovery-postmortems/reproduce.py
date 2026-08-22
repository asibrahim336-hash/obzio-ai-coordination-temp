#!/usr/bin/env python3
"""Sanitized, dependency-free reproductions of agent result-loss mechanisms."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "observed-results.json"


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and durable writes."""
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json_write(path: Path, value: Any) -> None:
    """Write and fsync a JSON file before atomically replacing its destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def controlled_checkpoint_trial(workers: int, protected: bool) -> dict[str, Any]:
    """Exercise one controlled stale-snapshot schedule.

    In the unprotected case every worker reads the same empty list before any
    worker publishes. Publishing those stale snapshots in a fixed order makes
    the last rebind erase all prior writes. In the protected control, the read,
    filter, rebind, and append occur inside one lock.
    """
    if workers < 2:
        raise ValueError("workers must be at least 2")

    pending: list[tuple[str, str]] = []
    read_barrier = threading.Barrier(workers)
    publish_condition = threading.Condition()
    critical_section = threading.Lock()
    next_worker = 0

    def worker(worker_index: int) -> None:
        nonlocal next_worker, pending
        task_id = f"task-{worker_index}"
        stale_snapshot = None
        if not protected:
            stale_snapshot = [item for item in pending if item[0] != task_id]

        read_barrier.wait()
        with publish_condition:
            publish_condition.wait_for(lambda: next_worker == worker_index)
            if protected:
                with critical_section:
                    current = [item for item in pending if item[0] != task_id]
                    pending = current
                    pending.append((task_id, f"result-{worker_index}"))
            else:
                assert stale_snapshot is not None
                pending = stale_snapshot
                pending.append((task_id, f"result-{worker_index}"))
            next_worker += 1
            publish_condition.notify_all()

    threads = [
        threading.Thread(target=worker, args=(index,), name=f"writer-{index}")
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError(f"thread did not finish: {thread.name}")

    retained_ids = sorted(task_id for task_id, _ in pending)
    return {
        "expected_writes": workers,
        "lost_writes": workers - len(retained_ids),
        "protected": protected,
        "retained_task_ids": retained_ids,
        "retained_writes": len(retained_ids),
    }


def run_checkpoint_trials(*, trials: int, workers: int, protected: bool) -> dict[str, Any]:
    observations = [
        controlled_checkpoint_trial(workers=workers, protected=protected)
        for _ in range(trials)
    ]
    return {
        "expected_writes": trials * workers,
        "lost_writes": sum(item["lost_writes"] for item in observations),
        "lossy_trials": sum(item["lost_writes"] > 0 for item in observations),
        "protected": protected,
        "retained_writes": sum(item["retained_writes"] for item in observations),
        "trials": trials,
        "workers_per_trial": workers,
    }


def _result_payload(trial: int) -> dict[str, str]:
    result_id = f"sanitized-result-{trial:02d}"
    return {
        "payload_sha256": sha256_bytes(result_id.encode("utf-8")),
        "result_id": result_id,
    }


def worker_main(mode: str, result_path: Path, trial: int) -> int:
    payload = _result_payload(trial)
    if mode == "durable":
        atomic_json_write(result_path, payload)
    elif mode != "ephemeral":
        raise ValueError(f"unsupported worker mode: {mode}")

    receipt = {
        "mode": mode,
        "provider_state": "COMPLETED",
        "result_id": payload["result_id"],
    }
    sys.stdout.buffer.write(canonical_json_bytes(receipt))
    return 0


def run_process_exit_trials(*, trials: int, mode: str) -> dict[str, Any]:
    completed_receipts = 0
    durable_readbacks = 0
    hash_verified_readbacks = 0

    with tempfile.TemporaryDirectory(prefix=".result-loss-", dir=HERE) as temp_name:
        temp_dir = Path(temp_name)
        for trial in range(trials):
            result_path = temp_dir / f"{mode}-{trial}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-mode",
                mode,
                "--result-path",
                str(result_path),
                "--trial",
                str(trial),
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"worker failed ({completed.returncode}): "
                    f"{completed.stderr.decode('utf-8', 'replace')}"
                )
            receipt = json.loads(completed.stdout)
            completed_receipts += receipt.get("provider_state") == "COMPLETED"

            if result_path.is_file():
                durable_readbacks += 1
                observed_bytes = result_path.read_bytes()
                observed = json.loads(observed_bytes)
                expected_bytes = canonical_json_bytes(_result_payload(trial))
                if (
                    observed == _result_payload(trial)
                    and sha256_bytes(observed_bytes) == sha256_bytes(expected_bytes)
                ):
                    hash_verified_readbacks += 1

    return {
        "durable_readbacks": durable_readbacks,
        "false_green_if_receipt_were_sufficient": (
            completed_receipts - hash_verified_readbacks
        ),
        "hash_verified_readbacks": hash_verified_readbacks,
        "mode": mode,
        "provider_completed_receipts": completed_receipts,
        "trials": trials,
    }


def build_observed_results() -> dict[str, Any]:
    checkpoint_trials = 30
    checkpoint_workers = 8
    process_trials = 12

    unsafe = run_checkpoint_trials(
        trials=checkpoint_trials,
        workers=checkpoint_workers,
        protected=False,
    )
    locked = run_checkpoint_trials(
        trials=checkpoint_trials,
        workers=checkpoint_workers,
        protected=True,
    )
    ephemeral = run_process_exit_trials(trials=process_trials, mode="ephemeral")
    durable = run_process_exit_trials(trials=process_trials, mode="durable")

    assertions = {
        "atomic_durable_results_survive_and_verify": (
            durable["hash_verified_readbacks"] == process_trials
        ),
        "ephemeral_provider_completion_has_no_durable_result": (
            ephemeral["provider_completed_receipts"] == process_trials
            and ephemeral["durable_readbacks"] == 0
        ),
        "lock_preserves_all_checkpoint_writes": locked["lost_writes"] == 0,
        "stale_snapshot_rebind_loses_checkpoint_writes": (
            unsafe["lossy_trials"] == checkpoint_trials
            and unsafe["lost_writes"] > 0
        ),
    }

    return {
        "assertions": assertions,
        "cases": {
            "checkpoint_locked_control": locked,
            "checkpoint_stale_snapshot_rebind": unsafe,
            "process_exit_atomic_file": durable,
            "process_exit_memory_only": ephemeral,
        },
        "command": (
            "PYTHONDONTWRITEBYTECODE=1 python3 "
            "workstreams/po03/attempts/wave-a/"
            "wave-a-022-agent-recovery-postmortems/reproduce.py"
        ),
        "environment": {
            "implementation": platform.python_implementation(),
            "platform": platform.system(),
            "python": platform.python_version(),
        },
        "fixture": "agent-result-loss-v1",
        "outcome": "PASS" if all(assertions.values()) else "FAIL",
        "schema_version": "1.0",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worker-mode", choices=("ephemeral", "durable"))
    parser.add_argument("--result-path", type=Path)
    parser.add_argument("--trial", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker_mode:
        if args.result_path is None:
            raise SystemExit("--result-path is required in worker mode")
        return worker_main(args.worker_mode, args.result_path, args.trial)

    results = build_observed_results()
    atomic_json_write(args.output, results)
    sys.stdout.buffer.write(canonical_json_bytes(results))
    return 0 if results["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
