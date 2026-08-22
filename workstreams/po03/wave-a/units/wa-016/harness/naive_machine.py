#!/usr/bin/env python3
"""Deliberately defective custody machines, used to test the harness itself.

A fault-injection harness that reports green on everything is worthless: it
cannot distinguish a machine that survives faults from one that never notices
them.  These mutants each remove one of the properties the real machine relies
on, and the transition matrix must report violations for them.

They are test instruments.  Nothing in the live path imports them.
"""

from __future__ import annotations

from typing import Any

from .custody_machine import COMMITTED_STATES, CustodyStore


class SnapshotFirstStore(CustodyStore):
    """Mutant 1: treats the rebuildable snapshot as the source of truth.

    Writes the snapshot before the journal and reloads from the snapshot, so a
    crash between the two silently loses the transition.
    """

    def _append(self, kind: str, task_id: str, **data: Any) -> dict[str, Any]:
        record = {"seq": self.last_seq + 1, "kind": kind, "task_id": task_id, "at": self.clock.now(), "data": data}
        self._apply(record)
        self.last_seq = record["seq"]
        self._write_snapshot()
        self.io.append_record(
            "journal.jsonl",
            record,
            pre="pre_journal_append",
            partial="journal_append_partial",
            post="post_journal_append",
        )
        return record

    def load(self) -> dict[str, Any]:
        snapshot = self.io.read_json("state.json")
        if snapshot is None:
            return super().load()
        self.tasks = {}
        self.last_seq = int(snapshot.get("last_seq", 0))
        read = self.io.read_records("journal.jsonl")
        replay = [r for r in read.records if int(r.get("seq", 0)) <= self.last_seq]
        for record in replay:
            self._apply(record)
        return {"records_replayed": len(replay), "torn_bytes_discarded": 0, "orphan_temp_files": []}


class ProviderTrustingStore(CustodyStore):
    """Mutant 2: believes the provider.

    Turns a provider ``COMPLETED`` observation straight into Obzio ``COMPLETED``
    with no durable commit, which is precisely the false completion the
    commission forbids.
    """

    def observe_provider(self, task_id: str, provider_state: str) -> str:
        self._append("PROVIDER_OBSERVED", task_id, provider_state=provider_state)
        state = self.state(task_id)
        if provider_state == "COMPLETED" and state.obzio_state not in COMMITTED_STATES:
            self._append(
                "TRANSITION",
                task_id,
                **{"from": state.obzio_state, "to": "COMPLETED", "completion_actor": "worker"},
            )
            return "COMPLETED"
        return state.obzio_state


class UnfencedStore(CustodyStore):
    """Mutant 3: keeps leases but never checks the fence token.

    A paused worker that wakes after ownership transferred can still write.
    """

    def _require_fence(self, task_id: str, fence_token: int) -> None:
        del task_id, fence_token


class TornTailTrustingStore(CustodyStore):
    """Mutant 4: replays a torn trailing journal record instead of healing it."""

    def load(self) -> dict[str, Any]:
        read = self.io.read_records("journal.jsonl")
        self.tasks = {}
        self.last_seq = 0
        for record in read.records:
            self._apply(record)
            self.last_seq = max(self.last_seq, int(record.get("seq", 0)))
        # The torn bytes are left in place, so the next append produces a log
        # that no longer parses as a sequence of records.
        return {"records_replayed": len(read.records), "torn_bytes_discarded": 0, "orphan_temp_files": []}


MUTANTS: tuple[tuple[str, type[CustodyStore], str], ...] = (
    ("SnapshotFirstStore", SnapshotFirstStore, "snapshot written before the journal and trusted on reload"),
    ("ProviderTrustingStore", ProviderTrustingStore, "provider completion promoted to Obzio completion"),
    ("UnfencedStore", UnfencedStore, "fence token never checked, so a stale worker can still write"),
    ("TornTailTrustingStore", TornTailTrustingStore, "torn trailing journal record left in place"),
)
