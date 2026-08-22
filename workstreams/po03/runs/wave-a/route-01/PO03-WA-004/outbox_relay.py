#!/usr/bin/env python3
"""PO03-WA-004 -- a lost callback is recovered from the durable outbox.

Frozen hypothesis
-----------------
"A lost callback is recovered from the durable outbox."

This is the failure that actually cost PO-02 its Code-2 result: the worker
finished, the callback went out, nothing arrived, and because the intent to
notify existed only inside the dying process there was nothing left to retry
from.  The result was real and the notification was not recoverable.

Design -- the transactional outbox pattern
------------------------------------------
The fix is to stop treating "write the result" and "notify the parent" as two
independent actions.  ``commit_and_enqueue`` writes the result record *and* the
outbox row in **one atomic file replacement**, so the two cannot diverge:

* if the process dies before the replace, neither exists and the work is simply
  retried;
* if it dies after, both exist and the pending outbox row is a durable,
  discoverable instruction to re-notify.

There is deliberately no path that produces a committed result with no outbox
row.  ``commit_without_outbox`` is provided as an explicitly labelled
*unsafe* control so the tests can demonstrate what is lost without the pattern.

A separate relay drains pending rows against an unreliable channel and marks
them acknowledged only on confirmed delivery.  Delivery is therefore
at-least-once; the receiver's idempotency key makes the *effect* exactly-once.

Executable entry point::

    python3 outbox_relay.py --demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class DeliveryFailed(Exception):
    """The channel refused or dropped this delivery attempt."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class WorkerStore:
    """The worker's own durable state: results plus a co-located outbox."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            _atomic_write(self.path, json.dumps({"results": {}, "outbox": []}, sort_keys=True).encode() + b"\n")

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def _write(self, state: dict[str, Any]) -> None:
        _atomic_write(self.path, json.dumps(state, sort_keys=True).encode() + b"\n")

    def commit_and_enqueue(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist the result and its notification intent in one replacement."""
        state = self.read()
        state["results"][task_id] = {
            "task_id": task_id,
            "payload": payload,
            "committed_at": _utc_now(),
        }
        state["outbox"].append(
            {
                "outbox_id": f"obx-{task_id}-{len(state['outbox']) + 1}",
                "task_id": task_id,
                "idempotency_key": f"PO03-WAVE-A-20260822:{task_id}:attempt-1",
                "payload": payload,
                "status": "PENDING",
                "attempts": 0,
                "enqueued_at": _utc_now(),
                "acknowledged_at": None,
            }
        )
        # One replace: results and outbox become durable together or not at all.
        self._write(state)
        return state["results"][task_id]

    def commit_without_outbox(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """UNSAFE control: commit the result with the intent held only in memory.

        This models the pre-outbox behaviour.  It exists so the suite can show
        that the loss is unrecoverable without the pattern, and must never be
        used on a real path.
        """
        state = self.read()
        state["results"][task_id] = {
            "task_id": task_id,
            "payload": payload,
            "committed_at": _utc_now(),
        }
        self._write(state)
        return state["results"][task_id]

    def pending(self) -> list[dict[str, Any]]:
        return [row for row in self.read()["outbox"] if row["status"] == "PENDING"]

    def mark(self, outbox_id: str, status: str, attempts: int) -> None:
        state = self.read()
        for row in state["outbox"]:
            if row["outbox_id"] == outbox_id:
                row["status"] = status
                row["attempts"] = attempts
                if status == "ACKNOWLEDGED":
                    row["acknowledged_at"] = _utc_now()
        self._write(state)


class UnreliableChannel:
    """A callback channel that drops deliveries on a deterministic schedule."""

    def __init__(self, drop_schedule: list[bool]) -> None:
        #: ``True`` at position *n* means the *n*-th delivery attempt is lost.
        self.drop_schedule = list(drop_schedule)
        self.attempts = 0
        self.delivered: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        index = self.attempts
        self.attempts += 1
        if index < len(self.drop_schedule) and self.drop_schedule[index]:
            # Silently lost in transit: the sender gets no error either.
            raise DeliveryFailed(f"attempt {index + 1} dropped in transit")
        self.delivered.append(message)


class ParentCoordinator:
    """The receiving side, deduplicating on the idempotency key."""

    def __init__(self) -> None:
        self.ingested: dict[str, dict[str, Any]] = {}
        self.deliveries = 0

    def callback(self, message: dict[str, Any]) -> str:
        self.deliveries += 1
        key = message["idempotency_key"]
        if key in self.ingested:
            return "DUPLICATE_IGNORED"
        self.ingested[key] = message
        return "INGESTED"


class OutboxRelay:
    """Drains pending outbox rows until the parent acknowledges each one."""

    def __init__(self, store: WorkerStore, channel: UnreliableChannel, parent: ParentCoordinator) -> None:
        self.store = store
        self.channel = channel
        self.parent = parent
        self.scans = 0

    def scan_once(self) -> dict[str, Any]:
        """One recovery pass over pending rows.  Safe to run any number of times."""
        self.scans += 1
        outcomes = []
        for row in self.store.pending():
            attempts = row["attempts"] + 1
            message = {
                "idempotency_key": row["idempotency_key"],
                "task_id": row["task_id"],
                "payload": row["payload"],
            }
            try:
                self.channel.send(message)
            except DeliveryFailed as error:
                self.store.mark(row["outbox_id"], "PENDING", attempts)
                outcomes.append({"outbox_id": row["outbox_id"], "outcome": "LOST", "detail": str(error)})
                continue
            acknowledgement = self.parent.callback(message)
            self.store.mark(row["outbox_id"], "ACKNOWLEDGED", attempts)
            outcomes.append({"outbox_id": row["outbox_id"], "outcome": acknowledgement, "attempts": attempts})
        return {"scan": self.scans, "outcomes": outcomes, "still_pending": len(self.store.pending())}

    def drain(self, max_scans: int = 10) -> list[dict[str, Any]]:
        history = []
        for _ in range(max_scans):
            report = self.scan_once()
            history.append(report)
            if report["still_pending"] == 0:
                break
        return history


def reproduce_lost_callback(directory: Path, drop_schedule: list[bool] | None = None) -> dict[str, Any]:
    """Lose the first callback outright, then recover it from the outbox."""
    schedule = [True, True, False] if drop_schedule is None else drop_schedule
    store = WorkerStore(directory / "worker.json")
    channel = UnreliableChannel(schedule)
    parent = ParentCoordinator()
    relay = OutboxRelay(store, channel, parent)

    store.commit_and_enqueue("PO03-WA-004", {"artifact_sha256": "c" * 64, "bytes": 512})
    pending_before = len(store.pending())
    history = relay.drain()

    return {
        "drop_schedule": schedule,
        "pending_after_commit": pending_before,
        "scans": len(history),
        "history": history,
        "channel_attempts": channel.attempts,
        "channel_deliveries": len(channel.delivered),
        "parent_ingested": len(parent.ingested),
        "parent_deliveries_seen": parent.deliveries,
        "pending_after_drain": len(store.pending()),
        "outbox_final": [
            {k: v for k, v in row.items() if k in ("outbox_id", "status", "attempts")}
            for row in store.read()["outbox"]
        ],
    }


def reproduce_unrecoverable_loss(directory: Path) -> dict[str, Any]:
    """The pre-outbox behaviour: the notification intent dies with the process."""
    store = WorkerStore(directory / "worker-unsafe.json")
    channel = UnreliableChannel([True])
    parent = ParentCoordinator()

    store.commit_without_outbox("PO03-WA-004-UNSAFE", {"artifact_sha256": "d" * 64})
    lost = False
    try:
        channel.send({"idempotency_key": "unsafe", "task_id": "PO03-WA-004-UNSAFE", "payload": {}})
    except DeliveryFailed:
        lost = True
    # The process now dies.  A fresh relay has nothing durable to work from.
    fresh_store = WorkerStore(directory / "worker-unsafe.json")
    relay = OutboxRelay(fresh_store, UnreliableChannel([]), parent)
    report = relay.scan_once()

    return {
        "result_committed": "PO03-WA-004-UNSAFE" in fresh_store.read()["results"],
        "callback_lost": lost,
        "recoverable_rows_after_restart": report["still_pending"],
        "recovery_outcomes": report["outcomes"],
        "parent_ingested": len(parent.ingested),
        "classification": "PROVIDER_COMPLETED_UNCOMMITTED",
    }


def demo() -> int:
    with tempfile.TemporaryDirectory() as directory:
        report = {
            "with_outbox": reproduce_lost_callback(Path(directory)),
            "without_outbox_control": reproduce_unrecoverable_loss(Path(directory)),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        return demo()
    parser.error("use --demo")
    return 2


if __name__ == "__main__":
    sys.exit(main())
