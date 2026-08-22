#!/usr/bin/env python3
"""Build and verify route-08 manifest and immutable blob receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


BASE = "081a7d709dee1af1ca47c1c69eb60085b9e59cd5"
CANARY = "3a19607985c137f0c812b582a000fce966507987"
PREFIX = "workstreams/po03/runs/wave-a/route-08/"
EXCLUDED = {PREFIX + "_route/manifest.json", PREFIX + "_route/receipt.json"}


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def tracked(repo: Path) -> list[str]:
    return sorted(
        set(run(repo, "ls-files", PREFIX).stdout.decode().splitlines()) - EXCLUDED
    )


def build_manifest(repo: Path) -> dict:
    entries = []
    for relative in tracked(repo):
        payload = (repo / relative).read_bytes()
        entries.append({"path": relative, "sha256": sha(payload), "bytes": len(payload)})
    return {
        "manifest_version": "PO03-WA-ROUTE-08-MANIFEST-v1",
        "branch": "cursor/po03-wa-route-08-material-6e19",
        "base_commit": BASE,
        "source_head": run(repo, "rev-parse", "HEAD").stdout.decode().strip(),
        "owned_prefix": PREFIX,
        "excluded_self_referential_paths": sorted(EXCLUDED),
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": sum(row["bytes"] for row in entries),
        "decision_changed": [],
    }


def build_receipt(repo: Path, manifest_path: Path, commit: str) -> dict:
    manifest = json.loads(manifest_path.read_text())
    readback, defects = [], []
    for entry in manifest["artifacts"]:
        try:
            payload = run(repo, "show", f"{commit}:{entry['path']}").stdout
        except subprocess.CalledProcessError:
            defects.append(f"missing_blob:{entry['path']}")
            continue
        row = {
            "path": entry["path"],
            "sha256": sha(payload),
            "bytes": len(payload),
            "matched": sha(payload) == entry["sha256"] and len(payload) == entry["bytes"],
        }
        if not row["matched"]:
            defects.append(f"blob_mismatch:{entry['path']}")
        readback.append(row)
    manifest_relative = manifest_path.relative_to(repo).as_posix()
    manifest_blob = run(repo, "show", f"{commit}:{manifest_relative}").stdout
    manifest_worktree = manifest_path.read_bytes()
    if manifest_blob != manifest_worktree:
        defects.append("manifest_blob_mismatch")
    changed = run(repo, "diff", "--name-only", f"{BASE}..{commit}").stdout.decode().splitlines()
    outside = sorted(path for path in changed if not path.startswith(PREFIX))
    if outside:
        defects.append("outside_owned_prefix")
    canary_relation = run(repo, "merge-base", "--is-ancestor", BASE, CANARY, check=False).returncode == 0
    ordered_commits = run(
        repo, "log", "--reverse", "--format=%H%x09%s", f"{BASE}..{commit}"
    ).stdout.decode().splitlines()
    return {
        "receipt_version": "PO03-WA-ROUTE-08-CUSTODY-RECEIPT-v1",
        "branch": manifest["branch"],
        "base_commit": BASE,
        "readback_commit": commit,
        "manifest": {
            "uri": manifest_relative,
            "sha256": sha(manifest_blob),
            "bytes": len(manifest_blob),
            "artifact_count": manifest["artifact_count"],
            "total_bytes": manifest["total_bytes"],
            "blob_matched_worktree": manifest_blob == manifest_worktree,
        },
        "blob_readback": readback,
        "blob_readback_matched": sum(row["matched"] for row in readback),
        "blob_readback_expected": len(manifest["artifacts"]),
        "path_ownership": {
            "changed_paths": changed,
            "outside_owned_prefix": outside,
            "passed": not outside,
        },
        "ordered_commits": ordered_commits,
        "recovery_events": [
            {
                "event": "CANARY_SIDE_HISTORY_READBACK",
                "canary_commit": CANARY,
                "base_is_ancestor_of_canary": canary_relation,
                "effect": "recorded; lease grant at exact base remained the launch authority",
            }
        ],
        "collision_events": [],
        "defects": defects,
        "decision_changed": [],
        "status": "READY_TO_COMMIT" if not defects else "RECOVERY_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("manifest", "receipt"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--commit")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.action == "manifest":
        document = build_manifest(repo)
    else:
        if args.manifest is None or args.commit is None:
            parser.error("receipt requires --manifest and --commit")
        document = build_receipt(repo, args.manifest.resolve(), args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "action": args.action,
                "status": document.get("status", "BUILT"),
                "artifacts": document.get("artifact_count", document.get("blob_readback_expected")),
                "defects": document.get("defects", []),
            },
            sort_keys=True,
        )
    )
    return 1 if document.get("defects") else 0


if __name__ == "__main__":
    raise SystemExit(main())
