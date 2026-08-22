#!/usr/bin/env python3
"""Sanitized Obzio reproductions for the current-method hypotheses.

Each reproduction runs on a repository-native workload and returns a verdict for
one frozen hypothesis.  Source claims, reproductions and mechanism changes stay
in separate records: a reproduction here never asserts that a mechanism changed,
only what the workload did.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import custody_invariants, fixtures, git_custody_probe, input_resolvability
from .custody_machine import Clock, Coordinator, CustodyStore, ExternalWorld
from .fault_injector import FaultInjector, Fault
from .recovery import RecoveryScanner
from .seeded import repository_root
from .transition_matrix import Cell, run_cell, run_matrix

RECOVERY_STATE_REL = "workstreams/po03/control/recovery-state.json"


# ------------------------------------------------------------------------ R1
def reproduce_po02_code2_loss(root: Path | None = None) -> dict[str, Any]:
    """R1: the lost PO-02 Code-2 packaging return, sanitized and replayed.

    The commission freezes that return as PROVIDER_COMPLETED_UNCOMMITTED and
    unrecovered after four reported routes, and instructs that it be used as a
    fault fixture.  The reproduction drives four routes in which the provider
    reports completion with no durable commit, then a fifth route that commits
    and loses its callback.
    """
    repo = root or repository_root()
    recorded = json.loads((repo / RECOVERY_STATE_REL).read_text(encoding="utf-8"))["po02_code2_fixture"]

    base = Path(tempfile.mkdtemp(prefix="po03-wa016-po02-"))
    try:
        injector = FaultInjector(active=True)
        clock = Clock()
        world = ExternalWorld(injector)
        store = CustodyStore(base, injector, clock)
        coordinator = Coordinator(store)
        scanner = RecoveryScanner(store, world, coordinator)
        task_id = "PO02-CODE2-PACKAGING-RETURN"
        immutable_input = fixtures.immutable_input_stub(task_id=task_id, idempotency_key="po02:code2:packaging:a01")
        store.create(task_id, immutable_input)

        routes: list[dict[str, Any]] = []
        fence = 1
        for route in range(1, 5):
            store.lease(task_id, f"attempt-r{route}", fence, immutable_input["idempotency_key"], "lease-po02-code2")
            store.start(task_id, fence)
            # The provider reports success; nothing durable was ever written.
            classified = store.observe_provider(task_id, "COMPLETED")
            report = scanner.scan({task_id: immutable_input})
            routes.append(
                {
                    "route": route,
                    "classified_as": classified,
                    "state_after_scan": store.state(task_id).obzio_state,
                    "recovery_actions": report.kinds(),
                    "durable_commit": store.state(task_id).result_commit_id,
                }
            )
            fence += 1

        never_completed = all(r["classified_as"] != "COMPLETED" for r in routes)
        classification_matches_record = all(
            r["classified_as"] == recorded["obzio_state"] for r in routes
        )
        four_routes_unrecovered = all(r["durable_commit"] is None for r in routes)

        # Fifth route: the work is actually committed but the callback is lost.
        store.lease(task_id, "attempt-r5", fence, immutable_input["idempotency_key"], "lease-po02-code2")
        store.start(task_id, fence)
        store.begin_staging(task_id, fence)
        store.stage_artifacts(task_id, fence, fixtures.default_payload())
        store.verify_staged(task_id, fence)
        commit_id = store.commit_result(task_id, fence, world)
        injector._faults.append(Fault(kind="CALLBACK_LOSS", point="pre_callback_send"))
        injector.arm()
        lost = store.relay(task_id, coordinator)
        store.verify_readback(task_id, world)
        recovery = scanner.scan({task_id: immutable_input})
        final = coordinator.complete(task_id, world)

        return {
            "reproduction_id": "R1-PO02-CODE2-LOST-RETURN",
            "recorded_fixture": recorded,
            "routes": routes,
            "never_reported_completed_without_commit": never_completed,
            "classification_matches_recorded_fixture": classification_matches_record,
            "four_routes_left_no_durable_result": four_routes_unrecovered,
            "route_five_commit_id": commit_id,
            "route_five_callback_outcome": lost,
            "route_five_recovery_actions": recovery.kinds(),
            "route_five_completion": final,
            "final_state": store.state(task_id).obzio_state,
            "verdict": "REPRODUCED"
            if never_completed and classification_matches_record and four_routes_unrecovered and final == "COMPLETED"
            else "NOT_REPRODUCED",
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ------------------------------------------------------------------------ R2
def reproduce_frozen_input_resolvability(root: Path | None = None) -> dict[str, Any]:
    """R2: can every frozen Wave A input still locate its own source base?"""
    report = input_resolvability.check_wave_a(root)
    unresolvable_pointers = sorted(report["pointer_failure_counts"])
    sample = next(
        (
            finding
            for row in report["rows"]
            if row["task_id"] == fixtures.TASK_ID
            for finding in row["findings"]
            if finding["disposition"] == "UNRESOLVABLE"
        ),
        None,
    )
    return {
        "reproduction_id": "R2-FROZEN-INPUT-RESOLVABILITY",
        "input_count": report["input_count"],
        "non_resumable_count": report["non_resumable_count"],
        "pointer_failure_counts": report["pointer_failure_counts"],
        "unresolvable_pointers": unresolvable_pointers,
        "this_unit_example": sample,
        "git_available": report["git_available"],
        "verdict": "DEFECT_REPRODUCED" if report["non_resumable_count"] else "NO_DEFECT_OBSERVED",
    }


# ------------------------------------------------------------------------ R3
def reproduce_git_custody(root: Path | None = None) -> dict[str, Any]:
    """R3: the push-is-idempotent assumption, checked against real git."""
    repo = root or repository_root()
    try:
        probe = git_custody_probe.run_probe()
    except git_custody_probe.GitUnavailable as exc:
        return {
            "reproduction_id": "R3-REAL-GIT-CUSTODY",
            "verdict": "NOT_SUPPORTED",
            "reason": f"git unavailable in this runtime: {exc}",
        }
    recorded = git_custody_probe.verify_recorded_canary(repo)
    return {
        "reproduction_id": "R3-REAL-GIT-CUSTODY",
        "probe": probe,
        "recorded_canary_check": recorded,
        "verdict": "REPRODUCED"
        if probe["push_is_idempotent"] and probe["all_artifacts_reconcile"] and probe["canary_sha256_matches_recorded"]
        else "NOT_REPRODUCED",
    }


# ------------------------------------------------------------------------ R4
def reproduce_deterministic_replay() -> dict[str, Any]:
    """R4: does a seeded fault schedule replay byte-identically?"""
    cell = Cell(transition_id="T08", kind="POST_WRITE_LOSS", point="post_external_effect")
    first = run_cell(cell)
    second = run_cell(cell)
    volatile = {"trace_digest"}
    comparable_first = {k: v for k, v in first.items() if k not in volatile}
    comparable_second = {k: v for k, v in second.items() if k not in volatile}
    return {
        "reproduction_id": "R4-DETERMINISTIC-REPLAY",
        "cell_id": cell.cell_id,
        "trace_digest_first": first["trace_digest"],
        "trace_digest_second": second["trace_digest"],
        "trace_digests_equal": first["trace_digest"] == second["trace_digest"],
        "rows_equal": comparable_first == comparable_second,
        "verdict": "REPRODUCED"
        if first["trace_digest"] == second["trace_digest"] and comparable_first == comparable_second
        else "NOT_REPRODUCED",
    }


# ------------------------------------------------------------------------ R5
def reproduce_seeded_validator_gaps() -> dict[str, Any]:
    """R5: documents the seeded validator admits while asserting completion."""
    rows = custody_invariants.measure_gaps()
    admitted = [r for r in rows if r["seeded_validator_admits"]]
    closed = [r for r in rows if r["closes_gap"]]
    return {
        "reproduction_id": "R5-SEEDED-VALIDATOR-GAPS",
        "gap_count": len(rows),
        "admitted_by_seeded_validator": len(admitted),
        "closed_by_strengthened_layer": len(closed),
        "gaps": rows,
        "verdict": "DEFECT_REPRODUCED" if admitted else "NO_DEFECT_OBSERVED",
    }


# ------------------------------------------------------------------------ R6
def reproduce_falsification_power() -> dict[str, Any]:
    """R6: does the harness detect a machine that is actually broken?"""
    from .naive_machine import MUTANTS

    rows: list[dict[str, Any]] = []
    for name, cls, description in MUTANTS:
        result = run_matrix(store_cls=cls)
        rows.append(
            {
                "mutant": name,
                "defect": description,
                "cells": result["cell_count"],
                "cells_with_violations": result["cells_with_violations"],
                "violation_counts": result["violation_counts"],
                "detected": result["cells_with_violations"] > 0,
            }
        )
    provider_trusting = next(r for r in rows if r["mutant"] == "ProviderTrustingStore")
    return {
        "reproduction_id": "R6-HARNESS-FALSIFICATION-POWER",
        "mutants": rows,
        "all_mutants_detected": all(r["detected"] for r in rows),
        "false_completion_detected_in_provider_trusting_mutant": provider_trusting["violation_counts"].get(
            "I1_NO_FALSE_COMPLETION", 0
        )
        > 0,
        "verdict": "REPRODUCED"
        if all(r["detected"] for r in rows)
        and provider_trusting["violation_counts"].get("I1_NO_FALSE_COMPLETION", 0) > 0
        else "NOT_REPRODUCED",
    }


# ------------------------------------------------------------------------ R7
def reproduce_idempotent_replay_conflict() -> dict[str, Any]:
    """R7: does a replay under one key with different parameters get caught?

    Stripe's documented behaviour is to compare incoming parameters against the
    stored request and error on mismatch rather than silently overwrite.  The
    Obzio analogue is a second attempt publishing different artifact bytes under
    the same frozen idempotency key.
    """
    base = Path(tempfile.mkdtemp(prefix="po03-wa016-idem-"))
    try:
        injector = FaultInjector(active=True)
        world = ExternalWorld(injector)
        store = CustodyStore(base, injector, Clock())
        task_id = fixtures.TASK_ID
        immutable_input = fixtures.immutable_input_stub()
        store.create(task_id, immutable_input)
        store.lease(task_id, immutable_input["attempt_id"], 1, immutable_input["idempotency_key"], immutable_input["lease_id"])
        store.start(task_id, 1)
        store.begin_staging(task_id, 1)
        store.stage_artifacts(task_id, 1, fixtures.default_payload())
        store.verify_staged(task_id, 1)
        first_commit = store.commit_result(task_id, 1, world)

        replay_same = store.commit_result(task_id, 1, world)

        # Now a second attempt tries to publish different bytes under the same key.
        divergent = [("canary.txt", fixtures.CANARY_TEXT + b"divergent\n"), ("unit-result.json", fixtures.unit_result_payload())]
        store.record_event("TRANSITION", task_id, **{"from": store.state(task_id).obzio_state, "to": "RECOVERY_REQUIRED"})
        store.begin_staging(task_id, 1)
        store.stage_artifacts(task_id, 1, divergent)
        store.verify_staged(task_id, 1)
        conflict: str
        try:
            store.commit_result(task_id, 1, world)
            conflict = "NOT_DETECTED"
        except Exception as exc:  # noqa: BLE001 - the type is the observation
            conflict = type(exc).__name__

        return {
            "reproduction_id": "R7-IDEMPOTENT-REPLAY-CONFLICT",
            "first_commit_id": first_commit,
            "same_parameter_replay_returns_same_commit": replay_same == first_commit,
            "distinct_external_effects": world.distinct_effect_count,
            "external_effect_attempts": len(world.attempts),
            "divergent_replay_outcome": conflict,
            "verdict": "REPRODUCED"
            if replay_same == first_commit and conflict == "IdempotencyConflict" and world.distinct_effect_count == 1
            else "NOT_REPRODUCED",
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


ALL_REPRODUCTIONS = (
    reproduce_po02_code2_loss,
    reproduce_frozen_input_resolvability,
    reproduce_git_custody,
    reproduce_deterministic_replay,
    reproduce_seeded_validator_gaps,
    reproduce_falsification_power,
    reproduce_idempotent_replay_conflict,
)


def run_all(root: Path | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for function in ALL_REPRODUCTIONS:
        try:
            results.append(function(root) if function.__code__.co_argcount else function())
        except Exception as exc:  # noqa: BLE001 - a failed reproduction is data
            results.append(
                {
                    "reproduction_id": function.__name__,
                    "verdict": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:400],
                }
            )
    return results
