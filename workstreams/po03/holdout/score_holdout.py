#!/usr/bin/env python3
"""Generation-neutral scorer for the frozen PO-03 evaluator holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REQUEST_VERSION = "OBZIO-PO03-HOLDOUT-REQUEST-v1"
RESPONSE_VERSION = "OBZIO-PO03-HOLDOUT-RESPONSE-v1"
SUITE_VERSION = "OBZIO-PO03-HOLDOUT-SUITE-v1"
TRANSCRIPT_VERSION = "OBZIO-PO03-HOLDOUT-TRANSCRIPT-v1"


class ContractError(ValueError):
    """Raised when a suite, response, or assertion violates the protocol."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_suite(path: Path) -> dict[str, Any]:
    try:
        suite = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load suite {path}: {exc}") from exc
    if not isinstance(suite, dict) or suite.get("protocol_version") != SUITE_VERSION:
        raise ContractError("unsupported or missing suite protocol_version")
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) < 20:
        raise ContractError("suite must contain at least 20 cases")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not isinstance(item, str) for item in ids):
        raise ContractError("every case must have a string id")
    if len(ids) != len(set(ids)):
        raise ContractError("case ids must be unique")
    for case in cases:
        if not isinstance(case.get("input"), dict):
            raise ContractError(f"{case['id']}: input must be an object")
        if not isinstance(case.get("assertions"), list) or not case["assertions"]:
            raise ContractError(f"{case['id']}: assertions must be non-empty")
        requirement = case.get("requirement")
        if not isinstance(requirement, dict):
            raise ContractError(f"{case['id']}: requirement must be an object")
        for key in ("commission_section", "quote", "novelty"):
            if not isinstance(requirement.get(key), str) or not requirement[key]:
                raise ContractError(f"{case['id']}: requirement.{key} is required")
    return suite


def json_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "":
        return True, document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ContractError(f"invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def evaluate_assertion(response: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ContractError("assertion must be an object")
    path = spec.get("path")
    operation = spec.get("op")
    if not isinstance(path, str) or operation not in {
        "eq",
        "ne",
        "contains",
        "not_contains",
        "exists",
        "gte",
        "lte",
    }:
        raise ContractError(f"invalid assertion: {spec!r}")
    found, actual = json_pointer(response, path)
    expected = spec.get("value")
    passed = False
    detail = ""
    if operation == "exists":
        passed = found is bool(expected)
        detail = f"found={found}, expected existence={bool(expected)}"
    elif not found:
        detail = "path is missing"
    elif operation == "eq":
        passed = actual == expected
        detail = f"actual={actual!r}, expected={expected!r}"
    elif operation == "ne":
        passed = actual != expected
        detail = f"actual={actual!r}, forbidden={expected!r}"
    elif operation in {"contains", "not_contains"}:
        try:
            contained = expected in actual
        except TypeError:
            contained = False
        passed = contained if operation == "contains" else not contained
        detail = f"actual={actual!r}, member={expected!r}"
    elif operation in {"gte", "lte"}:
        try:
            passed = actual >= expected if operation == "gte" else actual <= expected
        except TypeError:
            passed = False
        detail = f"actual={actual!r}, bound={expected!r}"
    return {
        "path": path,
        "op": operation,
        "expected": expected,
        "actual": actual if found else None,
        "passed": passed,
        "detail": detail,
    }


def validate_response(response: Any, case_id: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ContractError("response must be an object")
    if response.get("protocol_version") != RESPONSE_VERSION:
        raise ContractError("unsupported or missing response protocol_version")
    if response.get("case_id") != case_id:
        raise ContractError(
            f"response case_id {response.get('case_id')!r} does not match {case_id!r}"
        )
    status = response.get("status")
    if status not in {"EXECUTED", "NOT_SUPPORTED"}:
        raise ContractError("status must be EXECUTED or NOT_SUPPORTED")
    boundary = response.get("boundary")
    if status == "NOT_SUPPORTED":
        if not isinstance(boundary, str) or not boundary.strip():
            raise ContractError("NOT_SUPPORTED requires a non-empty boundary")
    else:
        if boundary is not None:
            raise ContractError("EXECUTED requires boundary null")
        observation = response.get("observation")
        if not isinstance(observation, dict):
            raise ContractError("EXECUTED requires an observation object")
    return response


def run_case(
    case: dict[str, Any],
    command: list[str],
    timeout_seconds: float,
    scratch_root: Path | None,
) -> dict[str, Any]:
    request = {
        "protocol_version": REQUEST_VERSION,
        "case_id": case["id"],
        "input": case["input"],
    }
    request_bytes = canonical_json_bytes(request)
    started_ns = time.monotonic_ns()
    prefix = f"po03-a13-{case['id'].lower()}-"
    temp_parent = str(scratch_root) if scratch_root else None
    with tempfile.TemporaryDirectory(prefix=prefix, dir=temp_parent) as temp_name:
        temp_dir = Path(temp_name)
        workdir = temp_dir / "work"
        workdir.mkdir(mode=0o700)
        request_path = temp_dir / "request.json"
        response_path = temp_dir / "response.json"
        request_path.write_bytes(request_bytes)
        full_command = [
            *command,
            "--request",
            str(request_path),
            "--response",
            str(response_path),
            "--workdir",
            str(workdir),
        ]
        try:
            process = subprocess.run(
                full_command,
                cwd=workdir,
                check=False,
                capture_output=True,
                text=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000
            return {
                "case_id": case["id"],
                "title": case["title"],
                "critical": case["critical"],
                "status": "TIMEOUT",
                "passed": False,
                "boundary": f"candidate exceeded {timeout_seconds:g} seconds",
                "request_sha256": sha256_bytes(request_bytes),
                "request_bytes": len(request_bytes),
                "elapsed_ms": elapsed_ms,
                "stdout": (exc.stdout or b"").decode("utf-8", errors="replace"),
                "stderr": (exc.stderr or b"").decode("utf-8", errors="replace"),
                "assertions": [],
            }
        elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000
        base = {
            "case_id": case["id"],
            "title": case["title"],
            "critical": case["critical"],
            "request_sha256": sha256_bytes(request_bytes),
            "request_bytes": len(request_bytes),
            "elapsed_ms": elapsed_ms,
            "exit_code": process.returncode,
            "stdout": process.stdout.decode("utf-8", errors="replace"),
            "stderr": process.stderr.decode("utf-8", errors="replace"),
            "assertions": [],
        }
        if request_path.read_bytes() != request_bytes:
            return {
                **base,
                "status": "INFRASTRUCTURE_ERROR",
                "passed": False,
                "boundary": "candidate modified the frozen request bytes",
            }
        if process.returncode != 0:
            return {
                **base,
                "status": "CRASHED",
                "passed": False,
                "boundary": f"candidate exited {process.returncode}",
            }
        if not response_path.is_file():
            return {
                **base,
                "status": "MALFORMED",
                "passed": False,
                "boundary": "candidate exited zero without creating response",
            }
        try:
            raw_response = response_path.read_bytes()
            response = json.loads(raw_response)
            response = validate_response(response, case["id"])
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            return {
                **base,
                "status": "MALFORMED",
                "passed": False,
                "boundary": str(exc),
            }
        base["response_sha256"] = sha256_bytes(raw_response)
        base["response"] = response
        if response["status"] == "NOT_SUPPORTED":
            return {
                **base,
                "status": "NOT_SUPPORTED",
                "passed": False,
                "boundary": response["boundary"],
            }
        try:
            assertions = [
                evaluate_assertion(response, assertion)
                for assertion in case["assertions"]
            ]
        except ContractError as exc:
            return {
                **base,
                "status": "INFRASTRUCTURE_ERROR",
                "passed": False,
                "boundary": str(exc),
            }
        return {
            **base,
            "status": "PASS" if all(item["passed"] for item in assertions) else "FAIL",
            "passed": all(item["passed"] for item in assertions),
            "boundary": None,
            "assertions": assertions,
        }


def build_summary(
    suite: dict[str, Any], label: str, case_results: list[dict[str, Any]]
) -> dict[str, Any]:
    total = len(case_results)
    passed = sum(result["passed"] for result in case_results)
    critical_results = [result for result in case_results if result["critical"]]
    critical_passed = sum(result["passed"] for result in critical_results)
    false_completions = 0
    false_completion_boundaries: list[str] = []
    for result in case_results:
        if result["status"] not in {"PASS", "FAIL"}:
            continue
        found, count = json_pointer(
            result["response"], "/observation/counts/false_completions"
        )
        if found and isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            false_completions += count
        else:
            false_completion_boundaries.append(result["case_id"])
    unsupported = [
        {"case_id": result["case_id"], "boundary": result["boundary"]}
        for result in case_results
        if result["status"] == "NOT_SUPPORTED"
    ]
    errors = [
        {
            "case_id": result["case_id"],
            "status": result["status"],
            "boundary": result["boundary"],
        }
        for result in case_results
        if result["status"]
        in {"TIMEOUT", "CRASHED", "MALFORMED", "INFRASTRUCTURE_ERROR"}
    ]
    return {
        "suite_id": suite["suite_id"],
        "candidate_label": label,
        "total_cases": total,
        "passed_cases": passed,
        "pass_rate": passed / total,
        "total_critical": len(critical_results),
        "passed_critical": critical_passed,
        "critical_pass_rate": critical_passed / len(critical_results),
        "false_completion_count": (
            false_completions if not false_completion_boundaries else "NOT_SUPPORTED"
        ),
        "false_completion_count_boundaries": false_completion_boundaries,
        "unsupported": unsupported,
        "execution_errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    default_suite = Path(__file__).resolve().parent / "cases" / "cases.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-command", required=True)
    parser.add_argument("--candidate-label", default="BLINDED")
    parser.add_argument("--suite", type=Path, default=default_suite)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        suite = load_suite(args.suite)
        command = shlex.split(args.candidate_command)
        if not command:
            raise ContractError("candidate command is empty")
        if args.timeout_seconds <= 0:
            raise ContractError("timeout must be positive")
        if args.scratch_root:
            args.scratch_root.mkdir(parents=True, exist_ok=True)
    except (ContractError, OSError) as exc:
        print(f"SCORER_ERROR: {exc}", file=sys.stderr)
        return 2

    started_at = time.time_ns()
    case_results = [
        run_case(case, command, args.timeout_seconds, args.scratch_root)
        for case in suite["cases"]
    ]
    summary = build_summary(suite, args.candidate_label, case_results)
    transcript = {
        "protocol_version": TRANSCRIPT_VERSION,
        "suite_id": suite["suite_id"],
        "suite_sha256": sha256_bytes(args.suite.read_bytes()),
        "candidate_label": args.candidate_label,
        "candidate_command": args.candidate_command,
        "scorer_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "started_at_unix_ns": started_at,
        "finished_at_unix_ns": time.time_ns(),
        "summary": summary,
        "cases": case_results,
    }
    try:
        args.transcript.parent.mkdir(parents=True, exist_ok=True)
        args.transcript.write_bytes(canonical_json_bytes(transcript))
    except OSError as exc:
        print(f"SCORER_ERROR: cannot write transcript: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if not summary["execution_errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
