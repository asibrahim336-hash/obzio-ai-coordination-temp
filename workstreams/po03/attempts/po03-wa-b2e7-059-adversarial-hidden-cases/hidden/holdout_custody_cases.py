#!/usr/bin/env python3
"""Sealed holdout custody cases for generation measurement.

These cases are evaluator-held.  They are deliberately kept out of the
producer-visible public suite so that a generation cannot be tuned against them
while it is being built, and they are sealed by sha256 before any successor
source exists.

Provenance, stated plainly: the hazards were found by adversarial reading of the
committed factory source, not by reading any generation's test results.  Six of
the ten cases probe hazards that the public suite does not cover at all; four
probe invariants the current factory is expected to satisfy, so the holdout is
not a list of known failures.

Generation adapter contract (implemented by the generation runner in unit 061):

    generation.name              -> "G0" | "G1" | "G2"
    generation.instance()        -> Instance

    Instance.module              -> the generation module, freshly imported and
                                    bound to this instance's sandbox
    Instance.module_path         -> Path of the generation source inside the
                                    sandbox, so a child process can import the
                                    same module independently
    Instance.root                -> Path of a sandbox repository root that
                                    contains an initialised Git repository and a
                                    workstreams/po03 skeleton
    Instance.git(*args)          -> run git in the sandbox, returning stdout text
    Instance.commit_bytes(rel, data) -> commit the bytes at rel, returning the
                                    commit sha
    Instance.close()             -> remove the sandbox

Every case returns a record:

    {"outcome": "PASS" | "FAIL" | "UNSUPPORTED",
     "detail": str,
     "reports_success": bool | None,
     "invariant_held": bool | None}

``reports_success`` is what the generation claimed; ``invariant_held`` is what
independent verification inside the case observed.  A case where the generation
reports success while the invariant is violated is a false green.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HOLDOUT_SUITE_VERSION = "PO03-HOLDOUT-CUSTODY-CASES-v1"
HASH = "c" * 64


def _passed(detail: str) -> dict[str, Any]:
    return {"outcome": "PASS", "detail": detail, "reports_success": False, "invariant_held": True}


def _failed(detail: str, *, reports_success: bool = True) -> dict[str, Any]:
    return {
        "outcome": "FAIL",
        "detail": detail,
        "reports_success": reports_success,
        "invariant_held": False,
    }


def _unsupported(missing: list[str]) -> dict[str, Any]:
    return {
        "outcome": "UNSUPPORTED",
        "detail": f"generation does not expose {', '.join(missing)}",
        "reports_success": None,
        "invariant_held": None,
    }


def _missing(module, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not hasattr(module, name)]


def _acceptance() -> dict[str, Any]:
    return {"acceptance_version": "PO03-HOLDOUT-ACCEPTANCE-v1", "criteria": ["holdout"], "decision_changed": []}


def _make_capsule(module, task_id: str, *, fence_token: int = 1, result_slot: str | None = None) -> None:
    slot = result_slot or f"workstreams/po03/attempts/{task_id}"
    module.task_capsule(
        task_id=task_id,
        head_sha="0" * 40,
        run_id="holdout-run",
        model="holdout-model",
        reasoning="high",
        hypothesis="holdout hypothesis",
        prompt="holdout prompt",
        owned_paths=[f"{slot}/**"],
        result_slot=slot,
        acceptance=_acceptance(),
        lease_seconds=60,
        fence_token=fence_token,
    )


def _result_document(
    *,
    task_id: str,
    commit: str,
    path: str,
    sha256: str,
    size: int,
    fence_token: int = 1,
    worker_id: str = "holdout-worker",
    parent_ingested_at: str | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": task_id,
        "commission_id": "COM-PO03-HOLDOUT",
        "immutable_input_manifest_sha256": HASH,
        "acceptance_contract_sha256": HASH,
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_COMMITTED",
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": f"COM-PO03-HOLDOUT:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "fence_token": fence_token,
            "provider_run_id": "holdout-provider-run",
            "worker_id": worker_id,
            "heartbeat_at": "2026-08-22T07:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"result-{task_id}-1",
            "state": "COMMITTED",
            "manifest_uri": f"git:{commit}:{path}",
            "manifest_sha256": HASH,
            "artifact_count": 1,
            "total_bytes": size,
            "committed_at": "2026-08-22T07:01:00Z",
            "verified_at": "2026-08-22T07:01:00Z",
            "parent_ingested_at": parent_ingested_at,
            "result_commit_id": commit,
        },
        "artifacts": [
            {
                "artifact_id": f"{task_id}-artifact-001",
                "logical_name": Path(path).name,
                "content_uri": f"git:{commit}:{path}",
                "sha256": sha256,
                "bytes": size,
                "media_type": "text/plain",
                "readback_verified_at": "2026-08-22T07:01:00Z",
            }
        ],
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }


def _commit_artifact(instance, task_id: str) -> tuple[str, str, str, int]:
    """Commit a real artifact in the sandbox and return its durable coordinates."""
    import hashlib

    slot = f"workstreams/po03/attempts/{task_id}"
    relative = f"{slot}/artifact.txt"
    payload = f"holdout artifact for {task_id}\n".encode("utf-8")
    commit = instance.commit_bytes(relative, payload)
    return commit, relative, hashlib.sha256(payload).hexdigest(), len(payload)


# ---------------------------------------------------------------- H01


def case_completion_is_bound_to_the_ingested_result(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result", "complete_unit"))
        if missing:
            return _unsupported(missing)
        task_id = "holdout-completion-binding"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        ingested = _result_document(task_id=task_id, commit=commit, path=path, sha256=sha, size=size)
        ingestion = module.ingest_result(task_id, ingested)
        if ingestion["errors"]:
            return _failed(
                f"a valid result was refused at ingestion: {ingestion['errors']}", reports_success=False
            )
        never_ingested = _result_document(
            task_id=task_id,
            commit=commit,
            path=path,
            sha256=sha,
            size=size,
            worker_id="a-different-worker",
            parent_ingested_at="2026-08-22T07:05:00Z",
        )
        never_ingested["result_transaction"]["result_txn_id"] = f"result-{task_id}-substituted"
        try:
            completed = module.complete_unit(task_id, never_ingested)
        except Exception as exc:  # noqa: BLE001 - refusal is the desired behaviour
            return _passed(f"completion refused a document that was never ingested: {type(exc).__name__}: {exc}")
        if completed.get("obzio_state") == "COMPLETED":
            return _failed(
                "completion accepted a substituted result document that was never ingested; the "
                "gate only checks that some PARENT_INGESTED event exists for the task"
            )
        return _passed("completion did not reach COMPLETED for a substituted document")
    finally:
        instance.close()


# ---------------------------------------------------------------- H02

_CHILD_ALLOCATOR = """
import importlib.util, json, os, sys, time
from pathlib import Path
module_path, barrier, out, rounds = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
spec = importlib.util.spec_from_file_location("gen_child", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
deadline = time.time() + 30
while not os.path.exists(barrier) and time.time() < deadline:
    time.sleep(0.001)
tokens = []
for _ in range(rounds):
    tokens.append(module.allocate_fence())
Path(out).write_text(json.dumps(tokens), encoding="utf-8")
"""


def case_fence_allocation_is_monotonic_under_concurrency(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("allocate_fence",))
        if missing:
            return _unsupported(missing)
        workers = 8
        rounds = 6
        child = instance.root / "_child_allocator.py"
        child.write_text(_CHILD_ALLOCATOR, encoding="utf-8")
        barrier = instance.root / "_barrier"
        outputs = [instance.root / f"_tokens-{index}.json" for index in range(workers)]
        processes = [
            subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-B",
                    str(child),
                    str(instance.module_path),
                    str(barrier),
                    str(output),
                    str(rounds),
                ),
                cwd=instance.root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            for output in outputs
        ]
        time.sleep(0.4)
        barrier.write_text("go", encoding="utf-8")
        errors = []
        for process in processes:
            _, stderr = process.communicate(timeout=120)
            if process.returncode != 0:
                errors.append(stderr.decode("utf-8", "replace").strip().splitlines()[-1:])
        tokens: list[int] = []
        for output in outputs:
            if output.is_file():
                tokens.extend(json.loads(output.read_text(encoding="utf-8")))
        expected = workers * rounds
        duplicates = len(tokens) - len(set(tokens))
        counter = instance.root / "workstreams/po03/control/fence-counter.json"
        final = json.loads(counter.read_text(encoding="utf-8"))["fence_token"] if counter.is_file() else None
        if errors and not tokens:
            return _failed(f"concurrent allocation crashed in every worker: {errors}", reports_success=False)
        if duplicates == 0 and final == expected and len(tokens) == expected:
            return _passed(
                f"{expected} concurrent allocations produced {expected} distinct tokens and a final "
                f"counter of {final}"
            )
        return _failed(
            f"{len(tokens)} allocations returned {duplicates} duplicate tokens and left the counter at "
            f"{final} instead of {expected}: the read-modify-write of the fence counter is not atomic"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H03


def case_ingestion_rejects_a_result_for_a_different_task(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result"))
        if missing:
            return _unsupported(missing)
        owner = "holdout-owner-unit"
        foreign = "holdout-foreign-unit"
        _make_capsule(module, owner)
        _make_capsule(module, foreign)
        commit, path, sha, size = _commit_artifact(instance, foreign)
        document = _result_document(task_id=foreign, commit=commit, path=path, sha256=sha, size=size)
        ingestion = module.ingest_result(owner, document)
        if ingestion["errors"]:
            return _passed(
                f"ingestion refused a result whose task_id is {foreign} under custody of {owner}: "
                f"{ingestion['errors']}"
            )
        return _failed(
            f"ingestion accepted a result document for {foreign} as the result of {owner}; the "
            f"document task_id is never compared with the custody task_id"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H04


def case_recovery_state_reports_real_collision_count(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("scan_recovery",))
        if missing:
            return _unsupported(missing)
        ownership = {
            "ownership_version": "PO03-PATH-OWNERSHIP-v1",
            "controller": {"run_id": "holdout-run", "owned_paths": ["workstreams/po03/control/**"]},
            "subordinates": [
                {
                    "task_id": "holdout-unit-a",
                    "provider_run_id": "x",
                    "owned_paths": ["workstreams/po03/attempts/shared/**"],
                    "fence_token": 1,
                },
                {
                    "task_id": "holdout-unit-b",
                    "provider_run_id": "y",
                    "owned_paths": ["workstreams/po03/attempts/shared/inner/**"],
                    "fence_token": 2,
                },
            ],
            "collision_policy": "FAIL_CLOSED",
            "decision_changed": [],
        }
        control = instance.root / "workstreams/po03/control"
        control.mkdir(parents=True, exist_ok=True)
        (control / "path-ownership.json").write_bytes(module.canonical_json(ownership))
        _make_capsule(module, "holdout-unit-a", result_slot="workstreams/po03/attempts/shared")
        state = module.scan_recovery("holdout-run", "0" * 40)
        reported = state.get("collision_count")
        if reported and reported > 0:
            return _passed(f"recovery state reported {reported} path collisions from the ownership record")
        return _failed(
            f"recovery state reported collision_count={reported!r} while two registered subordinates "
            f"claim overlapping owned paths; the field is asserted rather than computed"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H05


def case_event_chain_detects_truncation_of_the_latest_event(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("hash_chain_event", "verify_chain"))
        if missing:
            return _unsupported(missing)
        task_id = "holdout-truncation"
        for state in ("LEASED", "RUNNING", "CHECKPOINTED"):
            module.hash_chain_event(task_id, state, actor="holdout-controller", details={"state": state})
        events = sorted((instance.root / "workstreams/po03/control/events" / task_id).glob("*.json"))
        if len(events) != 3:
            return _failed(f"expected three events before truncation, observed {len(events)}", reports_success=False)
        before = module.verify_chain(task_id)
        if before:
            return _failed(f"an untampered chain was reported invalid: {before}", reports_success=False)
        events[-1].unlink()
        after = module.verify_chain(task_id)
        if after:
            return _passed(f"chain verification detected the removal of the latest event: {after}")
        return _failed(
            "the latest event was deleted and chain verification still reported the chain valid; "
            "verification walks only the files that remain, so truncation is invisible"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H06


def case_artifact_locator_must_name_an_immutable_object(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result"))
        if missing:
            return _unsupported(missing)
        task_id = "holdout-mutable-locator"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(task_id=task_id, commit=commit, path=path, sha256=sha, size=size)
        # HEAD is a mutable reference: the bytes it names can change after ingestion.
        document["artifacts"][0]["content_uri"] = f"git:HEAD:{path}"
        ingestion = module.ingest_result(task_id, document)
        if ingestion["errors"]:
            return _passed(f"ingestion refused a mutable-reference locator: {ingestion['errors']}")
        return _failed(
            "ingestion accepted git:HEAD as a durable artifact locator and recorded the unit as "
            "PARENT_INGESTED; a later commit silently changes the bytes the receipt points at"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H07


def case_ingestion_detects_artifact_byte_disagreement(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result"))
        if missing:
            return _unsupported(missing)
        task_id = "holdout-byte-disagreement"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(task_id=task_id, commit=commit, path=path, sha256="d" * 64, size=size)
        ingestion = module.ingest_result(task_id, document)
        if ingestion["errors"] and ingestion["obzio_state"] != "PARENT_INGESTED":
            return _passed(f"ingestion detected the digest disagreement and refused: {ingestion['errors']}")
        return _failed(
            f"ingestion accepted a result whose recorded digest does not match the committed bytes "
            f"(state {ingestion.get('obzio_state')})"
        )
    finally:
        instance.close()


# ---------------------------------------------------------------- H08


def case_completion_refuses_a_contract_invalid_document(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule", "ingest_result", "complete_unit"))
        if missing:
            return _unsupported(missing)
        task_id = "holdout-invalid-completion"
        _make_capsule(module, task_id)
        commit, path, sha, size = _commit_artifact(instance, task_id)
        document = _result_document(task_id=task_id, commit=commit, path=path, sha256=sha, size=size)
        ingestion = module.ingest_result(task_id, document)
        if ingestion["errors"]:
            return _failed(f"a valid result was refused at ingestion: {ingestion['errors']}", reports_success=False)
        broken = json.loads(json.dumps(document))
        del broken["result_transaction"]["result_commit_id"]
        try:
            module.complete_unit(task_id, broken)
        except Exception as exc:  # noqa: BLE001
            return _passed(f"completion refused a contract-invalid document: {type(exc).__name__}")
        return _failed("completion accepted a document that the result contract rejects")
    finally:
        instance.close()


# ---------------------------------------------------------------- H09


def case_capsule_refuses_foreign_owned_paths(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("task_capsule",))
        if missing:
            return _unsupported(missing)
        try:
            module.task_capsule(
                task_id="holdout-foreign-ownership",
                head_sha="0" * 40,
                run_id="holdout-run",
                model="holdout-model",
                reasoning="high",
                hypothesis="holdout hypothesis",
                prompt="holdout prompt",
                owned_paths=["packs/operator-packs-v1/**"],
                result_slot="packs/operator-packs-v1",
                acceptance=_acceptance(),
                lease_seconds=60,
                fence_token=1,
            )
        except ValueError as exc:
            return _passed(f"capsule creation refused ownership of a path outside PO-03: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _failed(f"capsule creation failed for the wrong reason: {type(exc).__name__}: {exc}")
        return _failed("a capsule was created that claims ownership of a path outside PO-03")
    finally:
        instance.close()


# ---------------------------------------------------------------- H10

_CHILD_APPENDER = """
import importlib.util, sys
module_path, worker, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
spec = importlib.util.spec_from_file_location("gen_child", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for index in range(rounds):
    module.append_registry({"worker": worker, "index": index, "payload": "x" * 200})
"""


def case_registry_append_survives_concurrent_appenders(generation) -> dict[str, Any]:
    instance = generation.instance()
    try:
        module = instance.module
        missing = _missing(module, ("append_registry",))
        if missing:
            return _unsupported(missing)
        workers = 8
        rounds = 10
        child = instance.root / "_child_appender.py"
        child.write_text(_CHILD_APPENDER, encoding="utf-8")
        processes = [
            subprocess.Popen(
                (sys.executable, "-I", "-B", str(child), str(instance.module_path), f"worker-{index}", str(rounds)),
                cwd=instance.root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            for index in range(workers)
        ]
        failures = []
        for process in processes:
            _, stderr = process.communicate(timeout=120)
            if process.returncode != 0:
                failures.append(stderr.decode("utf-8", "replace").strip().splitlines()[-1:])
        registry = instance.root / "workstreams/po03/control/work-unit-registry.jsonl"
        if not registry.is_file():
            return _failed(f"no registry file was written; worker failures: {failures}", reports_success=False)
        lines = [line for line in registry.read_text(encoding="utf-8").splitlines() if line.strip()]
        parsed = 0
        for line in lines:
            try:
                json.loads(line)
                parsed += 1
            except json.JSONDecodeError:
                pass
        expected = workers * rounds
        if parsed == expected and len(lines) == expected:
            return _passed(f"{expected} concurrent registry appends produced {parsed} intact JSON lines")
        return _failed(
            f"{expected} concurrent appends produced {len(lines)} lines of which {parsed} parse; "
            f"append-only durability is not preserved under contention"
        )
    finally:
        instance.close()


HOLDOUT_CASES: dict[str, dict[str, Any]] = {
    "H01-completion-bound-to-ingested-result": {
        "case": case_completion_is_bound_to_the_ingested_result,
        "hazard": "a substituted result document is completed because completion checks only that the task was ingested once",
        "public_suite_covers": False,
    },
    "H02-fence-monotonic-under-concurrency": {
        "case": case_fence_allocation_is_monotonic_under_concurrency,
        "hazard": "a non-atomic read-modify-write of the fence counter issues the same token twice",
        "public_suite_covers": False,
    },
    "H03-ingestion-rejects-foreign-task-result": {
        "case": case_ingestion_rejects_a_result_for_a_different_task,
        "hazard": "a result produced for one unit is ingested as the result of another",
        "public_suite_covers": False,
    },
    "H04-recovery-reports-real-collision-count": {
        "case": case_recovery_state_reports_real_collision_count,
        "hazard": "recovery state asserts zero path collisions instead of computing them",
        "public_suite_covers": False,
    },
    "H05-chain-detects-truncation": {
        "case": case_event_chain_detects_truncation_of_the_latest_event,
        "hazard": "deleting the newest event leaves a chain that still verifies",
        "public_suite_covers": False,
    },
    "H06-locator-must-be-immutable": {
        "case": case_artifact_locator_must_name_an_immutable_object,
        "hazard": "a mutable ref is accepted as a durable artifact locator",
        "public_suite_covers": False,
    },
    "H07-ingestion-detects-byte-disagreement": {
        "case": case_ingestion_detects_artifact_byte_disagreement,
        "hazard": "a recorded digest that disagrees with committed bytes is ingested",
        "public_suite_covers": True,
    },
    "H08-completion-refuses-invalid-document": {
        "case": case_completion_refuses_a_contract_invalid_document,
        "hazard": "completion is recorded for a document the contract rejects",
        "public_suite_covers": True,
    },
    "H09-capsule-refuses-foreign-owned-paths": {
        "case": case_capsule_refuses_foreign_owned_paths,
        "hazard": "a task capsule claims ownership of a path outside the commission",
        "public_suite_covers": True,
    },
    "H10-registry-append-under-concurrency": {
        "case": case_registry_append_survives_concurrent_appenders,
        "hazard": "concurrent registry appends interleave and corrupt lines",
        "public_suite_covers": True,
    },
}
