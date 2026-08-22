"""Transactional outbox: at-least-once delivery, exactly-once effect.

The PO-02 Code-2 return was lost because the provider's return route was
treated as result custody.  The general shape of that failure has two faces: a
message that never arrives, and a message that arrives twice.  Retrying fixes
the first and breaks the second unless the effect itself is idempotent.

So the effect is made idempotent by the filesystem rather than by an
application-level "have I done this already?" check, which is a race by
construction.  ``create_exclusive`` uses ``open(O_EXCL)`` plus ``link``: exactly
one caller creates the effect file and every later caller is told, atomically,
that it lost.

Delivery therefore never needs to be correct about whether it already ran::

    claim (durable)  ->  apply (atomic, self-deduplicating)  ->  mark (durable)

Crashing between any two of those steps is safe.  In particular, crashing after
``apply`` but before ``mark`` is the classic hole: the replay re-enters
``apply``, is told it lost, and records ``DUPLICATE_IGNORED`` instead of
producing a second effect.  A duplicate is never silently dropped: every one
appends a ``DUPLICATE_IGNORED`` row to the custody ledger, because an invisible
duplicate is indistinguishable from a lost message during recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .canonical import (
    atomic_write_json,
    canonical,
    create_exclusive,
    exclusive_lock,
    read_json,
    sha256_text,
    utc_now,
)
from .ledger import HashChainedLedger

PENDING = "PENDING"
CLAIMED = "CLAIMED"
APPLIED = "APPLIED"

EFFECT_APPLIED = "EFFECT_APPLIED"
DUPLICATE_IGNORED = "DUPLICATE_IGNORED"


class OutboxError(RuntimeError):
    """Raised when a delivery would violate the exactly-once invariant."""


class EffectSink(Protocol):
    """An external effect that can be attempted more than once safely."""

    def apply(self, idempotency_key: str, payload: dict[str, Any]) -> tuple[bool, Path]:
        """Return ``(created, locator)``; ``created`` is false on a duplicate."""

    def applied_keys(self) -> set[str]:
        ...


@dataclass(frozen=True)
class Delivery:
    record_id: str
    status: str
    attempt: int
    effect_locator: str | None
    idempotency_key: str

    @property
    def applied(self) -> bool:
        return self.status == EFFECT_APPLIED


class FileEffectSink:
    """An external effect represented by the one-time creation of a file.

    The observable effect count is the number of files in ``root``, so the test
    for "exactly one external effect" counts something the engine cannot fake:
    a second effect would be a second directory entry.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, idempotency_key: str) -> Path:
        return self.root / f"{sha256_text(idempotency_key)[:32]}.json"

    def apply(self, idempotency_key: str, payload: dict[str, Any]) -> tuple[bool, Path]:
        target = self._path_for(idempotency_key)
        body = canonical(
            {"idempotency_key": idempotency_key, "payload": payload, "applied_at": utc_now()}
        ).encode("utf-8")
        created = create_exclusive(target, body)
        return created, target

    def applied_keys(self) -> set[str]:
        keys: set[str] = set()
        for path in sorted(self.root.glob("*.json")):
            keys.add(read_json(path)["idempotency_key"])
        return keys

    def effect_count(self) -> int:
        return len(list(self.root.glob("*.json")))


class Outbox:
    """Durable record of intended effects, drained with exactly-once semantics."""

    def __init__(self, root: Path | str, ledger: HashChainedLedger) -> None:
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.locks_dir = self.root / "locks"
        self.ledger = ledger
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)

    # -- record state ------------------------------------------------------

    def _record_path(self, record_id: str) -> Path:
        return self.records_dir / f"{record_id}.json"

    def _lock_path(self, record_id: str) -> Path:
        return self.locks_dir / f"{record_id}.lock"

    def record(self, record_id: str) -> dict[str, Any]:
        path = self._record_path(record_id)
        if not path.exists():
            raise OutboxError(f"no outbox record for {record_id}")
        return read_json(path)

    def records(self) -> list[dict[str, Any]]:
        return [read_json(path) for path in sorted(self.records_dir.glob("*.json"))]

    def enqueue(
        self,
        record_id: str,
        *,
        unit_id: str,
        idempotency_key: str,
        effect_name: str,
        payload: dict[str, Any],
        actor: str = "po03-worker-a1",
    ) -> dict[str, Any]:
        path = self._record_path(record_id)
        if path.exists():
            existing = read_json(path)
            if existing["idempotency_key"] != idempotency_key:
                raise OutboxError(
                    f"{record_id} is already enqueued with a different idempotency key; "
                    "reusing a record id for a different effect would break exactly-once"
                )
            return existing
        record = {
            "record_id": record_id,
            "unit_id": unit_id,
            "idempotency_key": idempotency_key,
            "effect_name": effect_name,
            "payload": payload,
            "state": PENDING,
            "attempts": 0,
            "created_at": utc_now(),
            "claimed_at": None,
            "applied_at": None,
            "effect_locator": None,
        }
        atomic_write_json(path, record)
        self.ledger.append(
            unit_id,
            "OUTBOX_ENQUEUED",
            actor=actor,
            payload={"record_id": record_id, "idempotency_key": idempotency_key, "effect_name": effect_name},
        )
        return record

    # -- delivery ----------------------------------------------------------

    def deliver(
        self,
        record_id: str,
        sink: EffectSink,
        *,
        worker_id: str = "po03-worker-a1",
        fence_token: int | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> Delivery:
        """Attempt one delivery; safe to call any number of times."""
        with exclusive_lock(self._lock_path(record_id)):
            record = self.record(record_id)
            unit_id = record["unit_id"]
            key = record["idempotency_key"]

            if record["state"] == APPLIED:
                return self._observe_duplicate(
                    record, worker_id=worker_id, fence_token=fence_token, reason="record already APPLIED"
                )

            record["attempts"] += 1
            record["state"] = CLAIMED
            record["claimed_at"] = utc_now()
            atomic_write_json(self._record_path(record_id), record)
            self.ledger.append(
                unit_id,
                "OUTBOX_CLAIMED",
                actor=worker_id,
                fence_token=fence_token,
                payload={"record_id": record_id, "attempt": record["attempts"], "idempotency_key": key},
            )
            self._fire(fault_hook, "after_claim")

            created, locator = sink.apply(key, record["payload"])
            self._fire(fault_hook, "after_effect_before_mark")

            record["state"] = APPLIED
            record["applied_at"] = utc_now()
            record["effect_locator"] = str(locator)
            atomic_write_json(self._record_path(record_id), record)
            self._fire(fault_hook, "after_mark")

            if not created:
                # The effect already existed, so a previous attempt applied it
                # and lost the race to record that fact.  This is the recovery
                # path for "crashed after the effect, before the mark".
                self.ledger.append(
                    unit_id,
                    "DUPLICATE_IGNORED",
                    actor=worker_id,
                    fence_token=fence_token,
                    payload={
                        "record_id": record_id,
                        "attempt": record["attempts"],
                        "idempotency_key": key,
                        "reason": "effect already present; replay produced no second effect",
                        "effect_locator": str(locator),
                    },
                )
                return Delivery(record_id, DUPLICATE_IGNORED, record["attempts"], str(locator), key)

            self.ledger.append(
                unit_id,
                "OUTBOX_APPLIED",
                actor=worker_id,
                fence_token=fence_token,
                payload={
                    "record_id": record_id,
                    "attempt": record["attempts"],
                    "idempotency_key": key,
                    "effect_locator": str(locator),
                },
            )
            return Delivery(record_id, EFFECT_APPLIED, record["attempts"], str(locator), key)

    def _observe_duplicate(
        self, record: dict[str, Any], *, worker_id: str, fence_token: int | None, reason: str
    ) -> Delivery:
        record_id = record["record_id"]
        self.ledger.append(
            record["unit_id"],
            "DUPLICATE_IGNORED",
            actor=worker_id,
            fence_token=fence_token,
            payload={
                "record_id": record_id,
                "attempt": record["attempts"],
                "idempotency_key": record["idempotency_key"],
                "reason": reason,
                "effect_locator": record["effect_locator"],
            },
        )
        return Delivery(
            record_id,
            DUPLICATE_IGNORED,
            record["attempts"],
            record["effect_locator"],
            record["idempotency_key"],
        )

    @staticmethod
    def _fire(hook: Callable[[str], None] | None, point: str) -> None:
        if hook is not None:
            hook(point)

    # -- recovery ----------------------------------------------------------

    def redrivable(self) -> list[str]:
        """Records that a recovery scanner must attempt again.

        A ``CLAIMED`` record is exactly the ambiguous case: the effect may or
        may not have happened.  Re-driving is always correct because the sink
        resolves the ambiguity atomically.
        """
        return [r["record_id"] for r in self.records() if r["state"] in (PENDING, CLAIMED)]

    def drain(self, sink: EffectSink, *, worker_id: str = "po03-worker-a1") -> list[Delivery]:
        return [self.deliver(record_id, sink, worker_id=worker_id) for record_id in self.redrivable()]

    def duplicate_observations(self, unit_id: str, record_id: str) -> int:
        return sum(
            1
            for row in self.ledger.events_for(unit_id)
            if row["event"] == "DUPLICATE_IGNORED" and (row.get("payload") or {}).get("record_id") == record_id
        )

    def applied_observations(self, unit_id: str, record_id: str) -> int:
        return sum(
            1
            for row in self.ledger.events_for(unit_id)
            if row["event"] == "OUTBOX_APPLIED" and (row.get("payload") or {}).get("record_id") == record_id
        )
