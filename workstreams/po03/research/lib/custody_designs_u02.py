"""Two custody designs compared under injected callback loss (a5-u02).

Both designs receive the exact same sequence of callback-drop decisions, so
the comparison isolates the one variable the hypothesis is about: whether
recovery depends on a callback actually arriving.
"""

from __future__ import annotations

import hashlib


class MessagePassingReturn:
    """Result is only reachable through a single in-flight callback."""

    def __init__(self) -> None:
        self.received: dict[str, str] = {}

    def worker_finishes(self, unit_id: str, payload: str, *, callback_dropped: bool) -> None:
        if not callback_dropped:
            self.received[unit_id] = payload
        # If the callback is dropped there is, by construction of this
        # design, no other channel through which the parent can learn the
        # result exists.

    def parent_recover(self, unit_id: str) -> str | None:
        return self.received.get(unit_id)


class ContentAddressedCustody:
    """Result is durably committed to a content-addressed store keyed by its
    own hash, independent of whether any notification callback arrives. A
    lightweight commit-index (the append-only-ledger analogue) records which
    hash belongs to which unit, and is written in the same step as the
    durable content -- not gated on the callback."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.commit_index: dict[str, str] = {}
        self.notifications_delivered: dict[str, bool] = {}

    def worker_finishes(self, unit_id: str, payload: str, *, callback_dropped: bool) -> None:
        content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.store[content_hash] = payload
        self.commit_index[unit_id] = content_hash
        self.notifications_delivered[unit_id] = not callback_dropped

    def parent_recover(self, unit_id: str) -> str | None:
        """Recovery never consults the notification; it scans the durable
        commit index directly, exactly as control_plane.scan_recovery()
        rebuilds state from the ledger rather than from any worker's
        self-report."""
        content_hash = self.commit_index.get(unit_id)
        if content_hash is None:
            return None
        return self.store.get(content_hash)


def run_callback_loss_trial(unit_ids: list[str], drop_decisions: list[bool]) -> dict[str, float]:
    assert len(unit_ids) == len(drop_decisions)
    message_passing = MessagePassingReturn()
    content_addressed = ContentAddressedCustody()
    for unit_id, dropped in zip(unit_ids, drop_decisions):
        payload = f"result-payload-for-{unit_id}"
        message_passing.worker_finishes(unit_id, payload, callback_dropped=dropped)
        content_addressed.worker_finishes(unit_id, payload, callback_dropped=dropped)

    mp_recovered = sum(1 for uid in unit_ids if message_passing.parent_recover(uid) is not None)
    ca_recovered = sum(1 for uid in unit_ids if content_addressed.parent_recover(uid) is not None)
    total = len(unit_ids)
    return {
        "trials": total,
        "callback_drop_count": sum(drop_decisions),
        "message_passing_recovered": mp_recovered,
        "message_passing_recovery_rate": mp_recovered / total,
        "content_addressed_recovered": ca_recovered,
        "content_addressed_recovery_rate": ca_recovered / total,
    }
