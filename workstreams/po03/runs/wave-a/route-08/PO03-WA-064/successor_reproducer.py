#!/usr/bin/env python3
"""Verify a successor-generation manifest without founder relay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(repo: Path, manifest: dict) -> dict:
    defects = []
    if manifest.get("founder_relay_required") is not False:
        defects.append("founder_relay_not_zero")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        defects.append("empty_successor_manifest")
        entries = []
    seen = set()
    checked = []
    for index, entry in enumerate(entries):
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            defects.append(f"entry_{index}_path_invalid_or_duplicate")
            continue
        seen.add(relative)
        path = repo / relative
        try:
            path.resolve().relative_to(repo.resolve())
        except ValueError:
            defects.append(f"entry_{index}_path_escape")
            continue
        if not path.is_file():
            defects.append(f"entry_{index}_missing")
            continue
        observed = {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size}
        observed["matched"] = (
            observed["sha256"] == entry.get("sha256")
            and observed["bytes"] == entry.get("bytes")
        )
        if not observed["matched"]:
            defects.append(f"entry_{index}_byte_mismatch")
        checked.append(observed)
    return {
        "generation_id": manifest.get("generation_id"),
        "artifacts_declared": len(entries),
        "artifacts_checked": len(checked),
        "founder_relay_count": 0 if manifest.get("founder_relay_required") is False else 1,
        "defects": defects,
        "readback": checked,
        "disposition": "PASS" if entries and not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.repo, json.loads(args.manifest.read_text()))
    report.update(
        {
            "commands": [
                "python3 successor_reproducer.py --repo <fresh-checkout> --manifest <successor-generation.json>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "The reproducer verifies repository bytes and declared commands; it does not perform protected deployment effects."
            ],
            "terminal_report": "READY_TO_COMMIT",
        }
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
