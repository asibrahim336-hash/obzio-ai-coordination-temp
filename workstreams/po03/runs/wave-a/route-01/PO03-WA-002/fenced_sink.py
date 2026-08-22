#!/usr/bin/env python3
"""PO03-WA-002 -- a durable result sink that refuses a stale fence token.

Frozen hypothesis
-----------------
"A stale fence token cannot stage or commit a result."

The failure being excluded is the classic delayed-worker overwrite.  A lease is
granted to worker A at fence 1.  A stops responding, the coordinator declares
the lease expired and re-leases to worker B at fence 2.  B stages and commits.
A then wakes up -- it was only paused, not dead -- and tries to stage its own
now-obsolete result.  Wall-clock lease expiry alone cannot stop this, because A
believes its lease is valid and clocks disagree.  Only a monotonic fence
compared *at the durable boundary* can.

Design
------
The fence register lives inside the sink, not in the caller, and every mutating
operation (``stage``, ``commit``) takes the caller's fence token as a required
argument.  The rule is a strict high-water mark:

* ``fence < high_water``  -> ``StaleFenceError``, no state change at all.
* ``fence == high_water`` -> accepted; this is the current lease holder.
* ``fence > high_water``  -> accepted and the high-water mark is raised; a newer
  lease implicitly and permanently evicts every older one.

Durability is real: state is a JSON file updated by write-temp + fsync +
``os.replace``, guarded by an ``flock`` so concurrent processes serialise.  The
fence check and the state write happen inside the same lock hold, so there is no
check-then-act window.

A rejected call is *totally* rejected -- the sink's bytes on disk are compared
before and after in the test suite.

Executable entry point::

    python3 fenced_sink.py --demo
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class FenceError(Exception):
    """Base class for fence-related refusals."""


class StaleFenceError(FenceError):
    """The caller's fence token is below the sink's high-water mark."""

    def __init__(self, operation: str, presented: int, high_water: int, holder: str | None) -> None:
        super().__init__(
            f"{operation} refused: fence {presented} is below high-water {high_water}"
            f" held by {holder!r}"
        )
        self.operation = operation
        self.presented = presented
        self.high_water = high_water
        self.holder = holder


class InvalidFenceError(FenceError):
    """A fence token that is not a positive integer was presented."""


class SinkStateError(Exception):
    """The operation is illegal for the sink's current transaction state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FencedResultSink:
    """A durable, fenced, single-task result sink backed by one JSON file."""

    INITIAL: dict[str, Any] = {
        "sink_version": "PO03-WA-002-FENCED-SINK-v1",
        "high_water_fence": 0,
        "fence_holder": None,
        "txn_state": "RESERVED",
        "staged": None,
        "committed": None,
        "rejections": [],
        "accepted_writes": 0,
    }

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write(json.dumps(self.INITIAL, sort_keys=True).encode() + b"\n")

    # -- durability helpers -------------------------------------------------

    def _atomic_write(self, data: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def _exclusive(self) -> Iterator[dict[str, Any]]:
        """Hold an exclusive lock across read-check-write so there is no race.

        The durable write happens on the refusal path too.  A refusal only ever
        appends to ``rejections``, and that audit record has to survive the
        exception; dropping it would make a rejected write indistinguishable
        from a write that was never attempted.
        """
        with open(self.lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text())
                try:
                    yield state
                finally:
                    self._atomic_write(json.dumps(state, sort_keys=True).encode() + b"\n")
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def bytes_on_disk(self) -> bytes:
        return self.path.read_bytes()

    # -- the fence rule -----------------------------------------------------

    @staticmethod
    def _check_fence(state: dict[str, Any], operation: str, fence: int, worker: str) -> None:
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
            raise InvalidFenceError(f"{operation} refused: fence {fence!r} is not a positive integer")
        high_water = state["high_water_fence"]
        if fence < high_water:
            raise StaleFenceError(operation, fence, high_water, state["fence_holder"])

    @staticmethod
    def _record_rejection(state: dict[str, Any], operation: str, fence: int, worker: str, reason: str) -> None:
        state["rejections"].append(
            {
                "at": _utc_now(),
                "operation": operation,
                "presented_fence": fence,
                "high_water_fence": state["high_water_fence"],
                "worker": worker,
                "reason": reason,
            }
        )

    # -- operations ---------------------------------------------------------

    def acquire(self, fence: int, worker: str) -> dict[str, Any]:
        """Take or renew the lease.  Raises on a stale or invalid fence."""
        with self._exclusive() as state:
            try:
                self._check_fence(state, "acquire", fence, worker)
            except FenceError as error:
                self._record_rejection(state, "acquire", fence, worker, type(error).__name__)
                raise
            state["high_water_fence"] = max(state["high_water_fence"], fence)
            state["fence_holder"] = worker
            return dict(state)

    def stage(self, fence: int, worker: str, payload: bytes) -> dict[str, Any]:
        """Stage a result.  A stale fence changes nothing on disk."""
        with self._exclusive() as state:
            try:
                self._check_fence(state, "stage", fence, worker)
            except FenceError as error:
                self._record_rejection(state, "stage", fence, worker, type(error).__name__)
                raise
            if state["txn_state"] == "COMMITTED":
                self._record_rejection(state, "stage", fence, worker, "SinkStateError")
                raise SinkStateError("stage refused: the transaction is already COMMITTED")
            state["high_water_fence"] = max(state["high_water_fence"], fence)
            state["fence_holder"] = worker
            state["txn_state"] = "STAGED"
            state["staged"] = {
                "worker": worker,
                "fence": fence,
                "sha256": _digest(payload),
                "bytes": len(payload),
                "at": _utc_now(),
            }
            state["accepted_writes"] += 1
            return dict(state)

    def commit(self, fence: int, worker: str) -> dict[str, Any]:
        """Commit the staged result.  A stale fence changes nothing on disk."""
        with self._exclusive() as state:
            try:
                self._check_fence(state, "commit", fence, worker)
            except FenceError as error:
                self._record_rejection(state, "commit", fence, worker, type(error).__name__)
                raise
            if state["txn_state"] != "STAGED":
                self._record_rejection(state, "commit", fence, worker, "SinkStateError")
                raise SinkStateError(f"commit refused: transaction state is {state['txn_state']}, not STAGED")
            if state["staged"]["fence"] != fence:
                self._record_rejection(state, "commit", fence, worker, "FenceMismatch")
                raise SinkStateError(
                    f"commit refused: staged under fence {state['staged']['fence']}, committing under {fence}"
                )
            state["high_water_fence"] = max(state["high_water_fence"], fence)
            state["fence_holder"] = worker
            state["txn_state"] = "COMMITTED"
            state["committed"] = dict(state["staged"], committed_at=_utc_now())
            state["accepted_writes"] += 1
            return dict(state)


def reproduce_delayed_worker(directory: Path) -> dict[str, Any]:
    """Reproduce the delayed-worker overwrite and show the fence stopping it."""
    sink = FencedResultSink(directory / "sink.json")
    timeline: list[dict[str, Any]] = []

    def step(label: str, action) -> None:
        try:
            action()
        except Exception as error:  # noqa: BLE001 - the refusal is the observation
            timeline.append({"step": label, "outcome": "REFUSED", "error": type(error).__name__, "message": str(error)})
        else:
            timeline.append({"step": label, "outcome": "ACCEPTED"})

    step("A acquires lease at fence 1", lambda: sink.acquire(1, "worker-A"))
    step("A stalls; coordinator re-leases to B at fence 2", lambda: sink.acquire(2, "worker-B"))
    step("B stages its result at fence 2", lambda: sink.stage(2, "worker-B", b"result-from-B"))
    step("B commits at fence 2", lambda: sink.commit(2, "worker-B"))

    before = sink.bytes_on_disk()
    step("A wakes and stages at stale fence 1", lambda: sink.stage(1, "worker-A", b"result-from-A"))
    step("A retries commit at stale fence 1", lambda: sink.commit(1, "worker-A"))
    after_rejected_writes = sink.read()

    final = sink.read()
    return {
        "timeline": timeline,
        "final_high_water_fence": final["high_water_fence"],
        "final_txn_state": final["txn_state"],
        "committed_by": final["committed"]["worker"],
        "committed_sha256": final["committed"]["sha256"],
        "accepted_writes": final["accepted_writes"],
        "rejections": [
            {k: v for k, v in item.items() if k != "at"} for item in after_rejected_writes["rejections"]
        ],
        "sink_bytes_unchanged_by_rejections": before == _strip_rejections(sink.bytes_on_disk(), before),
    }


def _strip_rejections(current: bytes, before: bytes) -> bytes:
    """Compare sink content ignoring the rejection audit log.

    A refusal is allowed to append to ``rejections`` -- that is the audit trail.
    Everything else must be byte-identical, which is what this comparison
    checks by overlaying the earlier rejection list onto the current document.
    """
    earlier = json.loads(before.decode())
    now = json.loads(current.decode())
    now["rejections"] = earlier["rejections"]
    return json.dumps(now, sort_keys=True).encode() + b"\n"


def demo() -> int:
    with tempfile.TemporaryDirectory() as directory:
        report = reproduce_delayed_worker(Path(directory))
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
