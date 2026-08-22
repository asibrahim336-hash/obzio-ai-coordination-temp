#!/usr/bin/env python3
"""Run the sanitized stale-worker ownership-transfer concurrency fixture."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lease_fence import LeaseFenceStore, StaleFence  # noqa: E402


class ManualClock:
    """Thread-safe deterministic monotonic clock for lease fault injection."""

    def __init__(self, initial_ns: int) -> None:
        self._now = initial_ns
        self._lock = threading.Lock()

    def __call__(self) -> int:
        with self._lock:
            return self._now

    def advance(self, delta_ns: int) -> int:
        if delta_ns < 0:
            raise ValueError("manual clock cannot move backwards")
        with self._lock:
            self._now += delta_ns
            return self._now


def run_fixture() -> dict[str, Any]:
    """Force worker A to attempt a commit after worker B takes fence 2."""

    clock = ManualClock(1_000_000_000)
    a_has_lease = threading.Event()
    b_has_committed = threading.Event()
    values: dict[str, Any] = {}
    failures: list[BaseException] = []
    values_lock = threading.Lock()

    with tempfile.TemporaryDirectory(prefix=".wa014-fixture-", dir=UNIT_ROOT) as raw:
        store = LeaseFenceStore(Path(raw) / "lease.db", clock=clock)

        def worker_a() -> None:
            try:
                grant = store.claim(
                    "sanitized-po03-wa-014",
                    "worker-a-expiring",
                    "fixture-lease-a",
                    ttl_ns=100,
                )
                with values_lock:
                    values["grant_a"] = grant
                a_has_lease.set()
                if not b_has_committed.wait(timeout=5):
                    raise TimeoutError("worker B did not complete transfer")
                try:
                    store.commit(
                        grant,
                        idempotency_key="fixture-result-a",
                        payload=b"stale-worker-payload",
                    )
                except StaleFence as exc:
                    with values_lock:
                        values["stale_error_class"] = type(exc).__name__
                        values["stale_error"] = str(exc)
                else:
                    raise AssertionError("expired worker A committed after transfer")
            except BaseException as exc:
                failures.append(exc)
                a_has_lease.set()
                b_has_committed.set()

        def worker_b() -> None:
            try:
                if not a_has_lease.wait(timeout=5):
                    raise TimeoutError("worker A did not acquire initial lease")
                clock.advance(101)
                grant = store.claim(
                    "sanitized-po03-wa-014",
                    "worker-b-successor",
                    "fixture-lease-b",
                    ttl_ns=100,
                )
                receipt = store.commit(
                    grant,
                    idempotency_key="fixture-result-b",
                    payload=b"successor-worker-payload",
                )
                with values_lock:
                    values["grant_b"] = grant
                    values["receipt_b"] = receipt
                b_has_committed.set()
            except BaseException as exc:
                failures.append(exc)
                b_has_committed.set()

        stale_thread = threading.Thread(target=worker_a, name="expired-worker-a")
        successor_thread = threading.Thread(target=worker_b, name="successor-worker-b")
        stale_thread.start()
        successor_thread.start()
        stale_thread.join(timeout=10)
        successor_thread.join(timeout=10)
        if stale_thread.is_alive() or successor_thread.is_alive():
            raise TimeoutError("fixture thread failed to terminate")
        if failures:
            raise AssertionError(f"fixture worker failed: {failures!r}")

        grant_a = values["grant_a"]
        grant_b = values["grant_b"]
        receipt_b = values["receipt_b"]
        committed = store.committed_result("sanitized-po03-wa-014")
        current = store.current_lease("sanitized-po03-wa-014")
        assert grant_a.fence_token == 1
        assert grant_b.fence_token == 2
        assert receipt_b.fence_token == 2
        assert values["stale_error_class"] == "StaleFence"
        assert committed == receipt_b
        assert current == grant_b

        return {
            "protocol_version": "PO03-WA-014-CONCURRENCY-FIXTURE-v1",
            "task_id": "PO03-WA-014",
            "hypothesis_id": "H-PO03-WA-014",
            "fixture_task": "sanitized-po03-wa-014",
            "sanitized": True,
            "threads": [
                "expired-worker-a",
                "successor-worker-b",
            ],
            "ordering": [
                "worker A acquires fence 1",
                "clock advances beyond A expiry",
                "worker B transfers ownership and receives fence 2",
                "worker B commits at fence 2",
                "worker A resumes and attempts its fence-1 commit",
            ],
            "observed": {
                "initial_fence_token": grant_a.fence_token,
                "transfer_fence_token": grant_b.fence_token,
                "committed_fence_token": receipt_b.fence_token,
                "current_owner": current.owner_id,
                "current_lease_id": current.lease_id,
                "committed_payload_sha256": receipt_b.payload_sha256,
                "committed_payload_bytes": receipt_b.payload_bytes,
                "stale_commit_accepted": False,
                "stale_rejection": values["stale_error_class"],
                "durable_commit_count": 1,
            },
            "hypothesis_outcome": "SUPPORTED",
            "external_effects": [],
            "decision_changed": [],
        }


def _write_output(path: Path, report: dict[str, Any]) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(UNIT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("output must remain inside the WA-014 owned subtree") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_fixture()
    if args.output is not None:
        _write_output(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
