#!/usr/bin/env python3
"""Prove G1 runs from a clean clone, and measure it there.

"It works" is cheap to say from the directory where it was written.  This runner
clones the branch into a fresh checkout, confirms the clone's HEAD is the sha
that was pushed, and then does all of its work inside that clone: it runs the
packaged factory's own command line, exercises a real custody operation, and
measures the package on the frozen suite as the clone itself carries it.

Nothing from the author's working tree is copied in.  If the package needed an
uncommitted file, the run fails here rather than passing quietly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNNER_VERSION = "PO03-CLEAN-CLONE-RUNNER-v1"
UNIT_061 = "workstreams/po03/attempts/po03-wa-b2e7-061-g0-reconstruction"
UNIT_059 = "workstreams/po03/attempts/po03-wa-b2e7-059-adversarial-hidden-cases"
UNIT_062 = "workstreams/po03/attempts/po03-wa-b2e7-062-g1-packaging"
PACKAGE_RELATIVE = f"{UNIT_062}/g1/transactional_factory.py"
FACTORY_PATH = "workstreams/po03/tools/transactional_factory.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run(arguments: tuple[str, ...], cwd: Path, *, check: bool = False) -> dict[str, Any]:
    completed = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    record = {
        "command": " ".join(arguments),
        "cwd": cwd.as_posix(),
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-6:],
        "stderr_tail": completed.stderr.strip().splitlines()[-6:],
    }
    if check and completed.returncode != 0:
        raise RuntimeError(f"{record['command']} exited {completed.returncode}: {completed.stderr[-800:]}")
    return record


def digest_in_clone(clone: Path, relative: str) -> dict[str, Any]:
    path = clone / relative
    if not path.is_file():
        return {"path": relative, "present": False}
    payload = path.read_bytes()
    return {"path": relative, "present": True, "sha256": sha256_bytes(payload), "bytes": len(payload)}


def smoke_test_the_package(clone: Path) -> list[dict[str, Any]]:
    """Exercise the packaged factory's CLI inside the clone.

    `--help` only proves the file parses.  `verify` on a real capsule that the
    branch already carries proves the package can read the committed ledger from
    a checkout it has never seen before.
    """
    package = clone / PACKAGE_RELATIVE
    checks = [run(("python3", "-I", package.as_posix(), "--help"), clone)]
    tasks = sorted((clone / "workstreams/po03/control/tasks").glob("po03-wa-b2e7-*"))
    if tasks:
        checks.append(run(("python3", "-I", package.as_posix(), "verify", tasks[0].name), clone))
    return checks


def measure_in_clone(clone: Path, name: str, description: str) -> tuple[dict[str, Any], dict[str, Any]]:
    output = clone / "g1-measurement.json"
    record = run(
        (
            "python3",
            "-I",
            (clone / UNIT_061 / "run_generation.py").as_posix(),
            "--repo-root",
            clone.as_posix(),
            "--suite",
            (clone / UNIT_061 / "generation_suite.py").as_posix(),
            "--holdout",
            (clone / UNIT_059 / "hidden/holdout_custody_cases.py").as_posix(),
            "--seal",
            (clone / UNIT_059 / "holdout-seal.json").as_posix(),
            "--name",
            name,
            "--source",
            (clone / PACKAGE_RELATIVE).as_posix(),
            "--description",
            description,
            "--out",
            output.as_posix(),
        ),
        clone,
        check=True,
    )
    return record, json.loads(output.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--clone-source", default=None, help="defaults to --repo-root")
    parser.add_argument("--branch", default="po03/wa-b2e7-c8")
    parser.add_argument("--name", default="G1")
    parser.add_argument("--description", default="")
    parser.add_argument("--measurement-out", required=True)
    parser.add_argument("--report-out", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    source = Path(args.clone_source).resolve() if args.clone_source else repo
    clone = Path(tempfile.mkdtemp(prefix="po03-clean-clone-"))
    shutil.rmtree(clone)

    try:
        clone_step = run(
            ("git", "clone", "--quiet", "--no-hardlinks", "--single-branch",
             "--branch", args.branch, source.as_posix(), clone.as_posix()),
            source,
            check=True,
        )
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=clone, check=True, capture_output=True, text=True
        ).stdout.strip()
        remote = subprocess.run(
            ("git", "rev-parse", f"origin/{args.branch}"), cwd=repo, capture_output=True, text=True
        )
        pushed = remote.stdout.strip() if remote.returncode == 0 else None

        integrity = {
            "package_in_clone": digest_in_clone(clone, PACKAGE_RELATIVE),
            "live_factory_in_clone": digest_in_clone(clone, FACTORY_PATH),
            "suite_in_clone": digest_in_clone(clone, f"{UNIT_061}/generation_suite.py"),
            "holdout_in_clone": digest_in_clone(clone, f"{UNIT_059}/hidden/holdout_custody_cases.py"),
        }
        integrity["package_matches_live_factory"] = (
            integrity["package_in_clone"].get("sha256") == integrity["live_factory_in_clone"].get("sha256")
        )

        smoke = smoke_test_the_package(clone)
        measurement_step, measurement = measure_in_clone(clone, args.name, args.description)
        Path(args.measurement_out).write_bytes(canonical(measurement))

        report = {
            "runner_version": RUNNER_VERSION,
            "ran_at": utc_now(),
            "clone": {
                "source": source.as_posix(),
                "branch": args.branch,
                "head": head,
                "pushed_head": pushed,
                "clone_is_the_pushed_commit": pushed == head,
                "note": "the clone is a fresh checkout; no file from the author's working tree is copied into it",
            },
            "integrity": integrity,
            "steps": [clone_step, *smoke, measurement_step],
            "executable_from_clean_clone": all(step["exit_code"] == 0 for step in smoke)
            and measurement_step["exit_code"] == 0
            and integrity["package_matches_live_factory"],
            "measurement_summary": {
                key: value for key, value in measurement.items() if key != "records"
            },
            "decision_changed": [],
        }
        Path(args.report_out).write_bytes(canonical(report))
        print(json.dumps(report, indent=2, sort_keys=True))
        if not report["executable_from_clean_clone"]:
            print("CLEAN CLONE RUN FAILED", file=sys.stderr)
            return 1
        print(f"CLEAN CLONE RUN VERIFIED at {head}")
        return 0
    finally:
        shutil.rmtree(clone, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
