#!/usr/bin/env python3
"""Recovery scanner: classify surviving custody state and act on it.

The scanner runs after a crash, restart or lost callback.  It only trusts what
survived: the healed journal and the external world.  In particular it queries
the world before deciding that an uncommitted task has to be redone, because a
push can land without its acknowledgement ever reaching the worker.

Every classification produces an explicit action so the transition matrix can
assert that recovery did something specific, not merely that nothing crashed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .custody_machine import (
    COMMITTED_STATES,
    Coordinator,
    CustodyStore,
    ExternalWorld,
    LEGAL_TRANSITIONS,
)
from .durable_io import canonical_json, sha256_bytes

# Bounded so a scanner that cannot make progress fails loudly instead of looping.
MAX_SCAN_PASSES = 8

# Repeated read-back failure against an immutable commit is not retryable by the
# producer; after this many the task is classified terminally.
UNRECOVERABLE_READBACK_FAILURES = 2


@dataclass
class RecoveryReport:
    actions: list[dict[str, Any]] = field(default_factory=list)
    passes: int = 0
    exhausted: bool = False

    def add(self, action: str, task_id: str, **detail: Any) -> None:
        self.actions.append({"action": action, "task_id": task_id, **detail})

    def kinds(self) -> list[str]:
        return [a["action"] for a in self.actions]


class RecoveryScanner:
    """Replays lost work from what survived, never from a provider's word."""

    def __init__(self, store: CustodyStore, world: ExternalWorld, coordinator: Coordinator) -> None:
        self.store = store
        self.world = world
        self.coordinator = coordinator

    def scan(self, immutable_inputs: dict[str, dict[str, Any]] | None = None) -> RecoveryReport:
        report = RecoveryReport()
        inputs = immutable_inputs if immutable_inputs is not None else self.store.immutable_inputs
        for _ in range(MAX_SCAN_PASSES):
            report.passes += 1
            progressed = False
            for task_id in sorted(self.store.tasks):
                if self._scan_task(task_id, inputs.get(task_id, {}), report):
                    progressed = True
            if not progressed:
                return report
        report.exhausted = True
        return report

    # ------------------------------------------------------------------ passes
    def _scan_task(self, task_id: str, immutable_input: dict[str, Any], report: RecoveryReport) -> bool:
        state = self.store.state(task_id)

        if self.store.journal_heals:
            healed = self.store.journal_heals.pop(0)
            report.add("HEAL_TORN_JOURNAL", task_id, **healed)
            return True

        orphans = self.store.io.orphan_temp_files()
        if orphans:
            for rel in orphans:
                (self.store.io.root / rel).unlink(missing_ok=True)
            report.add("SWEEP_ORPHAN_TEMP_FILES", task_id, files=orphans)
            return True

        # A push can land without an acknowledgement.  Adopt an existing durable
        # commit instead of producing a second one.
        if not state.has_durable_commit and state.obzio_state not in COMMITTED_STATES:
            adopted = self._adopt_orphan_commit(task_id, report)
            if adopted:
                return True

        if state.obzio_state == "RESULT_COMMITTED" and not state.parent_ingested_at:
            if self.store.pending_callbacks(task_id):
                delivered = self.store.relay(task_id, self.coordinator)
                report.add("REPLAY_LOST_CALLBACK", task_id, deliveries=delivered)
                return True
            outcome = self.coordinator.ingest(
                task_id,
                {
                    "outbox_id": f"ob-{task_id.lower()}-recovered",
                    "idempotency_key": state.idempotency_key,
                    "kind": "RESULT_READY",
                    "result_commit_id": state.result_commit_id,
                },
            )
            report.add("REPLAY_PARENT_INGEST", task_id, outcome=outcome)
            return True

        if state.obzio_state == "PROVIDER_COMPLETED_UNCOMMITTED":
            report.add(
                "SCHEDULE_RETRY_FROM_IMMUTABLE_INPUT",
                task_id,
                immutable_input_present=bool(immutable_input),
                idempotency_key=state.idempotency_key,
            )
            self.store.record_event(
                "TRANSITION",
                task_id,
                **{"from": state.obzio_state, "to": "RETRY_SCHEDULED", "provider_state": "COMPLETED"},
            )
            return True

        if state.lease_expired and state.obzio_state not in COMMITTED_STATES | {"RETRY_SCHEDULED", "FAILED_TERMINAL", "CANCELLED"}:
            target = "RECOVERY_REQUIRED" if state.obzio_state != "RECOVERY_REQUIRED" else "RETRY_SCHEDULED"
            if target in LEGAL_TRANSITIONS.get(state.obzio_state, frozenset()):
                self.store.record_event("TRANSITION", task_id, **{"from": state.obzio_state, "to": target})
                report.add("FENCE_EXPIRED_LEASE", task_id, to=target, fence_token=state.fence_token)
                return True

        if state.obzio_state == "RECOVERY_REQUIRED":
            readback_failures = sum(1 for r in state.refusals if r["reason"] == "READBACK_FAILED")
            if readback_failures >= UNRECOVERABLE_READBACK_FAILURES:
                # The published commit is immutable, so a producer retry cannot
                # repair it.  Classify terminally rather than retry forever or
                # let a later pass mistake the state for progress.
                self.store.record_event(
                    "TRANSITION", task_id, **{"from": state.obzio_state, "to": "FAILED_TERMINAL"}
                )
                report.add(
                    "CLASSIFY_UNRECOVERABLE_REMOTE_DAMAGE",
                    task_id,
                    readback_failures=readback_failures,
                    result_commit_id=state.result_commit_id,
                )
                return True
            self.store.record_event(
                "TRANSITION", task_id, **{"from": state.obzio_state, "to": "RETRY_SCHEDULED"}
            )
            report.add("SCHEDULE_RETRY_AFTER_DAMAGE", task_id, idempotency_key=state.idempotency_key)
            return True

        if state.obzio_state in {"LEASED", "RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED"}:
            report.add(
                "RESUME_IN_PLACE",
                task_id,
                from_state=state.obzio_state,
                checkpoint_seq=state.checkpoint_seq,
                immutable_input_present=bool(immutable_input),
            )
            return False

        return False

    def _adopt_orphan_commit(self, task_id: str, report: RecoveryReport) -> bool:
        """Recover a durable commit whose acknowledgement was lost.

        This is the difference between "100% recovery of committed results" and
        quietly redoing work that already landed.
        """
        state = self.store.state(task_id)
        ref = self.store.result_ref(task_id)
        commit_id = self.world.lookup(ref)
        if not commit_id:
            return False
        effect_key = f"{state.idempotency_key}|push"
        if state.effects.get(effect_key, {}).get("state") == "DONE":
            return False
        manifest_blob = self.world.read(commit_id, "artifact-manifest.json")
        if manifest_blob is None:
            return False
        if not state.artifacts:
            return False
        expected = sha256_bytes(canonical_json(self.store.manifest_document(task_id)))
        if sha256_bytes(manifest_blob) != expected:
            report.add("REMOTE_COMMIT_DIVERGED", task_id, commit_id=commit_id)
            return False
        if "RESULT_COMMITTED" not in LEGAL_TRANSITIONS.get(state.obzio_state, frozenset()):
            return False
        self.store.record_event(
            "EFFECT_DONE",
            task_id,
            effect_key=effect_key,
            params_hash=state.effects.get(effect_key, {}).get("params_hash", ""),
            result=commit_id,
        )
        self.store.record_event(
            "TRANSITION",
            task_id,
            **{
                "from": state.obzio_state,
                "to": "RESULT_COMMITTED",
                "committed_at": self.store.clock.now(),
                "result_commit_id": commit_id,
                "manifest_sha256": expected,
                "manifest_uri": f"{ref}@{commit_id}:artifact-manifest.json",
                "outbox": [
                    {
                        "outbox_id": f"ob-{task_id.lower()}-adopted",
                        "idempotency_key": state.idempotency_key,
                        "kind": "RESULT_READY",
                        "result_commit_id": commit_id,
                        "delivered_at": None,
                    }
                ],
            },
        )
        report.add("ADOPT_UNACKNOWLEDGED_COMMIT", task_id, commit_id=commit_id)
        return True
