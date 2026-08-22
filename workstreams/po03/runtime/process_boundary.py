#!/usr/bin/env python3
"""Subprocess-boundary harness for PO-03 entry points (unit a3-u08).

Runs every declared entry point as a separate process with an environment built
from nothing, and requires each invocation to produce its declared exit code and
output.

Why the process boundary is not optional
----------------------------------------
Importing a module and calling ``main()`` shares the parent's ``sys.path``,
already-imported modules, working directory and whole environment.  A tool can
pass that way and still fail as a command, which is the only way CI and a
reviewer will ever run it.  The harness therefore never imports its targets.

The comparison that makes this evidence rather than ceremony is ``--compare``:
each entry point is additionally exercised in-process, and any invocation that
succeeds in-process while failing as a subprocess is reported as an
in-process-only assumption.  A harness that cannot tell the two apart proves
nothing about portability.

The child environment is constructed, not filtered.  Filtering leaves whatever
the filter's author forgot; building from nothing turns a new inherited
dependency into a failure instead of a pass that happens to work here.

Dependency-free: standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]
DEFAULT_MANIFEST = RUNTIME_DIR / "entry-points.json"

REPORT_SCHEMA = "po03-process-boundary-report-v1"

IN_ALLOWLIST_INPUT = "workstreams/po03/runtime/path_scope.py\nreceipts/po03/2026-08-22/ci-clean-clone.json\n"


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "po03-entry-points-v1":
        raise ValueError(f"unexpected manifest schema: {manifest.get('schema')!r}")
    return manifest


def clean_environment(scratch: Path) -> dict[str, str]:
    """Build a child environment from nothing.

    ``os.defpath`` is the interpreter's compiled-in default search path, so no
    absolute path is written here and none is inherited.  The interpreter's own
    directory is added because a child must be able to find the same python.
    """
    interpreter_dir = str(Path(sys.executable).parent)
    return {
        "PATH": interpreter_dir + os.defpath,
        "HOME": str(scratch / "home"),
        "TMPDIR": str(scratch / "tmp"),
        "LC_ALL": "C.UTF-8",
    }


def materialise_inputs(invocation: dict[str, Any], scratch: Path) -> None:
    name = invocation.get("writes_input")
    if name:
        (scratch / name).write_text(IN_ALLOWLIST_INPUT, encoding="utf-8")


def expand(tokens: list[str], scratch: Path) -> list[str]:
    return [
        token.replace("{scratch}", str(scratch)).replace("{repo}", str(REPO_ROOT))
        for token in tokens
    ]


def run_as_subprocess(entry: dict[str, Any], invocation: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="po03-boundary-") as raw_scratch:
        scratch = Path(raw_scratch)
        (scratch / "home").mkdir()
        (scratch / "tmp").mkdir()
        materialise_inputs(invocation, scratch)
        argv = [sys.executable, "-I", "-B", str(REPO_ROOT / entry["path"])] + expand(
            invocation["args"], scratch
        )
        completed = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            env=clean_environment(scratch),
            capture_output=True,
            text=True,
        )
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }


def run_in_process(entry: dict[str, Any], invocation: dict[str, Any]) -> dict[str, Any]:
    """Import the module and call main(), for comparison only.

    Never used to decide whether an entry point works.  Its only purpose is to
    detect an invocation that succeeds here and fails as a command.
    """
    with tempfile.TemporaryDirectory(prefix="po03-boundary-inproc-") as raw_scratch:
        scratch = Path(raw_scratch)
        (scratch / "home").mkdir()
        (scratch / "tmp").mkdir()
        materialise_inputs(invocation, scratch)
        args = expand(invocation["args"], scratch)
        module_path = REPO_ROOT / entry["path"]
        stdout, stderr = io.StringIO(), io.StringIO()
        previous_cwd = Path.cwd()
        exit_code: int
        try:
            os.chdir(REPO_ROOT)
            spec = importlib.util.spec_from_file_location(f"inproc_{entry['id']}", module_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                spec.loader.exec_module(module)
                try:
                    exit_code = int(module.main(args) or 0)
                except SystemExit as exc:
                    exit_code = int(exc.code or 0)
        except BaseException as exc:  # noqa: BLE001 - any failure is a result, not a crash
            exit_code = 70
            stderr.write(f"{type(exc).__name__}: {exc}")
        finally:
            os.chdir(previous_cwd)
        return {"exit_code": exit_code, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}


def judge(invocation: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected = invocation.get("expected_exit_code", 0)
    if outcome["exit_code"] != expected:
        failures.append(f"exit code {outcome['exit_code']}, expected {expected}")
    needle = invocation.get("expect_stdout_contains")
    if needle and needle not in outcome["stdout"]:
        failures.append(f"stdout does not contain {needle!r}")
    needle = invocation.get("expect_stderr_contains")
    if needle and needle not in outcome["stderr"]:
        failures.append(f"stderr does not contain {needle!r}")
    return failures


def run_harness(manifest: dict[str, Any], compare: bool = False) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for entry in manifest["entry_points"]:
        for invocation in entry["invocations"]:
            subprocess_outcome = run_as_subprocess(entry, invocation)
            subprocess_failures = judge(invocation, subprocess_outcome)
            record: dict[str, Any] = {
                "entry_point": entry["id"],
                "path": entry["path"],
                "owner": entry["owner"],
                "invocation": invocation["name"],
                "expected_exit_code": invocation.get("expected_exit_code", 0),
                "subprocess_exit_code": subprocess_outcome["exit_code"],
                "subprocess_failures": subprocess_failures,
                "verdict": "FAIL" if subprocess_failures else "PASS",
            }
            if compare:
                in_process_outcome = run_in_process(entry, invocation)
                in_process_failures = judge(invocation, in_process_outcome)
                record["in_process_exit_code"] = in_process_outcome["exit_code"]
                record["in_process_failures"] = in_process_failures
                record["in_process_only_success"] = bool(subprocess_failures) and not in_process_failures
                record["subprocess_only_success"] = bool(in_process_failures) and not subprocess_failures
            results.append(record)

    failing = [record for record in results if record["verdict"] == "FAIL"]
    return {
        "schema": REPORT_SCHEMA,
        "isolation": "separate process, constructed environment, per-invocation scratch tree",
        "inherited_variables": 0,
        "child_environment_keys": sorted(clean_environment(RUNTIME_DIR).keys()),
        "entry_points_declared": len(manifest["entry_points"]),
        "invocations_run": len(results),
        "compared_in_process": compare,
        "in_process_only_successes": [
            f"{record['entry_point']}:{record['invocation']}"
            for record in results
            if record.get("in_process_only_success")
        ],
        # The other direction is a boundary too: an entry point that only works
        # as a command cannot be driven in-process, which constrains any future
        # in-process orchestration.
        "subprocess_only_successes": [
            f"{record['entry_point']}:{record['invocation']}"
            for record in results
            if record.get("subprocess_only_success")
        ],
        "recorded_boundaries": [item["id"] for item in manifest.get("recorded_boundaries", [])],
        "failing_invocations": [f"{r['entry_point']}:{r['invocation']}" for r in failing],
        "verdict": "FAIL" if failing else "PASS",
        "results": results,
    }


def emit(report: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for record in report["results"]:
            print(f"{record['verdict']} {record['entry_point']}:{record['invocation']}")
            for failure in record["subprocess_failures"]:
                print(f"  {failure}")
            if record.get("in_process_only_success"):
                print("  IN_PROCESS_ONLY: succeeds when imported, fails as a command")
            if record.get("subprocess_only_success"):
                print("  SUBPROCESS_ONLY: succeeds as a command, cannot be driven in-process")
        if report["verdict"] == "FAIL":
            print(
                f"FAIL {len(report['failing_invocations'])} of {report['invocations_run']} "
                f"invocation(s) across {report['entry_points_declared']} entry point(s)"
            )
        else:
            print(
                f"PASS {report['invocations_run']} invocation(s) across "
                f"{report['entry_points_declared']} entry point(s) in separate processes "
                f"with {report['inherited_variables']} inherited variables"
            )
    return 1 if report["verdict"] == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO-03 subprocess-boundary harness")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--compare",
        action="store_true",
        help="also run each invocation in-process to expose in-process-only assumptions",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(Path(args.manifest))
        report = run_harness(manifest, compare=args.compare)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"PROCESS_BOUNDARY_ERROR: {exc}", file=sys.stderr)
        return 2
    return emit(report, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
