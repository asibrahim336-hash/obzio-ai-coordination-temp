"""Leases, monotonic fence tokens, heartbeat renewal and monotonic checkpoints.

Two failures are handled here, and they pull in opposite directions.

An interrupted worker must be able to *continue*.  That argues for keeping its
claim alive across a gap in contact, which is what heartbeat renewal and
monotonic checkpoints provide: work already committed is recorded in the
ledger, so a fresh process resumes at the last checkpoint instead of repeating
committed steps.

An *evicted* worker must not be able to continue.  A process that stalled long
enough to lose its lease may still be alive and about to write.  Renewal alone
cannot stop it, because the stalled process believes its lease is valid.  Fence
tokens solve it the way Kleppmann describes for distributed locks: every grant
increments a monotonic token, the ledger remembers the highest one issued, and
any write carrying a lower token is refused and recorded as ``FENCE_REJECTED``.

The refusal is durable on purpose.  A silently dropped stale write leaves no
evidence that two processes believed they owned the same unit, which is exactly
the condition that has to be visible during recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .canonical import utc_now
from .completion import CustodyAuthority
from .ledger import HashChainedLedger

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class LeaseError(RuntimeError):
    """Base class for lease and checkpoint violations."""


class FenceViolation(LeaseError):
    """Raised when a stale leaseholder attempts a write after eviction."""


class CheckpointRegression(LeaseError):
    """Raised when a checkpoint sequence would move backwards."""


def format_time(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(TIME_FORMAT)


def parse_time(text: str) -> float:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp()


@dataclass(frozen=True)
class Lease:
    unit_id: str
    lease_id: str
    worker_id: str
    fence_token: int
    granted_at: str
    expires_at: str
    ttl_seconds: int

    def expired(self, now: float) -> bool:
        return parse_time(self.expires_at) < now

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "lease_id": self.lease_id,
            "worker_id": self.worker_id,
            "fence_token": self.fence_token,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass(frozen=True)
class ResumePoint:
    """What a restarting worker may assume, derived only from the ledger."""

    unit_id: str
    checkpoint_seq: int
    committed_steps: tuple[str, ...]
    fence_token: int
    result_committed: bool

    def should_execute(self, step_id: str, step_seq: int) -> bool:
        return step_id not in self.committed_steps and step_seq > self.checkpoint_seq

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "checkpoint_seq": self.checkpoint_seq,
            "committed_steps": list(self.committed_steps),
            "fence_token": self.fence_token,
            "result_committed": self.result_committed,
        }


class LeaseManager:
    """Grants fenced leases and refuses every write from an evicted holder."""

    def __init__(
        self,
        ledger: HashChainedLedger,
        *,
        authority: CustodyAuthority | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.ledger = ledger
        self.authority = authority or CustodyAuthority()
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    # -- projections -------------------------------------------------------

    def current_fence(self, unit_id: str) -> int:
        """Highest fence token ever issued for the unit, from the ledger alone."""
        tokens = [
            int(row["fence_token"])
            for row in self.ledger.events_for(unit_id)
            if row["event"] == "LEASED" and row.get("fence_token") is not None
        ]
        return max(tokens) if tokens else 0

    def current_lease(self, unit_id: str) -> Lease | None:
        lease: Lease | None = None
        for row in self.ledger.events_for(unit_id):
            payload = row.get("payload") or {}
            if row["event"] == "LEASED":
                lease = Lease(
                    unit_id=unit_id,
                    lease_id=payload["lease_id"],
                    worker_id=payload["worker_id"],
                    fence_token=int(row["fence_token"]),
                    granted_at=row["ts"],
                    expires_at=payload["expires_at"],
                    ttl_seconds=int(payload.get("ttl_seconds", 0)),
                )
            elif row["event"] == "HEARTBEAT" and lease is not None:
                lease = Lease(
                    unit_id=lease.unit_id,
                    lease_id=lease.lease_id,
                    worker_id=lease.worker_id,
                    fence_token=lease.fence_token,
                    granted_at=lease.granted_at,
                    expires_at=payload["expires_at"],
                    ttl_seconds=lease.ttl_seconds,
                )
            elif row["event"] == "LEASE_EXPIRED":
                lease = None
        return lease

    def resume_point(self, unit_id: str) -> ResumePoint:
        checkpoint_seq = 0
        committed: list[str] = []
        result_committed = False
        for row in self.ledger.events_for(unit_id):
            payload = row.get("payload") or {}
            if row["event"] == "CHECKPOINTED":
                checkpoint_seq = max(checkpoint_seq, int(payload.get("checkpoint_seq", 0)))
            elif row["event"] == "STEP_COMMITTED":
                step_id = payload.get("step_id")
                if step_id is not None and step_id not in committed:
                    committed.append(step_id)
            elif row["event"] == "RESULT_COMMITTED":
                result_committed = True
        return ResumePoint(
            unit_id=unit_id,
            checkpoint_seq=checkpoint_seq,
            committed_steps=tuple(committed),
            fence_token=self.current_fence(unit_id),
            result_committed=result_committed,
        )

    # -- grant and eviction ------------------------------------------------

    def grant(
        self,
        unit_id: str,
        worker_id: str,
        *,
        ttl_seconds: int = 5400,
        actor_id: str = "coordinator",
    ) -> Lease:
        """Issue the next monotonic fence token for the unit."""
        fence = self.current_fence(unit_id) + 1
        expires_at = format_time(self.clock() + ttl_seconds)
        lease = Lease(
            unit_id=unit_id,
            lease_id=f"lease-{unit_id}-{fence}",
            worker_id=worker_id,
            fence_token=fence,
            granted_at=utc_now(),
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
        )
        self.ledger.append(
            unit_id,
            "LEASED",
            actor=actor_id,
            provider_state="RUNNING",
            fence_token=fence,
            payload={
                "lease_id": lease.lease_id,
                "worker_id": worker_id,
                "expires_at": expires_at,
                "ttl_seconds": ttl_seconds,
            },
        )
        return lease

    def expire(self, unit_id: str, *, reason: str, actor_id: str = "coordinator") -> None:
        lease = self.current_lease(unit_id)
        self.ledger.append(
            unit_id,
            "LEASE_EXPIRED",
            actor=actor_id,
            obzio_state="RECOVERY_REQUIRED",
            fence_token=lease.fence_token if lease else None,
            payload={
                "reason": reason,
                "expired_lease_id": lease.lease_id if lease else None,
                "expired_worker_id": lease.worker_id if lease else None,
            },
        )

    # -- the fence ---------------------------------------------------------

    def assert_current(self, lease: Lease, *, operation: str) -> None:
        """Refuse and durably record any write from a non-current holder."""
        current = self.current_fence(lease.unit_id)
        if lease.fence_token == current:
            return
        self.ledger.append(
            lease.unit_id,
            "FENCE_REJECTED",
            actor=lease.worker_id,
            fence_token=current,
            payload={
                "operation": operation,
                "rejected_fence_token": lease.fence_token,
                "current_fence_token": current,
                "rejected_lease_id": lease.lease_id,
                "rejected_worker_id": lease.worker_id,
                "reason": (
                    "stale leaseholder after ownership transfer"
                    if lease.fence_token < current
                    else "fence token was never issued"
                ),
            },
        )
        raise FenceViolation(
            f"{lease.unit_id}: refusing {operation} from {lease.worker_id}: fence token "
            f"{lease.fence_token} is not the current token {current}"
        )

    # -- fenced operations -------------------------------------------------

    def heartbeat(self, lease: Lease, *, ttl_seconds: int | None = None) -> Lease:
        self.assert_current(lease, operation="heartbeat")
        ttl = ttl_seconds if ttl_seconds is not None else lease.ttl_seconds
        expires_at = format_time(self.clock() + ttl)
        self.ledger.append(
            lease.unit_id,
            "HEARTBEAT",
            actor=lease.worker_id,
            obzio_state="RUNNING",
            fence_token=lease.fence_token,
            payload={"lease_id": lease.lease_id, "expires_at": expires_at, "ttl_seconds": ttl},
        )
        return Lease(
            unit_id=lease.unit_id,
            lease_id=lease.lease_id,
            worker_id=lease.worker_id,
            fence_token=lease.fence_token,
            granted_at=lease.granted_at,
            expires_at=expires_at,
            ttl_seconds=ttl,
        )

    def checkpoint(self, lease: Lease, seq: int, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.assert_current(lease, operation="checkpoint")
        current = self.resume_point(lease.unit_id).checkpoint_seq
        if seq <= current:
            raise CheckpointRegression(
                f"{lease.unit_id}: checkpoint {seq} would move backwards from {current}"
            )
        return self.ledger.append(
            lease.unit_id,
            "CHECKPOINTED",
            actor=lease.worker_id,
            fence_token=lease.fence_token,
            payload={**(payload or {}), "checkpoint_seq": seq, "lease_id": lease.lease_id},
        )

    def commit_step(self, lease: Lease, step_id: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.assert_current(lease, operation="commit_step")
        return self.ledger.append(
            lease.unit_id,
            "STEP_COMMITTED",
            actor=lease.worker_id,
            obzio_state="RUNNING",
            fence_token=lease.fence_token,
            payload={**(payload or {}), "step_id": step_id, "lease_id": lease.lease_id},
        )

    def commit_result(
        self,
        lease: Lease,
        *,
        result_commit_id: str,
        manifest_uri: str,
        manifest_sha256: str,
        artifact_count: int,
        total_bytes: int,
    ) -> dict[str, Any]:
        """The strongest state a subordinate may write."""
        self.assert_current(lease, operation="commit_result")
        return self.ledger.append(
            lease.unit_id,
            "RESULT_COMMITTED",
            actor=lease.worker_id,
            provider_state="COMPLETED",
            fence_token=lease.fence_token,
            payload={
                "result_commit_id": result_commit_id,
                "result_locator": manifest_uri,
                "manifest_sha256": manifest_sha256,
                "artifact_count": artifact_count,
                "total_bytes": total_bytes,
                "lease_id": lease.lease_id,
            },
        )

    # -- recovery ----------------------------------------------------------

    def expired_leases(self, unit_ids: list[str] | None = None) -> list[str]:
        now = self.clock()
        units = unit_ids if unit_ids is not None else sorted({row["unit_id"] for row in self.ledger.rows()})
        stale: list[str] = []
        for unit_id in units:
            lease = self.current_lease(unit_id)
            if lease is not None and lease.expired(now) and not self.resume_point(unit_id).result_committed:
                stale.append(unit_id)
        return stale

    def fence_rejections(self, unit_id: str) -> list[dict[str, Any]]:
        return [row for row in self.ledger.events_for(unit_id) if row["event"] == "FENCE_REJECTED"]


def lease_from_dict(data: dict[str, Any]) -> Lease:
    return Lease(
        unit_id=data["unit_id"],
        lease_id=data["lease_id"],
        worker_id=data["worker_id"],
        fence_token=int(data["fence_token"]),
        granted_at=data["granted_at"],
        expires_at=data["expires_at"],
        ttl_seconds=int(data["ttl_seconds"]),
    )


def write_lease(path: Path, lease: Lease) -> None:
    from .canonical import atomic_write_json

    atomic_write_json(path, lease.as_dict())
