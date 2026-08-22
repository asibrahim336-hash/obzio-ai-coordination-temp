#!/usr/bin/env python3
"""Build the non-circular route-08 successor-generation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


EXCLUDED = {
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/successor-generation.json",
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/observed-result.json",
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/manifest.json",
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/result.json",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    files = subprocess.run(
        ["git", "ls-files", "workstreams/po03/runs/wave-a/route-08"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    entries = []
    for relative in sorted(set(files) - EXCLUDED):
        path = repo / relative
        payload = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    manifest = {
        "manifest_version": "PO03-WA-SUCCESSOR-GENERATION-v1",
        "generation_id": "PO03-WAVE-A-G2-ROUTE-08",
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "founder_relay_required": False,
        "reproduction_command": (
            "python3 workstreams/po03/runs/wave-a/route-08/PO03-WA-064/"
            "successor_reproducer.py --repo . --manifest workstreams/po03/runs/wave-a/"
            "route-08/PO03-WA-064/successor-generation.json"
        ),
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": sum(row["bytes"] for row in entries),
        "decision_changed": [],
    }
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifacts": len(entries), "total_bytes": manifest["total_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
