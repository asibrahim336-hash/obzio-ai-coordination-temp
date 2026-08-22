#!/usr/bin/env python3
"""Deterministic fault injector for transactional custody transitions.

The injector is a passive schedule.  Instrumented code announces its arrival at
a named fault point; the injector decides whether a fault fires there.  Nothing
is timing dependent, so a fault schedule plus a seed reproduces a run exactly.

Fault points are named for the durability boundary they straddle, because a
crash before a boundary and a crash after it leave different bytes on disk.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable


class ProcessLoss(RuntimeError):
    """Raised where a real worker would be SIGKILLed.

    Nothing after the raise runs, so unflushed buffers and in-memory state are
    lost exactly as they would be on a killed process.  Callers must treat the
    surviving object graph as unusable and reopen from disk.
    """

    def __init__(self, point: str, kind: str) -> None:
        super().__init__(f"process loss at {point} ({kind})")
        self.point = point
        self.kind = kind


class ExternalUnavailable(RuntimeError):
    """The external world rejected an effect (network interruption, refusal)."""


class FencedOut(RuntimeError):
    """A stale worker attempted a write after ownership transferred."""


class IdempotencyConflict(RuntimeError):
    """A replay presented different parameters under an existing key."""


# Durability boundaries the harness can interrupt.
FAULT_POINTS: tuple[str, ...] = (
    "pre_journal_append",
    "journal_append_partial",
    "post_journal_append",
    "pre_snapshot_write",
    "post_snapshot_tmp_write",
    "post_snapshot_rename",
    "pre_artifact_write",
    "artifact_write_partial",
    "post_artifact_write",
    "pre_outbox_append",
    "post_outbox_append",
    "pre_external_effect",
    "post_external_effect",
    "pre_callback_send",
    "post_callback_send",
    "pre_readback",
    "post_readback",
)

# Fault classes required by the commission's fault-injection clause.
FAULT_KINDS: tuple[str, ...] = (
    "PRE_WRITE_LOSS",
    "POST_WRITE_LOSS",
    "PARTIAL_WRITE",
    "PROCESS_LOSS",
    "CALLBACK_LOSS",
    "DUPLICATE_CALLBACK",
    "STALE_LEASE",
    "CORRUPT_ARTIFACT",
    "MISSING_ARTIFACT",
    "NETWORK_INTERRUPTION",
    "PARENT_RESTART",
    "PROVIDER_RUNTIME_LOSS",
    "SNAPSHOT_ROLLBACK",
    "DUPLICATE_COMMIT_REPLAY",
)

# Kinds whose semantics at a fault point are "the worker stops existing".
LOSS_KINDS: frozenset[str] = frozenset(
    {"PRE_WRITE_LOSS", "POST_WRITE_LOSS", "PROCESS_LOSS", "SNAPSHOT_ROLLBACK", "PROVIDER_RUNTIME_LOSS"}
)

# Kinds the environment applies between phases rather than at a write boundary.
ENVIRONMENT_KINDS: frozenset[str] = frozenset(
    {"CORRUPT_ARTIFACT", "MISSING_ARTIFACT", "STALE_LEASE", "PARENT_RESTART", "DUPLICATE_COMMIT_REPLAY"}
)


@dataclass(frozen=True)
class Fault:
    """One scheduled fault.

    ``occurrence`` selects which arrival at ``point`` fires, so a fault can be
    aimed at the second journal append of a transition rather than the first.
    """

    kind: str
    point: str
    occurrence: int = 1
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind: {self.kind}")
        if self.point not in FAULT_POINTS and self.point != "environment":
            raise ValueError(f"unknown fault point: {self.point}")
        if self.occurrence < 1:
            raise ValueError("occurrence must be >= 1")

    @property
    def cell_id(self) -> str:
        return f"{self.kind}@{self.point}#{self.occurrence}"


class FaultInjector:
    """Fires a fixed schedule of faults at announced durability boundaries."""

    def __init__(self, faults: Iterable[Fault] = (), seed: int | None = None, *, active: bool = False) -> None:
        self._faults = list(faults)
        self.seed = seed
        self.active = active
        self._arrivals: dict[str, int] = {}
        self._consumed: set[int] = set()
        self.trace: list[dict[str, Any]] = []
        self.fired: list[dict[str, Any]] = []

    def arm(self) -> None:
        """Activate the schedule and restart occurrence counting.

        Occurrences are counted from the moment of arming so a fault can be
        aimed at the first journal append of the transition under test rather
        than the first journal append of the whole run.
        """
        self.active = True
        self._arrivals = {}

    @property
    def faults(self) -> list[Fault]:
        return list(self._faults)

    @property
    def armed(self) -> list[Fault]:
        return [f for i, f in enumerate(self._faults) if i not in self._consumed]

    def arrive(self, point: str, **context: Any) -> Fault | None:
        """Announce arrival at ``point``; return the fault that fires, if any."""
        if point not in FAULT_POINTS:
            raise ValueError(f"unknown fault point: {point}")
        count = self._arrivals.get(point, 0) + 1
        self._arrivals[point] = count
        self.trace.append({"point": point, "occurrence": count, "armed": self.active, "context": dict(context)})
        if not self.active:
            return None
        for index, fault in enumerate(self._faults):
            if index in self._consumed:
                continue
            if fault.point == point and fault.occurrence == count:
                self._consumed.add(index)
                self.fired.append({"cell_id": fault.cell_id, "point": point, "occurrence": count, "context": dict(context)})
                return fault
        return None

    def crash_if(self, point: str, **context: Any) -> Fault | None:
        """Arrive at ``point`` and raise :class:`ProcessLoss` for loss faults."""
        fault = self.arrive(point, **context)
        if fault is None:
            return None
        if fault.kind in LOSS_KINDS:
            raise ProcessLoss(point, fault.kind)
        return fault

    def arrivals(self, point: str) -> int:
        return self._arrivals.get(point, 0)

    def trace_digest(self) -> str:
        """Stable digest of the observed arrival sequence, for replay equality."""
        import hashlib
        import json

        payload = json.dumps(self.trace, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def single(kind: str, point: str, occurrence: int = 1, **params: Any) -> FaultInjector:
    """Injector armed with exactly one fault, active immediately."""
    return FaultInjector([Fault(kind=kind, point=point, occurrence=occurrence, params=params)], active=True)


def quiet() -> FaultInjector:
    """Injector that never fires, for baseline runs."""
    return FaultInjector(active=True)


def random_schedule(seed: int, max_faults: int = 3) -> FaultInjector:
    """Seeded multi-fault schedule.

    Used to test whether randomized scheduling discovers violation classes that
    exhaustive single-fault enumeration misses.
    """
    rng = random.Random(seed)
    count = rng.randint(1, max_faults)
    faults: list[Fault] = []
    for _ in range(count):
        point = rng.choice(FAULT_POINTS)
        kind = rng.choice(FAULT_KINDS)
        if kind in ENVIRONMENT_KINDS:
            point = "environment"
        faults.append(Fault(kind=kind, point=point, occurrence=rng.randint(1, 2)))
    return FaultInjector(faults, seed=seed, active=True)
