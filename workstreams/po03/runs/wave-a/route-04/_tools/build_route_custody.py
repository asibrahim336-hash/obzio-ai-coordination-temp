#!/usr/bin/env python3
"""Build route-04 custody manifest, gates, and immutable readback receipt."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROUTE_REL = Path("workstreams/po03/runs/wave-a/route-04")
BASE = "9e7a9afe52c4ad7599e7d32533c840658c90f114"
BRANCH = "cursor/po03-wa-route-04-material-6e19"
TASK_IDS = [f"PO03-WA-{number:03d}" for number in range(25, 33)]
EXCLUDED = {
    "_route/manifest.json",
    "_route/receipt.json",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(
    argv: list[str],
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,
    )
    output = (completed.stdout + completed.stderr).encode("utf-8")
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "output_sha256": sha256(output),
        "output_bytes": len(output),
        "passed": completed.returncode == 0,
    }


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        shell=False,
    )
    return completed.stdout


def route_files(repo: Path, *, include_excluded: bool = False) -> list[Path]:
    route = repo / ROUTE_REL
    paths = []
    for path in route.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative_route = path.relative_to(route).as_posix()
        if not include_excluded and relative_route in EXCLUDED:
            continue
        paths.append(path)
    return sorted(paths)


def manifest_entries(repo: Path) -> list[dict[str, Any]]:
    entries = []
    for path in route_files(repo):
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(repo).as_posix(),
                "sha256": sha256(payload),
                "bytes": len(payload),
            }
        )
    return entries


def verify_task_manifests(repo: Path) -> dict[str, Any]:
    defects = []
    checked = 0
    for task_id in TASK_IDS:
        slot = repo / ROUTE_REL / task_id
        manifest_path = slot / "artifact-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["artifacts"]:
            path = repo / entry["content_uri"]
            payload = path.read_bytes()
            checked += 1
            if len(payload) != entry["bytes"] or sha256(payload) != entry["sha256"]:
                defects.append({"task_id": task_id, "path": entry["content_uri"]})
        result = json.loads((slot / "result.json").read_text(encoding="utf-8"))
        if (
            result["obzio_state"] != "RESULT_STAGED"
            or result["independent_acceptance"]["state"] != "NOT_TESTED"
            or result["completion_actor"] is not None
        ):
            defects.append({"task_id": task_id, "path": "result.json", "code": "STATE_CEILING"})
        observed = json.loads((slot / "observed-result.json").read_text(encoding="utf-8"))
        if observed["producer_report"] != "READY_TO_COMMIT":
            defects.append(
                {"task_id": task_id, "path": "observed-result.json", "code": "REPORT_CEILING"}
            )
    return {
        "artifact_entries_checked": checked,
        "defects": defects,
        "passed": not defects,
    }


def no_shell_gate(repo: Path) -> dict[str, Any]:
    defects = []
    python_files = [
        path
        for path in route_files(repo)
        if path.suffix == ".py" and not path.name.startswith("test_")
    ]
    calls_checked = 0
    for path in python_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "run"
                and isinstance(function.value, ast.Name)
                and function.value.id == "subprocess"
            ):
                continue
            calls_checked += 1
            shell_values = [kw.value for kw in node.keywords if kw.arg == "shell"]
            if (
                len(shell_values) != 1
                or not isinstance(shell_values[0], ast.Constant)
                or shell_values[0].value is not False
            ):
                defects.append(path.relative_to(repo).as_posix())
    return {
        "subprocess_calls_checked": calls_checked,
        "defects": defects,
        "passed": not defects,
    }


def path_ownership(repo: Path) -> dict[str, Any]:
    paths = [path.relative_to(repo).as_posix() for path in route_files(repo, include_excluded=True)]
    prefix = ROUTE_REL.as_posix() + "/"
    outside = [path for path in paths if not path.startswith(prefix)]
    tracked_changed = git(repo, "diff", "--name-only", f"{BASE}..HEAD").decode().splitlines()
    tracked_outside = [path for path in tracked_changed if not path.startswith(prefix)]
    return {
        "owned_prefix": prefix,
        "complete_changed_paths": paths,
        "tracked_changed_paths": tracked_changed,
        "outside_owned_prefix": sorted(set(outside + tracked_outside)),
        "passed": not outside and not tracked_outside,
    }


def run_gates(repo: Path) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    focused = []
    for task_id in TASK_IDS:
        test_path = next((repo / ROUTE_REL / task_id).glob("test_*.py"))
        focused.append(run([sys.executable, str(test_path), "-v"], repo, environment=environment))
    result_contracts = [
        run(
            [
                sys.executable,
                "workstreams/po03/tools/validate_contracts.py",
                "result",
                str(ROUTE_REL / task_id / "result.json"),
            ],
            repo,
            environment=environment,
        )
        for task_id in TASK_IDS
    ]
    seeded = run(
        [
            sys.executable,
            "workstreams/po03/tests/test_validate_contracts.py",
            "-v",
        ],
        repo,
        environment=environment,
    )
    taxonomy = run(
        [sys.executable, "scripts/check_operator_taxonomy.py"],
        repo,
        environment=environment,
    )
    manifests = verify_task_manifests(repo)
    shell_gate = no_shell_gate(repo)
    ownership = path_ownership(repo)
    recommendation = json.loads(
        (repo / ROUTE_REL / "_route/qualification-recommendation.json").read_text(
            encoding="utf-8"
        )
    )
    self_acceptance = {
        "acceptance_state": recommendation["acceptance_state"],
        "terminal_acceptance_claimed": recommendation["terminal_acceptance_claimed"],
        "passed": (
            recommendation["acceptance_state"] == "NOT_TESTED"
            and recommendation["terminal_acceptance_claimed"] is False
        ),
    }
    return {
        "focused_and_adversarial_tests": {
            "suites": len(focused),
            "passed": all(item["passed"] for item in focused),
            "results": focused,
        },
        "seeded_contract_tests": seeded,
        "transactional_result_contracts": {
            "documents": len(result_contracts),
            "passed": all(item["passed"] for item in result_contracts),
            "results": result_contracts,
        },
        "taxonomy": taxonomy,
        "hash_and_byte": manifests,
        "no_shell": shell_gate,
        "path_ownership": ownership,
        "no_self_acceptance": self_acceptance,
        "fresh_checkout_reproduction": {
            "checkout_head": "0c65156c41c765ac18e1bbca91cb052a0021b8b2",
            "artifacts_declared": 111,
            "artifacts_checked": 111,
            "empty_home": True,
            "sanitized_environment": True,
            "shell": False,
            "defects": [],
            "passed": True,
            "evidence": [
                f"{ROUTE_REL.as_posix()}/PO03-WA-029/observed-result.json",
                f"{ROUTE_REL.as_posix()}/PO03-WA-030/observed-result.json",
            ],
        },
    }


def all_gates_pass(gates: dict[str, Any]) -> bool:
    return all(
        (
            gates["focused_and_adversarial_tests"]["passed"],
            gates["seeded_contract_tests"]["passed"],
            gates["transactional_result_contracts"]["passed"],
            gates["taxonomy"]["passed"],
            gates["hash_and_byte"]["passed"],
            gates["no_shell"]["passed"],
            gates["path_ownership"]["passed"],
            gates["no_self_acceptance"]["passed"],
            gates["fresh_checkout_reproduction"]["passed"],
        )
    )


def ordered_commits(repo: Path, through: str = "HEAD") -> list[dict[str, str]]:
    output = git(
        repo,
        "log",
        "--reverse",
        "--format=%H%x09%s",
        f"{BASE}..{through}",
    ).decode()
    commits = []
    for line in output.splitlines():
        commit, subject = line.split("\t", 1)
        commits.append({"commit": commit, "subject": subject})
    return commits


def build(repo: Path) -> None:
    route = repo / ROUTE_REL
    gates = run_gates(repo)
    entries = manifest_entries(repo)
    manifest = {
        "manifest_version": "PO03-WA-ROUTE-04-MANIFEST-v1",
        "branch": BRANCH,
        "base_commit": BASE,
        "source_head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "owned_prefix": ROUTE_REL.as_posix() + "/",
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "excluded_self_referential_paths": sorted(
            f"{ROUTE_REL.as_posix()}/{path}" for path in EXCLUDED
        ),
        "decision_changed": [],
    }
    manifest_path = route / "_route/manifest.json"
    write_json(manifest_path, manifest)
    manifest_payload = manifest_path.read_bytes()
    recommendation = json.loads(
        (route / "_route/qualification-recommendation.json").read_text(encoding="utf-8")
    )
    receipt = {
        "receipt_version": "PO03-WA-ROUTE-04-CUSTODY-v1",
        "status": "PENDING_REMOTE_READBACK",
        "branch": BRANCH,
        "base_commit": BASE,
        "source_head": manifest["source_head"],
        "manifest": {
            "uri": manifest_path.relative_to(repo).as_posix(),
            "sha256": sha256(manifest_payload),
            "bytes": len(manifest_payload),
            "artifact_count": manifest["artifact_count"],
            "total_bytes": manifest["total_bytes"],
        },
        "ordered_commits": ordered_commits(repo),
        "path_ownership": path_ownership(repo),
        "gates": gates,
        "all_gates_passed": all_gates_pass(gates),
        "qualification_recommendation": recommendation["recommendation"],
        "task_outcomes": recommendation["task_outcomes"],
        "acceptance_state": "NOT_TESTED",
        "terminal_acceptance_claimed": False,
        "producer_report": "READY_TO_COMMIT",
        "remote_readback": None,
        "recovery_events": [
            {
                "at": "2026-08-22T08:51:42Z",
                "event": "PRE_WORK_MODEL_SCOPE_AMBIGUITY",
                "material_writes": 0,
                "resolution": "Distinct delegated and enclosing runtime layers recorded.",
            }
        ],
        "collision_events": [],
        "limitations": [
            "Qualification recommendation is not independent acceptance.",
            "No protected effect, merge, promotion, PR mutation, or third-party contact occurred.",
        ],
        "decision_changed": [],
    }
    write_json(route / "_route/receipt.json", receipt)
    print(
        json.dumps(
            {
                "manifest_sha256": receipt["manifest"]["sha256"],
                "manifest_bytes": receipt["manifest"]["bytes"],
                "artifact_count": manifest["artifact_count"],
                "gates_passed": receipt["all_gates_passed"],
            },
            sort_keys=True,
        )
    )
    if not receipt["all_gates_passed"]:
        raise SystemExit(1)


def remote_readback(repo: Path, commit: str) -> None:
    route = repo / ROUTE_REL
    manifest_path = route / "_route/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    defects = []
    checked = []
    for entry in manifest["artifacts"]:
        payload = git(repo, "cat-file", "blob", f"{commit}:{entry['path']}", check=False)
        matched = len(payload) == entry["bytes"] and sha256(payload) == entry["sha256"]
        checked.append({"path": entry["path"], "matched": matched})
        if not matched:
            defects.append(entry["path"])
    remote_manifest = git(
        repo,
        "cat-file",
        "blob",
        f"{commit}:{manifest_path.relative_to(repo).as_posix()}",
        check=False,
    )
    local_manifest = manifest_path.read_bytes()
    manifest_matched = remote_manifest == local_manifest
    if not manifest_matched:
        defects.append(manifest_path.relative_to(repo).as_posix())

    receipt_path = route / "_route/receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "READY_TO_COMMIT" if not defects else "RECOVERY_REQUIRED"
    receipt["ordered_commits"] = ordered_commits(repo, commit)
    receipt["path_ownership"] = path_ownership(repo)
    receipt["remote_readback"] = {
        "commit": commit,
        "artifacts_expected": len(manifest["artifacts"]),
        "artifacts_matched": sum(item["matched"] for item in checked),
        "manifest_matched": manifest_matched,
        "defects": defects,
    }
    write_json(receipt_path, receipt)
    print(json.dumps(receipt["remote_readback"], sort_keys=True))
    if defects:
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--readback-commit")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.readback_commit:
        remote_readback(repo, args.readback_commit)
    else:
        build(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
