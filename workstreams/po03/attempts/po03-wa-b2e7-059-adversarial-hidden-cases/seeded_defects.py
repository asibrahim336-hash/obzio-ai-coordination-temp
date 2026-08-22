#!/usr/bin/env python3
"""Seeded defects and the two detection arms that are measured against them.

Each defect is an exact source mutation of the frozen contract validator, which
this cohort did not author.  A mutation that does not apply byte-exactly is
recorded as NOT_APPLIED and excluded from the differential, so a stale mutation
can never inflate a detection score.

Arm A is the producer-visible suite that ships in the repository.  Arm B is the
evaluator-held hidden case set.  Both arms run against the same mutant, in
separate processes, from a sandbox whose layout mirrors the repository so the
producer suite loads the mutant rather than the real tool.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFECT_CATALOGUE_VERSION = "PO03-SEEDED-DEFECTS-v1"
TARGET = "workstreams/po03/tools/validate_contracts.py"
PRODUCER_SUITE = "workstreams/po03/tests/test_validate_contracts.py"

SEEDED_DEFECTS: list[dict[str, str]] = [
    {
        "defect_id": "D01-worker-may-set-completed",
        "hazard": "a subordinate can turn provider completion into Obzio completion",
        "old": '    if state == "COMPLETED" and doc["completion_actor"] != "coordinator":',
        "new": '    if False and doc["completion_actor"] != "coordinator":',
    },
    {
        "defect_id": "D02-uppercase-hash-accepted",
        "hazard": "hash comparison becomes case-insensitive, so two spellings of one digest diverge",
        "old": 'SHA256_RE = re.compile(r"^[0-9a-f]{64}$")',
        "new": 'SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")',
    },
    {
        "defect_id": "D03-total-bytes-unchecked",
        "hazard": "a manifest can claim byte counts that its artifacts do not add up to",
        "old": '    if txn["total_bytes"] != byte_sum:',
        "new": "    if False:",
    },
    {
        "defect_id": "D04-zero-byte-artifact-accepted",
        "hazard": "an empty file counts as a durable artifact",
        "old": '        if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 1:',
        "new": '        if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:',
    },
    {
        "defect_id": "D05-duplicate-artifact-ids-accepted",
        "hazard": "one artifact counted twice inflates the artifact count",
        "old": '        if artifact["artifact_id"] in artifact_ids:',
        "new": "        if False:",
    },
    {
        "defect_id": "D06-self-acceptance-allowed",
        "hazard": "the producer accepts its own work as the independent reviewer",
        "old": '            if acceptance.get("reviewer_id") == attempt.get("worker_id"):',
        "new": "            if False:",
    },
    {
        "defect_id": "D07-provider-completion-ungated",
        "hazard": "provider completion without a durable commit is accepted as a real outcome",
        "old": '    if provider_state == "COMPLETED" and not _nonempty(txn["result_commit_id"]):',
        "new": '    if False and not _nonempty(txn["result_commit_id"]):',
    },
    {
        "defect_id": "D08-wave-decision-changed-unchecked",
        "hazard": "a compounding receipt can silently record a founder decision reversal",
        "old": '    if doc["decision_changed"] != []:',
        "new": "    if False:",
    },
    {
        "defect_id": "D09-wave-empty-arrays-accepted",
        "hazard": "a compounding receipt with no observations or reproductions passes",
        "old": "        if not isinstance(doc[field], list) or not doc[field]:",
        "new": "        if not isinstance(doc[field], list):",
    },
    {
        "defect_id": "D10-wave-baseline-hash-unchecked",
        "hazard": "the baseline a lift claim rests on is not pinned to a digest",
        "old": (
            '    if not isinstance(baseline, dict) or not _nonempty(baseline.get("metrics_uri")) '
            'or not _sha256(baseline.get("sha256")):'
        ),
        "new": '    if not isinstance(baseline, dict) or not _nonempty(baseline.get("metrics_uri")):',
    },
    {
        "defect_id": "D11-artifact-count-unchecked",
        "hazard": "a result can claim more artifacts than it carries",
        "old": '    if txn["artifact_count"] != len(artifacts):',
        "new": "    if False:",
    },
    {
        "defect_id": "D12-terminal-review-without-completion",
        "hazard": "an acceptance is recorded against a result that was never completed",
        "old": '            if state != "COMPLETED":',
        "new": "            if False:",
    },
]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_sandbox(repo: Path, defect: dict[str, str] | None) -> tuple[Path, bool]:
    """Materialise a sandbox mirroring the repository layout, optionally mutated."""
    root = Path(tempfile.mkdtemp(prefix="po03-059-"))
    (root / "workstreams/po03/tools").mkdir(parents=True)
    (root / "workstreams/po03/tests").mkdir(parents=True)
    source = (repo / TARGET).read_text(encoding="utf-8")
    applied = True
    if defect is not None:
        if defect["old"] not in source:
            applied = False
        else:
            source = source.replace(defect["old"], defect["new"], 1)
    (root / TARGET).write_text(source, encoding="utf-8")
    shutil.copy2(repo / PRODUCER_SUITE, root / PRODUCER_SUITE)
    return root, applied


def run_producer_arm(sandbox: Path) -> dict[str, Any]:
    """Run the repository's own producer-visible suite against the sandbox tool."""
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(sandbox / "workstreams/po03/tests"),
            "-p",
            "test_validate_contracts.py",
        ),
        cwd=sandbox,
        capture_output=True,
        text=True,
    )
    tail = completed.stderr.strip().splitlines()[-1:] or [""]
    return {
        "arm": "producer_visible_suite",
        "exit_code": completed.returncode,
        "killed": completed.returncode != 0,
        "summary": tail[0],
    }


def run_hidden_arm(sandbox: Path, hidden_module_path: Path) -> dict[str, Any]:
    """Run the evaluator-held hidden cases against the sandbox tool."""
    module = load_module(sandbox / TARGET, "po03_059_target")
    hidden = load_module(hidden_module_path, "po03_059_hidden")
    detections = [name for name, case in sorted(hidden.HIDDEN_CASES.items()) if case(module)]
    control_failures = [name for name, case in sorted(hidden.CONTROL_CASES.items()) if case(module)]
    return {
        "arm": "evaluator_held_hidden_cases",
        "killed": bool(detections),
        "detections": detections,
        "detection_count": len(detections),
        "control_failures": control_failures,
        "case_count": len(hidden.HIDDEN_CASES),
    }


def measure(repo: Path, hidden_module_path: Path) -> dict[str, Any]:
    """Measure both arms against every applicable seeded defect."""
    baseline_sandbox, _ = build_sandbox(repo, None)
    try:
        baseline_producer = run_producer_arm(baseline_sandbox)
        baseline_hidden = run_hidden_arm(baseline_sandbox, hidden_module_path)
    finally:
        shutil.rmtree(baseline_sandbox, ignore_errors=True)

    records: list[dict[str, Any]] = []
    for defect in SEEDED_DEFECTS:
        sandbox, applied = build_sandbox(repo, defect)
        try:
            if not applied:
                records.append(
                    {
                        "defect_id": defect["defect_id"],
                        "hazard": defect["hazard"],
                        "mutation_state": "NOT_APPLIED",
                        "note": "the seeded mutation did not match the current tool source byte-exactly",
                    }
                )
                continue
            producer = run_producer_arm(sandbox)
            hidden = run_hidden_arm(sandbox, hidden_module_path)
            records.append(
                {
                    "defect_id": defect["defect_id"],
                    "hazard": defect["hazard"],
                    "mutation_state": "APPLIED",
                    "producer_arm": producer,
                    "hidden_arm": hidden,
                    "killed_by": sorted(
                        arm
                        for arm, killed in (
                            ("producer_visible_suite", producer["killed"]),
                            ("evaluator_held_hidden_cases", hidden["killed"]),
                        )
                        if killed
                    ),
                }
            )
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    applied_records = [record for record in records if record["mutation_state"] == "APPLIED"]
    producer_kills = [r["defect_id"] for r in applied_records if r["producer_arm"]["killed"]]
    hidden_kills = [r["defect_id"] for r in applied_records if r["hidden_arm"]["killed"]]
    hidden_only = sorted(set(hidden_kills) - set(producer_kills))
    producer_only = sorted(set(producer_kills) - set(hidden_kills))
    survivors = sorted(
        r["defect_id"] for r in applied_records
        if not r["producer_arm"]["killed"] and not r["hidden_arm"]["killed"]
    )
    return {
        "differential_version": DEFECT_CATALOGUE_VERSION,
        "target": TARGET,
        "producer_suite": PRODUCER_SUITE,
        "baseline": {
            "producer_arm_on_unmutated_tool": baseline_producer,
            "hidden_arm_on_unmutated_tool": baseline_hidden,
            "false_positive_free": not baseline_producer["killed"] and not baseline_hidden["killed"],
        },
        "defects_seeded": len(SEEDED_DEFECTS),
        "defects_applied": len(applied_records),
        "defects_not_applied": [r["defect_id"] for r in records if r["mutation_state"] == "NOT_APPLIED"],
        "producer_kill_count": len(producer_kills),
        "hidden_kill_count": len(hidden_kills),
        "hidden_only_kills": hidden_only,
        "producer_only_kills": producer_only,
        "survivors": survivors,
        "records": records,
        "decision_changed": [],
    }


def hypothesis_verdict(differential: dict[str, Any]) -> dict[str, Any]:
    """Answer the unit hypothesis from the measured differential."""
    hidden_only = differential["hidden_only_kills"]
    applied = differential["defects_applied"]
    return {
        "hypothesis": "Hidden evaluator-held cases detect defects that producer-authored tests miss.",
        "verdict": "PASS" if hidden_only else ("NOT_YET" if applied else "NOT_SUPPORTED"),
        "hidden_only_kill_count": len(hidden_only),
        "hidden_only_kills": hidden_only,
        "producer_kill_rate": (
            differential["producer_kill_count"] / applied if applied else None
        ),
        "hidden_kill_rate": differential["hidden_kill_count"] / applied if applied else None,
        "basis": (
            "The hypothesis holds only if at least one applied seeded defect is killed by the hidden "
            "arm and survives the producer-visible suite. A defect killed by both arms is not "
            "evidence for the hypothesis."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--hidden-cases", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    differential = measure(Path(args.repo_root).resolve(), Path(args.hidden_cases).resolve())
    payload = {**differential, "hypothesis": hypothesis_verdict(differential)}
    if args.out:
        Path(args.out).write_bytes(
            (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
