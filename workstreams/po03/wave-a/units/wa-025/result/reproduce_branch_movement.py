#!/usr/bin/env python3
"""Run a sanitized branch-movement and immutable-readback reproduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from immutable_readback import VerificationError, verify_readback


BRANCH = "results/wa-025"
ARTIFACT_PATH = "result/obzio-sanitized-artifact.bin"
INITIAL_BYTES = (
    b"\x00OBZIO-WA-025-SANITIZED\r\n"
    b"immutable-result\xff\x80\n"
    b"no-secrets-no-external-effects\n"
)
MOVED_BYTES = b"replacement-branch-tip-must-not-substitute-pinned-bytes\n"
FIXED_DATE = "2026-08-22T07:20:00+00:00"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_DATE": FIXED_DATE,
            "GIT_COMMITTER_DATE": FIXED_DATE,
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return env


def _git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise VerificationError(f"fixture git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _configure(repo: Path) -> None:
    _git(repo, "config", "user.name", "PO03 Sanitized Fixture")
    _git(repo, "config", "user.email", "po03-fixture@invalid.example")


def _commit_fixture(repo: Path, content: bytes, message: str) -> str:
    artifact = repo / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(content)
    _git(repo, "add", ARTIFACT_PATH)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").decode("ascii").strip()


def _manifest(content: bytes) -> list[dict[str, Any]]:
    return [
        {
            "path": ARTIFACT_PATH,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
    ]


def run_reproduction(root: Path) -> dict[str, Any]:
    """Create unrelated branch tips and prove pinned bytes survive the force move."""

    root.mkdir(parents=True, exist_ok=True)
    origin = root / "origin.git"
    producer_a = root / "producer-a"
    producer_b = root / "producer-b"
    consumer = root / "consumer"

    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
    )
    for repo in (producer_a, producer_b, consumer):
        subprocess.run(
            ["git", "init", str(repo)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_env(),
        )

    _configure(producer_a)
    initial_commit = _commit_fixture(
        producer_a, INITIAL_BYTES, "sanitized immutable result"
    )
    _git(producer_a, "remote", "add", "origin", str(origin))
    _git(producer_a, "push", "origin", f"HEAD:refs/heads/{BRANCH}")

    before_move = verify_readback(
        repo=consumer,
        remote=str(origin),
        branch=BRANCH,
        expected_commit=initial_commit,
        artifacts=_manifest(INITIAL_BYTES),
    )
    if not before_move["success"] or before_move[
        "branch_tip_moved_from_expected_commit"
    ]:
        raise VerificationError("pre-movement control did not resolve the initial tip")

    _configure(producer_b)
    moved_commit = _commit_fixture(
        producer_b, MOVED_BYTES, "unrelated replacement result"
    )
    _git(producer_b, "remote", "add", "origin", str(origin))
    _git(
        producer_b,
        "push",
        "--force",
        "origin",
        f"HEAD:refs/heads/{BRANCH}",
    )

    after_move = verify_readback(
        repo=consumer,
        remote=str(origin),
        branch=BRANCH,
        expected_commit=initial_commit,
        artifacts=_manifest(INITIAL_BYTES),
        require_branch_moved=True,
    )
    moved_tip_bytes = _git(
        consumer, "show", "--no-textconv", f"{moved_commit}:{ARTIFACT_PATH}"
    )
    commits_related = (
        subprocess.run(
            [
                "git",
                "-C",
                str(consumer),
                "merge-base",
                "--is-ancestor",
                initial_commit,
                moved_commit,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_env(),
        ).returncode
        == 0
    )
    exact_hypothesis_supported = all(
        (
            after_move["success"],
            after_move["tracking_tip_before_fetch"] == initial_commit,
            after_move["tracking_tip_after_fetch"] == moved_commit,
            after_move["tracking_ref_moved_during_fetch"],
            after_move["branch_tip_moved_from_expected_commit"],
            after_move["all_artifacts_match"],
            moved_tip_bytes != INITIAL_BYTES,
            not commits_related,
        )
    )
    git_version = subprocess.run(
        ["git", "--version"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
    ).stdout.decode("utf-8").strip()
    return {
        "protocol_version": "OBZIO-SANITIZED-REPRODUCTION-v1",
        "task_id": "PO03-WA-025",
        "hypothesis_id": "H-PO03-WA-025",
        "reproduction_id": "R-PO03-WA-025-001",
        "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "workload": {
            "classification": "SANITIZED_OBZIO_REPOSITORY_NATIVE",
            "branch_ref": f"refs/heads/{BRANCH}",
            "artifact_path": ARTIFACT_PATH,
            "contains_secrets": False,
            "external_effects": False,
            "remote_kind": "temporary local bare Git repository",
        },
        "runtime": {
            "git_version": git_version,
            "python_version": sys.version.split()[0],
            "platform_details": "NOT_SUPPORTED",
        },
        "initial_commit": initial_commit,
        "moved_commit": moved_commit,
        "branch_move": {
            "kind": "FORCED_NON_FAST_FORWARD_UNRELATED_HISTORY",
            "initial_is_ancestor_of_moved": commits_related,
            "detected": after_move["branch_tip_moved_from_expected_commit"],
            "tracking_ref_changed": after_move["tracking_ref_moved_during_fetch"],
        },
        "readback": {
            "pinned_commit": initial_commit,
            "artifact_sha256": hashlib.sha256(INITIAL_BYTES).hexdigest(),
            "artifact_bytes": len(INITIAL_BYTES),
            "moved_tip_artifact_sha256": hashlib.sha256(moved_tip_bytes).hexdigest(),
            "moved_tip_artifact_bytes": len(moved_tip_bytes),
            "moved_tip_content_differs": moved_tip_bytes != INITIAL_BYTES,
            "all_pinned_bytes_match": after_move["all_artifacts_match"],
            "command": (
                f"git show --no-textconv {initial_commit}:{ARTIFACT_PATH}"
            ),
        },
        "pre_movement_control": before_move,
        "post_movement_verification": after_move,
        "exact_falsifiable_hypothesis": (
            "Fetch plus git-show at an immutable commit detects branch-tip "
            "movement and preserves exact artifact bytes."
        ),
        "hypothesis_outcome": (
            "SUPPORTED" if exact_hypothesis_supported else "REFUTED"
        ),
        "success": exact_hypothesis_supported,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.workspace:
            result = run_reproduction(args.workspace)
        else:
            with tempfile.TemporaryDirectory(prefix="po03-wa-025-") as temporary:
                result = run_reproduction(Path(temporary))
    except (OSError, subprocess.SubprocessError, VerificationError) as exc:
        result = {
            "protocol_version": "OBZIO-SANITIZED-REPRODUCTION-v1",
            "task_id": "PO03-WA-025",
            "hypothesis_id": "H-PO03-WA-025",
            "hypothesis_outcome": "NOT_SUPPORTED",
            "success": False,
            "error": str(exc),
        }

    encoded = _json_bytes(result)
    if args.output:
        args.output.write_bytes(encoded)
    sys.stdout.buffer.write(encoded)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
