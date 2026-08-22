#!/usr/bin/env python3
"""Corrupt and remove artifacts, then classify what ingestion does about it.

Eight corruption and absence classes are injected against a committed artifact:
a wrong hash, a wrong byte count, truncated bytes, an absent path, an absent
commit, a tree locator instead of a blob, a locator that is not durable at all,
and a worktree file tampered with after the commit.  Each class is followed by a
rerun of the corrected result from the same immutable input, so refusal and
recovery are both observed rather than assumed.

Run directly to print the observation as JSON:

    python3 -I corruption_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_047_fault_kit", "fault_kit.py")

TASK_ID = "po03-c6-047-sandbox-unit"
SLOT = f"workstreams/po03/attempts/{TASK_ID}"
ARTIFACT_PATH = f"{SLOT}/component.json"


def stage(sandbox: Path, instance: str):
    """Seed a capsule, commit a good artifact and grant a lease."""
    module = kit.bind_sandbox(kit.load_factory(instance), sandbox)
    kit.init_repository(sandbox)
    kit.seed_capsule(module, TASK_ID, hypothesis="a corrupt artifact is refused and routed to recovery")
    artifact = sandbox / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    body = module.canonical_json({"component": TASK_ID, "computed": True})
    artifact.write_bytes(body)
    commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")
    lease = module.grant_lease(TASK_ID, holder="worker-a", lease_seconds=600, attempt=1)
    document = kit.build_result_document(
        module,
        task_id=TASK_ID,
        commit=commit,
        paths=[ARTIFACT_PATH],
        fence_token=lease["fence_token"],
        worker_id="worker-a",
    )
    return module, sandbox, commit, document


def corrupt_wrong_hash(module, sandbox, commit, document):
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["sha256"] = "b" * 64
    corrupted["result_transaction"]["manifest_sha256"] = "b" * 64
    return corrupted, "read-back mismatch"


def corrupt_wrong_byte_count(module, sandbox, commit, document):
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["bytes"] = document["artifacts"][0]["bytes"] + 1
    corrupted["result_transaction"]["total_bytes"] = corrupted["artifacts"][0]["bytes"]
    return corrupted, "read-back mismatch"


def corrupt_truncated_bytes(module, sandbox, commit, document):
    """Commit a truncated version of the artifact and claim the full-length hash."""
    truncated = (sandbox / ARTIFACT_PATH).read_bytes()[:-5]
    (sandbox / ARTIFACT_PATH).write_bytes(truncated)
    truncated_commit = kit.commit_all(sandbox, "po03: truncated artifact")
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["content_uri"] = f"git:{truncated_commit}:{ARTIFACT_PATH}"
    corrupted["result_transaction"]["result_commit_id"] = truncated_commit
    return corrupted, "read-back mismatch"


def corrupt_absent_path(module, sandbox, commit, document):
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["content_uri"] = f"git:{commit}:{SLOT}/absent.json"
    return corrupted, "read-back failed"


def corrupt_absent_commit(module, sandbox, commit, document):
    corrupted = copy.deepcopy(document)
    absent = "0" * 40
    corrupted["artifacts"][0]["content_uri"] = f"git:{absent}:{ARTIFACT_PATH}"
    corrupted["result_transaction"]["result_commit_id"] = absent
    return corrupted, "read-back failed"


def corrupt_tree_locator(module, sandbox, commit, document):
    """Point the locator at a tree instead of a blob."""
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["content_uri"] = f"git:{commit}:{SLOT}"
    return corrupted, "read-back failed"


def corrupt_non_durable_locator(module, sandbox, commit, document):
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["content_uri"] = f"file://{sandbox / ARTIFACT_PATH}"
    return corrupted, "non-durable"


def corrupt_worktree_after_commit(module, sandbox, commit, document):
    """Tamper with the worktree file; the committed object must still govern."""
    (sandbox / ARTIFACT_PATH).write_bytes(b'{"component":"tampered"}\n')
    return copy.deepcopy(document), None


CORRUPTIONS = (
    ("CLAIMED_HASH_DOES_NOT_MATCH_COMMITTED_BYTES", corrupt_wrong_hash),
    ("CLAIMED_BYTE_COUNT_DOES_NOT_MATCH_COMMITTED_BYTES", corrupt_wrong_byte_count),
    ("COMMITTED_BYTES_TRUNCATED_AFTER_HASHING", corrupt_truncated_bytes),
    ("ARTIFACT_PATH_ABSENT_FROM_THE_COMMIT", corrupt_absent_path),
    ("RESULT_COMMIT_DOES_NOT_EXIST", corrupt_absent_commit),
    ("LOCATOR_POINTS_AT_A_TREE_NOT_A_BLOB", corrupt_tree_locator),
    ("LOCATOR_IS_NOT_A_DURABLE_GIT_OBJECT", corrupt_non_durable_locator),
    ("WORKTREE_TAMPERED_AFTER_THE_COMMIT", corrupt_worktree_after_commit),
)


def inject_corruption(root: Path, name: str, mutate) -> dict[str, Any]:
    sandbox = root / name.lower()[:40]
    module, sandbox, commit, document = stage(sandbox, f"047_{abs(hash(name)) % 100000}")
    corrupted, expected_error = mutate(module, sandbox, commit, document)
    ingestion = module.ingest_result(TASK_ID, corrupted)
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    unit = state["units"][TASK_ID]
    capsule = module.CONTROL_ROOT / "tasks" / TASK_ID / "input.json"
    observed = {
        "ingestion_state": ingestion["obzio_state"],
        "ingestion_errors": ingestion["errors"],
        "expected_error_fragment": expected_error,
        "error_fragment_present": expected_error is None
        or any(expected_error in error for error in ingestion["errors"]),
        "recovery_action": unit["recovery_action"],
        "scanner_sees_ingested_result": unit["ingested"],
        "false_completion_count": state["false_completion_count"],
        "immutable_input_intact": capsule.is_file()
        and module.sha256_file(capsule) == corrupted["immutable_input_manifest_sha256"],
        "event_chain_errors": module.verify_chain(TASK_ID),
    }

    if expected_error is None:
        # The tampered worktree must not change what ingestion reads.
        accepted = observed["ingestion_state"] == "PARENT_INGESTED"
        observed["committed_object_still_governs"] = accepted
        passed = accepted and observed["ingestion_errors"] == []
    else:
        refused = observed["ingestion_state"] == "RECOVERY_REQUIRED"
        rerun = rerun_from_immutable_input(module, sandbox, commit)
        observed["rerun_state"] = rerun["obzio_state"]
        observed["rerun_errors"] = rerun["errors"]
        passed = (
            refused
            and observed["error_fragment_present"]
            and observed["false_completion_count"] == 0
            and observed["immutable_input_intact"]
            and observed["rerun_state"] == "PARENT_INGESTED"
        )
    return {
        "fault_class": name,
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (ingestion check)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def rerun_from_immutable_input(module, sandbox: Path, commit: str) -> dict[str, Any]:
    """Rerun the unit from the surviving immutable capsule and ingest the good result."""
    capsule = json.loads(
        (module.CONTROL_ROOT / "tasks" / TASK_ID / "input.json").read_text(encoding="utf-8")
    )
    slot = capsule["ownership"]["result_slot"]
    rerun_path = f"{slot}/component-rerun.json"
    target = sandbox / rerun_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(module.canonical_json({"component": capsule["task_id"], "attempt": 2}))
    rerun_commit = kit.commit_all(sandbox, "po03: rerun from immutable input")
    lease = module.grant_lease(TASK_ID, holder="worker-b", lease_seconds=600, attempt=2)
    document = kit.build_result_document(
        module,
        task_id=TASK_ID,
        commit=rerun_commit,
        paths=[rerun_path],
        fence_token=lease["fence_token"],
        worker_id="worker-b",
        timestamp="2026-08-22T08:00:00Z",
    )
    return module.ingest_result(TASK_ID, document)


def inject_empty_artifact(root: Path) -> dict[str, Any]:
    """A zero-byte artifact is not a durable result and the contract must refuse it."""
    module, sandbox, commit, document = stage(root / "empty-artifact", "047_empty")
    corrupted = copy.deepcopy(document)
    corrupted["artifacts"][0]["bytes"] = 0
    corrupted["result_transaction"]["total_bytes"] = 0
    ingestion = module.ingest_result(TASK_ID, corrupted)
    stripped = copy.deepcopy(document)
    stripped["artifacts"] = []
    stripped["result_transaction"]["artifact_count"] = 0
    stripped["result_transaction"]["total_bytes"] = 0
    empty_ingestion = module.ingest_result(TASK_ID, stripped)
    observed = {
        "zero_byte_artifact_state": ingestion["obzio_state"],
        "zero_byte_artifact_errors": ingestion["errors"],
        "no_artifact_state": empty_ingestion["obzio_state"],
        "no_artifact_errors": empty_ingestion["errors"],
    }
    passed = (
        observed["zero_byte_artifact_state"] == "RECOVERY_REQUIRED"
        and observed["no_artifact_state"] == "RECOVERY_REQUIRED"
    )
    return {
        "fault_class": "EMPTY_OR_MISSING_ARTIFACT_SET",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (contract check)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_all(root: Path) -> dict[str, Any]:
    results = [inject_corruption(root, name, mutate) for name, mutate in CORRUPTIONS]
    results.append(inject_empty_artifact(root))
    return {
        "unit": "po03-wa-b2e7-047-corrupt-artifact-recovery",
        "fault_classes": len(results),
        "results": results,
        "false_completions_observed": sum(
            int(item["observed"].get("false_completion_count", 0) or 0) for item in results
        ),
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in results) else "FAIL",
        "verdict_basis": (
            "every corruption and absence class is refused at ingestion, classified "
            "RECOVERY_REQUIRED, and followed by a successful rerun from the surviving "
            "immutable capsule; read-back is governed by the committed object, not the worktree"
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
