#!/usr/bin/env python3
"""Seeded multi-fault fuzzing, for comparison against exhaustive enumeration.

The exhaustive matrix injects exactly one fault per run.  The open question is
whether randomized schedules that overlap several faults find custody defect
classes the single-fault matrix misses at this model's size.  This module runs
that comparison so the answer is measured rather than assumed.

Only *safety* invariants are compared.  A schedule that crashes the worker three
times in a row can legitimately prevent progress, so liveness expectations such
as "the result eventually completes" are not evidence of a defect here; they are
recorded separately.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import fixtures
from .custody_machine import (
    Clock,
    Coordinator,
    CustodyRefused,
    CustodyStore,
    ExternalWorld,
    to_transactional_result,
)
from .fault_injector import (
    ENVIRONMENT_KINDS,
    FAULT_KINDS,
    FAULT_POINTS,
    ExternalUnavailable,
    Fault,
    FaultInjector,
    FencedOut,
    IdempotencyConflict,
    ProcessLoss,
)
from .transition_matrix import (
    Cell,
    MAX_RESUMES,
    MAX_STEPS,
    Session,
    evaluate_invariants,
    next_step,
    run_step,
)

# Properties that must hold no matter how hostile the schedule is.
SAFETY_INVARIANTS = (
    "I1_NO_FALSE_COMPLETION",
    "I4_NO_DUPLICATE_EXTERNAL_EFFECT",
    "I5_COMPLETE_HASH_COVERAGE",
    "I6_JOURNAL_INTEGRITY",
    "I8_SEEDED_VALIDATOR_ACCEPTS",
    "I10_STRENGTHENED_INVARIANTS_HOLD",
)

# Excluded from the comparison, with the reason recorded in the report.
EXCLUDED_INVARIANTS = {
    "I2_COMMITTED_RESULT_RECOVERED": "liveness; a schedule may legitimately prevent progress",
    "I3_UNCOMMITTED_RESUMES_FROM_IMMUTABLE_INPUT": "conditional on a retry being required",
    "I7_STALE_FENCE_REJECTED": "conditional on a stale lease being scheduled at a reachable point",
    "I9_RECOVERY_TERMINATES": "bounded by the harness retry budget, not by the machine",
}


def build_schedule(seed: int, max_faults: int = 3) -> tuple[list[Fault], dict[int, str]]:
    """Seeded schedule of point faults plus environment faults at step ordinals."""
    rng = random.Random(seed)
    faults: list[Fault] = []
    environment: dict[int, str] = {}
    for _ in range(rng.randint(1, max_faults)):
        kind = rng.choice(FAULT_KINDS)
        if kind in ENVIRONMENT_KINDS:
            environment[rng.randint(1, 14)] = kind
            continue
        point = rng.choice(FAULT_POINTS)
        faults.append(Fault(kind=kind, point=point, occurrence=rng.randint(1, 2)))
    return faults, environment


def _apply_environment(session: Session, kind: str) -> dict[str, Any]:
    task_id = fixtures.TASK_ID
    store = session.store
    state = store.state(task_id)
    if kind == "STALE_LEASE":
        store.expire_lease(task_id)
        try:
            store.bump_fence(task_id, session.fence_token + 1)
        except CustodyRefused as exc:
            return {"kind": kind, "applied": False, "reason": type(exc).__name__}
        return {"kind": kind, "applied": True, "stale_fence": session.fence_token}
    if kind == "PARENT_RESTART":
        session.coordinator.restart()
        return {"kind": kind, "applied": True}
    if kind == "PROVIDER_RUNTIME_LOSS":
        return {"kind": kind, "applied": True, "classified_as": store.observe_provider(task_id, "COMPLETED")}
    if kind == "DUPLICATE_COMMIT_REPLAY":
        try:
            return {"kind": kind, "applied": True, "replayed": store.commit_result(task_id, session.fence_token, session.world)}
        except (CustodyRefused, IdempotencyConflict, FencedOut, ProcessLoss, ExternalUnavailable) as exc:
            return {"kind": kind, "applied": True, "outcome": type(exc).__name__}
    if kind in {"CORRUPT_ARTIFACT", "MISSING_ARTIFACT"}:
        names = sorted(state.artifacts)
        if not names:
            return {"kind": kind, "applied": False, "reason": "no artifacts yet"}
        target = names[0]
        if state.result_commit_id:
            ok = (
                session.world.corrupt(state.result_commit_id, target)
                if kind == "CORRUPT_ARTIFACT"
                else session.world.remove(state.result_commit_id, target)
            )
            return {"kind": kind, "applied": ok, "where": "remote", "artifact": target}
        path = store.io.path(f"staging/{task_id}/{target}")
        if not path.exists():
            return {"kind": kind, "applied": False, "reason": "not staged"}
        if kind == "CORRUPT_ARTIFACT":
            path.write_bytes(path.read_bytes() + b"\x00corrupted")
        else:
            path.unlink()
        return {"kind": kind, "applied": True, "where": "staging", "artifact": target}
    return {"kind": kind, "applied": False, "reason": "unhandled"}


def run_case(seed: int, *, max_faults: int = 3) -> dict[str, Any]:
    """One fuzz run: hostile schedule from the first transition onward."""
    faults, environment = build_schedule(seed, max_faults)
    payload = fixtures.default_payload()
    immutable_input = fixtures.immutable_input_stub()
    task_id = fixtures.TASK_ID
    base = Path(tempfile.mkdtemp(prefix="po03-wa016-fuzz-"))
    try:
        injector = FaultInjector(faults, seed=seed)
        clock = Clock()
        world = ExternalWorld(injector)
        store = CustodyStore(base, injector, clock)
        # The task record is written by the coordinator before dispatch, so the
        # worker's fault schedule starts only once the worker does.
        store.create(task_id, immutable_input)
        injector.arm()
        session = Session(
            root=base,
            injector=injector,
            world=world,
            store=store,
            coordinator=Coordinator(store),
            clock=clock,
            store_cls=CustodyStore,
        )
        environment_events: list[dict[str, Any]] = []
        resumes = 0
        steps = 0
        budget_exhausted = False
        while True:
            if resumes > MAX_RESUMES or steps > MAX_STEPS:
                budget_exhausted = True
                break
            steps += 1
            step = next_step(session.store.state(task_id))
            if step is None:
                break
            try:
                # The environment action is itself a durable write, so a
                # scheduled fault can interrupt it.  It shares the step's
                # recovery path rather than escaping the driver.
                if steps in environment:
                    environment_events.append(_apply_environment(session, environment.pop(steps)))
                run_step(session, step, payload, immutable_input)
            except ProcessLoss as exc:
                session.crashes.append({"step": step, "point": exc.point, "kind": exc.kind})
                session.reopen()
                session.scan(immutable_input)
                resumes += 1
            except ExternalUnavailable:
                session.crashes.append({"step": step, "point": "external", "kind": "NETWORK_INTERRUPTION"})
                session.scan(immutable_input)
                resumes += 1
            except FencedOut:
                session.fence_token = max(session.fence_token, session.store.state(task_id).fence_token)
                resumes += 1
            except (CustodyRefused, IdempotencyConflict):
                session.scan(immutable_input)
                resumes += 1

        document = to_transactional_result(
            session.store,
            task_id,
            commission_id=fixtures.COMMISSION_ID,
            immutable_input_manifest_sha256="b574ca414864bec359a8edef86f13f064a31a4304eed5c5b95fab83eae88a824",
            acceptance_contract_sha256="b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
            provider_run_id="bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            worker_id="best-of-n-runner-bc-b1956656-wa-016-a01",
        )
        synthetic = Cell(transition_id="T01", kind="PROCESS_LOSS", point="environment")
        invariants = evaluate_invariants(session, synthetic, document, payload, budget_exhausted=budget_exhausted)
        safety_violations = sorted(
            name for name in SAFETY_INVARIANTS if invariants[name]["disposition"] == "FAIL"
        )
        return {
            "seed": seed,
            "scheduled_faults": [f.cell_id for f in faults],
            "scheduled_environment_faults": sorted(f"{k}@step{s}" for s, k in build_schedule(seed, max_faults)[1].items()),
            "environment_events": environment_events,
            "crashes": len(session.crashes),
            "resumes": resumes,
            "steps": steps,
            "budget_exhausted": budget_exhausted,
            "final_obzio_state": session.store.state(task_id).obzio_state,
            "distinct_external_effects": session.world.distinct_effect_count,
            "safety_violations": safety_violations,
            "all_violations": sorted(n for n, r in invariants.items() if r["disposition"] == "FAIL"),
            "safety_evidence": {n: invariants[n]["evidence"][:200] for n in safety_violations},
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


def run_campaign(count: int = 300, *, start_seed: int = 1, max_faults: int = 3) -> dict[str, Any]:
    """Run a fuzz campaign and summarise which safety classes it discovered."""
    rows = [run_case(seed, max_faults=max_faults) for seed in range(start_seed, start_seed + count)]
    classes: dict[str, int] = {}
    for row in rows:
        for name in row["safety_violations"]:
            classes[name] = classes.get(name, 0) + 1
    return {
        "case_count": len(rows),
        "seed_range": [start_seed, start_seed + count - 1],
        "max_faults_per_case": max_faults,
        "compared_invariants": list(SAFETY_INVARIANTS),
        "excluded_invariants": EXCLUDED_INVARIANTS,
        "safety_violation_classes": classes,
        "cases_with_safety_violations": sum(1 for r in rows if r["safety_violations"]),
        "cases_budget_exhausted": sum(1 for r in rows if r["budget_exhausted"]),
        "final_state_histogram": {
            state: sum(1 for r in rows if r["final_obzio_state"] == state)
            for state in sorted({r["final_obzio_state"] for r in rows})
        },
        "max_distinct_external_effects": max(r["distinct_external_effects"] for r in rows) if rows else 0,
        "failing_cases": [r for r in rows if r["safety_violations"]][:10],
    }


def compare_with_exhaustive(matrix_summary: dict[str, Any], campaign: dict[str, Any]) -> dict[str, Any]:
    """Did randomized multi-fault scheduling find a class the matrix missed?"""
    matrix_classes = {
        name for name in matrix_summary.get("violation_counts", {}) if name in SAFETY_INVARIANTS
    }
    fuzz_classes = set(campaign["safety_violation_classes"])
    new_classes = sorted(fuzz_classes - matrix_classes)
    return {
        "exhaustive_safety_classes": sorted(matrix_classes),
        "fuzz_safety_classes": sorted(fuzz_classes),
        "classes_found_only_by_fuzz": new_classes,
        "fuzz_found_new_class": bool(new_classes),
        "exhaustive_cells": matrix_summary.get("cell_count"),
        "fuzz_cases": campaign["case_count"],
    }
