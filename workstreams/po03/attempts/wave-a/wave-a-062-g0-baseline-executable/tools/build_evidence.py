#!/usr/bin/env python3
"""Build deterministic provenance for the immutable G0/post-head boundary."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = UNIT_ROOT.parents[4]
HISTORICAL_HEAD = "1bb843b2a81fd8d73617caf2f1db81909266bb6e"
DISPATCH_BASE = "f5a01aa71b3a17d66eb2211cf45c50b62df207ef"


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def git_text(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def build() -> dict[str, Any]:
    if subprocess.run(
        ("git", "merge-base", "--is-ancestor", HISTORICAL_HEAD, DISPATCH_BASE),
        cwd=REPO_ROOT,
    ).returncode:
        raise ValueError("historical head is not an ancestor of dispatch base")

    commits = []
    log = git_text(
        "log",
        "--reverse",
        "--format=%H%x1f%aI%x1f%s",
        f"{HISTORICAL_HEAD}..{DISPATCH_BASE}",
    )
    for line in log.splitlines():
        commit, authored_at, subject = line.split("\x1f", 2)
        commits.append(
            {"commit": commit, "authored_at": authored_at, "subject": subject}
        )

    changed_paths = []
    for line in git_text(
        "diff", "--name-status", HISTORICAL_HEAD, DISPATCH_BASE
    ).splitlines():
        fields = line.split("\t")
        changed_paths.append({"status": fields[0], "paths": fields[1:]})

    insertions = 0
    deletions = 0
    binary_files = 0
    for line in git_text("diff", "--numstat", HISTORICAL_HEAD, DISPATCH_BASE).splitlines():
        added, removed, _path = line.split("\t", 2)
        if added == "-" or removed == "-":
            binary_files += 1
        else:
            insertions += int(added)
            deletions += int(removed)

    mechanism_paths = {
        ".github/workflows/po03-contracts.yml",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "workstreams/po03/tests/test_path_scope.py",
        "workstreams/po03/tests/test_transactional_factory.py",
        "workstreams/po03/tests/test_validate_contracts.py",
        "workstreams/po03/tools/register_wave_a.py",
        "workstreams/po03/tools/transactional_factory.py",
        "workstreams/po03/tools/validate_contracts.py",
    }
    mechanism_changes = [
        entry
        for entry in changed_paths
        if any(path in mechanism_paths for path in entry["paths"])
    ]
    historical_paths = set(
        git_text("ls-tree", "-r", "--name-only", HISTORICAL_HEAD).splitlines()
    )
    evidence_checks = [
        {
            "evidence": "historical public generation suite",
            "repository_path": "workstreams/po03/successor/g0/fixture-suite.json",
        },
        {
            "evidence": "historical G0 observed outputs",
            "repository_path": "workstreams/po03/successor/g0/observed-results.json",
        },
        {
            "evidence": "historical generation comparison metrics",
            "repository_path": "workstreams/po03/metrics/generation-comparison.json",
        },
    ]
    for check in evidence_checks:
        check["state_at_historical_head"] = (
            "PRESENT" if check["repository_path"] in historical_paths else "ABSENT"
        )

    return {
        "evidence_version": "PO03-G0-POST-HEAD-ADDITIONS-v1",
        "task_id": "wave-a-062-g0-baseline-executable",
        "historical_controller_head": HISTORICAL_HEAD,
        "dispatch_base": DISPATCH_BASE,
        "relationship": "HISTORICAL_HEAD_IS_ANCESTOR",
        "range": f"{HISTORICAL_HEAD}..{DISPATCH_BASE}",
        "summary": {
            "commit_count": len(commits),
            "changed_file_count": len(changed_paths),
            "insertions": insertions,
            "deletions": deletions,
            "binary_file_count": binary_files,
        },
        "controller_mechanism_changes": mechanism_changes,
        "commits": commits,
        "changed_paths": changed_paths,
        "historical_generation_evidence": evidence_checks,
        "execution_policy": (
            "All additions in this range are disclosed and excluded from G0 source execution."
        ),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=UNIT_ROOT / "evidence" / "post-head-additions.json",
    )
    args = parser.parse_args(argv)
    try:
        document = build()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json(document))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"EVIDENCE_BUILD_ERROR: {exc}")
        return 2
    print(
        f"EVIDENCE_BUILD_PASS output={args.output.as_posix()} "
        f"commits={document['summary']['commit_count']} "
        f"changed_files={document['summary']['changed_file_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
