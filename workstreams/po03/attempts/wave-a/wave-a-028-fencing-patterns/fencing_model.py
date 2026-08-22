"""Deterministic models for ownership fencing and ledger sequencing.

The safe model deliberately keeps two validations separate:

* the ownership snapshot says who may make a new write and with which fence;
* the ledger sequence says where that write may be appended.

The unsafe helpers are fault fixtures.  They are not implementation examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


class FencingError(RuntimeError):
    """Base class for expected fixture rejections."""


class StaleOwnership(FencingError):
    """The writer or fence no longer matches the current ownership snapshot."""


class FenceRegression(FencingError):
    """A transfer attempted to reuse or decrease a fence token."""


class LedgerSequenceMismatch(FencingError):
    """The proposed ledger position is not the next position."""


class IdempotencyConflict(FencingError):
    """An operation identifier was reused with different write content."""


@dataclass(frozen=True)
class OwnershipSnapshot:
    owner_id: str
    fence_token: int


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    owner_id: str
    fence_token: int
    operation_id: str
    payload: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "owner_id": self.owner_id,
            "fence_token": self.fence_token,
            "operation_id": self.operation_id,
            "payload": self.payload,
        }


class FencedLedger:
    """An in-memory reference model with atomic transfer and commit methods."""

    def __init__(self, initial_owner: str, initial_fence: int = 1) -> None:
        if not initial_owner:
            raise ValueError("initial_owner must not be empty")
        if initial_fence < 1:
            raise ValueError("initial_fence must be positive")
        self._snapshot = OwnershipSnapshot(initial_owner, initial_fence)
        self._entries: list[LedgerEntry] = []
        self._operations: dict[str, LedgerEntry] = {}
        self._mutex = RLock()

    @property
    def snapshot(self) -> OwnershipSnapshot:
        with self._mutex:
            return self._snapshot

    @property
    def next_sequence(self) -> int:
        with self._mutex:
            return len(self._entries) + 1

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        with self._mutex:
            return tuple(self._entries)

    def transfer(
        self, next_owner: str, requested_fence: int | None = None
    ) -> OwnershipSnapshot:
        """Transfer ownership while preserving a strictly increasing fence."""
        if not next_owner:
            raise ValueError("next_owner must not be empty")
        with self._mutex:
            candidate = (
                self._snapshot.fence_token + 1
                if requested_fence is None
                else requested_fence
            )
            if candidate <= self._snapshot.fence_token:
                raise FenceRegression(
                    f"fence {candidate} is not greater than "
                    f"{self._snapshot.fence_token}"
                )
            self._snapshot = OwnershipSnapshot(next_owner, candidate)
            return self._snapshot

    def validate_snapshot(self, observed: OwnershipSnapshot) -> None:
        """Validate a snapshot at the instant this method runs."""
        with self._mutex:
            self._validate_snapshot_locked(observed.owner_id, observed.fence_token)

    def commit(
        self,
        *,
        owner_id: str,
        fence_token: int,
        expected_sequence: int,
        operation_id: str,
        payload: str,
    ) -> LedgerEntry:
        """Atomically validate current ownership and the next ledger position.

        An exact replay returns its prior entry without a new effect, even after
        ownership transfers.  Reusing the identifier with different content is
        rejected.
        """
        with self._mutex:
            replay = self._operations.get(operation_id)
            if replay is not None:
                proposed = (
                    owner_id,
                    fence_token,
                    expected_sequence,
                    operation_id,
                    payload,
                )
                recorded = (
                    replay.owner_id,
                    replay.fence_token,
                    replay.sequence,
                    replay.operation_id,
                    replay.payload,
                )
                if proposed != recorded:
                    raise IdempotencyConflict(
                        f"operation {operation_id!r} conflicts with its prior write"
                    )
                return replay

            self._validate_snapshot_locked(owner_id, fence_token)
            self._validate_sequence_locked(expected_sequence)
            entry = LedgerEntry(
                sequence=expected_sequence,
                owner_id=owner_id,
                fence_token=fence_token,
                operation_id=operation_id,
                payload=payload,
            )
            self._entries.append(entry)
            self._operations[operation_id] = entry
            return entry

    def unsafe_append_after_prior_validation(
        self,
        *,
        prior_snapshot: OwnershipSnapshot,
        expected_sequence: int,
        operation_id: str,
        payload: str,
    ) -> LedgerEntry:
        """Fault fixture: append after a non-atomic, earlier snapshot check.

        Only the ledger sequence is checked here.  If ownership transferred
        after the caller's earlier validation, this method admits a stale-owner
        write.  Production code must not use this split validation pattern.
        """
        with self._mutex:
            self._validate_sequence_locked(expected_sequence)
            entry = LedgerEntry(
                sequence=expected_sequence,
                owner_id=prior_snapshot.owner_id,
                fence_token=prior_snapshot.fence_token,
                operation_id=operation_id,
                payload=payload,
            )
            self._entries.append(entry)
            self._operations[operation_id] = entry
            return entry

    def _validate_snapshot_locked(self, owner_id: str, fence_token: int) -> None:
        if (owner_id, fence_token) != (
            self._snapshot.owner_id,
            self._snapshot.fence_token,
        ):
            raise StaleOwnership(
                f"observed ({owner_id}, {fence_token}); current "
                f"({self._snapshot.owner_id}, {self._snapshot.fence_token})"
            )

    def _validate_sequence_locked(self, expected_sequence: int) -> None:
        actual = len(self._entries) + 1
        if expected_sequence != actual:
            raise LedgerSequenceMismatch(
                f"expected sequence {expected_sequence}; next sequence is {actual}"
            )


class HighestSeenFenceSink:
    """A target that rejects only fences below the highest one it has observed.

    This common rule has an observation-gap boundary: an old equal token can
    still make a distinct write after authority transfers but before the sink
    receives any operation carrying the new token.
    """

    def __init__(self) -> None:
        self.highest_seen_fence = 0
        self._operations: dict[str, tuple[int, str]] = {}
        self.writes: list[dict[str, Any]] = []

    def write(self, *, fence_token: int, operation_id: str, payload: str) -> bool:
        replay = self._operations.get(operation_id)
        if replay is not None:
            if replay != (fence_token, payload):
                raise IdempotencyConflict(
                    f"operation {operation_id!r} conflicts with its prior write"
                )
            return False
        if fence_token < self.highest_seen_fence:
            raise StaleOwnership(
                f"fence {fence_token} is below sink high-water "
                f"{self.highest_seen_fence}"
            )
        self.highest_seen_fence = max(self.highest_seen_fence, fence_token)
        self._operations[operation_id] = (fence_token, payload)
        self.writes.append(
            {
                "fence_token": fence_token,
                "operation_id": operation_id,
                "payload": payload,
            }
        )
        return True
