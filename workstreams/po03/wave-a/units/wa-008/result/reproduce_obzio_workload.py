#!/usr/bin/env python3
"""Sanitized repository-native reproduction for PO03-WA-008.

The fixture matrix proves the detector on synthetic repositories. This script
applies the same runner to real, in-scope PO-03 workloads at an immutable commit
of this repository, so the mechanism is exercised on an Obzio workload rather
than only on its own fixtures.

Scenarios:

``S1`` seeded PO-03 contract test suite, warm checkout carrying naturally
     generated Python bytecode caches. Expected: no hidden-state dependency,
     with the warm-cache class observed as present but not outcome-relevant.
``S2`` seeded contract validator invoked on a sanitized transactional-result
     document that exists only as an untracked file in the warm checkout.
     Expected: attribution to ``UNTRACKED_FILE_DEPENDENCY`` — the shape of a
     false-green "it validated on my machine" claim.
``S3`` repository taxonomy gate ``scripts/check_operator_taxonomy.py``.
     Expected: no hidden-state dependency.

Every scenario runs inside temporary directories, uses only committed repository
content plus a synthetic non-secret document, and causes no external effect.

    python3 reproduce_obzio_workload.py --commit <sha> --json reproduction-result.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from differential_run import (  # noqa: E402
    CLASS_ENVIRONMENT,
    CLASS_UNTRACKED,
    CLASS_WARM_CACHE,
    VERDICT_ATTRIBUTED,
    VERDICT_CLEAN,
    DifferentialRun,
    GlobSet,
    DEFAULT_CACHE_GLOBS,
    inventory_worktree_extras,
    materialise_clean_checkout,
    run_git,
    sanitised_environment,
    tracked_paths,
)

REPRODUCTION_PROTOCOL_VERSION = "OBZIO-WA-008-REPRODUCTION-v1"
REPRODUCTION_ID = "R-PO03-WA-008-001"

SEED_TEST_COMMAND = ["-m", "unittest", "-v", "workstreams.po03.tests.test_validate_contracts"]
SEED_TEST_PATH = "workstreams/po03/tests/test_validate_contracts.py"
VALIDATOR_PATH = "workstreams/po03/tools/validate_contracts.py"
TAXONOMY_PATH = "scripts/check_operator_taxonomy.py"

SANITIZED_HASH = "a" * 64

# Structurally valid transactional result carrying no real identifiers, hashes
# or secrets. Its only purpose is to give the seeded validator something to
# accept when it is present.
SANITIZED_RESULT_DOCUMENT = {
    "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
    "task_id": "po03-wa-008-sanitized-probe",
    "commission_id": "COM-PO03-SANITIZED-PROBE",
    "immutable_input_manifest_sha256": SANITIZED_HASH,
    "acceptance_contract_sha256": SANITIZED_HASH,
    "provider_state": "COMPLETED",
    "obzio_state": "COMPLETED",
    "attempt": {
        "attempt_id": "sanitized-attempt-1",
        "idempotency_key": "po03-wa-008-sanitized-probe:1",
        "lease_id": "sanitized-lease-1",
        "fence_token": 1,
        "provider_run_id": "sanitized-run-1",
        "worker_id": "sanitized-producer-1",
        "heartbeat_at": "2026-08-22T00:00:00Z",
        "checkpoint_seq": 1,
    },
    "result_transaction": {
        "result_txn_id": "sanitized-txn-1",
        "state": "INGESTED",
        "manifest_uri": "git:sanitized@0000000:manifest.json",
        "manifest_sha256": SANITIZED_HASH,
        "artifact_count": 1,
        "total_bytes": 7,
        "committed_at": "2026-08-22T00:01:00Z",
        "verified_at": "2026-08-22T00:02:00Z",
        "parent_ingested_at": "2026-08-22T00:03:00Z",
        "result_commit_id": "0000000",
    },
    "artifacts": [
        {
            "artifact_id": "sanitized-artifact-1",
            "logical_name": "result.json",
            "content_uri": "git:sanitized@0000000:result.json",
            "sha256": SANITIZED_HASH,
            "bytes": 7,
            "media_type": "application/json",
            "readback_verified_at": "2026-08-22T00:02:00Z",
        }
    ],
    "completion_actor": "coordinator",
    "independent_acceptance": {
        "state": "ACCEPTED",
        "reviewer_id": "sanitized-reviewer-2",
        "receipt_uri": "git:sanitized-review@0000000:receipt.json",
    },
}


def repo_root(start: Path) -> Path:
    return Path(
        run_git(["rev-parse", "--show-toplevel"], cwd=start).stdout.strip()
    ).resolve()


def prepare_warm(repo: Path, commit: str, base: Path):
    warm = base / "warm-checkout"
    home = base / "warm-home"
    tmp = base / "warm-tmp"
    cache = base / "warm-cache"
    materialise_clean_checkout(repo, commit, warm)
    env = sanitised_environment(home, tmp, cache)
    return warm, env, cache


def scenario_seeded_tests(repo: Path, commit: str, base: Path) -> dict:
    warm, env, cache = prepare_warm(repo, commit, base)
    # Generate the warm cache the way a real session does: by running once.
    subprocess.run(
        [sys.executable, *SEED_TEST_COMMAND], cwd=str(warm), env=env, capture_output=True, text=True
    )
    tracked = tracked_paths(repo, commit)
    _, cache_records = inventory_worktree_extras(warm, tracked, GlobSet(DEFAULT_CACHE_GLOBS))
    runner = DifferentialRun(
        repo=repo,
        commit=commit,
        command=[sys.executable, *SEED_TEST_COMMAND],
        warm_checkout=warm,
        warm_env=env,
        warm_cache_root=cache,
        repeats=2,
    )
    try:
        report = runner.execute()
    finally:
        runner.cleanup()
    return {
        "scenario_id": "S1",
        "workload": "seeded PO-03 transactional contract test suite",
        "workload_paths": [SEED_TEST_PATH, VALIDATOR_PATH],
        "expected_verdict": VERDICT_CLEAN,
        "expected_classes": [],
        "naturally_generated_cache_file_count": len(cache_records),
        "naturally_generated_cache_examples": [
            record["path"] for record in cache_records[:5]
        ],
        "report": report,
    }


def scenario_untracked_validator_input(repo: Path, commit: str, base: Path) -> dict:
    warm, env, cache = prepare_warm(repo, commit, base)
    document = warm / "sanitized-candidate-result.json"
    document.write_text(
        json.dumps(SANITIZED_RESULT_DOCUMENT, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runner = DifferentialRun(
        repo=repo,
        commit=commit,
        command=[
            sys.executable,
            VALIDATOR_PATH,
            "result",
            "sanitized-candidate-result.json",
        ],
        warm_checkout=warm,
        warm_env=env,
        warm_cache_root=cache,
        repeats=2,
    )
    try:
        report = runner.execute()
    finally:
        runner.cleanup()
    return {
        "scenario_id": "S2",
        "workload": "seeded contract validator on an untracked candidate document",
        "workload_paths": [VALIDATOR_PATH],
        "expected_verdict": VERDICT_ATTRIBUTED,
        "expected_classes": [CLASS_UNTRACKED],
        "sanitized_document": "sanitized-candidate-result.json",
        "report": report,
    }


def scenario_taxonomy_gate(repo: Path, commit: str, base: Path) -> dict:
    warm, env, cache = prepare_warm(repo, commit, base)
    runner = DifferentialRun(
        repo=repo,
        commit=commit,
        command=[sys.executable, TAXONOMY_PATH],
        warm_checkout=warm,
        warm_env=env,
        warm_cache_root=cache,
        repeats=2,
    )
    try:
        report = runner.execute()
    finally:
        runner.cleanup()
    return {
        "scenario_id": "S3",
        "workload": "repository operator-taxonomy gate",
        "workload_paths": [TAXONOMY_PATH],
        "expected_verdict": VERDICT_CLEAN,
        "expected_classes": [],
        "report": report,
    }


def observe_checkout(path: Path, repo: Path, commit: str) -> dict:
    """Read-only hidden-state census of an existing checkout.

    Used to record, without executing anything there, whether a live checkout
    already carries working-tree state absent from the commit it claims.
    """
    tracked = tracked_paths(repo, commit)
    untracked, cache = inventory_worktree_extras(path, tracked, GlobSet(DEFAULT_CACHE_GLOBS))
    return {
        "checkout": str(path),
        "commit_compared": commit,
        "untracked_file_count": len(untracked),
        "cache_file_count": len(cache),
        "cache_top_level_directories": sorted(
            {record["path"].split("/")[0] for record in cache}
        )[:10],
        "class_present": {
            CLASS_UNTRACKED: bool(untracked),
            CLASS_WARM_CACHE: bool(cache),
            CLASS_ENVIRONMENT: "NOT_MEASURED_NO_EXECUTION_IN_THIS_CHECKOUT",
        },
        "method": "read-only os.walk plus git ls-tree; nothing was written or executed here",
    }


def evaluate(scenario: dict) -> dict:
    report = scenario["report"]
    checks = []

    def record(name, passed, detail):
        checks.append({"check": name, "outcome": "PASS" if passed else "FAIL", "detail": detail})

    record(
        "verdict_matches_frozen_expectation",
        report["verdict"] == scenario["expected_verdict"],
        "expected {} observed {}".format(scenario["expected_verdict"], report["verdict"]),
    )
    record(
        "classes_match_frozen_expectation",
        sorted(report["attributed_classes"]) == sorted(scenario["expected_classes"]),
        "expected {} observed {}".format(
            sorted(scenario["expected_classes"]), sorted(report["attributed_classes"])
        ),
    )
    record(
        "both_sides_deterministic",
        report["warm"]["deterministic"] and report["clean"]["deterministic"],
        "warm={} clean={}".format(report["warm"]["deterministic"], report["clean"]["deterministic"]),
    )
    return {
        "scenario_id": scenario["scenario_id"],
        "workload": scenario["workload"],
        "workload_paths": scenario["workload_paths"],
        "expected_verdict": scenario["expected_verdict"],
        "observed_verdict": report["verdict"],
        "expected_classes": sorted(scenario["expected_classes"]),
        "observed_classes": sorted(report["attributed_classes"]),
        "warm_exit_code": report["warm"]["exit_code"],
        "clean_exit_code": report["clean"]["exit_code"],
        "class_present": report["hidden_state_inventory"]["class_present"],
        "classification_digest": report["classification_digest"],
        "naturally_generated_cache_file_count": scenario.get(
            "naturally_generated_cache_file_count"
        ),
        "naturally_generated_cache_examples": scenario.get("naturally_generated_cache_examples"),
        "sanitized_document": scenario.get("sanitized_document"),
        "checks": checks,
        "outcome": "PASS" if all(check["outcome"] == "PASS" for check in checks) else "FAIL",
    }


SCENARIOS = (
    ("S1", scenario_seeded_tests),
    ("S2", scenario_untracked_validator_input),
    ("S3", scenario_taxonomy_gate),
)


def run(repo: Path, commit: str, observe=None) -> dict:
    root = Path(tempfile.mkdtemp(prefix="po03-wa-008-reproduction-")).resolve()
    scenarios = []
    try:
        for scenario_id, builder in SCENARIOS:
            base = root / scenario_id
            base.mkdir(parents=True, exist_ok=True)
            scenarios.append(evaluate(builder(repo, commit, base)))
        observations = [observe_checkout(Path(item), repo, commit) for item in (observe or [])]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if observations:
        # Live-checkout observations name a runtime location and therefore do not
        # reproduce from an arbitrary clean clone; they are kept in a separate
        # artifact so the reproduction result stays clean-clone reproducible.
        Path("live-checkout-census.json").write_text(
            json.dumps(
                {
                    "protocol_version": "OBZIO-WA-008-LIVE-CENSUS-v1",
                    "task_id": "PO03-WA-008",
                    "commit_compared": commit,
                    "observations": observations,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "protocol_version": REPRODUCTION_PROTOCOL_VERSION,
        "reproduction_id": REPRODUCTION_ID,
        "task_id": "PO03-WA-008",
        "hypothesis_id": "H-PO03-WA-008",
        "repository_commit": commit,
        "python": sys.version.split()[0],
        "git": run_git(["--version"]).stdout.strip(),
        "scenario_count": len(scenarios),
        "outcome": "PASS" if all(row["outcome"] == "PASS" for row in scenarios) else "FAIL",
        "scenarios": scenarios,
        "live_checkout_census_artifact": "live-checkout-census.json" if observations else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the PO03-WA-008 repository-native reproduction.")
    parser.add_argument("--repo", default=None, help="repository root; defaults to the containing repo")
    parser.add_argument("--commit", default="HEAD", help="immutable commit to reproduce against")
    parser.add_argument(
        "--observe-checkout",
        action="append",
        default=None,
        help="existing checkout to census read-only (no execution, no writes)",
    )
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve() if args.repo else repo_root(Path(__file__).resolve().parent)
    commit = run_git(["rev-parse", args.commit], cwd=repo).stdout.strip()
    summary = run(repo, commit, observe=args.observe_checkout)
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.json_path:
        Path(args.json_path).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if summary["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
