"""A minimal, hand-rolled custody engine used only to test a5-u01.

This is deliberately NOT the real control plane. It exists so the four
invariants named in a5-u01's frozen hypothesis -- idempotency key, fence
token, checkpoint, outbox -- can each be switched off independently and the
resulting behaviour measured against four fault classes, one per invariant.
The real control plane (which has all four invariants) is exercised
separately, in sandbox, as a cross-check that its actual observed behaviour
matches what this model predicts for the "all invariants present" row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class InvariantConfig:
    idempotency_key: bool = True
    fence_token: bool = True
    checkpoint: bool = True
    outbox: bool = True

    def label(self) -> str:
        if all((self.idempotency_key, self.fence_token, self.checkpoint, self.outbox)):
            return "FULL"
        missing = [
            name
            for name, present in (
                ("idempotency_key", self.idempotency_key),
                ("fence_token", self.fence_token),
                ("checkpoint", self.checkpoint),
                ("outbox", self.outbox),
            )
            if not present
        ]
        return "NO_" + "_".join(missing).upper()


FULL = InvariantConfig()
NO_IDEMPOTENCY = replace(FULL, idempotency_key=False)
NO_FENCE = replace(FULL, fence_token=False)
NO_CHECKPOINT = replace(FULL, checkpoint=False)
NO_OUTBOX = replace(FULL, outbox=False)

ALL_CONFIGS = [FULL, NO_IDEMPOTENCY, NO_FENCE, NO_CHECKPOINT, NO_OUTBOX]


class MinimalCustodyEngine:
    """Toy custody engine whose only job is to make each invariant's effect
    on survivability mechanically checkable."""

    def __init__(self, config: InvariantConfig):
        self.config = config
        self._fence: dict[str, int] = {}
        self._durable_records: dict[str, list[str]] = {}
        self.effect_log: list[tuple[str, str]] = []

    def lease(self, unit_id: str, worker_id: str) -> int:
        if self.config.fence_token:
            self._fence[unit_id] = self._fence.get(unit_id, 0) + 1
            return self._fence[unit_id]
        return 0

    def submit(self, unit_id: str, worker_fence: int, payload_hash: str, *, crash_before_record: bool = False) -> dict:
        if self.config.fence_token:
            current = self._fence.get(unit_id, 0)
            if worker_fence < current:
                return {"rejected_stale_fence": True, "effect_applied": False, "recorded": False}

        if self.config.idempotency_key:
            already = payload_hash in self._durable_records.get(unit_id, [])
            if already:
                return {"duplicate_noop": True, "effect_applied": False, "recorded": True}

        self.effect_log.append((unit_id, payload_hash))
        effect_applied = True

        if self.config.outbox:
            recorded = True
        else:
            recorded = not crash_before_record

        if recorded and self.config.checkpoint:
            self._durable_records.setdefault(unit_id, []).append(payload_hash)

        return {"effect_applied": effect_applied, "recorded": recorded}

    def can_recover_after_restart(self, unit_id: str) -> bool:
        if not self.config.checkpoint:
            return False
        return unit_id in self._durable_records

    def effect_count(self, unit_id: str) -> int:
        return sum(1 for uid, _ in self.effect_log if uid == unit_id)
