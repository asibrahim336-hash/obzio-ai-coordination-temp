#!/usr/bin/env python3
"""Declare every durable artifact in this attempt's result slot.

The manifest excludes itself, because a digest cannot cover the file carrying
it. Git blob SHAs are recorded when the object already exists in the local
object store, which lets a verifier cross-check the content digest against
Git's own addressing.

Usage:
    python3 tools/build_manifest.py --out manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ATTEMPT_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = ATTEMPT_ROOT.parents[4]
SLOT = "workstreams/po03/attempts/wave-a/wave-a-033-lost-callback-reproduction"

MANIFEST_NAME = "manifest.json"
EXCLUDED_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache"})

MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".log": "text/plain",
}

ROLES = {
    "frozen-hypothesis.json": "hypothesis and predictions frozen before execution",
    "capsule-verification.json": "frozen capsule hashes verified against immutable Git bytes",
    "observed-results.json": "raw observations from the fault injection",
    "analysis.md": "producer analysis, findings and verdicts",
    "limitations.json": "limitations plus negative and refuting outcomes",
    "runtime-binding.json": "requested versus machine-observed runtime, topology and scope compliance",
    "commands.json": "exact commands, exit codes, failures and repairs",
    "readback-evidence.json": "immutable read-back verification from a separate fresh clone",
    "run_reproduction.py": "driver that executes the scenarios and records results",
    "tests/sandbox.py": "sandbox builder that loads the pinned mechanism from immutable Git bytes",
    "tests/scenarios.py": "deterministic lost-callback fault injection scenarios",
    "tests/test_lost_callback_recovery.py": "assertions against the frozen predictions",
    "tools/build_manifest.py": "this manifest builder",
    "tools/check_determinism.py": "cross-run determinism comparator",
    "tools/verify_capsule.py": "capsule hash verifier and hardening disclosure generator",
    "tools/readback_verify.py": "verifies manifested artifacts from immutable bytes",
    "logs/pytest.log": "captured pytest output",
    "logs/run_reproduction.log": "captured reproduction driver output",
    "logs/determinism.log": "captured determinism comparison output",
    "logs/verify_capsule.log": "captured capsule verification output",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_blob_sha(path: Path) -> str | None:
    """Return Git's own object ID for these bytes when it is already known."""
    result = subprocess.run(
        ("git", "hash-object", "--", str(path)),
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    candidate = result.stdout.strip()
    known = subprocess.run(
        ("git", "cat-file", "-e", candidate),
        cwd=REPOSITORY,
        capture_output=True,
    )
    return candidate if known.returncode == 0 else None


def durable_artifacts() -> list[Path]:
    paths = []
    for path in sorted(ATTEMPT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(ATTEMPT_ROOT).parts):
            continue
        if path.name == MANIFEST_NAME and path.parent == ATTEMPT_ROOT:
            continue
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ATTEMPT_ROOT / MANIFEST_NAME))
    arguments = parser.parse_args()

    artifacts = []
    total_bytes = 0
    for path in durable_artifacts():
        relative = path.relative_to(ATTEMPT_ROOT).as_posix()
        payload = path.read_bytes()
        total_bytes += len(payload)
        artifacts.append(
            {
                "artifact_id": f"wave-a-033-{relative.replace('/', '-')}",
                # ``path`` is the slot-relative envelope the shared factory
                # consumes; ``logical_name`` and ``content_uri`` are retained for
                # readers and are always the same path, slot-relative and
                # repository-relative respectively.
                "path": relative,
                "logical_name": relative,
                "content_uri": f"{SLOT}/{relative}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "git_blob_sha": git_blob_sha(path),
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                "role": ROLES.get(relative, "supporting artifact"),
            }
        )

    document = {
        "manifest_version": "PO03-WAVE-A-033-MANIFEST-v1",
        "task_id": "wave-a-033-lost-callback-reproduction",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "recorded_at": utc_now(),
        "decision_changed": [],
        "result_slot": SLOT,
        "self_exclusion": (
            f"{MANIFEST_NAME} is deliberately absent from the artifact list: a manifest "
            "cannot carry its own digest. Every other durable artifact in the slot is declared."
        ),
        "artifact_count": len(artifacts),
        "total_bytes": total_bytes,
        # The shared factory reads this field when artifacts carry ``path``, and
        # requires it to equal the summed declared artifact bytes exactly. The
        # manifest is excluded from its own artifact list, so it is excluded here.
        "total_artifact_bytes_excluding_manifest": total_bytes,
        "git_blob_sha_note": (
            "git_blob_sha is populated when the object already exists in the local object "
            "store, which is true for committed artifacts. It is null for artifacts not yet "
            "committed at manifest time; the sha256 and byte count are always authoritative."
        ),
        "base_and_head": {
            "immutable_dispatch_base_sha": "e63fbae079774b151fd24a4132e4a5e571f75298",
            "attempt_branch": "po03/wave-a-033-lost-callback-reproduction",
            "head_at_manifest_time": subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=REPOSITORY,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "final_commit": "recorded in readback-evidence.json after the final push",
        },
        "clone_topology": {
            "clone_path": "/home/ubuntu/po03-wave-a-033-lost-callback-reproduction-isolated",
            "git_dir": "/home/ubuntu/po03-wave-a-033-lost-callback-reproduction-isolated/.git",
            "git_common_dir": "/home/ubuntu/po03-wave-a-033-lost-callback-reproduction-isolated/.git",
            "index_path": "/home/ubuntu/po03-wave-a-033-lost-callback-reproduction-isolated/.git/index",
            "own_object_store": True,
            "object_store_alternates": "NONE",
            "is_linked_worktree": False,
            "linked_worktree_relationship_to_workspace": "NONE",
        },
        "runtime_evidence": {
            "requested_exact_model": "claude-opus-5-thinking-high",
            "requested_reasoning_control": "high",
            "parent_cloud_run_original_model_name": "gpt-5.6-sol-max-fast",
            "executing_subagent_exact_model": "NOT_SUPPORTED",
            "observed_boundary": "no exposed API returns the executing subagent's own model identifier",
            "python_version": "3.12.3",
            "git_version": "git version 2.43.0",
            "pytest_version": "pytest 9.1.1",
            "platform": "Linux 6.12.94+ x86_64"
        },
        "verification_commands": {
            "tests": "python3 -m pytest tests/test_lost_callback_recovery.py -v",
            "tests_stdlib": "python3 tests/test_lost_callback_recovery.py",
            "reproduction": "python3 run_reproduction.py --out observed-results.json",
            "determinism": "python3 tools/check_determinism.py observed-results.json <second-run.json>",
            "capsule": "python3 tools/verify_capsule.py --out capsule-verification.json",
            "readback": "python3 tools/readback_verify.py --clone <fresh-read-only-clone>"
        },
        "exit_codes": {
            "pytest": 0,
            "tests_stdlib": 0,
            "run_reproduction": 0,
            "check_determinism": 0,
            "verify_capsule": 0
        },
        "limitations_reference": "limitations.json",
        "disposition": {
            "producer_report": "READY_TO_COMMIT",
            "obzio_state_claimed": "RESULT_STAGED_BY_PRODUCER",
            "obzio_completion_claimed": False,
            "self_acceptance_claimed": False,
            "independent_acceptance": "PENDING"
        },
        "artifacts": artifacts,
    }

    destination = Path(arguments.out)
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {destination}")
    print(f"  artifact_count={len(artifacts)} total_bytes={total_bytes}")
    missing = [item["logical_name"] for item in artifacts if item["git_blob_sha"] is None]
    print(f"  artifacts_without_known_git_blob={len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
