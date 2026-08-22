#!/usr/bin/env python3
"""Independently rerun and freeze the 32 route-08 challenger outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rubric


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
BASE_COMMIT = "081a7d709dee1af1ca47c1c69eb60085b9e59cd5"
TARGETS = {
    "route-01": range(1, 9),
    "route-05": range(33, 41),
    "route-06": range(41, 49),
    "route-07": range(49, 57),
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_registry() -> dict[str, dict[str, Any]]:
    rows = {}
    path = REPO / "workstreams/po03/control/work-unit-registry.jsonl"
    for line in path.read_text().splitlines():
        row = json.loads(line)
        rows[row["task_id"]] = row
    return rows


def producer_test_command(route: str, task_id: str) -> tuple[str, Path]:
    slot = REPO / f"workstreams/po03/runs/wave-a/{route}/{task_id}"
    start = slot / "tests" if (slot / "tests").is_dir() else slot
    relative = start.relative_to(REPO).as_posix()
    return (
        f"PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s {relative} -p 'test*.py' -q",
        start,
    )


def run_tests(route: str, task_id: str) -> dict[str, Any]:
    command, start = producer_test_command(route, task_id)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(start), "-p", "test*.py", "-q"],
        cwd=REPO,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    observed = (completed.stdout + completed.stderr).strip()
    match = re.search(r"Ran (\d+) tests?", observed)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "critical": True,
        "tests_ran": int(match.group(1)) if match else None,
        "observed_output": observed,
    }


def completion_rows() -> dict[str, dict[str, Any]]:
    rows = {}
    for route in TARGETS:
        path = REPO / f"workstreams/po03/control/completions/{route}.json"
        receipt = json.loads(path.read_text())
        for row in receipt["task_results"]:
            rows[row["task_id"]] = {
                **row,
                "route_id": route,
                "coordinator_completion_uri": path.relative_to(REPO).as_posix(),
                "coordinator_completion_sha256": sha256_file(path),
            }
    return rows


def immutable_artifact_readback(result: dict[str, Any], commit: str) -> tuple[list[dict[str, Any]], list[str]]:
    evidence, failures = [], []
    for artifact in result["artifacts"]:
        uri = artifact["content_uri"]
        try:
            payload = git_blob(commit, uri)
        except subprocess.CalledProcessError:
            failures.append(f"git_blob_missing:{uri}")
            continue
        observed_sha = sha256_bytes(payload)
        observed_bytes = len(payload)
        matched = observed_sha == artifact["sha256"] and observed_bytes == artifact["bytes"]
        if not matched:
            failures.append(f"git_blob_mismatch:{uri}")
        evidence.append(
            {
                "content_uri": uri,
                "commit": commit,
                "sha256": observed_sha,
                "bytes": observed_bytes,
                "matched": matched,
            }
        )
    return evidence, failures


def evaluate() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rubric_doc = json.loads((HERE / "RUBRIC.json").read_text())
    held_out_doc = json.loads((HERE / "held-out-cases.json").read_text())
    held_out_results = json.loads((HERE / "held-out-results.json").read_text())
    hidden_by_task = {row["task_id"]: row for row in held_out_results["cases"]}
    registry = read_registry()
    completions = completion_rows()
    reports: dict[str, dict[str, Any]] = {}
    outcomes = []

    for route, numbers in TARGETS.items():
        for number in numbers:
            task_id = f"PO03-WA-{number:03d}"
            meta = registry[task_id]
            completion = completions[task_id]
            input_path = REPO / meta["input_uri"]
            acceptance_path = REPO / meta["acceptance_uri"]
            result_path = REPO / completion["result_uri"]
            base_result = git_blob(BASE_COMMIT, completion["result_uri"])
            result_sha = sha256_bytes(base_result)
            result = json.loads(base_result)

            binding_failures, binding_evidence = rubric.check_frozen_inputs(
                REPO,
                rubric_doc,
                input_path,
                acceptance_path,
                result_path,
                result_sha,
                completion["result_commit_id"],
            )
            if sha256_file(input_path) != meta["input_sha256"]:
                binding_failures.append("registry_input_hash_mismatch")
            if sha256_file(acceptance_path) != meta["acceptance_sha256"]:
                binding_failures.append("registry_acceptance_hash_mismatch")
            if result_path.read_bytes() != base_result:
                binding_failures.append("base_completed_result_bytes_mismatch")
            if completion["result_commit_id"] != meta["result_commit_id"]:
                binding_failures.append("completion_registry_commit_mismatch")
            if completion["result_uri"] != f"workstreams/po03/control/results/{task_id}.json":
                binding_failures.append("completion_result_uri_mismatch")

            artifact_readback, blob_failures = immutable_artifact_readback(
                result, completion["result_commit_id"]
            )
            binding_failures.extend(blob_failures)
            test = run_tests(route, task_id)
            hidden = hidden_by_task[task_id]
            report_for_score = {
                "tests": [test],
                "hidden_cases": [hidden],
                "defects": (
                    []
                    if hidden["status"] == "PASS"
                    else [
                        {
                            "severity": "critical",
                            "case_id": hidden["case_id"],
                            "detail": hidden["detail"],
                        }
                    ]
                ),
            }
            recommendation, reject_reasons, retest_reasons = rubric.score_report(
                task_id, report_for_score, held_out_doc
            )
            if binding_failures:
                recommendation = rubric.RECOMMEND_REJECT
                reject_reasons = sorted(set(reject_reasons + binding_failures))

            report = {
                "report_version": "PO03-WA-ROUTE-08-INDEPENDENT-TEST-v1",
                "task_id": task_id,
                "route_id": route,
                "reviewer_family": "gpt",
                "exact_model_configuration": rubric_doc["exact_model_configuration"],
                "rubric_sha256": sha256_file(HERE / "RUBRIC.json"),
                "held_out_suite_sha256": sha256_file(HERE / "held-out-cases.json"),
                "criteria_sha256": rubric_doc["criteria"]["sha256"],
                "source_lock_sha256": rubric_doc["source_lock"]["sha256"],
                "completed_result": {
                    "uri": completion["result_uri"],
                    "sha256": result_sha,
                    "base_commit": BASE_COMMIT,
                    "result_commit_id": completion["result_commit_id"],
                },
                "coordinator_completion": {
                    "uri": completion["coordinator_completion_uri"],
                    "sha256": completion["coordinator_completion_sha256"],
                    "completed_receipt_sha256": completion["completed_receipt_sha256"],
                    "parent_ingested_receipt_sha256": completion["parent_ingested_receipt_sha256"],
                },
                "frozen_contracts": {
                    "input_uri": meta["input_uri"],
                    "input_sha256": sha256_file(input_path),
                    "acceptance_uri": meta["acceptance_uri"],
                    "acceptance_sha256": sha256_file(acceptance_path),
                },
                "tests": [test],
                "hidden_cases": [hidden],
                "artifact_readback": artifact_readback,
                "artifact_count": binding_evidence["artifact_count"],
                "artifact_total_bytes": binding_evidence["artifact_total_bytes"],
                "binding_failures": sorted(set(binding_failures)),
                "defects": report_for_score["defects"],
                "limitations": [
                    "Recommendation is challenger evidence, not terminal independent acceptance.",
                    "Observed timings are runtime-local and are not used as cross-route performance claims.",
                ],
                "recommendation": recommendation,
                "reject_reasons": reject_reasons,
                "retest_reasons": retest_reasons,
                "decision_changed": [],
            }
            reports[task_id] = report
            outcomes.append(
                {
                    "task_id": task_id,
                    "route_id": route,
                    "recommendation": recommendation,
                    "completed_result_sha256": result_sha,
                    "result_commit_id": completion["result_commit_id"],
                    "producer_tests": {
                        "passed": test["passed"],
                        "tests_ran": test["tests_ran"],
                    },
                    "held_out_case": {
                        "case_id": hidden["case_id"],
                        "status": hidden["status"],
                    },
                    "binding_failures": sorted(set(binding_failures)),
                    "reject_reasons": reject_reasons,
                    "retest_reasons": retest_reasons,
                }
            )

    freeze = {
        "freeze_version": "PO03-WA-ROUTE-08-OUTCOMES-FREEZE-v1",
        "frozen_at": utc_now(),
        "base_commit": BASE_COMMIT,
        "rubric_commit": subprocess.run(
            ["git", "rev-parse", "67b9ae6^{commit}"],
            cwd=REPO,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "rubric_sha256": sha256_file(HERE / "RUBRIC.json"),
        "held_out_suite_sha256": sha256_file(HERE / "held-out-cases.json"),
        "outcomes": outcomes,
        "recommendation_counts": {
            name: sum(row["recommendation"] == name for row in outcomes)
            for name in (rubric.RECOMMEND_ACCEPT, rubric.RECOMMEND_REJECT, rubric.RETEST)
        },
        "route_07_reviews_opened": False,
        "decision_changed": [],
    }
    return freeze, reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    freeze, reports = evaluate()
    if args.write:
        reports_dir = HERE / "reports"
        reports_dir.mkdir(exist_ok=True)
        for task_id, report in reports.items():
            (reports_dir / f"{task_id}.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
        (HERE / "OUTCOMES-FROZEN.json").write_text(
            json.dumps(freeze, indent=2, sort_keys=True) + "\n"
        )
    else:
        print(json.dumps(freeze, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
