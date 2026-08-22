#!/usr/bin/env python3
"""Transactional outbox replay for PO-03 result custody.

The processor keeps one append-only framed journal per store.  Every admitted
callback commits its task transition *and* its outbox enqueue inside a single
journal frame, so no crash can leave a transition without its queued effect or
an effect without its transition.  External effects are applied through a sink
that is idempotent on ``effect_key`` and is consulted *before* the journal
records the dispatch, so a crash between sink apply and dispatch record replays
as ``ALREADY_APPLIED`` instead of producing a second external effect.

Durable state is exactly the journal: every projection is rebuilt by replaying
frames from byte zero.  A torn tail frame is detected by its length/CRC header
and truncated by the recovery scanner, never partially applied.

The module carries no wall-clock or environment values, so a report compiled
from a fixed workload is byte-identical across runs, machines and clones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Iterable


PROTOCOL_VERSION = "OBZIO-WA015-OUTBOX-v1"
WORKLOAD_PROTOCOL = "OBZIO-WA015-WORKLOAD-v1"

MAGIC = b"OBZJ1"
HEADER_BYTES = len(MAGIC) + 8

ROLES = ("controller", "coordinator", "worker", "reviewer", "provider")

INITIAL_STATE = "CREATED"

PROVIDER_STATES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN")

#: ``(from_state, to_state) -> permitted actor roles``.  The happy path follows
#: the PO-03 commission lifecycle; the remaining edges are the recovery and
#: termination edges the recovery scanner needs.
TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("CREATED", "LEASED"): frozenset({"controller"}),
    ("LEASED", "RUNNING"): frozenset({"worker"}),
    ("RUNNING", "CHECKPOINTED"): frozenset({"worker"}),
    ("CHECKPOINTED", "CHECKPOINTED"): frozenset({"worker"}),
    ("RUNNING", "RESULT_STAGING"): frozenset({"worker"}),
    ("CHECKPOINTED", "RESULT_STAGING"): frozenset({"worker"}),
    ("RESULT_STAGING", "RESULT_STAGED"): frozenset({"worker"}),
    ("RESULT_STAGED", "RESULT_VERIFIED"): frozenset({"controller"}),
    ("RESULT_VERIFIED", "RESULT_COMMITTED"): frozenset({"worker"}),
    ("RESULT_COMMITTED", "PARENT_INGESTED"): frozenset({"controller"}),
    ("PARENT_INGESTED", "COMPLETED"): frozenset({"coordinator"}),
    ("COMPLETED", "ACCEPTED"): frozenset({"reviewer"}),
    ("COMPLETED", "REJECTED"): frozenset({"reviewer"}),
    ("RUNNING", "RECOVERY_REQUIRED"): frozenset({"controller"}),
    ("CHECKPOINTED", "RECOVERY_REQUIRED"): frozenset({"controller"}),
    ("RESULT_STAGING", "RECOVERY_REQUIRED"): frozenset({"controller"}),
    ("RESULT_STAGED", "RECOVERY_REQUIRED"): frozenset({"controller"}),
    ("RECOVERY_REQUIRED", "RETRY_SCHEDULED"): frozenset({"controller"}),
    ("RETRY_SCHEDULED", "RUNNING"): frozenset({"worker"}),
    ("RECOVERY_REQUIRED", "FAILED_TERMINAL"): frozenset({"controller"}),
    ("RUNNING", "CANCELLED"): frozenset({"controller"}),
}

#: States that prove a durable result commit already exists.
COMMITTED_STATES = frozenset(
    {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED", "ACCEPTED", "REJECTED"}
)

#: Reaching this state requires an external effect: the durable commit itself.
EFFECT_REQUIRED_STATES = frozenset({"RESULT_COMMITTED"})

TASK_STATES = frozenset({INITIAL_STATE}) | {
    state for edge in TRANSITIONS for state in edge
}

CALLBACK_KINDS = ("transition", "lease_transfer", "provider_observation")

RECORD_KINDS = (
    "task_registered",
    "callback_admitted",
    "callback_rejected",
    "lease_transferred",
    "provider_observed",
    "effect_dispatched",
    "recovery_truncation",
)

REJECT_CODES = (
    "MALFORMED_CALLBACK",
    "UNKNOWN_TASK",
    "STALE_FENCE",
    "FUTURE_FENCE",
    "ILLEGAL_TRANSITION",
    "STATE_MISMATCH",
    "ROLE_NOT_PERMITTED",
    "WORKER_IDENTITY_MISMATCH",
    "CHECKPOINT_REGRESSION",
    "COMPLETION_ACTOR_FORBIDDEN",
    "PRODUCER_SELF_REVIEW",
    "MISSING_REQUIRED_EFFECT",
    "EFFECT_KEY_REBINDING",
    "IDEMPOTENCY_PAYLOAD_CONFLICT",
)

DECISIONS = (
    "APPLIED",
    "DUPLICATE_SUPPRESSED",
    "REJECTED",
)

#: A retriable rejection means "not yet", not "never": the delivery describes a
#: legal callback that arrived out of order.  Such a rejection is recorded as
#: evidence but does not claim the delivery id, so the sender may redeliver the
#: same callback once the store reaches the state it expects.  Every other
#: rejection is terminal and permanently claims the delivery id.
RETRIABLE_REJECT_CODES = frozenset({"STATE_MISMATCH", "FUTURE_FENCE"})

_STRING_FIELDS = (
    "delivery_id",
    "task_id",
    "kind",
    "actor",
    "from_state",
    "to_state",
    "producer_id",
    "new_producer_id",
    "provider_state",
    "note",
)
_INT_FIELDS = ("fence_token", "checkpoint_seq")
_CALLBACK_FIELDS = frozenset(_STRING_FIELDS) | frozenset(_INT_FIELDS) | {"effect"}


class MalformedCallback(ValueError):
    """The delivery is not a well-formed callback and cannot be interpreted."""


class InjectedCrash(RuntimeError):
    """A fault injector aborted the process at a named durability boundary."""


class EffectRebinding(ValueError):
    """An effect key was reused for a different payload; the sink refuses it."""


# --------------------------------------------------------------------------- #
# canonical encoding
# --------------------------------------------------------------------------- #


def canonical_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


# --------------------------------------------------------------------------- #
# framed append-only journal
# --------------------------------------------------------------------------- #


def encode_frame(payload: bytes) -> bytes:
    """Frame a payload as magic + length + CRC32 + payload."""
    return MAGIC + struct.pack(">II", len(payload), zlib.crc32(payload) & 0xFFFFFFFF) + payload


def scan_frames(data: bytes) -> tuple[list[bytes], int, str | None]:
    """Return ``(payloads, last_intact_offset, torn_reason)``.

    Scanning stops at the first frame that is not provably intact.  Everything
    before ``last_intact_offset`` is durable; everything after it is a torn tail
    that the recovery scanner truncates.
    """
    payloads: list[bytes] = []
    offset = 0
    total = len(data)
    while offset < total:
        if total - offset < HEADER_BYTES:
            return payloads, offset, "SHORT_HEADER"
        if data[offset : offset + len(MAGIC)] != MAGIC:
            return payloads, offset, "BAD_MAGIC"
        length, crc = struct.unpack(
            ">II", data[offset + len(MAGIC) : offset + HEADER_BYTES]
        )
        end = offset + HEADER_BYTES + length
        if end > total:
            return payloads, offset, "SHORT_PAYLOAD"
        payload = data[offset + HEADER_BYTES : end]
        if zlib.crc32(payload) & 0xFFFFFFFF != crc:
            return payloads, offset, "CRC_MISMATCH"
        payloads.append(payload)
        offset = end
    return payloads, offset, None


class FramedJournal:
    """Append-only file of CRC-framed payloads with fsync on every append."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self) -> tuple[list[bytes], int, str | None]:
        if not self.path.exists():
            return [], 0, None
        return scan_frames(self.path.read_bytes())

    def append(self, payload: bytes, *, keep_bytes: int | None = None) -> int:
        """Append one frame, optionally truncated to ``keep_bytes`` (torn write)."""
        frame = encode_frame(payload)
        if keep_bytes is not None:
            frame = frame[: max(0, keep_bytes)]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as handle:
            handle.write(frame)
            handle.flush()
            os.fsync(handle.fileno())
        return len(frame)

    def truncate(self, size: int) -> None:
        with open(self.path, "r+b") as handle:
            handle.truncate(size)
            handle.flush()
            os.fsync(handle.fileno())


# --------------------------------------------------------------------------- #
# fault injection protocol
# --------------------------------------------------------------------------- #


class NoFault:
    """The production fault injector: never trips, never tears."""

    def trip(self, point: str) -> None:  # noqa: D102 - protocol method
        return None

    def tear(self, point: str) -> int | None:  # noqa: D102 - protocol method
        return None


NO_FAULT = NoFault()


# --------------------------------------------------------------------------- #
# idempotent effect sink
# --------------------------------------------------------------------------- #


class IdempotentEffectSink:
    """Applies each ``effect_key`` exactly once, durably, across restarts.

    The sink log *is* the external effect surface: one record per key means one
    external effect.  A torn sink tail means the effect never became durable, so
    it is truncated and the effect is legitimately re-applied.
    """

    def __init__(self, path: Path | str, fault: Any = NO_FAULT) -> None:
        self.journal = FramedJournal(path)
        self.fault = fault
        self.truncated_bytes = 0
        self.torn_reason: str | None = None
        self.applied: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        payloads, intact, torn = self.journal.read()
        if torn is not None:
            self.torn_reason = torn
            size = self.journal.path.stat().st_size
            self.truncated_bytes = size - intact
            self.journal.truncate(intact)
        self.applied = {}
        for payload in payloads:
            record = json.loads(payload)
            self.applied[record["effect_key"]] = record

    @property
    def effect_count(self) -> int:
        return len(self.applied)

    def receipts(self) -> list[dict[str, Any]]:
        return sorted(self.applied.values(), key=lambda row: row["receipt_seq"])

    def apply(self, task_id: str, effect: dict[str, Any]) -> dict[str, Any]:
        key = effect["effect_key"]
        payload_digest = digest({"kind": effect["kind"], "payload": effect["payload"]})
        existing = self.applied.get(key)
        if existing is not None:
            if existing["payload_digest"] != payload_digest:
                raise EffectRebinding(key)
            return {
                "status": "ALREADY_APPLIED",
                "effect_key": key,
                "receipt_seq": existing["receipt_seq"],
            }
        record = {
            "effect_key": key,
            "kind": effect["kind"],
            "payload_digest": payload_digest,
            "receipt_seq": len(self.applied) + 1,
            "task_id": task_id,
        }
        self.fault.trip("before_sink_write")
        keep = self.fault.tear("sink_torn_write")
        self.journal.append(canonical_bytes(record), keep_bytes=keep)
        if keep is not None:
            raise InjectedCrash("sink_torn_write")
        self.applied[key] = record
        self.fault.trip("after_sink_write")
        return {
            "status": "APPLIED",
            "effect_key": key,
            "receipt_seq": record["receipt_seq"],
        }


# --------------------------------------------------------------------------- #
# callback normalisation
# --------------------------------------------------------------------------- #


def _require_actor(actor: str) -> tuple[str, str]:
    role, _, identity = actor.partition(":")
    if role not in ROLES or not identity:
        raise MalformedCallback(f"actor: {actor!r}")
    return role, identity


def _normalize_effect(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MalformedCallback("effect: must be an object")
    if set(raw) != {"effect_key", "kind", "payload"}:
        raise MalformedCallback("effect: requires exactly effect_key, kind, payload")
    for field in ("effect_key", "kind"):
        if not isinstance(raw[field], str) or not raw[field].strip():
            raise MalformedCallback(f"effect.{field}: must be a non-empty string")
    if not isinstance(raw["payload"], dict):
        raise MalformedCallback("effect.payload: must be an object")
    return {
        "effect_key": raw["effect_key"],
        "kind": raw["kind"],
        "payload": json.loads(canonical_bytes(raw["payload"]).decode("utf-8")),
    }


def normalize_callback(raw: Any) -> dict[str, Any]:
    """Validate a delivery and project it onto the canonical callback shape."""
    if not isinstance(raw, dict):
        raise MalformedCallback("callback: must be an object")
    unknown = sorted(set(raw) - _CALLBACK_FIELDS)
    if unknown:
        raise MalformedCallback(f"unknown fields: {unknown}")
    for field in _STRING_FIELDS:
        if field in raw and (not isinstance(raw[field], str) or not raw[field].strip()):
            raise MalformedCallback(f"{field}: must be a non-empty string")
    for field in _INT_FIELDS:
        if field in raw and (
            isinstance(raw[field], bool) or not isinstance(raw[field], int)
        ):
            raise MalformedCallback(f"{field}: must be an integer")

    for field in ("delivery_id", "task_id", "actor", "fence_token"):
        if field not in raw:
            raise MalformedCallback(f"{field}: missing")
    if raw["fence_token"] < 1:
        raise MalformedCallback("fence_token: must be >= 1")

    kind = raw.get("kind", "transition")
    if kind not in CALLBACK_KINDS:
        raise MalformedCallback(f"kind: {kind!r}")
    role, identity = _require_actor(raw["actor"])

    call: dict[str, Any] = {
        "delivery_id": raw["delivery_id"],
        "task_id": raw["task_id"],
        "kind": kind,
        "actor": raw["actor"],
        "actor_role": role,
        "actor_id": identity,
        "fence_token": raw["fence_token"],
    }
    if "note" in raw:
        call["note"] = raw["note"]

    if kind == "transition":
        for field in ("from_state", "to_state"):
            if field not in raw:
                raise MalformedCallback(f"{field}: missing for a transition")
            if raw[field] not in TASK_STATES:
                raise MalformedCallback(f"{field}: unknown state {raw[field]!r}")
        checkpoint = raw.get("checkpoint_seq", 0)
        if checkpoint < 0:
            raise MalformedCallback("checkpoint_seq: must be >= 0")
        call["from_state"] = raw["from_state"]
        call["to_state"] = raw["to_state"]
        call["checkpoint_seq"] = checkpoint
        if raw["to_state"] == "LEASED":
            if "producer_id" not in raw:
                raise MalformedCallback("producer_id: missing for a LEASED transition")
            call["producer_id"] = raw["producer_id"]
        elif "producer_id" in raw:
            raise MalformedCallback("producer_id: only valid on a LEASED transition")
        if "effect" in raw:
            call["effect"] = _normalize_effect(raw["effect"])
        for field in ("new_producer_id", "provider_state"):
            if field in raw:
                raise MalformedCallback(f"{field}: not valid on a transition")
    elif kind == "lease_transfer":
        if "new_producer_id" not in raw:
            raise MalformedCallback("new_producer_id: missing for a lease transfer")
        call["new_producer_id"] = raw["new_producer_id"]
        for field in ("from_state", "to_state", "checkpoint_seq", "effect", "producer_id", "provider_state"):
            if field in raw:
                raise MalformedCallback(f"{field}: not valid on a lease transfer")
    else:
        if "provider_state" not in raw:
            raise MalformedCallback("provider_state: missing for a provider observation")
        if raw["provider_state"] not in PROVIDER_STATES:
            raise MalformedCallback(f"provider_state: {raw['provider_state']!r}")
        call["provider_state"] = raw["provider_state"]
        for field in ("from_state", "to_state", "checkpoint_seq", "effect", "producer_id", "new_producer_id"):
            if field in raw:
                raise MalformedCallback(f"{field}: not valid on a provider observation")
    return call


def callback_digest(call: dict[str, Any]) -> str:
    """Digest every field except the delivery id, which is the dedupe key."""
    return digest({k: v for k, v in call.items() if k != "delivery_id"})


# --------------------------------------------------------------------------- #
# workload loading
# --------------------------------------------------------------------------- #


def load_workload(path: Path | str) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("workload: root must be an object")
    if document.get("protocol_version") != WORKLOAD_PROTOCOL:
        raise ValueError("workload: unsupported protocol_version")
    tasks = document.get("tasks")
    callbacks = document.get("callbacks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("workload: tasks must be a non-empty array")
    if not isinstance(callbacks, list) or not callbacks:
        raise ValueError("workload: callbacks must be a non-empty array")
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
            raise ValueError("workload: task requires a string task_id")
        if task["task_id"] in seen:
            raise ValueError(f"workload: duplicate task {task['task_id']}")
        seen.add(task["task_id"])
    for entry in callbacks:
        if not isinstance(entry, dict) or "ref" not in entry:
            raise ValueError("workload: callback requires a ref")
        if not isinstance(entry["ref"], str) or not entry["ref"].strip():
            raise ValueError("workload: callback ref must be a non-empty string")
    refs = [entry["ref"] for entry in callbacks]
    if len(set(refs)) != len(refs):
        raise ValueError("workload: duplicate callback ref")
    return document


# --------------------------------------------------------------------------- #
# processor
# --------------------------------------------------------------------------- #


class OutboxProcessor:
    """Replay-safe callback processor over one durable store directory."""

    def __init__(self, root: Path | str, fault: Any = NO_FAULT) -> None:
        self.root = Path(root)
        self.fault = fault
        self.journal = FramedJournal(self.root / "journal.log")
        self.sink = IdempotentEffectSink(self.root / "effects.log", fault=fault)
        self.recovery: dict[str, Any] = {
            "journal_torn_reason": None,
            "journal_truncated_bytes": 0,
            "sink_torn_reason": self.sink.torn_reason,
            "sink_truncated_bytes": self.sink.truncated_bytes,
        }
        self._rebuild()

    # -- durable projection -------------------------------------------------- #

    def _rebuild(self) -> None:
        payloads, intact, torn = self.journal.read()
        if torn is not None:
            size = self.journal.path.stat().st_size
            self.recovery["journal_torn_reason"] = torn
            self.recovery["journal_truncated_bytes"] = size - intact
            self.journal.truncate(intact)
        self.records: list[dict[str, Any]] = [json.loads(p) for p in payloads]
        self.seq = len(self.records)
        self.tasks: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, str] = {}
        self.seen: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.dispatched: dict[str, dict[str, Any]] = {}
        for record in self.records:
            self._project(record)

    def _project(self, record: dict[str, Any]) -> None:
        kind = record["kind"]
        if kind == "task_registered":
            self.tasks[record["task_id"]] = dict(record["task"])
            return
        if kind == "effect_dispatched":
            key = record["effect_key"]
            self.dispatched[key] = record
            self.outbox.pop(key, None)
            return
        if kind == "recovery_truncation":
            return
        if "task" in record:
            self.tasks[record["task_id"]] = dict(record["task"])
        entry = record.get("outbox_entry")
        if entry is not None and entry["effect_key"] not in self.dispatched:
            self.outbox[entry["effect_key"]] = entry
        if record.get("retriable"):
            return
        key = record["idempotency_key"]
        self.seen[key] = {
            "decision": record["decision"],
            "code": record.get("code"),
            "seq": record["seq"],
        }
        delivery_id = record.get("delivery_id")
        if isinstance(delivery_id, str):
            self.claims.setdefault(delivery_id, record["payload_digest"])

    def _append(self, record: dict[str, Any]) -> dict[str, Any]:
        record = dict(record)
        record["seq"] = self.seq + 1
        payload = canonical_bytes(record)
        self.fault.trip("before_journal_append")
        keep = self.fault.tear("journal_torn_write")
        self.journal.append(payload, keep_bytes=keep)
        if keep is not None:
            raise InjectedCrash("journal_torn_write")
        self.seq = record["seq"]
        self.records.append(record)
        self._project(record)
        self.fault.trip("after_journal_append")
        return record

    # -- registration -------------------------------------------------------- #

    def register(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["task_id"]
        if task_id in self.tasks:
            return {"decision": "DUPLICATE_SUPPRESSED", "task_id": task_id}
        snapshot = {
            "task_id": task_id,
            "state": task.get("state", INITIAL_STATE),
            "fence_token": int(task.get("fence_token", 1)),
            "checkpoint_seq": int(task.get("checkpoint_seq", 0)),
            "producer_id": task.get("producer_id"),
            "provider_state": task.get("provider_state", "QUEUED"),
            "provider_completed_uncommitted": False,
            "transition_count": 0,
        }
        if snapshot["state"] not in TASK_STATES:
            raise ValueError(f"unknown seed state: {snapshot['state']}")
        if snapshot["fence_token"] < 1:
            raise ValueError("seed fence_token must be >= 1")
        self._append({"kind": "task_registered", "task_id": task_id, "task": snapshot})
        return {"decision": "APPLIED", "task_id": task_id}

    def register_workload(self, document: dict[str, Any]) -> None:
        for task in document["tasks"]:
            self.register(task)

    # -- callback admission -------------------------------------------------- #

    def handle(self, raw: Any) -> dict[str, Any]:
        """Admit, suppress or reject one callback delivery."""
        try:
            call = normalize_callback(raw)
        except MalformedCallback as exc:
            payload_digest = digest({"raw": _safe(raw), "reason": str(exc)})
            return self._reject(
                None, payload_digest, "MALFORMED_CALLBACK", detail=str(exc)
            )

        payload_digest = callback_digest(call)
        key = f"{call['delivery_id']}\x00{payload_digest}"
        prior = self.seen.get(key)
        if prior is not None:
            return {
                "decision": "DUPLICATE_SUPPRESSED",
                "delivery_id": call["delivery_id"],
                "suppressed_decision": prior["decision"],
                "code": prior["code"],
                "original_seq": prior["seq"],
                "seq": None,
            }
        claimed = self.claims.get(call["delivery_id"])
        if claimed is not None and claimed != payload_digest:
            return self._reject(
                call,
                payload_digest,
                "IDEMPOTENCY_PAYLOAD_CONFLICT",
                detail=f"claimed_digest={claimed}",
            )

        task = self.tasks.get(call["task_id"])
        if task is None:
            return self._reject(call, payload_digest, "UNKNOWN_TASK")

        if call["kind"] == "lease_transfer":
            return self._lease_transfer(call, payload_digest, task)
        fence_error = self._fence_error(call["fence_token"], task["fence_token"])
        if fence_error is not None:
            return self._reject(call, payload_digest, fence_error)
        if call["kind"] == "provider_observation":
            return self._provider_observation(call, payload_digest, task)
        return self._transition(call, payload_digest, task)

    @staticmethod
    def _fence_error(offered: int, current: int) -> str | None:
        if offered < current:
            return "STALE_FENCE"
        if offered > current:
            return "FUTURE_FENCE"
        return None

    def _lease_transfer(
        self, call: dict[str, Any], payload_digest: str, task: dict[str, Any]
    ) -> dict[str, Any]:
        if call["actor_role"] != "controller":
            return self._reject(call, payload_digest, "ROLE_NOT_PERMITTED")
        expected = task["fence_token"] + 1
        fence_error = self._fence_error(call["fence_token"], expected)
        if fence_error is not None:
            return self._reject(call, payload_digest, fence_error)
        snapshot = dict(task)
        snapshot["fence_token"] = call["fence_token"]
        snapshot["producer_id"] = call["new_producer_id"]
        record = self._append(
            {
                "kind": "lease_transferred",
                "decision": "APPLIED",
                "delivery_id": call["delivery_id"],
                "idempotency_key": f"{call['delivery_id']}\x00{payload_digest}",
                "payload_digest": payload_digest,
                "task_id": call["task_id"],
                "actor": call["actor"],
                "fence_token": call["fence_token"],
                "new_producer_id": call["new_producer_id"],
                "task": snapshot,
            }
        )
        return {
            "decision": "APPLIED",
            "effect_kind": "lease_transferred",
            "delivery_id": call["delivery_id"],
            "fence_token": call["fence_token"],
            "seq": record["seq"],
        }

    def _provider_observation(
        self, call: dict[str, Any], payload_digest: str, task: dict[str, Any]
    ) -> dict[str, Any]:
        if call["actor_role"] not in {"provider", "controller"}:
            return self._reject(call, payload_digest, "ROLE_NOT_PERMITTED")
        snapshot = dict(task)
        snapshot["provider_state"] = call["provider_state"]
        uncommitted = (
            call["provider_state"] == "COMPLETED" and task["state"] not in COMMITTED_STATES
        )
        snapshot["provider_completed_uncommitted"] = uncommitted
        record = self._append(
            {
                "kind": "provider_observed",
                "decision": "APPLIED",
                "delivery_id": call["delivery_id"],
                "idempotency_key": f"{call['delivery_id']}\x00{payload_digest}",
                "payload_digest": payload_digest,
                "task_id": call["task_id"],
                "actor": call["actor"],
                "fence_token": call["fence_token"],
                "provider_state": call["provider_state"],
                "derived_obzio_state": (
                    "PROVIDER_COMPLETED_UNCOMMITTED" if uncommitted else task["state"]
                ),
                "task": snapshot,
            }
        )
        return {
            "decision": "APPLIED",
            "effect_kind": "provider_observed",
            "delivery_id": call["delivery_id"],
            "derived_obzio_state": record["derived_obzio_state"],
            "seq": record["seq"],
        }

    def _transition(
        self, call: dict[str, Any], payload_digest: str, task: dict[str, Any]
    ) -> dict[str, Any]:
        if call["from_state"] != task["state"]:
            return self._reject(call, payload_digest, "STATE_MISMATCH")
        edge = (call["from_state"], call["to_state"])
        permitted = TRANSITIONS.get(edge)
        if permitted is None:
            return self._reject(call, payload_digest, "ILLEGAL_TRANSITION")
        if call["to_state"] == "COMPLETED" and call["actor_role"] != "coordinator":
            return self._reject(call, payload_digest, "COMPLETION_ACTOR_FORBIDDEN")
        if call["actor_role"] not in permitted:
            return self._reject(call, payload_digest, "ROLE_NOT_PERMITTED")
        if call["actor_role"] == "worker" and task["producer_id"] not in (
            None,
            call["actor_id"],
        ):
            return self._reject(call, payload_digest, "WORKER_IDENTITY_MISMATCH")
        if call["actor_role"] == "reviewer" and call["actor_id"] == task["producer_id"]:
            return self._reject(call, payload_digest, "PRODUCER_SELF_REVIEW")
        if call["checkpoint_seq"] < task["checkpoint_seq"]:
            return self._reject(call, payload_digest, "CHECKPOINT_REGRESSION")
        if (
            call["to_state"] == "CHECKPOINTED"
            and call["checkpoint_seq"] <= task["checkpoint_seq"]
        ):
            return self._reject(call, payload_digest, "CHECKPOINT_REGRESSION")
        effect = call.get("effect")
        if effect is None and call["to_state"] in EFFECT_REQUIRED_STATES:
            return self._reject(call, payload_digest, "MISSING_REQUIRED_EFFECT")
        if effect is not None:
            bound = self._binding(effect["effect_key"])
            offered = digest({"kind": effect["kind"], "payload": effect["payload"]})
            if bound is not None and (
                bound["payload_digest"] != offered or bound["task_id"] != call["task_id"]
            ):
                return self._reject(call, payload_digest, "EFFECT_KEY_REBINDING")

        snapshot = dict(task)
        snapshot["state"] = call["to_state"]
        snapshot["checkpoint_seq"] = call["checkpoint_seq"]
        snapshot["transition_count"] = task["transition_count"] + 1
        if call["to_state"] == "LEASED":
            snapshot["producer_id"] = call["producer_id"]
        if call["to_state"] in COMMITTED_STATES:
            snapshot["provider_completed_uncommitted"] = False

        record: dict[str, Any] = {
            "kind": "callback_admitted",
            "decision": "APPLIED",
            "delivery_id": call["delivery_id"],
            "idempotency_key": f"{call['delivery_id']}\x00{payload_digest}",
            "payload_digest": payload_digest,
            "task_id": call["task_id"],
            "actor": call["actor"],
            "fence_token": call["fence_token"],
            "from_state": call["from_state"],
            "to_state": call["to_state"],
            "checkpoint_seq": call["checkpoint_seq"],
            "task": snapshot,
        }
        if effect is not None:
            record["outbox_entry"] = {
                "effect_key": effect["effect_key"],
                "kind": effect["kind"],
                "payload": effect["payload"],
                "payload_digest": digest(
                    {"kind": effect["kind"], "payload": effect["payload"]}
                ),
                "task_id": call["task_id"],
                "delivery_id": call["delivery_id"],
            }
        committed = self._append(record)
        return {
            "decision": "APPLIED",
            "effect_kind": "transition",
            "delivery_id": call["delivery_id"],
            "from_state": call["from_state"],
            "to_state": call["to_state"],
            "enqueued_effect": None if effect is None else effect["effect_key"],
            "seq": committed["seq"],
        }

    def _binding(self, effect_key: str) -> dict[str, Any] | None:
        entry = self.outbox.get(effect_key)
        if entry is not None:
            return entry
        dispatch = self.dispatched.get(effect_key)
        if dispatch is not None:
            return {
                "payload_digest": dispatch["payload_digest"],
                "task_id": dispatch["task_id"],
            }
        return None

    def _reject(
        self,
        call: dict[str, Any] | None,
        payload_digest: str,
        code: str,
        *,
        detail: str | None = None,
    ) -> dict[str, Any]:
        delivery_id = None if call is None else call["delivery_id"]
        prefix = "!malformed" if delivery_id is None else delivery_id
        retriable = code in RETRIABLE_REJECT_CODES
        prior = self.seen.get(f"{prefix}\x00{payload_digest}")
        if prior is not None:
            # A malformed delivery cannot be deduplicated before normalisation,
            # so the terminal-rejection index is consulted here as well.
            return {
                "decision": "DUPLICATE_SUPPRESSED",
                "delivery_id": delivery_id,
                "suppressed_decision": prior["decision"],
                "code": prior["code"],
                "original_seq": prior["seq"],
                "seq": None,
            }
        record: dict[str, Any] = {
            "kind": "callback_rejected",
            "decision": "REJECTED",
            "code": code,
            "retriable": retriable,
            "delivery_id": delivery_id,
            "idempotency_key": f"{prefix}\x00{payload_digest}",
            "payload_digest": payload_digest,
            "task_id": None if call is None else call["task_id"],
        }
        if detail is not None:
            record["detail"] = detail
        committed = self._append(record)
        return {
            "decision": "REJECTED",
            "code": code,
            "retriable": retriable,
            "delivery_id": delivery_id,
            "seq": committed["seq"],
        }

    # -- outbox drain -------------------------------------------------------- #

    def pending_outbox(self) -> list[dict[str, Any]]:
        return sorted(self.outbox.values(), key=lambda entry: entry["effect_key"])

    def drain(self) -> list[dict[str, Any]]:
        """Dispatch every pending outbox entry through the idempotent sink."""
        results: list[dict[str, Any]] = []
        for entry in self.pending_outbox():
            self.fault.trip("before_sink_apply")
            receipt = self.sink.apply(
                entry["task_id"],
                {
                    "effect_key": entry["effect_key"],
                    "kind": entry["kind"],
                    "payload": entry["payload"],
                },
            )
            self.fault.trip("after_sink_apply")
            self._append(
                {
                    "kind": "effect_dispatched",
                    "effect_key": entry["effect_key"],
                    "task_id": entry["task_id"],
                    "delivery_id": entry["delivery_id"],
                    "payload_digest": entry["payload_digest"],
                    "sink_status": receipt["status"],
                    "receipt_seq": receipt["receipt_seq"],
                }
            )
            self.fault.trip("after_dispatch_record")
            results.append(
                {
                    "effect_key": entry["effect_key"],
                    "sink_status": receipt["status"],
                    "receipt_seq": receipt["receipt_seq"],
                }
            )
        return results

    # -- recovery scanner ---------------------------------------------------- #

    def scan_recovery(self) -> dict[str, Any]:
        """Record any tail repair and report what must replay.

        Idempotent: a second scan over an intact journal records nothing new.
        """
        report = {
            "journal_torn_reason": self.recovery["journal_torn_reason"],
            "journal_truncated_bytes": self.recovery["journal_truncated_bytes"],
            "sink_torn_reason": self.recovery["sink_torn_reason"],
            "sink_truncated_bytes": self.recovery["sink_truncated_bytes"],
            "pending_effects": [e["effect_key"] for e in self.pending_outbox()],
            "uncommitted_tasks": sorted(
                task_id
                for task_id, task in self.tasks.items()
                if task["state"] not in COMMITTED_STATES
            ),
            "provider_completed_uncommitted": sorted(
                task_id
                for task_id, task in self.tasks.items()
                if task["provider_completed_uncommitted"]
            ),
        }
        if report["journal_torn_reason"] is not None and not any(
            record["kind"] == "recovery_truncation"
            and record["reason"] == report["journal_torn_reason"]
            and record["truncated_bytes"] == report["journal_truncated_bytes"]
            for record in self.records
        ):
            self._append(
                {
                    "kind": "recovery_truncation",
                    "reason": report["journal_torn_reason"],
                    "truncated_bytes": report["journal_truncated_bytes"],
                }
            )
        return report

    # -- observation --------------------------------------------------------- #

    def snapshot(self) -> dict[str, Any]:
        return {
            "journal_records": self.seq,
            "tasks": [self.tasks[task_id] for task_id in sorted(self.tasks)],
            "pending_outbox": [entry["effect_key"] for entry in self.pending_outbox()],
            "dispatched_effects": sorted(self.dispatched),
            "sink_effects": self.sink.effect_count,
            "sink_receipts": self.sink.receipts(),
            "distinct_deliveries": len(self.claims),
            "record_kinds": {
                kind: sum(1 for r in self.records if r["kind"] == kind)
                for kind in RECORD_KINDS
                if any(r["kind"] == kind for r in self.records)
            },
        }


def _safe(value: Any) -> Any:
    """Render an arbitrary delivery as canonical-JSON-safe evidence."""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #


def run_workload(store: Path, workload: dict[str, Any], callbacks: Iterable[Any]) -> dict[str, Any]:
    processor = OutboxProcessor(store)
    processor.register_workload(workload)
    outcomes = [processor.handle(callback) for callback in callbacks]
    dispatched = processor.drain()
    return {
        "outcomes": outcomes,
        "dispatched": dispatched,
        "recovery": processor.scan_recovery(),
        "snapshot": processor.snapshot(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args(argv)
    document = load_workload(args.workload)
    index = {entry["ref"]: entry for entry in document["callbacks"]}
    report = run_workload(
        args.store,
        document,
        [
            {k: v for k, v in index[ref].items() if k != "ref"}
            for ref in sorted(index)
        ],
    )
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
