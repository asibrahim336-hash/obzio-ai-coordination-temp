#!/usr/bin/env python3
"""Durable transactional custody machine for PO-03 work-unit results.

Implements the commission's custody lifecycle

    CREATED -> LEASED -> RUNNING -> CHECKPOINTED* -> RESULT_STAGING ->
    RESULT_STAGED -> RESULT_VERIFIED -> RESULT_COMMITTED -> PARENT_INGESTED ->
    COMPLETED

with the durability machinery the commission requires: an append-only journal,
a transactional outbox, leases with fencing tokens, monotonic checkpoints, an
idempotent external-effect ledger and a recovery scanner.

Two design rules carry the anti-false-completion guarantee:

1. The journal is the only source of truth.  ``state.json`` is a rebuildable
   cache, so losing it cannot lose a transition.
2. ``COMPLETED`` is gated on evidence that survives the worker: a durable
   external commit, a manifest, and a fresh read-back of every artifact from the
   external world.  A provider that merely says it finished cannot produce it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .durable_io import DurableIO, canonical_json, sha256_bytes
from .fault_injector import ExternalUnavailable, FaultInjector, FencedOut, IdempotencyConflict

JOURNAL = "journal.jsonl"
SNAPSHOT = "state.json"
STAGING = "staging"

STATES: tuple[str, ...] = (
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
)

_RECOVERABLE = {"RECOVERY_REQUIRED", "RETRY_SCHEDULED", "PROVIDER_COMPLETED_UNCOMMITTED", "FAILED_TERMINAL"}

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"LEASED", "CANCELLED"} | _RECOVERABLE),
    "LEASED": frozenset({"RUNNING", "CANCELLED"} | _RECOVERABLE),
    "RUNNING": frozenset({"CHECKPOINTED", "RESULT_STAGING", "CANCELLED"} | _RECOVERABLE),
    "CHECKPOINTED": frozenset({"CHECKPOINTED", "RESULT_STAGING", "CANCELLED"} | _RECOVERABLE),
    "RESULT_STAGING": frozenset({"RESULT_STAGED"} | _RECOVERABLE),
    "RESULT_STAGED": frozenset({"RESULT_VERIFIED", "RESULT_STAGING"} | _RECOVERABLE),
    "RESULT_VERIFIED": frozenset({"RESULT_COMMITTED", "RESULT_STAGING"} | _RECOVERABLE),
    "RESULT_COMMITTED": frozenset({"PARENT_INGESTED", "RECOVERY_REQUIRED"}),
    "PARENT_INGESTED": frozenset({"COMPLETED", "RECOVERY_REQUIRED"}),
    "COMPLETED": frozenset(),
    "PROVIDER_COMPLETED_UNCOMMITTED": frozenset({"RECOVERY_REQUIRED", "RETRY_SCHEDULED", "RESULT_COMMITTED", "FAILED_TERMINAL"}),
    "RECOVERY_REQUIRED": frozenset(
        {
            "LEASED",
            "RETRY_SCHEDULED",
            "RESULT_STAGING",
            "RESULT_STAGED",
            "RESULT_VERIFIED",
            "RESULT_COMMITTED",
            "PARENT_INGESTED",
            "PROVIDER_COMPLETED_UNCOMMITTED",
            "FAILED_TERMINAL",
        }
    ),
    "RETRY_SCHEDULED": frozenset({"LEASED", "FAILED_TERMINAL"}),
    "FAILED_TERMINAL": frozenset(),
    "CANCELLED": frozenset(),
}

# States that assert a durable result exists.
COMMITTED_STATES = frozenset({"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"})


class CustodyRefused(RuntimeError):
    """A custody guard refused an operation; recorded durably, not an accident."""


class IllegalTransition(CustodyRefused):
    pass


class Clock:
    """Deterministic logical clock.

    Wall-clock time would make runs unrepeatable, which would defeat the whole
    point of a seeded fault schedule.
    """

    def __init__(self, epoch: str = "2026-08-22T07:13:11Z", start: int = 0) -> None:
        self.epoch = epoch
        self._tick = start

    def now(self) -> str:
        self._tick += 1
        return f"{self.epoch[:-1]}+{self._tick:06d}Z"

    @property
    def tick(self) -> int:
        return self._tick


@dataclass
class ArtifactRecord:
    logical_name: str
    sha256: str
    bytes: int
    media_type: str = "application/json"
    readback_verified_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "media_type": self.media_type,
            "readback_verified_at": self.readback_verified_at,
        }


@dataclass
class TaskState:
    task_id: str
    obzio_state: str = "CREATED"
    provider_state: str = "UNKNOWN"
    attempt_id: str | None = None
    idempotency_key: str | None = None
    lease_id: str | None = None
    fence_token: int = 0
    lease_expired: bool = False
    checkpoint_seq: int = 0
    artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)
    staged_at: str | None = None
    verified_at: str | None = None
    readback_at: str | None = None
    committed_at: str | None = None
    parent_ingested_at: str | None = None
    result_commit_id: str | None = None
    manifest_sha256: str | None = None
    manifest_uri: str | None = None
    completion_actor: str | None = None
    history: list[str] = field(default_factory=lambda: ["CREATED"])
    outbox: list[dict[str, Any]] = field(default_factory=list)
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    refusals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def total_bytes(self) -> int:
        return sum(a.bytes for a in self.artifacts.values())

    @property
    def has_durable_commit(self) -> bool:
        return bool(self.result_commit_id)

    @property
    def fully_readback_verified(self) -> bool:
        return bool(self.artifacts) and all(a.readback_verified_at for a in self.artifacts.values())


class ExternalWorld:
    """Content-addressed stand-in for the immutable remote.

    Push is idempotent by content, which is the property real git gives us: two
    pushes of identical trees to the same ref converge on one commit id.  The
    ledger therefore separates *attempts* (which may repeat after a crash) from
    *distinct effects* (which must not).
    """

    def __init__(self, injector: FaultInjector) -> None:
        self.injector = injector
        self.refs: dict[str, str] = {}
        self.commits: dict[str, dict[str, bytes]] = {}
        self.attempts: list[dict[str, Any]] = []
        self.distinct_effects: dict[str, str] = {}

    @staticmethod
    def commit_id_for(ref: str, tree: dict[str, bytes]) -> str:
        digest = hashlib.sha256()
        digest.update(ref.encode("utf-8"))
        for name in sorted(tree):
            digest.update(b"\x00" + name.encode("utf-8") + b"\x00" + sha256_bytes(tree[name]).encode("ascii"))
        return digest.hexdigest()

    def push(self, ref: str, tree: dict[str, bytes], *, effect_key: str) -> str:
        commit_id = self.commit_id_for(ref, tree)
        self.attempts.append({"ref": ref, "commit_id": commit_id, "effect_key": effect_key})
        fault = self.injector.crash_if("pre_external_effect", ref=ref, commit_id=commit_id)
        if fault is not None and fault.kind == "NETWORK_INTERRUPTION":
            raise ExternalUnavailable(f"push to {ref} interrupted before the effect landed")
        self.commits[commit_id] = dict(tree)
        self.refs[ref] = commit_id
        self.distinct_effects.setdefault(effect_key, commit_id)
        fault = self.injector.crash_if("post_external_effect", ref=ref, commit_id=commit_id)
        if fault is not None and fault.kind == "NETWORK_INTERRUPTION":
            # The effect landed but the acknowledgement did not.  The caller
            # cannot tell the difference; only a world query can.
            raise ExternalUnavailable(f"push to {ref} landed but was not acknowledged")
        return commit_id

    def lookup(self, ref: str) -> str | None:
        return self.refs.get(ref)

    def read(self, commit_id: str, name: str) -> bytes | None:
        return self.commits.get(commit_id, {}).get(name)

    # ------------------------------------------------ environment damage hooks
    def corrupt(self, commit_id: str, name: str) -> bool:
        blob = self.commits.get(commit_id, {}).get(name)
        if blob is None:
            return False
        self.commits[commit_id][name] = blob + b"\x00corrupted"
        return True

    def remove(self, commit_id: str, name: str) -> bool:
        if name in self.commits.get(commit_id, {}):
            del self.commits[commit_id][name]
            return True
        return False

    @property
    def distinct_effect_count(self) -> int:
        return len(self.distinct_effects)


class CustodyStore:
    """Journal-first durable store for custody state."""

    def __init__(self, root: Path, injector: FaultInjector, clock: Clock | None = None) -> None:
        self.io = DurableIO(Path(root), injector)
        self.injector = injector
        self.clock = clock or Clock()
        self.tasks: dict[str, TaskState] = {}
        self.last_seq = 0
        self.journal_heals: list[dict[str, Any]] = []
        self.immutable_inputs: dict[str, dict[str, Any]] = {}
        self.load()

    # --------------------------------------------------------------- journal
    def load(self) -> dict[str, Any]:
        """Rebuild in-memory state from the journal, healing a torn tail."""
        healed = self.io.heal_records(JOURNAL)
        read = self.io.read_records(JOURNAL)
        self.tasks = {}
        self.last_seq = 0
        for record in read.records:
            self._apply(record)
            self.last_seq = max(self.last_seq, int(record.get("seq", 0)))
        report = {
            "records_replayed": len(read.records),
            "torn_bytes_discarded": healed,
            "orphan_temp_files": self.io.orphan_temp_files(),
        }
        if healed:
            self.journal_heals.append(report)
        return report

    def _append(self, kind: str, task_id: str, **data: Any) -> dict[str, Any]:
        record = {
            "seq": self.last_seq + 1,
            "kind": kind,
            "task_id": task_id,
            "at": self.clock.now(),
            "data": data,
        }
        self.io.append_record(
            JOURNAL,
            record,
            pre="pre_journal_append",
            partial="journal_append_partial",
            post="post_journal_append",
        )
        self.last_seq = record["seq"]
        self._apply(record)
        self._write_snapshot()
        return record

    def _write_snapshot(self) -> None:
        """Refresh the rebuildable state cache.

        Losing this write is survivable by construction, so a crash here is
        recorded but not fatal to the transaction.
        """
        payload = {
            "last_seq": self.last_seq,
            "tasks": {tid: self.describe(tid) for tid in sorted(self.tasks)},
        }
        self.io.atomic_write(
            SNAPSHOT,
            canonical_json(payload),
            pre="pre_snapshot_write",
            mid="post_snapshot_tmp_write",
            post="post_snapshot_rename",
        )

    # ----------------------------------------------------------------- replay
    def _apply(self, record: dict[str, Any]) -> None:
        kind = record.get("kind")
        task_id = record.get("task_id")
        data = record.get("data") or {}
        if not isinstance(task_id, str):
            return
        if kind == "CREATE":
            self.tasks[task_id] = TaskState(task_id=task_id)
            self.immutable_inputs[task_id] = data.get("immutable_input", {})
            return
        state = self.tasks.get(task_id)
        if state is None:
            return
        if kind == "TRANSITION":
            state.obzio_state = data["to"]
            state.history.append(data["to"])
            for name in ("attempt_id", "idempotency_key", "lease_id", "provider_state", "completion_actor"):
                if data.get(name) is not None:
                    setattr(state, name, data[name])
            if data.get("fence_token") is not None:
                state.fence_token = int(data["fence_token"])
            if data.get("lease_expired") is not None:
                state.lease_expired = bool(data["lease_expired"])
            for name in ("staged_at", "verified_at", "committed_at", "parent_ingested_at", "result_commit_id", "manifest_sha256", "manifest_uri"):
                if data.get(name) is not None:
                    setattr(state, name, data[name])
            if data.get("checkpoint_seq") is not None:
                state.checkpoint_seq = int(data["checkpoint_seq"])
            for entry in data.get("artifacts", ()):
                state.artifacts[entry["logical_name"]] = ArtifactRecord(**entry)
            for entry in data.get("outbox", ()):
                state.outbox.append(dict(entry))
        elif kind == "READBACK":
            for entry in data.get("artifacts", ()):
                if entry["logical_name"] in state.artifacts:
                    state.artifacts[entry["logical_name"]].readback_verified_at = entry["readback_verified_at"]
                state.readback_at = entry["readback_verified_at"]
        elif kind == "EFFECT_INTENT":
            state.effects[data["effect_key"]] = {
                "params_hash": data["params_hash"],
                "state": "INTENT",
                "result": None,
                "attempts": state.effects.get(data["effect_key"], {}).get("attempts", 0) + 1,
            }
        elif kind == "EFFECT_DONE":
            entry = state.effects.setdefault(data["effect_key"], {"params_hash": data["params_hash"], "attempts": 1})
            entry.update({"state": "DONE", "result": data["result"], "params_hash": data["params_hash"]})
        elif kind == "CALLBACK_DELIVERED":
            for entry in state.outbox:
                if entry["outbox_id"] == data["outbox_id"]:
                    entry["delivered_at"] = data["at"]
        elif kind == "REFUSAL":
            state.refusals.append(dict(data))
        elif kind == "PROVIDER_OBSERVED":
            state.provider_state = data["provider_state"]
        elif kind == "FENCE_BUMP":
            state.fence_token = int(data["fence_token"])
        elif kind == "LEASE_EXPIRED":
            state.lease_expired = True

    # ------------------------------------------------------------- accessors
    def state(self, task_id: str) -> TaskState:
        if task_id not in self.tasks:
            raise KeyError(f"unknown task: {task_id}")
        return self.tasks[task_id]

    def describe(self, task_id: str) -> dict[str, Any]:
        state = self.tasks[task_id]
        return {
            "task_id": state.task_id,
            "obzio_state": state.obzio_state,
            "provider_state": state.provider_state,
            "attempt_id": state.attempt_id,
            "idempotency_key": state.idempotency_key,
            "fence_token": state.fence_token,
            "lease_expired": state.lease_expired,
            "checkpoint_seq": state.checkpoint_seq,
            "artifacts": [a.to_json() for a in sorted(state.artifacts.values(), key=lambda x: x.logical_name)],
            "staged_at": state.staged_at,
            "verified_at": state.verified_at,
            "committed_at": state.committed_at,
            "parent_ingested_at": state.parent_ingested_at,
            "result_commit_id": state.result_commit_id,
            "manifest_sha256": state.manifest_sha256,
            "manifest_uri": state.manifest_uri,
            "completion_actor": state.completion_actor,
            "history": list(state.history),
            "outbox": [dict(e) for e in state.outbox],
            "refusals": [dict(r) for r in state.refusals],
        }

    # ------------------------------------------------------------ guard rails
    def record_event(self, kind: str, task_id: str, **data: Any) -> dict[str, Any]:
        """Public journal append, for the coordinator and recovery scanner.

        Refusals are recorded rather than swallowed: a guard that declines
        silently is indistinguishable from one that never noticed.
        """
        return self._append(kind, task_id, **data)

    def _require_fence(self, task_id: str, fence_token: int) -> None:
        state = self.state(task_id)
        if fence_token < state.fence_token:
            self._append("REFUSAL", task_id, reason="FENCED_OUT", detail=f"token {fence_token} < {state.fence_token}")
            raise FencedOut(f"fence token {fence_token} below current {state.fence_token}")

    def _require_transition(self, task_id: str, to_state: str) -> TaskState:
        state = self.state(task_id)
        if to_state not in LEGAL_TRANSITIONS.get(state.obzio_state, frozenset()):
            self._append(
                "REFUSAL",
                task_id,
                reason="ILLEGAL_TRANSITION",
                detail=f"{state.obzio_state} -> {to_state}",
            )
            raise IllegalTransition(f"{state.obzio_state} -> {to_state} is not legal")
        return state

    # ------------------------------------------------------------ transitions
    def create(self, task_id: str, immutable_input: dict[str, Any]) -> None:
        self._append("CREATE", task_id, immutable_input=immutable_input)

    def lease(self, task_id: str, attempt_id: str, fence_token: int, idempotency_key: str, lease_id: str) -> None:
        self._require_transition(task_id, "LEASED")
        state = self.state(task_id)
        if fence_token < state.fence_token:
            self._append("REFUSAL", task_id, reason="FENCED_OUT", detail=f"lease token {fence_token} < {state.fence_token}")
            raise FencedOut("cannot lease with a stale fence token")
        self._append(
            "TRANSITION",
            task_id,
            **{
                "from": state.obzio_state,
                "to": "LEASED",
                "attempt_id": attempt_id,
                "fence_token": fence_token,
                "idempotency_key": idempotency_key,
                "lease_id": lease_id,
                "lease_expired": False,
            },
        )

    def start(self, task_id: str, fence_token: int) -> None:
        self._require_fence(task_id, fence_token)
        state = self._require_transition(task_id, "RUNNING")
        self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": "RUNNING", "provider_state": "RUNNING"})

    def checkpoint(self, task_id: str, fence_token: int, checkpoint_seq: int) -> None:
        self._require_fence(task_id, fence_token)
        state = self.state(task_id)
        if checkpoint_seq <= state.checkpoint_seq:
            self._append(
                "REFUSAL",
                task_id,
                reason="NON_MONOTONIC_CHECKPOINT",
                detail=f"{checkpoint_seq} <= {state.checkpoint_seq}",
            )
            raise CustodyRefused("checkpoint_seq must increase strictly")
        self._require_transition(task_id, "CHECKPOINTED")
        # The sequence number travels in the same record as the transition.  Two
        # records would let a crash between them leave a task that claims to be
        # checkpointed at a sequence it never reached.
        self._append(
            "TRANSITION",
            task_id,
            **{"from": state.obzio_state, "to": "CHECKPOINTED", "checkpoint_seq": checkpoint_seq},
        )

    def begin_staging(self, task_id: str, fence_token: int) -> None:
        self._require_fence(task_id, fence_token)
        state = self._require_transition(task_id, "RESULT_STAGING")
        self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": "RESULT_STAGING"})

    def stage_artifacts(self, task_id: str, fence_token: int, payload: Iterable[tuple[str, bytes]]) -> None:
        """Write artifact bytes, then record RESULT_STAGED in one journal record.

        The state change lands only after every byte is fsynced, so a crash
        mid-write leaves the task in RESULT_STAGING and recovery restages rather
        than trusting a half written set.
        """
        self._require_fence(task_id, fence_token)
        state = self.state(task_id)
        entries: list[dict[str, Any]] = []
        for logical_name, data in payload:
            rel = f"{STAGING}/{task_id}/{logical_name}"
            written = self.io.write_artifact(rel, data)
            entries.append(
                {
                    "logical_name": logical_name,
                    "sha256": sha256_bytes(data),
                    "bytes": written,
                    "media_type": "application/json" if logical_name.endswith(".json") else "text/plain; charset=utf-8",
                    "readback_verified_at": None,
                }
            )
        self._require_transition(task_id, "RESULT_STAGED")
        self._append(
            "TRANSITION",
            task_id,
            **{"from": state.obzio_state, "to": "RESULT_STAGED", "artifacts": entries, "staged_at": self.clock.now()},
        )

    def staged_bytes(self, task_id: str) -> dict[str, bytes | None]:
        state = self.state(task_id)
        return {
            name: self.io.read_artifact(f"{STAGING}/{task_id}/{name}")
            for name in sorted(state.artifacts)
        }

    def reconcile_staged(self, task_id: str) -> list[dict[str, Any]]:
        """Compare staged bytes on disk against the recorded hashes."""
        state = self.state(task_id)
        mismatches: list[dict[str, Any]] = []
        for name, record in sorted(state.artifacts.items()):
            data = self.io.read_artifact(f"{STAGING}/{task_id}/{name}")
            if data is None:
                mismatches.append({"logical_name": name, "reason": "MISSING"})
                continue
            if len(data) != record.bytes or sha256_bytes(data) != record.sha256:
                mismatches.append(
                    {
                        "logical_name": name,
                        "reason": "HASH_OR_BYTE_MISMATCH",
                        "observed_sha256": sha256_bytes(data),
                        "observed_bytes": len(data),
                    }
                )
        return mismatches

    def verify_staged(self, task_id: str, fence_token: int) -> dict[str, Any]:
        """Re-read every staged artifact and reconcile hash and byte count."""
        self._require_fence(task_id, fence_token)
        state = self.state(task_id)
        mismatches = self.reconcile_staged(task_id)
        if mismatches or not state.artifacts:
            detail = "no artifacts staged" if not state.artifacts else canonical_json(mismatches).decode()
            self._append("REFUSAL", task_id, reason="STAGED_VERIFICATION_FAILED", detail=detail)
            self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": "RECOVERY_REQUIRED"})
            raise CustodyRefused(f"staged verification failed: {detail}")
        manifest = self.manifest_document(task_id)
        manifest_sha = sha256_bytes(canonical_json(manifest))
        self._require_transition(task_id, "RESULT_VERIFIED")
        self._append(
            "TRANSITION",
            task_id,
            **{
                "from": state.obzio_state,
                "to": "RESULT_VERIFIED",
                "verified_at": self.clock.now(),
                "manifest_sha256": manifest_sha,
            },
        )
        return manifest

    def manifest_document(self, task_id: str) -> dict[str, Any]:
        state = self.state(task_id)
        return {
            "task_id": task_id,
            "artifacts": [
                {"logical_name": a.logical_name, "sha256": a.sha256, "bytes": a.bytes, "media_type": a.media_type}
                for a in sorted(state.artifacts.values(), key=lambda x: x.logical_name)
            ],
            "artifact_count": state.artifact_count,
            "total_bytes": state.total_bytes,
        }

    def result_ref(self, task_id: str) -> str:
        return f"refs/po03/{task_id.lower()}"

    def commit_result(self, task_id: str, fence_token: int, world: ExternalWorld) -> str:
        """Publish the result to the external world, exactly once in effect.

        The intent is journaled before the effect and the completion after it, so
        a crash in between is detectable.  The effect itself is content
        addressed, so a replay converges on the same commit instead of creating a
        second durable result.
        """
        self._require_fence(task_id, fence_token)

        # A replay of an already committed result is a no-op, not an illegal
        # transition.  Duplicate callbacks and retried commits must be harmless.
        state = self.state(task_id)
        recorded = state.effects.get(f"{state.idempotency_key}|push")
        if state.obzio_state in COMMITTED_STATES and recorded and recorded.get("state") == "DONE":
            return str(recorded["result"])

        state = self._require_transition(task_id, "RESULT_COMMITTED")

        # Re-reconcile immediately before publishing.  Damage that lands between
        # verification and commit would otherwise be published under the earlier
        # manifest, and the idempotency ledger then blocks the repair because the
        # effect key is already spent.
        mismatches = self.reconcile_staged(task_id)
        if mismatches or not state.artifacts:
            detail = "no artifacts staged" if not state.artifacts else canonical_json(mismatches).decode()
            self._append("REFUSAL", task_id, reason="PRE_COMMIT_RECONCILIATION_FAILED", detail=detail)
            self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": "RECOVERY_REQUIRED"})
            raise CustodyRefused(f"pre-commit reconciliation failed: {detail}")

        manifest = self.manifest_document(task_id)
        tree: dict[str, bytes] = {"artifact-manifest.json": canonical_json(manifest)}
        for name, data in self.staged_bytes(task_id).items():
            if data is None:
                self._append("REFUSAL", task_id, reason="MISSING_STAGED_ARTIFACT", detail=name)
                raise CustodyRefused(f"cannot commit: staged artifact missing: {name}")
            tree[name] = data
        effect_key = f"{state.idempotency_key}|push"
        params_hash = sha256_bytes(canonical_json(sorted((k, sha256_bytes(v)) for k, v in tree.items())))

        ref = self.result_ref(task_id)
        existing = state.effects.get(effect_key)
        if existing and existing.get("state") == "DONE":
            if existing.get("params_hash") != params_hash:
                self._append("REFUSAL", task_id, reason="IDEMPOTENCY_CONFLICT", detail=effect_key)
                raise IdempotencyConflict(f"replay of {effect_key} changed parameters")
            commit_id = str(existing["result"])
            if state.obzio_state in COMMITTED_STATES:
                # Already durably recorded; the replay is a no-op by design.
                return commit_id
            # The effect landed but its transition did not survive.  Re-enter the
            # transition without repeating the effect.
            self._record_commit_transition(task_id, ref, commit_id, manifest)
            return commit_id

        self._append("EFFECT_INTENT", task_id, effect_key=effect_key, params_hash=params_hash)
        commit_id = world.push(ref, tree, effect_key=effect_key)
        self._append("EFFECT_DONE", task_id, effect_key=effect_key, params_hash=params_hash, result=commit_id)

        self._record_commit_transition(task_id, ref, commit_id, manifest)
        return commit_id

    def _record_commit_transition(self, task_id: str, ref: str, commit_id: str, manifest: dict[str, Any]) -> None:
        """Journal RESULT_COMMITTED with its outbox entry in one atomic record.

        The callback is enqueued in the same durable record as the state change,
        so the callback exists if and only if the transition committed.
        """
        state = self.state(task_id)
        outbox_entry = {
            "outbox_id": f"ob-{task_id.lower()}-{len(state.outbox) + 1}",
            "idempotency_key": state.idempotency_key,
            "kind": "RESULT_READY",
            "result_commit_id": commit_id,
            "delivered_at": None,
        }
        self._append(
            "TRANSITION",
            task_id,
            **{
                "from": state.obzio_state,
                "to": "RESULT_COMMITTED",
                # Preserved on re-entry: the commit time is when the effect
                # landed, not when a later attempt noticed.
                "committed_at": state.committed_at or self.clock.now(),
                "result_commit_id": commit_id,
                "manifest_sha256": sha256_bytes(canonical_json(manifest)),
                "manifest_uri": f"{ref}@{commit_id}:artifact-manifest.json",
                "outbox": [outbox_entry],
            },
        )

    def verify_readback(self, task_id: str, world: ExternalWorld) -> list[dict[str, Any]]:
        """Read every artifact back from the external world and reconcile it."""
        state = self.state(task_id)
        if not state.result_commit_id:
            raise CustodyRefused("cannot read back before a durable commit exists")
        self.injector.crash_if("pre_readback", task_id=task_id)
        mismatches: list[dict[str, Any]] = []
        verified: list[dict[str, Any]] = []
        stamp = self.clock.now()
        for name, record in sorted(state.artifacts.items()):
            blob = world.read(state.result_commit_id, name)
            if blob is None:
                mismatches.append({"logical_name": name, "reason": "MISSING_IN_REMOTE"})
                continue
            if len(blob) != record.bytes or sha256_bytes(blob) != record.sha256:
                mismatches.append(
                    {
                        "logical_name": name,
                        "reason": "REMOTE_HASH_OR_BYTE_MISMATCH",
                        "observed_sha256": sha256_bytes(blob),
                        "observed_bytes": len(blob),
                    }
                )
                continue
            verified.append({"logical_name": name, "readback_verified_at": stamp})
        if mismatches:
            self._append("REFUSAL", task_id, reason="READBACK_FAILED", detail=canonical_json(mismatches).decode())
            if state.obzio_state in LEGAL_TRANSITIONS and "RECOVERY_REQUIRED" in LEGAL_TRANSITIONS[state.obzio_state]:
                self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": "RECOVERY_REQUIRED"})
            return mismatches
        self._append("READBACK", task_id, artifacts=verified)
        self.injector.crash_if("post_readback", task_id=task_id)
        return []

    # -------------------------------------------------------------- callbacks
    def pending_callbacks(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self.state(task_id).outbox if not e.get("delivered_at")]

    def relay(self, task_id: str, coordinator: "Coordinator") -> list[dict[str, Any]]:
        """Deliver outbox entries.

        Delivery is at-least-once and the receiver is idempotent, so a lost send
        is replayable and a duplicated send is harmless.
        """
        delivered: list[dict[str, Any]] = []
        for entry in self.pending_callbacks(task_id):
            fault = self.injector.arrive("pre_callback_send", task_id=task_id, outbox_id=entry["outbox_id"])
            if fault is not None and fault.kind == "CALLBACK_LOSS":
                delivered.append({"outbox_id": entry["outbox_id"], "outcome": "LOST_IN_TRANSIT"})
                continue
            times = 2 if fault is not None and fault.kind == "DUPLICATE_CALLBACK" else 1
            outcomes = [coordinator.ingest(task_id, entry) for _ in range(times)]
            self.injector.crash_if("post_callback_send", task_id=task_id, outbox_id=entry["outbox_id"])
            self._append("CALLBACK_DELIVERED", task_id, outbox_id=entry["outbox_id"], at=self.clock.now())
            delivered.append({"outbox_id": entry["outbox_id"], "outcome": "DELIVERED", "deliveries": outcomes})
        return delivered

    # ------------------------------------------------------- provider observer
    def observe_provider(self, task_id: str, provider_state: str) -> str:
        """Record what the provider claims, and classify it honestly.

        Provider completion is an observation.  Without a durable result commit
        it becomes PROVIDER_COMPLETED_UNCOMMITTED, never COMPLETED.
        """
        self._append("PROVIDER_OBSERVED", task_id, provider_state=provider_state)
        state = self.state(task_id)
        if provider_state == "COMPLETED" and not state.has_durable_commit and state.obzio_state not in COMMITTED_STATES:
            target = "PROVIDER_COMPLETED_UNCOMMITTED"
            if target in LEGAL_TRANSITIONS.get(state.obzio_state, frozenset()):
                self._append("TRANSITION", task_id, **{"from": state.obzio_state, "to": target})
                return target
            self._append(
                "REFUSAL",
                task_id,
                reason="PROVIDER_CLAIM_UNCLASSIFIED",
                detail=f"cannot classify provider COMPLETED from {state.obzio_state}",
            )
        return state.obzio_state

    def expire_lease(self, task_id: str) -> None:
        self._append("LEASE_EXPIRED", task_id)

    def bump_fence(self, task_id: str, fence_token: int) -> None:
        """Transfer ownership by raising the durable fence token.

        Recorded independently of the lifecycle state because ownership can move
        while a task sits mid-transition.  The store then actively rejects the
        previous owner, which is the property a lease alone cannot provide.
        """
        state = self.state(task_id)
        if fence_token <= state.fence_token:
            self._append("REFUSAL", task_id, reason="NON_MONOTONIC_FENCE", detail=f"{fence_token} <= {state.fence_token}")
            raise CustodyRefused("fence tokens must increase strictly")
        self._append("FENCE_BUMP", task_id, fence_token=fence_token)


class Coordinator:
    """The only actor permitted to record COMPLETED.

    In-memory ingestion bookkeeping is deliberately volatile so that a parent
    restart has to rebuild from the journal.
    """

    def __init__(self, store: CustodyStore) -> None:
        self.store = store
        self.seen_keys: set[str] = set()
        self.ingest_calls = 0
        self.duplicate_ingests = 0

    def restart(self) -> None:
        """Drop volatile state; rebuild the idempotency set from the journal."""
        self.seen_keys = set()
        for task_id, state in self.store.tasks.items():
            del task_id
            if state.parent_ingested_at:
                for entry in state.outbox:
                    if entry.get("delivered_at"):
                        self.seen_keys.add(f"{entry['idempotency_key']}|{entry['outbox_id']}")

    def ingest(self, task_id: str, callback: dict[str, Any]) -> str:
        """Idempotent ingestion keyed by the frozen idempotency key."""
        self.ingest_calls += 1
        key = f"{callback['idempotency_key']}|{callback['outbox_id']}"
        state = self.store.state(task_id)
        if key in self.seen_keys or state.parent_ingested_at:
            self.duplicate_ingests += 1
            return "DUPLICATE_IGNORED"
        self.seen_keys.add(key)
        if not state.has_durable_commit:
            self.store.record_event("REFUSAL", task_id, reason="INGEST_WITHOUT_COMMIT", detail=key)
            return "REFUSED_NO_COMMIT"
        if "PARENT_INGESTED" not in LEGAL_TRANSITIONS.get(state.obzio_state, frozenset()):
            self.store.record_event("REFUSAL", task_id, reason="INGEST_ILLEGAL_STATE", detail=state.obzio_state)
            return "REFUSED_ILLEGAL_STATE"
        self.store.record_event(
            "TRANSITION",
            task_id,
            **{"from": state.obzio_state, "to": "PARENT_INGESTED", "parent_ingested_at": self.store.clock.now()},
        )
        return "INGESTED"

    def complete(self, task_id: str, world: ExternalWorld, actor: str = "coordinator") -> str:
        """Gate COMPLETED on evidence that outlives the producer."""
        state = self.store.state(task_id)
        reasons: list[str] = []
        if actor != "coordinator":
            reasons.append(f"actor {actor} is not the coordinator")
        if state.obzio_state != "PARENT_INGESTED":
            reasons.append(f"state {state.obzio_state} is not PARENT_INGESTED")
        if not state.result_commit_id:
            reasons.append("no durable result commit")
        if not state.verified_at or not state.committed_at or not state.parent_ingested_at:
            reasons.append("incomplete custody timestamps")
        if not state.artifacts:
            reasons.append("no artifacts")
        if not state.fully_readback_verified:
            reasons.append("artifacts not fully read back")
        if not reasons:
            fresh = self.store.verify_readback(task_id, world)
            if fresh:
                reasons.append("fresh read-back mismatch")
        if reasons:
            self.store.record_event("REFUSAL", task_id, reason="COMPLETION_REFUSED", detail="; ".join(reasons))
            return "REFUSED"
        self.store.record_event(
            "TRANSITION",
            task_id,
            **{"from": state.obzio_state, "to": "COMPLETED", "completion_actor": actor},
        )
        return "COMPLETED"


def to_transactional_result(
    store: CustodyStore,
    task_id: str,
    *,
    commission_id: str,
    immutable_input_manifest_sha256: str,
    acceptance_contract_sha256: str,
    provider_run_id: str,
    worker_id: str,
) -> dict[str, Any]:
    """Emit a document in the seeded OBZIO-TRANSACTIONAL-RESULT-v1 shape."""
    state = store.state(task_id)
    txn_state = {
        "CREATED": "RESERVED",
        "LEASED": "RESERVED",
        "RUNNING": "RESERVED",
        "CHECKPOINTED": "RESERVED",
        "RESULT_STAGING": "STAGING",
        "RESULT_STAGED": "STAGED",
        "RESULT_VERIFIED": "VERIFIED",
        "RESULT_COMMITTED": "COMMITTED",
        "PARENT_INGESTED": "INGESTED",
        "COMPLETED": "INGESTED",
    }.get(state.obzio_state, "RESERVED")
    artifacts = [
        {
            "artifact_id": f"art-{task_id.lower()}-{a.logical_name.replace('.', '-')}",
            "logical_name": a.logical_name,
            "content_uri": f"{store.result_ref(task_id)}@{state.result_commit_id or 'STAGED'}:{a.logical_name}",
            "sha256": a.sha256,
            "bytes": a.bytes,
            "media_type": a.media_type,
            "readback_verified_at": a.readback_verified_at,
        }
        for a in sorted(state.artifacts.values(), key=lambda x: x.logical_name)
    ]
    provider_state = state.provider_state if state.provider_state in {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"} else "UNKNOWN"
    if state.obzio_state == "PROVIDER_COMPLETED_UNCOMMITTED":
        provider_state = "COMPLETED"
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": task_id,
        "commission_id": commission_id,
        "immutable_input_manifest_sha256": immutable_input_manifest_sha256,
        "acceptance_contract_sha256": acceptance_contract_sha256,
        "provider_state": provider_state,
        "obzio_state": state.obzio_state,
        "attempt": {
            "attempt_id": state.attempt_id or f"{task_id}-A00",
            "idempotency_key": state.idempotency_key or f"{task_id.lower()}:a00",
            "lease_id": state.lease_id or f"lease-{task_id.lower()}",
            "fence_token": max(1, state.fence_token),
            "provider_run_id": provider_run_id,
            "worker_id": worker_id,
            "heartbeat_at": state.staged_at,
            "checkpoint_seq": state.checkpoint_seq,
        },
        "result_transaction": {
            "result_txn_id": f"txn-{task_id.lower()}",
            "state": txn_state,
            "manifest_uri": state.manifest_uri,
            "manifest_sha256": state.manifest_sha256,
            "artifact_count": len(artifacts),
            "total_bytes": sum(a["bytes"] for a in artifacts),
            "committed_at": state.committed_at,
            # The seeded contract's verified_at is the durability verification,
            # so a completed result reports its read-back time; before any
            # read-back exists the staged verification stands in.
            "verified_at": state.readback_at or state.verified_at,
            "parent_ingested_at": state.parent_ingested_at,
            "result_commit_id": state.result_commit_id,
        },
        "artifacts": artifacts,
        "completion_actor": state.completion_actor,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
