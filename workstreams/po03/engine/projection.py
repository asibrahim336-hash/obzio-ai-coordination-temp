"""The work-unit registry is a projection, so losing it loses nothing.

A parent that keeps authoritative state in a derived file has two sources of
truth, and after a crash it cannot tell which one is right.  The rule here is
strict: the ledger is the only source of truth and the registry is a pure
function of it.  Deleting the registry must therefore be a non-event, and that
is checked by deleting it and demanding byte-identical bytes back.

Purity is structural, not aspirational.  :func:`project` takes rows and returns
a value: it opens no file, reads no clock, consults no environment and never
looks at the registry it is about to overwrite.  Anything time-varying would
make the rebuild differ from the original, which is precisely what the a1-u05
acceptance forbids.

Semantics are deliberately identical to ``control_plane.project_units`` for
every field the two share, including the rule that observation-only events
(``DUPLICATE_IGNORED``, ``FENCE_REJECTED``, ``FAULT_INJECTED``, and every
additive engine event) never advance custody state.  The projection tests
assert that agreement over randomised histories, because a coordinator and a
subordinate that disagree about what a ledger means have split custody in two
without anyone noticing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .canonical import GENESIS_HASH, atomic_write_text, canonical, sha256_text
from .ledger import ENGINE_EVENT_KINDS, HashChainedLedger

# Events that carry information but must never move a unit's custody state.
OBSERVATION_ONLY = frozenset({"DUPLICATE_IGNORED", "FENCE_REJECTED", "FAULT_INJECTED"}) | ENGINE_EVENT_KINDS

# Events whose meaning is a disposition rather than a custody state.
DISPOSITION_EVENTS = frozenset({"ACCEPTED", "REJECTED"})

COMMITTING_EVENTS = frozenset({"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"})


def _new_unit(unit_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "obzio_state": "CREATED",
        "provider_state": "UNKNOWN",
        "fence_token": 0,
        "checkpoint_seq": 0,
        "first_seen_ts": row["ts"],
        "last_event_ts": row["ts"],
        "last_event_seq": row["seq"],
        "lease": None,
        "result_commit_id": None,
        "result_locator": None,
        "artifact_count": 0,
        "total_bytes": 0,
        "attempts": 0,
        "retries": 0,
        "acceptance": "NOT_TESTED",
        "reviewer_id": None,
        "heartbeats": 0,
        "committed_steps": [],
        "duplicate_ignored": 0,
        "fence_rejected": 0,
        "event_counts": {},
    }


def project(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rebuild per-unit state from ledger rows alone.

    Pure by construction: rows in, dictionary out, no I/O and no clock.
    """
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit_id = row["unit_id"]
        unit = units.get(unit_id)
        if unit is None:
            unit = _new_unit(unit_id, row)
            units[unit_id] = unit
        event = row["event"]
        payload = row.get("payload") or {}
        unit["last_event_ts"] = row["ts"]
        unit["last_event_seq"] = row["seq"]
        unit["event_counts"][event] = unit["event_counts"].get(event, 0) + 1
        if row.get("fence_token") is not None:
            unit["fence_token"] = max(unit["fence_token"], int(row["fence_token"]))
        if row.get("provider_state"):
            unit["provider_state"] = row["provider_state"]

        if event == "HEARTBEAT":
            unit["heartbeats"] += 1
            if unit["lease"] is not None and payload.get("expires_at"):
                unit["lease"] = {**unit["lease"], "expires_at": payload["expires_at"]}
            continue
        if event == "STEP_COMMITTED":
            step_id = payload.get("step_id")
            if step_id is not None and step_id not in unit["committed_steps"]:
                unit["committed_steps"].append(step_id)
            continue
        if event == "DUPLICATE_IGNORED":
            unit["duplicate_ignored"] += 1
            continue
        if event == "FENCE_REJECTED":
            unit["fence_rejected"] += 1
            continue
        if event in OBSERVATION_ONLY:
            continue
        if event in DISPOSITION_EVENTS:
            unit["acceptance"] = event
            unit["reviewer_id"] = payload.get("reviewer_id")
            continue

        if event == "LEASED":
            unit["lease"] = {
                "lease_id": payload.get("lease_id"),
                "worker_id": payload.get("worker_id"),
                "granted_at": row["ts"],
                "expires_at": payload.get("expires_at"),
            }
            unit["attempts"] += 1
        elif event == "LEASE_EXPIRED":
            unit["lease"] = None
            unit["obzio_state"] = "RECOVERY_REQUIRED"
            continue
        elif event == "RETRY_SCHEDULED":
            unit["retries"] += 1
        elif event == "CHECKPOINTED":
            unit["checkpoint_seq"] = max(unit["checkpoint_seq"], int(payload.get("checkpoint_seq", 0)))
        if event in COMMITTING_EVENTS:
            unit["result_commit_id"] = payload.get("result_commit_id") or unit["result_commit_id"]
            unit["result_locator"] = payload.get("result_locator") or unit["result_locator"]
            unit["artifact_count"] = payload.get("artifact_count", unit["artifact_count"])
            unit["total_bytes"] = payload.get("total_bytes", unit["total_bytes"])

        unit["obzio_state"] = row.get("obzio_state") or event
    return units


def render(units: dict[str, dict[str, Any]]) -> str:
    """Deterministic registry bytes: one canonical unit per line, sorted."""
    lines = [canonical(units[unit_id]) for unit_id in sorted(units)]
    return "".join(line + "\n" for line in lines)


def project_and_render(rows: Iterable[dict[str, Any]]) -> str:
    return render(project(rows))


class Registry:
    """A materialised view of the ledger that may be deleted at any time."""

    def __init__(
        self,
        ledger: HashChainedLedger,
        path: Path | str,
        *,
        renderer: Callable[[Iterable[dict[str, Any]]], str] = project_and_render,
    ) -> None:
        self.ledger = ledger
        self.path = Path(path)
        self.renderer = renderer

    def materialize(self) -> str:
        """Write the registry from the ledger; return the bytes' digest."""
        text = self.renderer(self.ledger.rows())
        return atomic_write_text(self.path, text)

    def bytes_on_disk(self) -> bytes:
        return self.path.read_bytes() if self.path.exists() else b""

    def digest(self) -> str:
        return sha256_text(self.bytes_on_disk().decode("utf-8")) if self.path.exists() else GENESIS_HASH

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    def rebuild(self) -> str:
        """Delete and regenerate.  Must be indistinguishable from not doing so."""
        self.delete()
        return self.materialize()

    def units(self) -> dict[str, dict[str, Any]]:
        return project(self.ledger.rows())

    def is_faithful(self) -> bool:
        """True when the file on disk is exactly what the ledger projects to."""
        return self.bytes_on_disk() == self.renderer(self.ledger.rows()).encode("utf-8")
