"""a5-u10: a small, honest model of the "mutable status file" design -- one
JSON-like status object per unit_id, read-modify-written in place, with NO
historical log retained. This is the alternative the frozen hypothesis
compares the real append-only-log-with-projections design against.

Both designs are driven from the SAME real Wave A history
(``workstreams/po03/control/events/ledger.jsonl``) by the reproduction
script; this module only implements the mutable-status-file side plus a
two-phase (read, then write) actor so a DST-style scheduler (reused from
``dst_scheduler_u07``) can interleave concurrent writers exactly the way
``lease_race_actors_u07`` interleaves concurrent lease attempts.
"""

from __future__ import annotations

from typing import Any, Iterator


class MutableStatusStore:
    """One mutable "file" per unit_id. Writing REPLACES the file; there is
    no append, no history, and no hash chain -- by construction, the same
    way a naive ``status/<unit_id>.json`` design behaves."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = {}
        self.write_count = 0

    def read(self, unit_id: str) -> dict[str, Any]:
        return dict(self.files.get(unit_id, {}))

    def write(self, unit_id: str, contents: dict[str, Any]) -> None:
        self.files[unit_id] = contents
        self.write_count += 1


def mutable_update_actor(
    store: MutableStatusStore, unit_id: str, new_fields: dict[str, Any], out: dict[str, Any]
) -> Iterator[str]:
    """Two-phase (read, then merge-and-write) update, mirroring exactly how
    a real concurrent writer of a mutable status file operates: read
    whatever is currently on disk, merge in what this writer knows, write
    the whole file back. If another writer's write lands in between this
    writer's read and write, that other writer's fields are silently lost
    from the merge, because this writer's ``current`` snapshot never saw
    them."""
    current = store.read(unit_id)
    out["read_snapshot"] = current
    yield "read"
    merged = {**current, **new_fields}
    store.write(unit_id, merged)
    out["written"] = merged
    yield "write"


def apply_event_sequentially(store: MutableStatusStore, event_row: dict[str, Any]) -> None:
    """Applies one real ledger row to the mutable store, non-interleaved --
    the design's ordinary single-writer-at-a-time operating mode."""
    unit_id = event_row["unit_id"]
    new_fields = {
        "last_event": event_row["event"],
        "last_seq_seen": event_row["seq"],
        "obzio_state": event_row.get("obzio_state"),
        "provider_state": event_row.get("provider_state"),
        "fence_token": event_row.get("fence_token"),
    }
    out: dict[str, Any] = {}
    for _ in mutable_update_actor(store, unit_id, new_fields, out):
        pass


def replay_history_sequentially(rows: list[dict[str, Any]]) -> MutableStatusStore:
    store = MutableStatusStore()
    for row in rows:
        apply_event_sequentially(store, row)
    return store


def attempt_tamper_detection(store: MutableStatusStore, unit_id: str, tampered_contents: dict[str, Any]) -> bool:
    """There is no hash chain over a mutable status file, so there is
    structurally no way to tell a legitimately-written status from a
    tampered one after the fact: overwriting IS indistinguishable from a
    normal write. Returns whether tampering was detected -- always False,
    demonstrated by construction rather than asserted."""
    store.write(unit_id, tampered_contents)
    return False  # no chain, no prior hash, nothing to verify against
