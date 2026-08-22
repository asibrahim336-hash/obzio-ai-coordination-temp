#!/usr/bin/env python3
"""Run recursively discovered PO-03 tests under isolated interpreter matrices."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MISSING_IMPORT = re.compile(
    r"(?:ModuleNotFoundError|ImportError):[^\n]*?(?:named |from )['\"]?([A-Za-z0-9_.-]+)"
)
MATRICES = (("-I",), ("-I", "-S"))


def execute(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def discover(clone: Path, commit: str) -> list[str]:
    listing = execute(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", "workstreams/po03"],
        clone,
    )
    if listing.returncode:
        raise RuntimeError("cannot enumerate committed tests")
    return sorted(
        path
        for path in listing.stdout.split("\0")
        if path and Path(path).name.startswith("test_") and path.endswith(".py")
    )


def run_matrix(source: Path, commit: str, workspace: Path) -> tuple[int, dict[str, object]]:
    if not source.exists() or not OBJECT_ID.fullmatch(commit):
        return 2, {"error": "source must exist and commit must be a full object ID"}
    if workspace.exists() or not workspace.parent.is_dir():
        return 2, {"error": "workspace must be absent and its parent must exist"}
    workspace.mkdir()
    clone = workspace / "clone"
    try:
        cloned = execute(
            ["git", "clone", "--quiet", "--no-checkout", str(source), str(clone)],
            source,
        )
        if cloned.returncode:
            return 2, {"error": "clone failed", "stderr": cloned.stderr}
        checkout = execute(["git", "checkout", "--quiet", "--detach", commit], clone)
        if checkout.returncode:
            return 2, {"error": "checkout failed", "stderr": checkout.stderr}
        tests = discover(clone, commit)
        if not tests:
            return 2, {"error": "no committed PO-03 tests found"}

        cases: list[dict[str, object]] = []
        escaped_imports: list[dict[str, str]] = []
        for index, flags in enumerate(MATRICES, start=1):
            runtime = workspace / f"runtime-{index}"
            runtime.mkdir()
            environment = {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": os.environ.get("PATH", ""),
                "TMPDIR": str(runtime),
            }
            try:
                for path in tests:
                    result = execute(
                        [sys.executable, *flags, "-B", path],
                        clone,
                        environment,
                    )
                    record: dict[str, object] = {
                        "flags": list(flags),
                        "path": path,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                    cases.append(record)
                    for module in MISSING_IMPORT.findall(result.stdout + result.stderr):
                        escaped_imports.append(
                            {
                                "flags": " ".join(flags),
                                "path": path,
                                "module": module,
                            }
                        )
            finally:
                shutil.rmtree(runtime)
        failed = [
            {"flags": item["flags"], "path": item["path"]}
            for item in cases
            if item["returncode"] != 0
        ]
        status = execute(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            clone,
        )
        clean = status.returncode == 0 and not status.stdout
        report: dict[str, object] = {
            "commit": commit,
            "test_file_count": len(tests),
            "matrix_case_count": len(cases),
            "matrices": [list(flags) for flags in MATRICES],
            "failed_cases": failed,
            "imports_escaping_standard_environment": escaped_imports,
            "clean_after_run": clean,
            "cases": cases,
        }
        return (0 if not failed and not escaped_imports and clean else 1), report
    except RuntimeError as exc:
        return 2, {"error": str(exc)}
    finally:
        shutil.rmtree(workspace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args(argv)
    code, report = run_matrix(
        args.source.resolve(), args.commit, args.workspace.resolve()
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
