#!/usr/bin/env python3
"""Recurrence harness for PO03-WA-013-A02.

Compares a checkout against ``recurrence-expectations.json``, which was frozen
before this harness was ever run from a clean clone.  Every check is a
comparison against a pinned value, so a clean-clone run either reproduces the
frozen result or reports exactly which value moved.

Checks, in order:

1. fixture manifest digest and every committed fixture's digest and byte count;
2. deterministic regeneration of the fixtures from the committed generator;
3. per-fixture classification and process exit code through the command line;
4. mixed-fleet separation of every recovery disposition in one pass;
5. the live PO-03 ledger's report digest, histogram and integrity;
6. reconstruction of this unit's own attempt lineage from the live ledger;
7. the focused test suite;
8. the seeded PO-03 contract tests;
9. the operator taxonomy check.

Writes nothing outside this unit's owned subtree.  Usage:

    PYTHONDONTWRITEBYTECODE=1 python3 run_recurrence.py [--out recurrence-evidence.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import recovery_scan as rs  # noqa: E402
import make_fixtures  # noqa: E402

EXPECTATIONS = HERE / "recurrence-expectations.json"
FIXTURES = HERE / "fixtures"
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-013/"


def repo_root() -> Path:
    for candidate in [HERE, *HERE.parents]:
        if (candidate / "workstreams" / "po03" / "control" / "events" / "ledger.jsonl").is_file():
            return candidate
    raise SystemExit("UNSCANNABLE: live PO-03 ledger not found above this unit")


def child_env() -> dict[str, str]:
    return {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
    }


class Recorder:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def record(self, name: str, expected: Any, observed: Any, *, detail: str = "") -> bool:
        passed = expected == observed
        entry: dict[str, Any] = {
            "check": name,
            "outcome": "PASS" if passed else "FAIL",
            "expected": expected,
            "observed": observed,
        }
        if detail:
            entry["detail"] = detail
        self.checks.append(entry)
        return passed

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["outcome"] != "PASS"]


def check_fixture_bytes(rec: Recorder, expect: dict[str, Any]) -> None:
    manifest_path = FIXTURES / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    rec.record(
        "fixtures.manifest_sha256",
        expect["fixtures"]["manifest_sha256"],
        hashlib.sha256(manifest_raw).hexdigest(),
    )
    manifest = json.loads(manifest_raw)
    rec.record("fixtures.fixture_count", expect["fixtures"]["fixture_count"], manifest["fixture_count"])
    rec.record(
        "fixtures.total_bytes", expect["fixtures"]["total_fixture_bytes"], manifest["total_fixture_bytes"]
    )
    for entry in manifest["fixtures"]:
        raw = (FIXTURES / entry["fixture"]).read_bytes()
        rec.record(
            f"fixtures.{entry['fixture']}.sha256", entry["sha256"], hashlib.sha256(raw).hexdigest()
        )
        rec.record(f"fixtures.{entry['fixture']}.bytes", entry["bytes"], len(raw))
        for sidecar in entry["sidecars"]:
            blob = (FIXTURES / sidecar["file"]).read_bytes()
            rec.record(
                f"fixtures.{sidecar['file']}.sha256",
                sidecar["sha256"],
                hashlib.sha256(blob).hexdigest(),
            )


def check_regeneration(rec: Recorder) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "fixtures"
        make_fixtures.build(target)
        committed = sorted(path.name for path in FIXTURES.iterdir())
        rec.record(
            "regeneration.file_list", committed, sorted(path.name for path in target.iterdir())
        )
        mismatched = [
            name
            for name in committed
            if (FIXTURES / name).read_bytes() != (target / name).read_bytes()
        ]
        rec.record("regeneration.byte_identical", [], mismatched)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", "-I", str(HERE / "recovery_scan.py"), *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(HERE),
    )


def check_fixture_classifications(rec: Recorder, expect: dict[str, Any]) -> None:
    for name, wanted in sorted(expect["fixture_classifications"].items()):
        number = name.split("-")[1]
        sidecar = FIXTURES / f"fx-{number}-provider-observations.json"
        args = [str(FIXTURES / name), "--now", "2026-08-22T12:00:00Z", "--quiet"]
        if sidecar.is_file():
            args.extend(["--provider-observations", str(sidecar)])
        result = run_cli(*args)
        rec.record(f"{name}.exit_code", wanted["exit_code"], result.returncode, detail=result.stderr.strip())

        observations = json.loads(sidecar.read_bytes()) if sidecar.is_file() else {}
        report = rs.scan(
            (FIXTURES / name).read_bytes(),
            now="2026-08-22T12:00:00Z",
            provider_observations=observations,
        )
        rec.record(f"{name}.integrity", wanted["integrity"], report["integrity"])
        task = next((t for t in report["tasks"] if t["task_id"] == wanted["task"]), None)
        rec.record(f"{name}.task_present", True, task is not None)
        if task is not None:
            rec.record(f"{name}.obzio_state", wanted["obzio_state"], task["obzio_state"])
            rec.record(f"{name}.recovery_action", wanted["recovery_action"], task["recovery_action"])


def check_mixed_fleet(rec: Recorder, expect: dict[str, Any]) -> None:
    wanted = expect["mixed_fleet"]
    raw = (FIXTURES / wanted["fixture"]).read_bytes()
    observations = json.loads((FIXTURES / "fx-16-provider-observations.json").read_bytes())
    report = rs.scan(raw, now="2026-08-22T12:00:00Z", provider_observations=observations)
    for field in (
        "integrity",
        "committed_not_ingested",
        "provider_completed_uncommitted",
        "orphaned_lease_expired",
        "false_completion_admitted",
        "state_histogram",
    ):
        rec.record(f"mixed_fleet.{field}", wanted[field], report[field])


def check_live_ledger(rec: Recorder, expect: dict[str, Any]) -> dict[str, Any]:
    wanted = expect["live_ledger"]
    ledger_path = repo_root() / wanted["path"]
    raw = ledger_path.read_bytes()
    rec.record("live_ledger.sha256", wanted["sha256"], hashlib.sha256(raw).hexdigest())
    rec.record("live_ledger.bytes", wanted["bytes"], len(raw))
    report = rs.scan(raw, now=wanted["evaluation_instant"])
    rec.record("live_ledger.report_sha256", wanted["report_sha256"], rs.report_digest(report))
    rec.record("live_ledger.events_parsed", wanted["events_parsed"], report["ledger"]["events_parsed"])
    rec.record("live_ledger.events_applied", wanted["events_applied"], report["ledger"]["events_applied"])
    rec.record("live_ledger.task_count", wanted["task_count"], report["task_count"])
    rec.record("live_ledger.integrity", wanted["integrity"], report["integrity"])
    rec.record("live_ledger.severity_counts", wanted["severity_counts"], report["severity_counts"])
    rec.record("live_ledger.state_histogram", wanted["state_histogram"], report["state_histogram"])
    for field in (
        "committed_not_ingested",
        "provider_completed_uncommitted",
        "false_completion_admitted",
        "orphaned_lease_expired",
        "unreconstructable_tasks",
    ):
        rec.record(f"live_ledger.{field}", wanted[field], report[field])
    rec.record("live_ledger.exit_code", wanted["exit_code"], rs.exit_code_for(report))

    self_expect = expect["self_reconstruction"]
    task = next((t for t in report["tasks"] if t["task_id"] == self_expect["task_id"]), None)
    rec.record("self_reconstruction.task_present", True, task is not None)
    if task is not None:
        attempt = task["live_attempt"]
        rec.record("self_reconstruction.attempt_id", self_expect["live_attempt_id"], attempt["attempt_id"])
        rec.record("self_reconstruction.fence_token", self_expect["fence_token"], attempt["fence_token"])
        rec.record("self_reconstruction.lease_id", self_expect["lease_id"], attempt["lease_id"])
        rec.record(
            "self_reconstruction.reconstructed_state",
            self_expect["reconstructed_state"],
            attempt["reconstructed_state"],
        )
        rec.record("self_reconstruction.obzio_state", self_expect["obzio_state"], task["obzio_state"])
        superseded = task["superseded_attempts"]
        rec.record("self_reconstruction.superseded_count", 1, len(superseded))
        if superseded:
            rec.record(
                "self_reconstruction.superseded_attempt_id",
                self_expect["superseded_attempt_id"],
                superseded[0]["attempt_id"],
            )
            rec.record(
                "self_reconstruction.superseded_attempt_state",
                self_expect["superseded_attempt_state"],
                superseded[0]["state"],
            )
    return report


TEST_COUNT_RE = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)


def run_suite(rec: Recorder, name: str, argv: list[str], cwd: Path, expected_count: int | None) -> None:
    result = subprocess.run(
        [sys.executable, "-B", *argv], capture_output=True, text=True, env=child_env(), cwd=str(cwd)
    )
    stream = result.stderr + result.stdout
    match = TEST_COUNT_RE.search(stream)
    observed_count = int(match.group(1)) if match else None
    rec.record(f"{name}.exit_code", 0, result.returncode, detail=stream.strip()[-1500:])
    if expected_count is not None:
        rec.record(f"{name}.test_count", expected_count, observed_count)


def check_taxonomy(rec: Recorder, root: Path) -> None:
    script = root / "scripts" / "check_operator_taxonomy.py"
    result = subprocess.run(
        [sys.executable, "-B", str(script)], capture_output=True, text=True, env=child_env(), cwd=str(root)
    )
    rec.record("operator_taxonomy.exit_code", 0, result.returncode, detail=result.stdout.strip())
    rec.record(
        "operator_taxonomy.verdict",
        True,
        "OPERATOR TAXONOMY CHECK: PASS" in result.stdout,
    )


def check_write_boundary(rec: Recorder, root: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(root),
    )
    if result.returncode != 0:
        rec.record("write_boundary.git_available", 0, result.returncode, detail=result.stderr.strip())
        return
    outside = []
    for entry in result.stdout.splitlines():
        path = entry[3:].strip().strip('"')
        if path and not path.startswith(OWNED_PREFIX):
            outside.append(path)
    rec.record("write_boundary.paths_outside_owned_subtree", [], sorted(outside))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "recurrence-evidence.json")
    parser.add_argument("--run-label", default="UNLABELLED")
    args = parser.parse_args(argv)

    expect = json.loads(EXPECTATIONS.read_bytes())
    root = repo_root()
    rec = Recorder()

    check_fixture_bytes(rec, expect)
    check_regeneration(rec)
    check_fixture_classifications(rec, expect)
    check_mixed_fleet(rec, expect)
    check_live_ledger(rec, expect)
    run_suite(
        rec,
        "focused_tests",
        ["-I", "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_recovery_scan.py"],
        HERE,
        expect["test_suites"]["focused"]["expected_count"],
    )
    run_suite(
        rec,
        "seeded_po03_contracts",
        ["-I", "-m", "unittest", "discover", "-s", "workstreams/po03/tests", "-p", "test_*.py"],
        root,
        expect["test_suites"]["seeded_po03_contracts"]["expected_count"],
    )
    check_taxonomy(rec, root)
    check_write_boundary(rec, root)

    failures = rec.failures
    evidence = {
        "protocol_version": "OBZIO-RECURRENCE-EVIDENCE-v1",
        "task_id": "PO03-WA-013",
        "attempt_id": "PO03-WA-013-A02",
        "run_label": args.run_label,
        "expectations_path": "workstreams/po03/wave-a/units/wa-013/result/recurrence-expectations.json",
        "expectations_sha256": hashlib.sha256(EXPECTATIONS.read_bytes()).hexdigest(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "check_count": len(rec.checks),
        "pass_count": len(rec.checks) - len(failures),
        "fail_count": len(failures),
        "outcome": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checks": rec.checks,
        "decision_changed": [],
    }
    payload = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode("utf-8")
    args.out.write_bytes(payload)

    print(f"recurrence outcome={evidence['outcome']} checks={evidence['check_count']} failures={evidence['fail_count']}")
    print(f"evidence_sha256={hashlib.sha256(payload).hexdigest()}")
    for failure in failures[:20]:
        print(f"  FAIL {failure['check']}: expected {failure['expected']!r} observed {failure['observed']!r}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
