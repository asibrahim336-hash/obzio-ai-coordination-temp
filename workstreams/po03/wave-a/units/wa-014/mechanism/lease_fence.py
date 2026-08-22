#!/usr/bin/env python3
"""Transactional SQLite lease store with server-issued monotonic fence tokens.

Every state-changing operation is serialized with ``BEGIN IMMEDIATE``.  The
store, not a caller, allocates fence tokens.  A commit is accepted only when
its token, lease id, owner, and unexpired lease exactly match the current row.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


SQLITE_INT_MAX = (1 << 63) - 1


class LeaseFenceError(RuntimeError):
    """Base class for fail-closed lease/fence errors."""


class InvalidRequest(LeaseFenceError):
    """The request cannot be represented safely."""


class LeaseBusy(LeaseFenceError):
    """Another unexpired lease currently owns the task."""


class LeaseExpired(LeaseFenceError):
    """The supplied lease has expired."""


class StaleFence(LeaseFenceError):
    """The supplied token is not the current token."""


class StaleLease(LeaseFenceError):
    """The token is current but owner or lease identity is not."""


class AlreadyCommitted(LeaseFenceError):
    """The task already has a different committed result."""


class IdempotencyConflict(LeaseFenceError):
    """An idempotency key was replayed with different semantics."""


@dataclass(frozen=True)
class LeaseGrant:
    task_id: str
    owner_id: str
    lease_id: str
    fence_token: int
    expires_at_ns: int


@dataclass(frozen=True)
class CommitReceipt:
    task_id: str
    owner_id: str
    lease_id: str
    fence_token: int
    idempotency_key: str
    payload_sha256: str
    payload_bytes: int
    committed_at_ns: int
    replayed: bool


class LeaseFenceStore:
    """A process-safe lease/fence store backed by one SQLite database."""

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], int] = time.monotonic_ns,
        busy_timeout_ms: int = 10_000,
    ) -> None:
        self.database = Path(database)
        self._clock = clock
        self._busy_timeout_ms = busy_timeout_ms
        if busy_timeout_ms < 1:
            raise InvalidRequest("busy_timeout_ms must be positive")
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS leases (
                    task_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
                    expires_at_ns INTEGER NOT NULL CHECK (expires_at_ns >= 0),
                    updated_at_ns INTEGER NOT NULL CHECK (updated_at_ns >= 0)
                );

                CREATE TABLE IF NOT EXISTS commits (
                    task_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_sha256 TEXT NOT NULL,
                    payload_bytes INTEGER NOT NULL CHECK (payload_bytes >= 0),
                    committed_at_ns INTEGER NOT NULL CHECK (committed_at_ns >= 0),
                    FOREIGN KEY (task_id) REFERENCES leases(task_id)
                );
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _now(self) -> int:
        now = self._clock()
        if isinstance(now, bool) or not isinstance(now, int) or now < 0:
            raise InvalidRequest("clock must return a non-negative integer")
        return now

    @staticmethod
    def _text(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequest(f"{name} must be a non-empty string")
        return value

    @staticmethod
    def _expiry(now: int, ttl_ns: int) -> int:
        if isinstance(ttl_ns, bool) or not isinstance(ttl_ns, int) or ttl_ns < 1:
            raise InvalidRequest("ttl_ns must be a positive integer")
        if now > SQLITE_INT_MAX - ttl_ns:
            raise InvalidRequest("lease expiry exceeds SQLite integer range")
        return now + ttl_ns

    @staticmethod
    def _grant(row: sqlite3.Row) -> LeaseGrant:
        return LeaseGrant(
            task_id=row["task_id"],
            owner_id=row["owner_id"],
            lease_id=row["lease_id"],
            fence_token=row["fence_token"],
            expires_at_ns=row["expires_at_ns"],
        )

    @staticmethod
    def _receipt(row: sqlite3.Row, *, replayed: bool) -> CommitReceipt:
        return CommitReceipt(
            task_id=row["task_id"],
            owner_id=row["owner_id"],
            lease_id=row["lease_id"],
            fence_token=row["fence_token"],
            idempotency_key=row["idempotency_key"],
            payload_sha256=row["payload_sha256"],
            payload_bytes=row["payload_bytes"],
            committed_at_ns=row["committed_at_ns"],
            replayed=replayed,
        )

    def claim(
        self,
        task_id: str,
        owner_id: str,
        lease_id: str,
        *,
        ttl_ns: int,
    ) -> LeaseGrant:
        """Claim an absent/expired task and return its server-issued token.

        A repeated claim by the active identity is idempotent and does not
        extend the lease.  Ownership transfer requires expiry and a fresh
        lease id.  Each successful transfer increments the token exactly once.
        """

        task_id = self._text("task_id", task_id)
        owner_id = self._text("owner_id", owner_id)
        lease_id = self._text("lease_id", lease_id)
        now = self._now()
        expires_at = self._expiry(now, ttl_ns)

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO leases (
                        task_id, owner_id, lease_id, fence_token,
                        expires_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (task_id, owner_id, lease_id, expires_at, now),
                )
            else:
                if now < row["expires_at_ns"]:
                    if row["owner_id"] == owner_id and row["lease_id"] == lease_id:
                        return self._grant(row)
                    raise LeaseBusy(
                        f"task {task_id!r} is owned through {row['expires_at_ns']} "
                        f"at fence {row['fence_token']}"
                    )
                if row["lease_id"] == lease_id:
                    raise InvalidRequest(
                        "ownership transfer requires a fresh lease_id"
                    )
                if row["fence_token"] >= SQLITE_INT_MAX:
                    raise InvalidRequest("fence token exhausted")
                next_token = row["fence_token"] + 1
                connection.execute(
                    """
                    UPDATE leases
                    SET owner_id = ?, lease_id = ?, fence_token = ?,
                        expires_at_ns = ?, updated_at_ns = ?
                    WHERE task_id = ?
                    """,
                    (
                        owner_id,
                        lease_id,
                        next_token,
                        expires_at,
                        now,
                        task_id,
                    ),
                )
            current = connection.execute(
                "SELECT * FROM leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            assert current is not None
            return self._grant(current)

    def _require_current(
        self,
        connection: sqlite3.Connection,
        grant: LeaseGrant,
        now: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM leases WHERE task_id = ?", (grant.task_id,)
        ).fetchone()
        if row is None:
            raise StaleLease(f"task {grant.task_id!r} has no lease")
        if grant.fence_token != row["fence_token"]:
            raise StaleFence(
                f"fence {grant.fence_token} is stale; "
                f"current fence is {row['fence_token']}"
            )
        if grant.owner_id != row["owner_id"] or grant.lease_id != row["lease_id"]:
            raise StaleLease("owner or lease identity does not match current row")
        if now >= row["expires_at_ns"]:
            raise LeaseExpired(
                f"lease expired at {row['expires_at_ns']}; observed {now}"
            )
        return row

    def renew(self, grant: LeaseGrant, *, ttl_ns: int) -> LeaseGrant:
        """Extend only the exact current, unexpired grant."""

        now = self._now()
        expires_at = self._expiry(now, ttl_ns)
        with self._transaction() as connection:
            self._require_current(connection, grant, now)
            connection.execute(
                """
                UPDATE leases
                SET expires_at_ns = ?, updated_at_ns = ?
                WHERE task_id = ?
                """,
                (expires_at, now, grant.task_id),
            )
            row = connection.execute(
                "SELECT * FROM leases WHERE task_id = ?", (grant.task_id,)
            ).fetchone()
            assert row is not None
            return self._grant(row)

    def commit(
        self,
        grant: LeaseGrant,
        *,
        idempotency_key: str,
        payload: bytes,
    ) -> CommitReceipt:
        """Commit once if and only if ``grant`` is exactly current.

        Fence/identity/expiry validation deliberately occurs before replay
        handling, so an old worker cannot turn a historical idempotent request
        into an accepted post-transfer callback.
        """

        idempotency_key = self._text("idempotency_key", idempotency_key)
        if not isinstance(payload, bytes):
            raise InvalidRequest("payload must be bytes")
        now = self._now()
        payload_sha256 = hashlib.sha256(payload).hexdigest()

        with self._transaction() as connection:
            self._require_current(connection, grant, now)
            existing = connection.execute(
                "SELECT * FROM commits WHERE task_id = ?", (grant.task_id,)
            ).fetchone()
            if existing is not None:
                same = (
                    existing["owner_id"] == grant.owner_id
                    and existing["lease_id"] == grant.lease_id
                    and existing["fence_token"] == grant.fence_token
                    and existing["idempotency_key"] == idempotency_key
                    and existing["payload_sha256"] == payload_sha256
                    and existing["payload_bytes"] == len(payload)
                )
                if same:
                    return self._receipt(existing, replayed=True)
                if existing["idempotency_key"] == idempotency_key:
                    raise IdempotencyConflict(
                        "idempotency key was replayed with different semantics"
                    )
                raise AlreadyCommitted(
                    f"task {grant.task_id!r} already has a committed result"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO commits (
                        task_id, owner_id, lease_id, fence_token,
                        idempotency_key, payload_sha256, payload_bytes,
                        committed_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        grant.task_id,
                        grant.owner_id,
                        grant.lease_id,
                        grant.fence_token,
                        idempotency_key,
                        payload_sha256,
                        len(payload),
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdempotencyConflict(
                    "idempotency key is already bound to another commit"
                ) from exc
            row = connection.execute(
                "SELECT * FROM commits WHERE task_id = ?", (grant.task_id,)
            ).fetchone()
            assert row is not None
            return self._receipt(row, replayed=False)

    def current_lease(self, task_id: str) -> LeaseGrant | None:
        """Return the current row for observation; this grants no authority."""

        task_id = self._text("task_id", task_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            return None if row is None else self._grant(row)

    def committed_result(self, task_id: str) -> CommitReceipt | None:
        """Return the durable commit row for observation."""

        task_id = self._text("task_id", task_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM commits WHERE task_id = ?", (task_id,)
            ).fetchone()
            return None if row is None else self._receipt(row, replayed=False)
