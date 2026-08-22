#!/usr/bin/env python3
"""Frozen, target-agnostic PO-03 Wave A challenger rubric."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


RECOMMEND_ACCEPT = "RECOMMEND_ACCEPT"
RECOMMEND_REJECT = "RECOMMEND_REJECT"
RETEST = "RETEST"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_repo_path(repo: Path, uri: str) -> Path:
    if not isinstance(uri, str) or not uri or "://" in uri:
        raise ValueError(f"not a repository-relative URI: {uri!r}")
    candidate = (repo / uri).resolve()
    candidate.relative_to(repo.resolve())
    return candidate


def check_frozen_inputs(
    repo: Path,
    rubric: dict[str, Any],
    task_input_path: Path,
    acceptance_path: Path,
    result_path: Path,
    expected_result_sha256: str,
    expected_result_commit: str,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    task_input = read_json(task_input_path)
    acceptance = read_json(acceptance_path)
    result = read_json(result_path)

    for label in ("criteria", "source_lock", "transactional_schema"):
        binding = rubric[label]
        path = resolve_repo_path(repo, binding["uri"])
        if not path.is_file() or sha256(path) != binding["sha256"]:
            failures.append(f"frozen_{label}_hash_mismatch")

    acceptance_hash = sha256(acceptance_path)
    result_hash = sha256(result_path)
    if acceptance_hash != task_input.get("acceptance_contract_sha256"):
        failures.append("task_acceptance_hash_mismatch")
    if result_hash != expected_result_sha256:
        failures.append("completed_result_hash_mismatch")
    if result.get("task_id") != task_input.get("task_id"):
        failures.append("result_task_id_mismatch")
    if result.get("commission_id") != task_input.get("commission_id"):
        failures.append("result_commission_mismatch")
    if (
        result.get("immutable_input_manifest_sha256")
        != task_input.get("immutable_input_manifest_sha256")
        or result.get("immutable_input_manifest_sha256")
        != rubric["source_lock"]["sha256"]
    ):
        failures.append("result_source_lock_mismatch")
    if result.get("acceptance_contract_sha256") != acceptance_hash:
        failures.append("result_acceptance_hash_mismatch")

    transaction = result.get("result_transaction")
    if not isinstance(transaction, dict):
        failures.append("missing_result_transaction")
        transaction = {}
    if transaction.get("result_commit_id") != expected_result_commit:
        failures.append("result_commit_mismatch")
    if (
        result.get("provider_state") == "COMPLETED"
        and not transaction.get("result_commit_id")
    ):
        failures.append("provider_only_false_completion")

    independent = result.get("independent_acceptance")
    if not isinstance(independent, dict):
        failures.append("missing_independent_acceptance")
    elif independent.get("state") == "ACCEPTED" and (
        not independent.get("reviewer_id")
        or independent.get("reviewer_id") == result.get("completion_actor")
    ):
        failures.append("producer_self_acceptance")

    manifest_uri = transaction.get("manifest_uri")
    manifest_hash = transaction.get("manifest_sha256")
    if manifest_uri is not None or manifest_hash is not None:
        try:
            manifest_path = resolve_repo_path(repo, manifest_uri)
            if not manifest_path.is_file():
                failures.append("transaction_manifest_missing")
            elif sha256(manifest_path) != manifest_hash:
                failures.append("transaction_manifest_hash_mismatch")
        except (TypeError, ValueError):
            failures.append("transaction_manifest_uri_invalid")

    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        failures.append("artifact_manifest_empty")
        artifacts = []
    declared_count = transaction.get("artifact_count")
    declared_bytes = transaction.get("total_bytes")
    if declared_count != len(artifacts):
        failures.append("artifact_count_mismatch")

    seen_uris: set[str] = set()
    actual_total = 0
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"artifact_{index}_not_object")
            continue
        uri = artifact.get("content_uri")
        if uri in seen_uris:
            failures.append(f"artifact_{index}_duplicate_uri")
        if isinstance(uri, str):
            seen_uris.add(uri)
        try:
            artifact_path = resolve_repo_path(repo, uri)
        except (TypeError, ValueError):
            failures.append(f"artifact_{index}_uri_invalid")
            continue
        if not artifact_path.is_file():
            failures.append(f"artifact_{index}_missing")
            continue
        actual_bytes = artifact_path.stat().st_size
        actual_total += actual_bytes
        if actual_bytes != artifact.get("bytes"):
            failures.append(f"artifact_{index}_bytes_mismatch")
        if sha256(artifact_path) != artifact.get("sha256"):
            failures.append(f"artifact_{index}_hash_mismatch")
    if declared_bytes != actual_total:
        failures.append("artifact_total_bytes_mismatch")

    return failures, {
        "task_input": task_input,
        "acceptance": acceptance,
        "result": result,
        "completed_result_sha256": result_hash,
        "artifact_count": len(artifacts),
        "artifact_total_bytes": actual_total,
    }


def score_report(
    task_id: str,
    report: dict[str, Any],
    held_out: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    reject_reasons: list[str] = []
    retest_reasons: list[str] = []

    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        retest_reasons.append("no_independent_test_rerun")
        tests = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            reject_reasons.append(f"test_{index}_malformed")
            continue
        if not test.get("command") or not isinstance(test.get("exit_code"), int):
            reject_reasons.append(f"test_{index}_missing_execution_evidence")
        if test.get("critical", True) and test.get("passed") is not True:
            reject_reasons.append(f"test_{index}_critical_failure")

    expected_cases = {
        case["case_id"]
        for case in held_out.get("cases", [])
        if isinstance(case, dict) and case.get("task_id") == task_id
    }
    observed_cases = report.get("hidden_cases")
    if not isinstance(observed_cases, list):
        observed_cases = []
    observed_by_id = {
        case.get("case_id"): case
        for case in observed_cases
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    for case_id in sorted(expected_cases):
        observed = observed_by_id.get(case_id)
        if observed is None:
            retest_reasons.append(f"{case_id}_not_run")
        elif observed.get("status") == "FAIL":
            reject_reasons.append(f"{case_id}_failed")
        elif observed.get("status") != "PASS":
            retest_reasons.append(f"{case_id}_{observed.get('status', 'unknown')}")

    defects = report.get("defects", [])
    if not isinstance(defects, list):
        reject_reasons.append("defects_not_array")
    else:
        for index, defect in enumerate(defects):
            if isinstance(defect, dict) and defect.get("severity") == "critical":
                reject_reasons.append(f"critical_defect_{index}")

    if reject_reasons:
        return RECOMMEND_REJECT, reject_reasons, retest_reasons
    if retest_reasons:
        return RETEST, reject_reasons, retest_reasons
    return RECOMMEND_ACCEPT, reject_reasons, retest_reasons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--task-input", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--expected-result-commit", required=True)
    parser.add_argument("--test-report", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--held-out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    rubric = read_json(args.rubric)
    held_out = read_json(args.held_out)
    report = read_json(args.test_report)
    binding_failures, evidence = check_frozen_inputs(
        repo,
        rubric,
        args.task_input,
        args.acceptance,
        args.result,
        args.expected_result_sha256,
        args.expected_result_commit,
    )
    recommendation, reject_reasons, retest_reasons = score_report(
        evidence["task_input"]["task_id"], report, held_out
    )
    if binding_failures:
        recommendation = RECOMMEND_REJECT
        reject_reasons = sorted(set(reject_reasons + binding_failures))
    output = {
        "rubric_id": rubric["rubric_id"],
        "task_id": evidence["task_input"]["task_id"],
        "recommendation": recommendation,
        "binding_failures": binding_failures,
        "reject_reasons": reject_reasons,
        "retest_reasons": retest_reasons,
        "completed_result_sha256": evidence["completed_result_sha256"],
        "artifact_count": evidence["artifact_count"],
        "artifact_total_bytes": evidence["artifact_total_bytes"],
        "tests_rerun": len(report.get("tests", [])),
        "decision_changed": [],
    }
    json.dump(output, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if recommendation != RECOMMEND_REJECT else 1


if __name__ == "__main__":
    raise SystemExit(main())
