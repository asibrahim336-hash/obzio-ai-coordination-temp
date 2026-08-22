#!/usr/bin/env python3
"""Generate the artifact manifest for PO03-WA-013-A02 with complete accounting.

Walks this unit's owned subtree, hashes every file, and writes
``artifact-manifest.json``.  A file cannot contain its own digest, so the
manifest covers every strict payload predecessor and the closure is completed by
``ready-to-commit.json``, which carries the manifest's digest.

Also validates every changed path against the owned write prefix and refuses to
write a manifest if anything outside it changed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNIT_ROOT = HERE.parent
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-013/"

# Written after the manifest, so they cannot appear inside it.
DEFERRED = {
    "artifact-manifest.json",
    "ready-to-commit.json",
    "readback-verification.json",
    "recurrence-evidence-clean-clone.json",
}

MEDIA_TYPES = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def repo_root() -> Path:
    for candidate in [HERE, *HERE.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit("no git root found above this unit")


def artifact_id(relative: str) -> str:
    slug = relative.replace("/", "-").replace("_", "-")
    for suffix in (".json", ".jsonl", ".py", ".txt"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
            break
    return f"art-po03-wa-013-{slug}"


def validate_changed_paths(root: Path) -> list[str]:
    base = "6559606ac8db12e3f484e9bb74c2b4a05cc3a998"
    tracked = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(root),
        check=True,
    ).stdout.split()
    # -uall expands untracked directories to individual files, otherwise a new
    # directory collapses to one entry and the changed-path count understates.
    working = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        capture_output=True,
        text=True,
        cwd=str(root),
        check=True,
    ).stdout.splitlines()
    changed = set(tracked)
    for entry in working:
        path = entry[3:].strip().strip('"')
        if path:
            changed.add(path)
    return sorted(changed)


def main() -> int:
    root = repo_root()
    changed = validate_changed_paths(root)
    outside = [path for path in changed if not path.startswith(OWNED_PREFIX)]
    if outside:
        print("REFUSING: changed paths outside the owned write boundary:", file=sys.stderr)
        for path in outside:
            print(f"  {path}", file=sys.stderr)
        return 2

    entries = []
    total = 0
    for path in sorted(UNIT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative_to_unit = path.relative_to(UNIT_ROOT).as_posix()
        if path.name in DEFERRED and path.parent == HERE:
            continue
        raw = path.read_bytes()
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        entries.append(
            {
                "artifact_id": artifact_id(relative_to_unit),
                "logical_name": relative_to_unit,
                "content_uri": f"{OWNED_PREFIX}{relative_to_unit}",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                "git_mode": mode,
            }
        )
        total += len(raw)

    manifest = {
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "manifest_id": "man-po03-wa-013-a02",
        "task_id": "PO03-WA-013",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "controller_run_id": "bc-b1956656-b897-4889-aeab-82c4556c1a9f",
        "result_txn_id": "txn-po03-wa-013-a02",
        "attempt": {
            "attempt_id": "PO03-WA-013-A02",
            "idempotency_key": "po03:100bc2079ced:wa-013:a02",
            "lease_id": "lease-po03-wa-013-a02",
            "fence_token": 2,
            "checkpoint_seq": 0,
        },
        "immutable_input": {
            "path": "workstreams/po03/control/inputs/wave-a/wa-013-a02.json",
            "supplied_sha256": "0adf6ed3291f356993c373830b463fe2a463ea912e618a8bbab19fc5b96748df",
            "observed_sha256": "43a460d2acc02badd9235509418715bfb531657e0acf9c995748944ccda43db3",
            "observed_bytes": 4509,
            "digest_gate_outcome": "FAIL",
            "digest_gate_evidence": f"{OWNED_PREFIX}result/input-digest-verification.json",
        },
        "immutable_input_manifest_sha256": "43a460d2acc02badd9235509418715bfb531657e0acf9c995748944ccda43db3",
        "immutable_input_manifest_sha256_note": "This is the observed exact-bytes digest. The dispatch-supplied digest failed verification and is recorded above rather than asserted here.",
        "acceptance_contract_sha256": "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
        "acceptance_contract_path": "workstreams/po03/control/acceptance/wave-a-material-v1.json",
        "hash_algorithm": "sha256",
        "material_work": True,
        "source_base": {
            "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
            "immutable_controller_base": "6559606ac8db12e3f484e9bb74c2b4a05cc3a998",
            "commission_commit": "552b12eacee637716451492a98980fb0da19ff3e",
            "minimum_protocol_ancestor": "100bc2079cedc193af3524234ab833cc9f9f4669",
            "producer_start_commit": "6559606ac8db12e3f484e9bb74c2b4a05cc3a998",
        },
        "runner": {
            "runner_id": "best-of-n-runner-bc-b1956656-wa-013-a02",
            "subagent_type": "best-of-n-runner",
            "execution_environment": "isolated-git-worktree",
            "remote_branch": "cursor/po03-wa-013-b195-a02-1a9f",
            "model_requested": "claude-opus-5-thinking-high",
            "model_observed": "claude-opus-5",
            "reasoning_requested": "high",
            "reasoning_observed": "NOT_SUPPORTED",
        },
        "owned_subtree": OWNED_PREFIX,
        "result_slot": f"{OWNED_PREFIX}result/",
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": total,
        "changed_paths": changed,
        "changed_path_count": len(changed),
        "changed_paths_outside_owned_prefix": 0,
        "required_artifacts_ledger": [
            {"logical_name": "result/result.json", "hash_carrier": "this manifest"},
            {"logical_name": "result/tests.json", "hash_carrier": "this manifest"},
            {"logical_name": "result/limitations.json", "hash_carrier": "this manifest"},
            {
                "logical_name": "result/artifact-manifest.json",
                "sha256": None,
                "bytes": None,
                "hash_carrier": "ready-to-commit.json ($.manifest_sha256)",
            },
            {
                "logical_name": "result/ready-to-commit.json",
                "sha256": None,
                "bytes": None,
                "hash_carrier": "producer READY_TO_COMMIT terminal report and the immutable return commit tree",
            },
        ],
        "hash_closure": {
            "ordering": [
                f"{len(entries)} payload artifacts",
                "readback-verification.json and recurrence-evidence-clean-clone.json",
                "artifact-manifest.json",
                "ready-to-commit.json",
            ],
            "rule": "A file cannot contain its own digest. This manifest hashes every strict payload predecessor. The two return-phase evidence files are written after the result commit and are hashed in ready-to-commit.json. ready-to-commit.json carries this manifest's digest, and the terminal report carries ready-to-commit.json's digest read back from the immutable return commit.",
        },
        "decision_changed": [],
    }

    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    (HERE / "artifact-manifest.json").write_bytes(payload)
    print(f"artifact_count={len(entries)} total_bytes={total}")
    print(f"manifest_sha256={hashlib.sha256(payload).hexdigest()} manifest_bytes={len(payload)}")
    print(f"changed_paths={len(changed)} outside_owned_prefix=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
