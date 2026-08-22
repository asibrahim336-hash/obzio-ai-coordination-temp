#!/usr/bin/env python3
"""Evaluate the PO-03 path-scope guard against the frozen hidden case set.

The harness never mutates the repository it is executed from. Path cases are
pure strings passed to the guard's own functions. Git cases are replayed inside
throwaway repositories created under a temporary directory, so every dangerous
mutation exists only in a scratch repository that is removed afterwards.

Usage:
    python3 -I tests/harness.py --out observed-results.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SLOT.parents[4]
GUARD = REPO_ROOT / "workstreams" / "po03" / "tools" / "check_path_scope.py"
HIDDEN_CASES = SLOT / "hidden-cases.json"

FIXED_ENV = {
    "GIT_AUTHOR_NAME": "po03-043-harness",
    "GIT_AUTHOR_EMAIL": "po03-043-harness@invalid.local",
    "GIT_COMMITTER_NAME": "po03-043-harness",
    "GIT_COMMITTER_EMAIL": "po03-043-harness@invalid.local",
    "GIT_AUTHOR_DATE": "2026-08-22T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2026-08-22T00:00:00 +0000",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def load_guard():
    spec = importlib.util.spec_from_file_location("po03_check_path_scope_under_review", GUARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def decode(path_hex: str) -> str:
    return bytes.fromhex(path_hex).decode("utf-8", "surrogateescape")


# ---------------------------------------------------------------------------
# Pure path evaluation
# ---------------------------------------------------------------------------


def evaluate_path_cases(module, cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        path = decode(case["path_hex"])
        try:
            observed = "REJECT" if module.violations([path]) else "ALLOW"
            error = None
        except Exception as exc:  # a raised exception is itself an observation
            observed = "RAISED"
            error = f"{type(exc).__name__}: {exc}"

        cli_exit: int | None = None
        cli_disposition = "NOT_APPLICABLE"
        cli_stderr = ""
        if "\x00" not in path:
            completed = subprocess.run(
                [sys.executable, "-I", str(GUARD), "--path", path],
                capture_output=True,
                cwd=str(REPO_ROOT),
                env={**os.environ, **FIXED_ENV},
            )
            cli_exit = completed.returncode
            cli_stderr = completed.stderr.decode("utf-8", "replace").strip()
            cli_disposition = "ALLOW" if cli_exit == 0 else "REJECT"
        else:
            cli_stderr = "argv cannot carry a NUL byte; in-process evaluation only"

        results.append(
            {
                "case_id": case["case_id"],
                "family": case["family"],
                "path_display": case["path_display"],
                "commission_requirement": case["commission_requirement"],
                "predicted_guard_disposition": case["predicted_guard_disposition"],
                "observed_guard_disposition": observed,
                "observed_error": error,
                "prediction_held": observed == case["predicted_guard_disposition"],
                "requirement_satisfied": observed == case["commission_requirement"],
                "cli_exit_code": cli_exit,
                "cli_disposition": cli_disposition,
                "cli_agrees_with_in_process": cli_disposition in (observed, "NOT_APPLICABLE"),
                "cli_stderr": cli_stderr,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Throwaway repository construction
# ---------------------------------------------------------------------------


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", *args),
        cwd=str(repo),
        capture_output=True,
        check=check,
        env={**os.environ, **FIXED_ENV},
    )


def write_file(repo: Path, rel: bytes, content: str) -> None:
    target = Path(os.fsdecode(repo / os.fsdecode(rel)))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def apply_operation(repo: Path, op: dict) -> None:
    kind = op["op"]
    if kind == "noop":
        return
    if kind == "write":
        write_file(repo, os.fsencode(op["path"]), op["content"])
    elif kind == "write_hex":
        write_file(repo, bytes.fromhex(op["path_hex"]), op["content"])
    elif kind == "copy":
        source = repo / op["from"]
        target = repo / op["to"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    elif kind == "move":
        source = repo / op["from"]
        target = repo / op["to"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    elif kind == "delete":
        (repo / op["path"]).unlink()
    elif kind == "chmod":
        (repo / op["path"]).chmod(int(op["mode"], 8))
    elif kind == "symlink":
        target = repo / op["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(op["target"])
    elif kind == "gitlink":
        run_git(repo, "update-index", "--add", "--cacheinfo", f"160000,{op['sha1']},{op['path']}")
    elif kind == "stage":
        run_git(repo, "add", "--", op["path"])
    elif kind == "git_config":
        run_git(repo, "config", op["key"], op["value"])
    elif kind == "commit":
        if op.get("add", True):
            run_git(repo, "add", "-A")
        run_git(repo, "commit", "--quiet", "--allow-empty", "-m", op["message"])
    elif kind == "tag":
        run_git(repo, "tag", "-f", op["name"])
    elif kind == "branch":
        if op.get("checkout"):
            run_git(repo, "checkout", "--quiet", "-b", op["name"])
        else:
            run_git(repo, "branch", op["name"])
    elif kind == "checkout":
        run_git(repo, "checkout", "--quiet", op["ref"])
    elif kind == "merge":
        run_git(repo, "merge", "--quiet", "--no-ff", "-m", op["message"], op["ref"])
    else:
        raise ValueError(f"unknown operation: {kind}")


def build_repository(root: Path, case: dict) -> Path:
    repo = root / case["case_id"]
    repo.mkdir(parents=True)
    run_git(repo, "init", "--quiet", "-b", "master")
    run_git(repo, "config", "user.name", "po03-043-harness")
    run_git(repo, "config", "user.email", "po03-043-harness@invalid.local")
    run_git(repo, "config", "commit.gpgsign", "false")
    run_git(repo, "config", "core.autocrlf", "false")
    for rel, content in sorted(case["seed_files"].items()):
        write_file(repo, os.fsencode(rel), content)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "--quiet", "-m", "seed")
    run_git(repo, "tag", "-f", "base")
    for op in case["operations"]:
        apply_operation(repo, op)
    return repo


def git_reported_paths(repo: Path, base: str, head: str) -> tuple[list[str], list[str], str]:
    """Return (--name-only paths, --name-status entries, error text)."""
    name_only = subprocess.run(
        ("git", "diff", "--name-only", "--diff-filter=ACMRDTUXB", "-z", f"{base}...{head}"),
        cwd=str(repo),
        capture_output=True,
        env={**os.environ, **FIXED_ENV},
    )
    if name_only.returncode != 0:
        return [], [], name_only.stderr.decode("utf-8", "replace").strip()
    paths = [
        item.decode("utf-8", "surrogateescape")
        for item in name_only.stdout.split(b"\0")
        if item
    ]
    status = subprocess.run(
        ("git", "diff", "--name-status", "--diff-filter=ACMRDTUXB", f"{base}...{head}"),
        cwd=str(repo),
        capture_output=True,
        env={**os.environ, **FIXED_ENV},
    )
    entries = [
        line for line in status.stdout.decode("utf-8", "replace").splitlines() if line.strip()
    ]
    return paths, entries, ""


def evaluate_git_cases(cases: list[dict], keep: bool) -> list[dict]:
    results = []
    root = Path(tempfile.mkdtemp(prefix="po03-043-throwaway-"))
    try:
        for case in cases:
            repo = build_repository(root, case)
            base = case["base_ref"]
            head = case["head_ref"]
            reported, status_entries, git_error = git_reported_paths(repo, base, head)
            completed = subprocess.run(
                [sys.executable, "-I", str(GUARD), "--base", base, "--head", head],
                cwd=str(repo),
                capture_output=True,
                env={**os.environ, **FIXED_ENV},
            )
            exit_code = completed.returncode
            stderr = completed.stderr.decode("utf-8", "replace").strip()
            stdout = completed.stdout.decode("utf-8", "replace").strip()
            violations = sorted(
                line.split("PO03_PATH_SCOPE_VIOLATION: ", 1)[1]
                for line in stderr.splitlines()
                if line.startswith("PO03_PATH_SCOPE_VIOLATION: ")
            )
            requirement = case["commission_requirement"]
            requirement_satisfied = (exit_code != 0) if requirement == "REJECT" else (exit_code == 0)
            missed = sorted(set(case["predicted_violation_paths"]) - set(violations))
            results.append(
                {
                    "case_id": case["case_id"],
                    "family": case["family"],
                    "status_class": case["status_class"],
                    "description": case["description"],
                    "commission_requirement": requirement,
                    "predicted_guard_exit_code": case["predicted_guard_exit_code"],
                    "observed_guard_exit_code": exit_code,
                    "prediction_held": exit_code == case["predicted_guard_exit_code"],
                    "requirement_satisfied": requirement_satisfied,
                    "observed_git_name_only": reported,
                    "observed_git_name_status": status_entries,
                    "observed_git_error": git_error,
                    "observed_violation_paths": violations,
                    "predicted_violation_paths": case["predicted_violation_paths"],
                    "unreported_expected_violations": missed,
                    "guard_stdout": stdout,
                    "guard_stderr": stderr,
                }
            )
    finally:
        if keep:
            print(f"kept throwaway repositories under {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return results


# ---------------------------------------------------------------------------


def summarise(path_results: list[dict], git_results: list[dict]) -> dict:
    path_requirement_failures = [
        r["case_id"] for r in path_results if not r["requirement_satisfied"]
    ]
    git_requirement_failures = [
        r["case_id"] for r in git_results if not r["requirement_satisfied"]
    ]
    false_positives = [
        r["case_id"]
        for r in path_results
        if r["commission_requirement"] == "ALLOW" and not r["requirement_satisfied"]
    ] + [
        r["case_id"]
        for r in git_results
        if r["commission_requirement"] == "ALLOW" and not r["requirement_satisfied"]
    ]
    false_negatives = [
        r["case_id"]
        for r in path_results
        if r["commission_requirement"] == "REJECT" and not r["requirement_satisfied"]
    ] + [
        r["case_id"]
        for r in git_results
        if r["commission_requirement"] == "REJECT" and not r["requirement_satisfied"]
    ]
    return {
        "path_cases_evaluated": len(path_results),
        "git_cases_evaluated": len(git_results),
        "path_predictions_refuted": sorted(
            r["case_id"] for r in path_results if not r["prediction_held"]
        ),
        "git_predictions_refuted": sorted(
            r["case_id"] for r in git_results if not r["prediction_held"]
        ),
        "requirement_failures": sorted(path_requirement_failures + git_requirement_failures),
        "false_positives_against_allowlist": sorted(false_positives),
        "false_negatives_against_readonly_estate": sorted(false_negatives),
        "hypothesis_under_test": "The scope guard rejects modified, added, copied, renamed, and deleted out-of-allowlist paths.",
        "hypothesis_verdict": "REFUTED" if false_negatives else "NOT_REFUTED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(SLOT / "observed-results.json"))
    parser.add_argument("--cases", default=str(HIDDEN_CASES))
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    document = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    module = load_guard()
    path_results = evaluate_path_cases(module, document["path_cases"])
    git_results = evaluate_git_cases(document["git_cases"], keep=args.keep_temp)
    summary = summarise(path_results, git_results)

    output = {
        "results_version": "PO03-WAVE-A-043-OBSERVED-RESULTS-v1",
        "task_id": document["task_id"],
        "decision_changed": [],
        "case_set_version": document["case_set_version"],
        "guard_under_review": "workstreams/po03/tools/check_path_scope.py",
        "runtime": {
            "python": sys.version.split()[0],
            "git": subprocess.run(
                ("git", "--version"), capture_output=True, check=True
            ).stdout.decode().strip(),
            "platform": sys.platform,
        },
        "summary": summary,
        "path_results": path_results,
        "git_results": git_results,
    }
    Path(args.out).write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
