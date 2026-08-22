#!/usr/bin/env python3
"""Read every durable artifact of this attempt back from immutable Git bytes.

Intended to be run from a separate fresh read-only clone of the result branch,
by a process that did not produce the artifacts. It proves four things:

1. every durable file in the result slot is readable at the given ref and its
   SHA-256 and byte count are recomputed from Git blob bytes rather than from a
   working-tree copy;
2. the full base..result change set is confined to the owned slot;
3. the local ref equals the remote branch tip exactly;
4. when a manifest is present at the ref, it declares exactly the durable set
   minus itself, with matching hashes and byte counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


TASK_ID = "wave-a-043-path-scope-adversarial-review"
RESULT_SLOT = "workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review"
DISPATCH_BASE = "06210fb82ba2b0b9e30b2a9c752ca781c0d2d466"
RESULT_BRANCH = "po03/wave-a-043-path-scope-adversarial-review"
MANIFEST_NAME = "manifest.json"


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    return subprocess.run(
        ("git", *args), cwd=str(repo), capture_output=True, check=check
    ).stdout


def blob_bytes(repo: Path, ref: str, path: str) -> bytes:
    return git(repo, "cat-file", "blob", f"{ref}:{path}")


def slot_files(repo: Path, ref: str) -> list[str]:
    raw = git(repo, "ls-tree", "-r", "--name-only", "-z", ref, "--", RESULT_SLOT)
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def changed_paths(repo: Path, base: str, ref: str) -> list[str]:
    raw = git(repo, "diff", "--name-only", "-z", f"{base}...{ref}")
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--base", default=DISPATCH_BASE)
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    ref = args.ref
    head = git(repo, "rev-parse", ref).decode().strip()

    files = slot_files(repo, ref)
    artifacts = []
    for path in files:
        data = blob_bytes(repo, ref, path)
        artifacts.append(
            {
                "path": path,
                "slot_relative_path": path[len(RESULT_SLOT) + 1 :],
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "git_blob_sha1": git(repo, "rev-parse", f"{ref}:{path}").decode().strip(),
            }
        )

    changed = changed_paths(repo, args.base, ref)
    outside = [p for p in changed if not p.startswith(RESULT_SLOT + "/")]

    remote = git(repo, "ls-remote", "origin", RESULT_BRANCH).decode().split()
    remote_tip = remote[0] if remote else None

    manifest_state = "ABSENT_AT_REF"
    manifest_checks: dict = {}
    if f"{RESULT_SLOT}/{MANIFEST_NAME}" in files:
        manifest = json.loads(blob_bytes(repo, ref, f"{RESULT_SLOT}/{MANIFEST_NAME}"))
        declared = {a["path"]: a for a in manifest["artifacts"]}
        durable = {
            a["slot_relative_path"]: a
            for a in artifacts
            if a["slot_relative_path"] != MANIFEST_NAME
        }
        mismatched = sorted(
            name
            for name in declared.keys() & durable.keys()
            if declared[name]["sha256"] != durable[name]["sha256"]
            or declared[name]["bytes"] != durable[name]["bytes"]
        )
        manifest_checks = {
            "declared_count": manifest["artifact_count"],
            "declared_total_bytes": manifest["total_artifact_bytes_excluding_manifest"],
            "recomputed_count": len(durable),
            "recomputed_total_bytes": sum(a["bytes"] for a in durable.values()),
            "declared_but_absent": sorted(declared.keys() - durable.keys()),
            "durable_but_undeclared": sorted(durable.keys() - declared.keys()),
            "hash_or_size_mismatches": mismatched,
            "manifest_declares_itself": MANIFEST_NAME in declared,
            "top_level_fields_present": sorted(
                field
                for field in (
                    "task_id",
                    "result_slot",
                    "decision_changed",
                    "artifact_count",
                    "total_artifact_bytes_excluding_manifest",
                    "artifacts",
                )
                if field in manifest
            ),
            "task_id_matches": manifest.get("task_id") == TASK_ID,
            "result_slot_matches": manifest.get("result_slot") == RESULT_SLOT,
            "decision_changed_empty": manifest.get("decision_changed") == [],
        }
        manifest_checks["pass"] = (
            not manifest_checks["declared_but_absent"]
            and not manifest_checks["durable_but_undeclared"]
            and not manifest_checks["hash_or_size_mismatches"]
            and not manifest_checks["manifest_declares_itself"]
            and manifest_checks["declared_count"] == manifest_checks["recomputed_count"]
            and manifest_checks["declared_total_bytes"] == manifest_checks["recomputed_total_bytes"]
            and manifest_checks["task_id_matches"]
            and manifest_checks["result_slot_matches"]
            and manifest_checks["decision_changed_empty"]
            and len(manifest_checks["top_level_fields_present"]) == 6
        )
        manifest_state = "VERIFIED" if manifest_checks["pass"] else "FAILED"

    document = {
        "readback_version": "PO03-WAVE-A-043-READBACK-v1",
        "task_id": TASK_ID,
        "decision_changed": [],
        "performed_in": str(repo),
        "performed_by": "a separate fresh read-only clone, not the producing checkout",
        "ref": ref,
        "head_commit": head,
        "dispatch_base": args.base,
        "result_branch": RESULT_BRANCH,
        "remote_tip": remote_tip,
        "remote_tip_equals_head": remote_tip == head,
        "artifact_count": len(artifacts),
        "total_bytes": sum(a["bytes"] for a in artifacts),
        "changed_paths_base_to_ref": changed,
        "changed_path_count": len(changed),
        "paths_outside_owned_slot": outside,
        "path_confinement": "PASS" if not outside else "FAIL",
        "manifest_state": manifest_state,
        "manifest_checks": manifest_checks,
        "artifacts": artifacts,
    }

    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "head_commit": head,
                "remote_tip_equals_head": document["remote_tip_equals_head"],
                "changed_path_count": document["changed_path_count"],
                "path_confinement": document["path_confinement"],
                "artifact_count": document["artifact_count"],
                "manifest_state": manifest_state,
            },
            indent=2,
            sort_keys=True,
        )
    )
    ok = document["path_confinement"] == "PASS" and document["remote_tip_equals_head"]
    if manifest_state == "FAILED":
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
