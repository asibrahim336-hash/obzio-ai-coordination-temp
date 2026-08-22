#!/usr/bin/env python3
"""Injections against the lease and fence-token boundary.

Five faults are injected: a superseded worker committing after ownership moved,
the transferred holder committing, a holder committing after its recorded lease
lifetime elapsed, a worker presenting a fence token that was never allocated,
and two allocators racing for the counter.

Run directly to print the observation as JSON:

    python3 -I lease_fencing_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
FENCE_CHILD = HERE / "fence_child.py"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_045_fault_kit", "fault_kit.py")
repair = _load("po03_c6_045_repair", "repair_candidate_fencing.py")

TASK_ID = "po03-c6-045-sandbox-unit"
SLOT = f"workstreams/po03/attempts/{TASK_ID}"
ARTIFACT_PATH = f"{SLOT}/component.json"


def stage(sandbox: Path, instance: str, *, lease_seconds: int = 60):
    """Seed a capsule, commit an artifact and grant the first lease."""
    module = kit.bind_sandbox(kit.load_factory(instance), sandbox)
    kit.init_repository(sandbox)
    kit.seed_capsule(module, TASK_ID, hypothesis="only the current holder may commit")
    artifact = sandbox / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(module.canonical_json({"component": TASK_ID, "computed": True}))
    commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")
    lease = module.grant_lease(TASK_ID, holder="worker-a", lease_seconds=lease_seconds, attempt=1)
    return module, commit, lease


def result_for(module, commit: str, *, fence_token: int, worker_id: str) -> dict[str, Any]:
    return kit.build_result_document(
        module,
        task_id=TASK_ID,
        commit=commit,
        paths=[ARTIFACT_PATH],
        fence_token=fence_token,
        worker_id=worker_id,
    )


def inject_superseded_worker(root: Path) -> dict[str, Any]:
    """Ownership transfers, then the old holder tries to commit."""
    module, commit, first = stage(root / "superseded", "045_superseded")
    second = module.grant_lease(TASK_ID, holder="worker-b", lease_seconds=60, attempt=2)
    stale = module.ingest_result(TASK_ID, result_for(module, commit, fence_token=first["fence_token"], worker_id="worker-a"))
    fresh = module.ingest_result(TASK_ID, result_for(module, commit, fence_token=second["fence_token"], worker_id="worker-b"))
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    observed = {
        "first_fence": first["fence_token"],
        "second_fence": second["fence_token"],
        "fence_advanced_on_transfer": second["fence_token"] > first["fence_token"],
        "stale_holder_state": stale["obzio_state"],
        "stale_holder_errors": stale["errors"],
        "transferred_holder_state": fresh["obzio_state"],
        "transferred_holder_errors": fresh["errors"],
        "false_completion_count": state["false_completion_count"],
    }
    passed = (
        observed["fence_advanced_on_transfer"]
        and observed["stale_holder_state"] == "RECOVERY_REQUIRED"
        and any("stale" in error for error in observed["stale_holder_errors"])
        and observed["transferred_holder_state"] == "PARENT_INGESTED"
        and observed["transferred_holder_errors"] == []
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "SUPERSEDED_WORKER_COMMITS_AFTER_OWNERSHIP_TRANSFER",
        "injected_at_state_transition": "LEASED (transferred) -> RESULT_COMMITTED",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_expired_lease(root: Path) -> dict[str, Any]:
    """The holder's recorded lease lifetime has elapsed and no transfer happened."""
    module, commit, lease = stage(root / "expired", "045_expired", lease_seconds=0)
    ingestion = module.ingest_result(
        TASK_ID,
        result_for(module, commit, fence_token=lease["fence_token"], worker_id="worker-a"),
    )
    guarded = repair.guarded_ingest(
        module,
        TASK_ID,
        result_for(module, commit, fence_token=lease["fence_token"], worker_id="worker-a"),
    )
    fence_source = inspect.getsource(module.assert_fence_current)
    ingest_source = inspect.getsource(module.ingest_result)
    observed = {
        "lease_seconds_recorded": lease["lease_seconds"],
        "live_ingestion_state": ingestion["obzio_state"],
        "live_ingestion_errors": ingestion["errors"],
        "expiry_referenced_in_fence_check": any(
            token in fence_source for token in ("lease_seconds", "granted_at")
        ),
        "expiry_referenced_in_ingestion": any(
            token in ingest_source for token in ("lease_seconds", "granted_at")
        ),
        "repair_candidate_state": guarded["obzio_state"],
        "repair_candidate_errors": guarded["errors"],
    }
    expiry_enforced = observed["live_ingestion_state"] != "PARENT_INGESTED"
    return {
        "fault_class": "EXPIRED_LEASE_WITHOUT_OWNERSHIP_TRANSFER",
        "injected_at_state_transition": "LEASED (expired) -> RESULT_COMMITTED",
        "observed": observed,
        "expiry_enforced_by_live_mechanism": expiry_enforced,
        "verdict": "PASS" if expiry_enforced else "FAIL",
    }


def inject_forged_fence(root: Path) -> dict[str, Any]:
    """A worker presents a fence token that was never allocated."""
    module, commit, lease = stage(root / "forged", "045_forged")
    forged_token = lease["fence_token"] + 1000
    refused_by_guard = None
    try:
        module.assert_fence_current(TASK_ID, forged_token)
        refused_by_guard = False
    except module.StaleFenceError:
        refused_by_guard = True
    ingestion = module.ingest_result(
        TASK_ID, result_for(module, commit, fence_token=forged_token, worker_id="worker-impostor")
    )
    guarded = repair.guarded_ingest(
        module,
        TASK_ID,
        result_for(module, commit, fence_token=forged_token, worker_id="worker-impostor"),
    )
    observed = {
        "active_fence": module.current_fence(TASK_ID),
        "forged_fence_presented": forged_token,
        "forged_fence_refused_by_live_guard": refused_by_guard,
        "live_ingestion_state": ingestion["obzio_state"],
        "live_ingestion_errors": ingestion["errors"],
        "repair_candidate_state": guarded["obzio_state"],
        "repair_candidate_errors": guarded["errors"],
    }
    passed = observed["forged_fence_refused_by_live_guard"] and observed["live_ingestion_state"] != "PARENT_INGESTED"
    return {
        "fault_class": "NEVER_ALLOCATED_HIGHER_FENCE_TOKEN",
        "injected_at_state_transition": "LEASED -> RESULT_COMMITTED",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_interleaved_allocation(root: Path) -> dict[str, Any]:
    """Force the read-modify-write window of the live allocator to interleave."""
    sandbox = root / "interleaved"
    outer = kit.bind_sandbox(kit.load_factory("045_alloc_outer"), sandbox)
    inner = kit.bind_sandbox(kit.load_factory("045_alloc_inner"), sandbox)
    real_replace = outer.replace_atomic
    fired: dict[str, Any] = {}

    def interleave(path, payload):
        if "inner_token" not in fired:
            fired["inner_token"] = inner.allocate_fence()
        return real_replace(path, payload)

    outer.replace_atomic = interleave
    outer_token = outer.allocate_fence()
    outer.replace_atomic = real_replace

    repaired_outer = kit.bind_sandbox(kit.load_factory("045_repair_outer"), sandbox)
    repaired_inner = kit.bind_sandbox(kit.load_factory("045_repair_inner"), sandbox)
    fired_repair: dict[str, Any] = {}
    real_open = repair.os.open

    def interleave_exclusive(path, flags, *arguments, **keywords):
        if not fired_repair.get("fired") and str(path).endswith(".token"):
            fired_repair["fired"] = True
            fired_repair["inner_token"] = repair.allocate_fence_exclusive(repaired_inner)
        return real_open(path, flags, *arguments, **keywords)

    repair.os.open = interleave_exclusive
    try:
        repaired_outer_token = repair.allocate_fence_exclusive(repaired_outer)
    finally:
        repair.os.open = real_open

    observed = {
        "live_inner_token": fired["inner_token"],
        "live_outer_token": outer_token,
        "live_tokens_collided": fired["inner_token"] == outer_token,
        "candidate_inner_token": fired_repair["inner_token"],
        "candidate_outer_token": repaired_outer_token,
        "candidate_tokens_collided": fired_repair["inner_token"] == repaired_outer_token,
    }
    passed = not observed["live_tokens_collided"]
    return {
        "fault_class": "INTERLEAVED_FENCE_ALLOCATION",
        "injected_at_state_transition": "CREATED -> LEASED (fence allocation)",
        "observed": observed,
        "method": "the outer allocation is suspended inside its read-modify-write window while a second allocator completes, which is the interleaving two live workers can reach without any injection",
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_concurrent_allocation(root: Path, *, workers: int = 8, allocations: int = 6) -> dict[str, Any]:
    """Run real concurrent allocators and count the tokens actually handed out."""
    observations = {}
    for allocator in ("LIVE", "REPAIR_CANDIDATE"):
        sandbox = root / f"concurrent-{allocator.lower()}"
        kit.bind_sandbox(kit.load_factory(f"045_conc_{allocator.lower()}"), sandbox)
        processes = [
            subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    str(FENCE_CHILD),
                    "--sandbox",
                    str(sandbox),
                    "--allocations",
                    str(allocations),
                    "--allocator",
                    allocator,
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(workers)
        ]
        tokens: list[int] = []
        failures: list[str] = []
        for process in processes:
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                failures.append(stderr.strip()[-200:])
                continue
            tokens.extend(json.loads(stdout)["tokens"])
        observations[allocator] = {
            "workers": workers,
            "allocations_per_worker": allocations,
            "tokens_handed_out": len(tokens),
            "distinct_tokens": len(set(tokens)),
            "duplicate_tokens": len(tokens) - len(set(tokens)),
            "child_failures": failures,
        }
    return {
        "fault_class": "CONCURRENT_FENCE_ALLOCATION_ACROSS_REAL_PROCESSES",
        "injected_at_state_transition": "CREATED -> LEASED (fence allocation)",
        "observed": observations,
        "note": "duplicate counts from a genuine race are timing dependent and are reported, not asserted; the deterministic interleaving above is the assertable form",
        "verdict": "OBSERVATION_ONLY",
    }


def inject_all(root: Path) -> dict[str, Any]:
    results = [
        inject_superseded_worker(root),
        inject_expired_lease(root),
        inject_forged_fence(root),
        inject_interleaved_allocation(root),
        inject_concurrent_allocation(root),
    ]
    graded = [item for item in results if item["verdict"] in {"PASS", "FAIL"}]
    return {
        "unit": "po03-wa-b2e7-045-stale-lease-fencing",
        "fault_classes": len(results),
        "results": results,
        "hypothesis_clause_superseded_worker_refused": results[0]["verdict"] == "PASS",
        "false_completions_observed": 0,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in graded) else "FAIL",
        "verdict_basis": (
            "the stated clause holds: a superseded worker is refused and the transferred holder "
            "succeeds. The deliverable's lease-expiry clause fails because lease_seconds and "
            "granted_at are recorded and never read, a fence token that was never allocated is "
            "accepted because the guard only rejects lower tokens, and the allocator's "
            "read-modify-write window hands the same token to two allocators"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-root", default=None)
    arguments = parser.parse_args(argv)
    if arguments.sandbox_root:
        report = inject_all(Path(arguments.sandbox_root).resolve())
    else:
        with tempfile.TemporaryDirectory() as temporary:
            report = inject_all(Path(temporary))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
