#!/usr/bin/env python3
"""Transition matrix runner: one custody transition crossed with one fault.

For every cell the runner drives a fresh custody store to the transition under
test, arms exactly one fault, lets the transition run, discards all in-memory
state if the worker was lost, recovers from disk plus the external world, and
then drives the workload to whatever end it can reach.  Nine invariants are
evaluated on the surviving evidence.

The runner is parameterised by the store class so the same matrix can be run
against a deliberately defective machine.  A fault-injection harness that cannot
fail proves nothing, so that mutant run is part of the evidence.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import custody_invariants, fixtures
from .custody_machine import (
    Clock,
    Coordinator,
    CustodyRefused,
    CustodyStore,
    ExternalWorld,
    to_transactional_result,
)
from .durable_io import JournalRead, canonical_json, sha256_bytes
from .fault_injector import (
    ENVIRONMENT_KINDS,
    ExternalUnavailable,
    Fault,
    FaultInjector,
    FencedOut,
    IdempotencyConflict,
    ProcessLoss,
)
from .recovery import RecoveryScanner
from .seeded import load_validator

MAX_RESUMES = 12
# A safety net: a machine that neither progresses nor fails must not spin.
MAX_STEPS = 200

# The ten custody transitions under test, with the fault points each exposes.
TRANSITIONS: tuple[dict[str, Any], ...] = (
    {"id": "T01", "name": "CREATED->LEASED", "step": "lease"},
    {"id": "T02", "name": "LEASED->RUNNING", "step": "start"},
    {"id": "T03", "name": "RUNNING->CHECKPOINTED", "step": "checkpoint"},
    {"id": "T04", "name": "CHECKPOINTED->CHECKPOINTED", "step": "checkpoint"},
    {"id": "T05", "name": "CHECKPOINTED->RESULT_STAGING", "step": "begin_staging"},
    {"id": "T06", "name": "RESULT_STAGING->RESULT_STAGED", "step": "stage"},
    {"id": "T07", "name": "RESULT_STAGED->RESULT_VERIFIED", "step": "verify"},
    {"id": "T08", "name": "RESULT_VERIFIED->RESULT_COMMITTED", "step": "commit"},
    {"id": "T09", "name": "RESULT_COMMITTED->PARENT_INGESTED", "step": "ingest"},
    {"id": "T10", "name": "PARENT_INGESTED->COMPLETED", "step": "complete"},
)

TRANSITION_BY_ID = {t["id"]: t for t in TRANSITIONS}

# Journal and snapshot boundaries exist in every transition.
UNIVERSAL_POINTS = (
    "pre_journal_append",
    "journal_append_partial",
    "post_journal_append",
    "pre_snapshot_write",
    "post_snapshot_tmp_write",
    "post_snapshot_rename",
)

# Extra boundaries only some transitions cross.
EXTRA_POINTS: dict[str, tuple[str, ...]] = {
    "T06": ("pre_artifact_write", "artifact_write_partial", "post_artifact_write"),
    "T08": ("pre_external_effect", "post_external_effect"),
    "T09": ("pre_callback_send", "post_callback_send"),
    "T10": ("pre_readback", "post_readback"),
}

# Which fault kind is meaningful at which point.
POINT_KINDS: dict[str, tuple[str, ...]] = {
    "pre_journal_append": ("PRE_WRITE_LOSS",),
    "journal_append_partial": ("PARTIAL_WRITE",),
    "post_journal_append": ("POST_WRITE_LOSS",),
    "pre_snapshot_write": ("SNAPSHOT_ROLLBACK",),
    "post_snapshot_tmp_write": ("SNAPSHOT_ROLLBACK",),
    "post_snapshot_rename": ("PROCESS_LOSS",),
    "pre_artifact_write": ("PRE_WRITE_LOSS",),
    "artifact_write_partial": ("PARTIAL_WRITE",),
    "post_artifact_write": ("POST_WRITE_LOSS",),
    "pre_external_effect": ("NETWORK_INTERRUPTION", "PRE_WRITE_LOSS"),
    "post_external_effect": ("NETWORK_INTERRUPTION", "POST_WRITE_LOSS"),
    "pre_callback_send": ("CALLBACK_LOSS", "DUPLICATE_CALLBACK"),
    "post_callback_send": ("POST_WRITE_LOSS",),
    "pre_readback": ("PROCESS_LOSS",),
    "post_readback": ("PROCESS_LOSS",),
}

# Environment faults the runner applies around the transition under test.
ENVIRONMENT_MATRIX: dict[str, tuple[str, ...]] = {
    "STALE_LEASE": ("T02", "T03", "T04", "T05", "T06", "T07", "T08"),
    "PARENT_RESTART": ("T01", "T05", "T08", "T09", "T10"),
    "PROVIDER_RUNTIME_LOSS": ("T02", "T06", "T07", "T08", "T09"),
    "CORRUPT_ARTIFACT": ("T06", "T07", "T08", "T09"),
    "MISSING_ARTIFACT": ("T06", "T07", "T08", "T09"),
    "DUPLICATE_COMMIT_REPLAY": ("T08",),
    "DUPLICATE_CALLBACK": ("T09",),
}

# Faults whose damage lands on the immutable remote, where redoing cannot help.
IMMUTABLE_DAMAGE = frozenset({"CORRUPT_ARTIFACT", "MISSING_ARTIFACT"})


@dataclass
class Cell:
    transition_id: str
    kind: str
    point: str
    occurrence: int = 1
    damage_target: str = "none"

    @property
    def cell_id(self) -> str:
        suffix = f":{self.damage_target}" if self.damage_target != "none" else ""
        return f"{self.transition_id}|{self.kind}@{self.point}#{self.occurrence}{suffix}"

    @property
    def transition_name(self) -> str:
        return TRANSITION_BY_ID[self.transition_id]["name"]

    @property
    def expected_outcome(self) -> str:
        if self.kind in IMMUTABLE_DAMAGE and self.damage_target == "remote":
            return "BLOCKED_NO_FALSE_COMPLETION"
        return "COMPLETED"


def enumerate_cells() -> list[Cell]:
    """All applicable (transition, fault) cells, with no silent omissions."""
    cells: list[Cell] = []
    for transition in TRANSITIONS:
        tid = transition["id"]
        points = UNIVERSAL_POINTS + EXTRA_POINTS.get(tid, ())
        for point in points:
            for kind in POINT_KINDS[point]:
                cells.append(Cell(transition_id=tid, kind=kind, point=point))
    for kind, transitions in ENVIRONMENT_MATRIX.items():
        for tid in transitions:
            if kind in IMMUTABLE_DAMAGE:
                for target in ("staging", "remote"):
                    if target == "remote" and tid in {"T06", "T07"}:
                        continue  # no remote commit exists yet
                    if target == "staging" and tid == "T09":
                        continue  # staging no longer gates progress after commit
                    cells.append(Cell(transition_id=tid, kind=kind, point="environment", damage_target=target))
            else:
                cells.append(Cell(transition_id=tid, kind=kind, point="environment"))
    return cells


def inapplicable_cells() -> list[dict[str, str]]:
    """Explicit record of every (transition, fault) pair deliberately excluded."""
    applicable = {(c.transition_id, c.kind) for c in enumerate_cells()}
    rows: list[dict[str, str]] = []
    from .fault_injector import FAULT_KINDS

    for transition in TRANSITIONS:
        for kind in FAULT_KINDS:
            if (transition["id"], kind) in applicable:
                continue
            rows.append(
                {
                    "transition_id": transition["id"],
                    "transition": transition["name"],
                    "fault_kind": kind,
                    "disposition": "NOT_APPLICABLE",
                    "reason": _inapplicable_reason(transition["id"], kind),
                }
            )
    return rows


def _inapplicable_reason(transition_id: str, kind: str) -> str:
    reasons = {
        "PARTIAL_WRITE": "no additional byte-stream boundary beyond the journal append already covered",
        "CALLBACK_LOSS": "transition emits no outbox delivery",
        "DUPLICATE_CALLBACK": "transition emits no outbox delivery",
        "NETWORK_INTERRUPTION": "transition performs no external effect",
        "CORRUPT_ARTIFACT": "no artifact bytes exist at this transition",
        "MISSING_ARTIFACT": "no artifact bytes exist at this transition",
        "DUPLICATE_COMMIT_REPLAY": "transition performs no committing external effect",
        "STALE_LEASE": "transition is not driven by a leased worker",
        "PARENT_RESTART": "coordinator holds no volatile state relevant to this transition",
        "PROVIDER_RUNTIME_LOSS": "covered by the process-loss points on this transition",
        "SNAPSHOT_ROLLBACK": "snapshot boundaries are covered universally",
        "PRE_WRITE_LOSS": "no distinct pre-write boundary beyond those enumerated",
        "POST_WRITE_LOSS": "no distinct post-write boundary beyond those enumerated",
        "PROCESS_LOSS": "covered by the enumerated loss points on this transition",
    }
    del transition_id
    return reasons.get(kind, "not reachable in this transition")


# --------------------------------------------------------------------- session
@dataclass
class Session:
    root: Path
    injector: FaultInjector
    world: ExternalWorld
    store: CustodyStore
    coordinator: Coordinator
    clock: Clock
    store_cls: type[CustodyStore]
    fence_token: int = 1
    attempt_index: int = 1
    crashes: list[dict[str, Any]] = field(default_factory=list)
    recovery_actions: list[dict[str, Any]] = field(default_factory=list)
    step_log: list[dict[str, Any]] = field(default_factory=list)
    scanner_exhausted: bool = False

    def reopen(self) -> None:
        """Discard every in-memory object and rebuild from what survived."""
        self.store = self.store_cls(self.root, self.injector, self.clock)
        self.coordinator = Coordinator(self.store)
        self.coordinator.restart()

    def scan(self, immutable_input: dict[str, Any]) -> None:
        scanner = RecoveryScanner(self.store, self.world, self.coordinator)
        report = scanner.scan({fixtures.TASK_ID: immutable_input})
        self.recovery_actions.extend(report.actions)
        self.scanner_exhausted = self.scanner_exhausted or report.exhausted


def _next_step(state: Any) -> str | None:
    current = state.obzio_state
    if current == "CREATED":
        return "lease"
    if current == "LEASED":
        return "start"
    if current == "RUNNING":
        return "checkpoint"
    if current == "CHECKPOINTED":
        return "checkpoint" if state.checkpoint_seq < 2 else "begin_staging"
    if current == "RESULT_STAGING":
        return "stage"
    if current == "RESULT_STAGED":
        return "verify"
    if current == "RESULT_VERIFIED":
        return "commit"
    if current == "RESULT_COMMITTED":
        return "readback" if not state.fully_readback_verified else "ingest"
    if current == "PARENT_INGESTED":
        # A replayed ingest can land before the read-back; completion still
        # requires the read-back, so do that first rather than looping on a
        # refusal.
        return "complete" if state.fully_readback_verified else "readback"
    if current in {"RETRY_SCHEDULED", "PROVIDER_COMPLETED_UNCOMMITTED", "RECOVERY_REQUIRED"}:
        return "release"
    return None


def _run_step(session: Session, step: str, payload: list[tuple[str, bytes]], immutable_input: dict[str, Any]) -> None:
    task_id = fixtures.TASK_ID
    store = session.store
    if step == "lease":
        store.lease(
            task_id,
            attempt_id=f"{immutable_input['attempt_id']}-r{session.attempt_index}",
            fence_token=session.fence_token,
            idempotency_key=immutable_input["idempotency_key"],
            lease_id=immutable_input["lease_id"],
        )
    elif step == "start":
        store.start(task_id, session.fence_token)
    elif step == "checkpoint":
        store.checkpoint(task_id, session.fence_token, store.state(task_id).checkpoint_seq + 1)
    elif step == "begin_staging":
        store.begin_staging(task_id, session.fence_token)
    elif step == "stage":
        store.stage_artifacts(task_id, session.fence_token, payload)
    elif step == "verify":
        store.verify_staged(task_id, session.fence_token)
    elif step == "commit":
        store.commit_result(task_id, session.fence_token, session.world)
    elif step == "readback":
        store.verify_readback(task_id, session.world)
    elif step == "ingest":
        if store.pending_callbacks(task_id):
            store.relay(task_id, session.coordinator)
        else:
            session.scan(immutable_input)
    elif step == "complete":
        session.coordinator.complete(task_id, session.world)
    elif step == "release":
        # A new attempt takes over from the immutable input with a higher fence.
        session.fence_token += 1
        session.attempt_index += 1
        state = store.state(task_id)
        if state.obzio_state != "RETRY_SCHEDULED":
            session.scan(immutable_input)
            state = store.state(task_id)
        if state.obzio_state == "RETRY_SCHEDULED":
            store.lease(
                task_id,
                attempt_id=f"{immutable_input['attempt_id']}-r{session.attempt_index}",
                fence_token=session.fence_token,
                idempotency_key=immutable_input["idempotency_key"],
                lease_id=immutable_input["lease_id"],
            )
    else:
        raise ValueError(f"unknown step: {step}")


def _apply_environment_fault(session: Session, cell: Cell, when: str, payload: list[tuple[str, bytes]]) -> dict[str, Any] | None:
    """Apply an environment fault around the transition under test."""
    task_id = fixtures.TASK_ID
    store = session.store
    if cell.kind == "STALE_LEASE" and when == "before":
        # Ownership moves while the current worker is mid-transition.  The
        # worker keeps its old token, so its next write must be refused.
        store.expire_lease(task_id)
        stale = session.fence_token
        store.bump_fence(task_id, stale + 1)
        return {"kind": "STALE_LEASE", "stale_fence": stale, "new_fence": stale + 1}
    if cell.kind == "PARENT_RESTART" and when == "after":
        session.coordinator.restart()
        return {"kind": "PARENT_RESTART", "seen_keys": len(session.coordinator.seen_keys)}
    if cell.kind == "PROVIDER_RUNTIME_LOSS" and when == "after":
        classified = store.observe_provider(task_id, "COMPLETED")
        return {"kind": "PROVIDER_RUNTIME_LOSS", "classified_as": classified}
    if cell.kind in IMMUTABLE_DAMAGE and when == "after":
        state = store.state(task_id)
        names = sorted(state.artifacts)
        if not names:
            return {"kind": cell.kind, "applied": False, "reason": "no artifacts"}
        target = names[0]
        if cell.damage_target == "remote":
            if not state.result_commit_id:
                return {"kind": cell.kind, "applied": False, "reason": "no remote commit"}
            ok = (
                session.world.corrupt(state.result_commit_id, target)
                if cell.kind == "CORRUPT_ARTIFACT"
                else session.world.remove(state.result_commit_id, target)
            )
            return {"kind": cell.kind, "target": "remote", "artifact": target, "applied": ok}
        path = store.io.path(f"staging/{task_id}/{target}")
        if not path.exists():
            return {"kind": cell.kind, "applied": False, "reason": "artifact not staged"}
        if cell.kind == "CORRUPT_ARTIFACT":
            path.write_bytes(path.read_bytes() + b"\x00corrupted")
        else:
            path.unlink()
        return {"kind": cell.kind, "target": "staging", "artifact": target, "applied": True}
    if cell.kind == "DUPLICATE_COMMIT_REPLAY" and when == "after":
        try:
            replayed = store.commit_result(task_id, session.fence_token, session.world)
            return {"kind": cell.kind, "replayed_commit_id": replayed, "outcome": "IDEMPOTENT"}
        except (CustodyRefused, IdempotencyConflict, FencedOut) as exc:
            return {"kind": cell.kind, "outcome": type(exc).__name__}
    if cell.kind == "DUPLICATE_CALLBACK" and when == "before":
        return {"kind": cell.kind, "armed": True}
    del payload
    return None


def run_cell(
    cell: Cell,
    *,
    store_cls: type[CustodyStore] = CustodyStore,
    payload: list[tuple[str, bytes]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Drive one matrix cell and evaluate every invariant on the survivors."""
    payload = payload or fixtures.default_payload()
    immutable_input = fixtures.immutable_input_stub()
    task_id = fixtures.TASK_ID
    temporary = root is None
    base = Path(root or tempfile.mkdtemp(prefix="po03-wa016-"))
    try:
        faults: list[Fault] = []
        if cell.point != "environment":
            faults.append(Fault(kind=cell.kind, point=cell.point, occurrence=cell.occurrence))
        elif cell.kind == "DUPLICATE_CALLBACK":
            faults.append(Fault(kind="DUPLICATE_CALLBACK", point="pre_callback_send"))
        injector = FaultInjector(faults)
        clock = Clock()
        world = ExternalWorld(injector)
        store = store_cls(base, injector, clock)
        store.create(task_id, immutable_input)
        session = Session(
            root=base,
            injector=injector,
            world=world,
            store=store,
            coordinator=Coordinator(store),
            clock=clock,
            store_cls=store_cls,
        )

        target_step = TRANSITION_BY_ID[cell.transition_id]["step"]
        target_checkpoint = 2 if cell.transition_id == "T04" else 1
        armed = False
        environment_events: list[dict[str, Any]] = []
        resumes = 0
        steps = 0
        budget_exhausted = False
        refusals_seen: list[str] = []

        while True:
            if resumes > MAX_RESUMES or steps > MAX_STEPS:
                budget_exhausted = True
                break
            steps += 1
            state = session.store.state(task_id)
            step = _next_step(state)
            if step is None:
                break
            at_target = step == target_step and (
                cell.transition_id not in {"T03", "T04"} or state.checkpoint_seq + 1 == target_checkpoint
            )
            fire_now = at_target and not armed
            if fire_now:
                # Arm once.  Anything that goes wrong from here on is recovery,
                # not a second injection.
                armed = True
                if cell.point == "environment":
                    event = _apply_environment_fault(session, cell, "before", payload)
                    if event:
                        environment_events.append(event)
                # Arming restarts occurrence counting, so the fault lands on the
                # transition under test rather than an earlier lookalike.
                session.injector.arm()
            try:
                _run_step(session, step, payload, immutable_input)
                if fire_now and cell.point == "environment":
                    event = _apply_environment_fault(session, cell, "after", payload)
                    if event:
                        environment_events.append(event)
            except ProcessLoss as exc:
                session.crashes.append({"step": step, "point": exc.point, "kind": exc.kind})
                session.reopen()
                session.scan(immutable_input)
                resumes += 1
                continue
            except ExternalUnavailable as exc:
                session.crashes.append({"step": step, "point": "external", "kind": "NETWORK_INTERRUPTION", "detail": str(exc)})
                session.scan(immutable_input)
                resumes += 1
                continue
            except FencedOut as exc:
                refusals_seen.append(f"FENCED_OUT:{exc}")
                # The new owner continues from the durable fence token.
                session.fence_token = max(session.fence_token, session.store.state(task_id).fence_token)
                resumes += 1
                continue
            except (CustodyRefused, IdempotencyConflict) as exc:
                refusals_seen.append(f"{type(exc).__name__}:{exc}")
                session.scan(immutable_input)
                resumes += 1
                continue

        document = to_transactional_result(
            session.store,
            task_id,
            commission_id=fixtures.COMMISSION_ID,
            immutable_input_manifest_sha256="b574ca414864bec359a8edef86f13f064a31a4304eed5c5b95fab83eae88a824",
            acceptance_contract_sha256="b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
            provider_run_id="bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            worker_id="best-of-n-runner-bc-b1956656-wa-016-a01",
        )
        invariants = evaluate_invariants(session, cell, document, payload, budget_exhausted=budget_exhausted)
        return {
            "cell_id": cell.cell_id,
            "transition_id": cell.transition_id,
            "transition": cell.transition_name,
            "fault_kind": cell.kind,
            "fault_point": cell.point,
            "damage_target": cell.damage_target,
            "expected_outcome": cell.expected_outcome,
            "fault_fired": bool(session.injector.fired) or bool(environment_events),
            "crashes": session.crashes,
            "environment_events": environment_events,
            "recovery_actions": [a["action"] for a in session.recovery_actions],
            "refusals_recorded": sorted({r["reason"] for r in session.store.state(task_id).refusals}),
            "refusals_raised": refusals_seen[:6],
            "resumes": resumes,
            "steps": steps,
            "budget_exhausted": budget_exhausted,
            "final_obzio_state": session.store.state(task_id).obzio_state,
            "final_provider_state": session.store.state(task_id).provider_state,
            "history": session.store.state(task_id).history,
            "distinct_external_effects": session.world.distinct_effect_count,
            "external_effect_attempts": len(session.world.attempts),
            "duplicate_ingests_ignored": session.coordinator.duplicate_ingests,
            "trace_digest": session.injector.trace_digest(),
            "invariants": invariants,
            "violations": sorted(name for name, result in invariants.items() if result["disposition"] == "FAIL"),
        }
    finally:
        if temporary:
            shutil.rmtree(base, ignore_errors=True)


# ------------------------------------------------------------------ invariants
def evaluate_invariants(
    session: Session,
    cell: Cell,
    document: dict[str, Any],
    payload: list[tuple[str, bytes]],
    *,
    budget_exhausted: bool = False,
) -> dict[str, dict[str, Any]]:
    task_id = fixtures.TASK_ID
    state = session.store.state(task_id)
    results: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool, evidence: str) -> None:
        results[name] = {"disposition": "PASS" if ok else "FAIL", "evidence": evidence}

    # I1 -- the central claim: no completion without durable, re-read evidence.
    completed = state.obzio_state == "COMPLETED"
    false_completion_reasons: list[str] = []
    if completed:
        if not state.result_commit_id:
            false_completion_reasons.append("COMPLETED without result_commit_id")
        if state.completion_actor != "coordinator":
            false_completion_reasons.append(f"COMPLETED by {state.completion_actor}")
        if not state.fully_readback_verified:
            false_completion_reasons.append("COMPLETED without full artifact read-back")
        if not (state.committed_at and state.verified_at and state.parent_ingested_at):
            false_completion_reasons.append("COMPLETED with incomplete custody timestamps")
        if "RESULT_COMMITTED" not in state.history:
            false_completion_reasons.append("COMPLETED without passing RESULT_COMMITTED")
        for name, record_ in sorted(state.artifacts.items()):
            blob = session.world.read(state.result_commit_id or "", name)
            if blob is None or sha256_bytes(blob) != record_.sha256 or len(blob) != record_.bytes:
                false_completion_reasons.append(f"COMPLETED while remote artifact {name} does not reconcile")
    if state.history.count("COMPLETED") > 1:
        false_completion_reasons.append("COMPLETED recorded more than once")
    record(
        "I1_NO_FALSE_COMPLETION",
        not false_completion_reasons,
        "; ".join(false_completion_reasons) or f"final state {state.obzio_state} carries complete durable evidence",
    )

    # I2 -- committed results are recovered; damaged remotes are refused.
    if cell.expected_outcome == "COMPLETED":
        record(
            "I2_COMMITTED_RESULT_RECOVERED",
            completed,
            f"final state {state.obzio_state} (expected COMPLETED after recovery)",
        )
    else:
        blocked = (
            not completed
            and state.obzio_state == "FAILED_TERMINAL"
            and any(
                r["reason"] in {"READBACK_FAILED", "COMPLETION_REFUSED", "STAGED_VERIFICATION_FAILED"}
                for r in state.refusals
            )
        )
        record(
            "I2_COMMITTED_RESULT_RECOVERED",
            blocked,
            f"final state {state.obzio_state} with refusals {sorted({r['reason'] for r in state.refusals})}",
        )

    # I3 -- uncommitted work resumes from the immutable input, not from memory.
    needed_retry = any(s in state.history for s in ("PROVIDER_COMPLETED_UNCOMMITTED", "RETRY_SCHEDULED"))
    if needed_retry:
        retried = [
            a
            for a in session.recovery_actions
            if a["action"].startswith("SCHEDULE_RETRY") and a.get("immutable_input_present", True)
        ]
        key_preserved = state.idempotency_key == fixtures.IDEMPOTENCY_KEY
        record(
            "I3_UNCOMMITTED_RESUMES_FROM_IMMUTABLE_INPUT",
            bool(retried) and key_preserved,
            f"retry actions={len(retried)} idempotency_key_preserved={key_preserved}",
        )
    else:
        record("I3_UNCOMMITTED_RESUMES_FROM_IMMUTABLE_INPUT", True, "no uncommitted retry was required")

    # I4 -- at-least-once delivery, at-most-once effect.
    distinct = session.world.distinct_effect_count
    ingest_count = state.history.count("PARENT_INGESTED")
    record(
        "I4_NO_DUPLICATE_EXTERNAL_EFFECT",
        distinct <= 1 and ingest_count <= 1 and len(set(session.world.refs.values())) <= 1,
        f"distinct_effects={distinct} attempts={len(session.world.attempts)} parent_ingested_records={ingest_count}",
    )

    # I5 -- every declared artifact carries a reconciled hash and byte count.
    txn = document["result_transaction"]
    hash_ok = (
        txn["artifact_count"] == len(document["artifacts"])
        and txn["total_bytes"] == sum(a["bytes"] for a in document["artifacts"])
        and all(len(a["sha256"]) == 64 and a["bytes"] >= 1 for a in document["artifacts"])
    )
    expected_names = {name for name, _ in payload}
    if state.artifacts:
        hash_ok = hash_ok and set(state.artifacts) <= expected_names
    record(
        "I5_COMPLETE_HASH_COVERAGE",
        hash_ok,
        f"artifact_count={txn['artifact_count']} total_bytes={txn['total_bytes']}",
    )

    # I6 -- the journal survived as a strictly ordered, gapless log.
    read: JournalRead = session.store.io.read_records("journal.jsonl")
    seqs = [int(r.get("seq", -1)) for r in read.records]
    ordered = seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    gapless = not seqs or seqs == list(range(1, len(seqs) + 1))
    snapshot = session.store.io.read_json("state.json")
    snapshot_sane = snapshot is None or int(snapshot.get("last_seq", 0)) <= (seqs[-1] if seqs else 0)
    record(
        "I6_JOURNAL_INTEGRITY",
        ordered and gapless and not read.torn and snapshot_sane,
        f"records={len(seqs)} torn_bytes={read.torn_bytes} ordered={ordered} gapless={gapless} snapshot_sane={snapshot_sane}",
    )

    # I7 -- a fenced-out worker cannot commit after ownership transfers.
    if cell.kind == "STALE_LEASE":
        fenced = any(r["reason"] == "FENCED_OUT" for r in state.refusals)
        record("I7_STALE_FENCE_REJECTED", fenced, f"fenced_out_refusals={fenced}")
    else:
        record("I7_STALE_FENCE_REJECTED", True, "no stale lease was injected")

    # I8 -- the emitted document satisfies the read-only seeded validator.
    validator = load_validator()
    errors = validator.validate_result(document)
    record("I8_SEEDED_VALIDATOR_ACCEPTS", not errors, "; ".join(errors[:4]) or "seeded validator returned no errors")

    # I9 -- recovery terminates without spending the safety budget.
    record(
        "I9_RECOVERY_TERMINATES",
        not session.scanner_exhausted and not budget_exhausted,
        f"scanner_exhausted={session.scanner_exhausted} budget_exhausted={budget_exhausted}",
    )

    # I10 -- the strengthened layer proposed by this unit also accepts.
    strengthened = custody_invariants.validate_result_strict(document)
    record(
        "I10_STRENGTHENED_INVARIANTS_HOLD",
        not strengthened,
        "; ".join(strengthened[:4]) or "strengthened layer returned no errors",
    )
    return results


# ---------------------------------------------------------------------- runner
def run_matrix(
    cells: Iterable[Cell] | None = None,
    *,
    store_cls: type[CustodyStore] = CustodyStore,
    payload: list[tuple[str, bytes]] | None = None,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run every cell and summarise invariant outcomes."""
    cell_list = list(cells) if cells is not None else enumerate_cells()
    rows: list[dict[str, Any]] = []
    for index, cell in enumerate(cell_list, 1):
        row = run_cell(cell, store_cls=store_cls, payload=payload)
        rows.append(row)
        if progress:
            progress(index, len(cell_list), row)
    violation_counts: dict[str, int] = {}
    for row in rows:
        for name in row["violations"]:
            violation_counts[name] = violation_counts.get(name, 0) + 1
    return {
        "machine": store_cls.__name__,
        "cell_count": len(rows),
        "transitions_covered": sorted({r["transition_id"] for r in rows}),
        "fault_kinds_covered": sorted({r["fault_kind"] for r in rows}),
        "cells_with_violations": sum(1 for r in rows if r["violations"]),
        "violation_counts": violation_counts,
        "false_completions": violation_counts.get("I1_NO_FALSE_COMPLETION", 0),
        "rows": rows,
        "inapplicable": inapplicable_cells(),
        "rows_digest": sha256_bytes(canonical_json([{k: v for k, v in r.items() if k != "trace_digest"} for r in rows])),
    }
