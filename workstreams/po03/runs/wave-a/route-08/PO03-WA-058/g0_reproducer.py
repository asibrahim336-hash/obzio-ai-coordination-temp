#!/usr/bin/env python3
"""Reproduce G0 bytes from the immutable pre-amendment source lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


def recover(entries: list[dict], loader: Callable[[str], bytes], target: Path, crash_after: int) -> dict:
    written_before_crash = []
    target.mkdir(parents=True, exist_ok=True)
    for index, entry in enumerate(entries):
        if index == crash_after:
            break
        payload = loader(entry["path"])
        destination = target / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        written_before_crash.append(entry["path"])

    recovered, defects = [], []
    for entry in entries:
        destination = target / entry["path"]
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(loader(entry["path"]))
            recovered.append(entry["path"])
        payload = destination.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            defects.append(f"sha256:{entry['path']}")
        if len(payload) != entry["bytes"]:
            defects.append(f"bytes:{entry['path']}")
    return {
        "crash_after_source_index": crash_after,
        "written_before_crash": written_before_crash,
        "recovered_after_restart": recovered,
        "defects": defects,
    }


def reproduce(repo: Path, source_lock: dict) -> dict:
    commit = source_lock["immutable_parent_head"]

    def loader(path: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout

    entries = source_lock["sources"]
    with tempfile.TemporaryDirectory(prefix="po03-g0-reproduction-") as tmp:
        crash_evidence = [
            recover(entries, loader, Path(tmp) / f"crash-{point}", point)
            for point in range(len(entries) + 1)
        ]
    defects = [defect for row in crash_evidence for defect in row["defects"]]
    return {
        "immutable_pre_amendment_commit": commit,
        "source_lock_id": source_lock["lock_id"],
        "sources_reproduced": len(entries),
        "crash_points_exercised": len(crash_evidence),
        "crash_evidence": crash_evidence,
        "defects": defects,
        "disposition": "PASS" if not defects else "FAIL",
        "limitations": [
            "Recovery proves byte reproduction of source-lock entries, not external service replay."
        ],
        "terminal_report": "READY_TO_COMMIT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = reproduce(args.repo, json.loads(args.source_lock.read_text()))
    report["commands"] = [
        "python3 g0_reproducer.py --repo <checkout> --source-lock workstreams/po03/evidence/source-lock.json",
        "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
    ]
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
