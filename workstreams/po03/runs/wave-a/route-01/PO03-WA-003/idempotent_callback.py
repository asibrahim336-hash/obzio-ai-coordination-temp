#!/usr/bin/env python3
"""PO03-WA-003 -- duplicate callbacks collapse into one result transaction.

Frozen hypothesis
-----------------
"Duplicate callbacks are idempotent and create one result transaction."

At-least-once delivery is the only delivery guarantee a retrying caller can
actually offer.  A coordinator that treats every arriving callback as a new
event will therefore create duplicate result transactions for a single unit of
work, which inflates throughput counts and produces two locators for one
result.  Exactly-once *effect* has to be reconstructed at the receiver from an
idempotency key.

Design
------
The receiver keeps a content-addressed reservation table keyed by the
idempotency key, written to an append-only durable ledger.

* First arrival for a key: a new ``result_txn_id`` is reserved and returned as
  ``CREATED``.
* Repeat arrival with the *same* request digest: the original transaction is
  returned unchanged as ``DUPLICATE_IGNORED``.  No new transaction, no new
  ledger effect record, no mutation of the stored result.
* Repeat arrival with a *different* request digest under the same key: this is
  not a duplicate, it is a collision.  It raises
  :class:`IdempotencyConflict` rather than silently overwriting, because
  choosing either payload would discard a real result.

The key insight the tests target is that dedupe must be decided *inside* the
same critical section that allocates the transaction.  A receiver that checks
"have I seen this key" and then allocates outside the lock will create two
transactions under concurrent duplicate delivery, which is exactly the race a
retrying HTTP client produces.

Executable entry point::

    python3 idempotent_callback.py --demo
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IdempotencyConflict(Exception):
    """The same idempotency key arrived with a different request body."""

    def __init__(self, key: str, stored_digest: str, presented_digest: str) -> None:
        super().__init__(
            f"idempotency key {key!r} was first seen with digest {stored_digest}"
            f" but is now presented with {presented_digest}"
        )
        self.key = key
        self.stored_digest = stored_digest
        self.presented_digest = presented_digest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_digest(body: dict[str, Any]) -> str:
    """Digest a request body independent of key ordering and whitespace."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotentCallbackReceiver:
    """Receives result callbacks and collapses duplicates onto one transaction."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "reservations.json"
        self.ledger_path = self.directory / "ledger.jsonl"
        self.lock_path = self.directory / "receiver.lock"
        if not self.state_path.exists():
            self._atomic_write(self.state_path, b"{}\n")
        self.ledger_path.touch()
        # Counts real transaction allocations, in-process, for race detection.
        self._allocations = 0
        self._allocation_lock = threading.Lock()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
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

    def _append_ledger(self, record: dict[str, Any]) -> None:
        with self.ledger_path.open("ab", buffering=0) as stream:
            stream.write(json.dumps(record, sort_keys=True).encode() + b"\n")
            os.fsync(stream.fileno())

    def receive(self, idempotency_key: str, body: dict[str, Any]) -> dict[str, Any]:
        """Handle one callback delivery.

        Returns a dict with ``outcome`` in ``{"CREATED", "DUPLICATE_IGNORED"}``
        and the stable ``result_txn_id`` for this idempotency key.
        """
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        digest = canonical_digest(body)

        # The whole decision -- lookup, conflict check and allocation -- happens
        # under one exclusive lock.  Splitting it is the bug this guards.
        with open(self.lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                reservations = json.loads(self.state_path.read_text())
                existing = reservations.get(idempotency_key)
                if existing is not None:
                    if existing["request_digest"] != digest:
                        raise IdempotencyConflict(idempotency_key, existing["request_digest"], digest)
                    self._append_ledger(
                        {
                            "at": _utc_now(),
                            "event": "DUPLICATE_IGNORED",
                            "idempotency_key": idempotency_key,
                            "result_txn_id": existing["result_txn_id"],
                        }
                    )
                    return {
                        "outcome": "DUPLICATE_IGNORED",
                        "result_txn_id": existing["result_txn_id"],
                        "request_digest": digest,
                        "delivery_count": self._bump_delivery(reservations, idempotency_key),
                    }

                with self._allocation_lock:
                    self._allocations += 1
                result_txn_id = f"rtxn-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"
                reservations[idempotency_key] = {
                    "result_txn_id": result_txn_id,
                    "request_digest": digest,
                    "created_at": _utc_now(),
                    "delivery_count": 1,
                    "body": body,
                }
                self._atomic_write(
                    self.state_path, json.dumps(reservations, sort_keys=True).encode() + b"\n"
                )
                self._append_ledger(
                    {
                        "at": _utc_now(),
                        "event": "CREATED",
                        "idempotency_key": idempotency_key,
                        "result_txn_id": result_txn_id,
                        "request_digest": digest,
                    }
                )
                return {
                    "outcome": "CREATED",
                    "result_txn_id": result_txn_id,
                    "request_digest": digest,
                    "delivery_count": 1,
                }
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _bump_delivery(self, reservations: dict[str, Any], key: str) -> int:
        reservations[key]["delivery_count"] += 1
        self._atomic_write(self.state_path, json.dumps(reservations, sort_keys=True).encode() + b"\n")
        return reservations[key]["delivery_count"]

    # -- observation helpers ------------------------------------------------

    def transactions(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text())

    def ledger(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.ledger_path.read_text().splitlines() if line]

    def created_count(self) -> int:
        return sum(1 for record in self.ledger() if record["event"] == "CREATED")

    def allocations(self) -> int:
        return self._allocations


def reproduce_duplicate_storm(directory: Path, deliveries: int = 32, threads: int = 16) -> dict[str, Any]:
    """Deliver the same callback many times, concurrently, and count effects."""
    receiver = IdempotentCallbackReceiver(directory)
    key = "PO03-WAVE-A-20260822:PO03-WA-003:attempt-1"
    body = {"task_id": "PO03-WA-003", "artifact_sha256": "a" * 64, "bytes": 1024}

    outcomes: list[str] = []
    txn_ids: set[str] = set()
    collect_lock = threading.Lock()
    barrier = threading.Barrier(threads)

    def deliver(count: int) -> None:
        barrier.wait()  # maximise contention on the first delivery
        for _ in range(count):
            result = receiver.receive(key, body)
            with collect_lock:
                outcomes.append(result["outcome"])
                txn_ids.add(result["result_txn_id"])

    per_thread = max(1, deliveries // threads)
    workers = [threading.Thread(target=deliver, args=(per_thread,)) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    return {
        "deliveries": len(outcomes),
        "created": outcomes.count("CREATED"),
        "duplicates_ignored": outcomes.count("DUPLICATE_IGNORED"),
        "distinct_result_txn_ids": sorted(txn_ids),
        "transactions_in_store": len(receiver.transactions()),
        "ledger_created_events": receiver.created_count(),
        "allocations": receiver.allocations(),
    }


def demo() -> int:
    with tempfile.TemporaryDirectory() as directory:
        report = reproduce_duplicate_storm(Path(directory))
        conflict: dict[str, Any]
        receiver = IdempotentCallbackReceiver(Path(directory) / "conflict")
        receiver.receive("k1", {"result": "A"})
        try:
            receiver.receive("k1", {"result": "B"})
        except IdempotencyConflict as error:
            conflict = {"raised": "IdempotencyConflict", "message": str(error)}
        else:
            conflict = {"raised": None}
        report["conflicting_body_under_same_key"] = conflict
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
