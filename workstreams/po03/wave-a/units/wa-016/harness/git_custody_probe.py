#!/usr/bin/env python3
"""Real-git custody probe: commit, lose the push, recover, read back.

The simulated external world models a push as an idempotent content-addressed
effect.  This probe checks that assumption against actual git plumbing on a
sanitized local repository, so the matrix runner's central assumption is not
merely asserted.

Everything happens in a throwaway directory with a ``file://`` remote.  No
network, no credentials, no configured identity is required or used.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import fixtures
from .durable_io import canonical_json

GIT_ENV = {
    "GIT_AUTHOR_NAME": "po03-wa-016-probe",
    "GIT_AUTHOR_EMAIL": "po03-wa-016-probe@invalid",
    "GIT_COMMITTER_NAME": "po03-wa-016-probe",
    "GIT_COMMITTER_EMAIL": "po03-wa-016-probe@invalid",
    "GIT_AUTHOR_DATE": "2026-08-22T07:13:11+00:00",
    "GIT_COMMITTER_DATE": "2026-08-22T07:13:11+00:00",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}

RESULT_REF = "refs/heads/po03-wa-016-probe"


class GitUnavailable(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    env.update(GIT_ENV)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=env,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def git_version() -> str:
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitUnavailable(str(exc)) from exc
    if result.returncode != 0:
        raise GitUnavailable(result.stderr.strip())
    return result.stdout.strip()


def run_probe(root: Path | None = None) -> dict[str, Any]:
    """Drive one real-git custody sequence with a lost push, then recover it."""
    version = git_version()
    temporary = root is None
    base = Path(root or tempfile.mkdtemp(prefix="po03-wa016-git-"))
    try:
        remote = base / "remote.git"
        work = base / "work"
        remote.mkdir(parents=True)
        work.mkdir(parents=True)
        _git(remote, "init", "--bare", "--quiet", ".")
        _git(work, "init", "--quiet", "-b", "main", ".")
        _git(work, "remote", "add", "origin", remote.as_uri())

        payload = dict(fixtures.default_payload())
        manifest = {
            "task_id": fixtures.TASK_ID,
            "artifacts": [
                {"logical_name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                for name, data in sorted(payload.items())
            ],
        }
        result_dir = work / "result"
        result_dir.mkdir()
        for name, data in payload.items():
            (result_dir / name).write_bytes(data)
        (result_dir / "artifact-manifest.json").write_bytes(canonical_json(manifest))

        _git(work, "add", "result")
        _git(work, "commit", "--quiet", "-m", "po03-wa-016 probe: stage sanitized custody payload")
        commit = _git(work, "rev-parse", "HEAD").stdout.strip()
        _git(work, "branch", "--quiet", "-f", "po03-wa-016-probe", commit)

        # Fault: the process is lost between the local commit and the push.  The
        # commit is durable locally and absent remotely, which is exactly the
        # state a recovery scanner has to distinguish.
        before = _git(work, "ls-remote", "origin", RESULT_REF).stdout.strip()
        remote_had_commit_before_push = bool(before)

        push_one = _git(work, "push", "--quiet", "origin", f"{commit}:{RESULT_REF}")
        after_first = _git(work, "ls-remote", "origin", RESULT_REF).stdout.split()[0]

        # Replay the same effect.  A real remote converges rather than creating a
        # second durable result, which is the property the simulated world models.
        push_two = _git(work, "push", "origin", f"{commit}:{RESULT_REF}", check=False)
        after_second = _git(work, "ls-remote", "origin", RESULT_REF).stdout.split()[0]

        # Read every artifact back from the immutable remote commit through a
        # fresh clone that shares no working tree with the producer.
        verifier = base / "verify"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", "--single-branch", "--branch", "po03-wa-016-probe", remote.as_uri(), str(verifier)],
            capture_output=True,
            check=True,
            timeout=120,
        )
        readback: list[dict[str, Any]] = []
        for name, data in sorted(payload.items()):
            blob = subprocess.run(
                ["git", "-C", str(verifier), "show", f"{commit}:result/{name}"],
                capture_output=True,
                check=True,
                timeout=60,
            ).stdout
            readback.append(
                {
                    "logical_name": name,
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "bytes": len(blob),
                    "expected_sha256": hashlib.sha256(data).hexdigest(),
                    "expected_bytes": len(data),
                    "matches": blob == data,
                }
            )

        canary = next(r for r in readback if r["logical_name"] == "canary.txt")
        return {
            "git_version": version,
            "commit": commit,
            "result_ref": RESULT_REF,
            "remote_had_commit_before_push": remote_had_commit_before_push,
            "first_push_returncode": push_one.returncode,
            "second_push_returncode": push_two.returncode,
            "second_push_stderr": push_two.stderr.strip()[:200],
            "remote_tip_after_first_push": after_first,
            "remote_tip_after_replay": after_second,
            "push_is_idempotent": after_first == after_second == commit,
            "readback": readback,
            "all_artifacts_reconcile": all(r["matches"] for r in readback),
            "canary_sha256_matches_recorded": canary["sha256"] == fixtures.CANARY_SHA256,
            "canary_bytes_matches_recorded": canary["bytes"] == fixtures.CANARY_BYTES,
        }
    finally:
        if temporary:
            shutil.rmtree(base, ignore_errors=True)


def verify_recorded_canary(repo: Path) -> dict[str, Any]:
    """Compare the embedded canary fixture with the immutable commit it came from.

    The commit lives on another PO-03 branch, so a single-branch clone may not
    have the object.  That is recorded as NOT_SUPPORTED rather than guessed.
    """
    try:
        git_version()
    except GitUnavailable as exc:
        return {"disposition": "NOT_SUPPORTED", "reason": f"git unavailable: {exc}"}
    probe = _git(repo, "cat-file", "-t", fixtures.CANARY_COMMIT, check=False)
    if probe.returncode != 0 or probe.stdout.strip() != "commit":
        return {
            "disposition": "NOT_SUPPORTED",
            "reason": f"commit {fixtures.CANARY_COMMIT} not present in this clone",
            "embedded_sha256": fixtures.CANARY_SHA256,
        }
    blob = subprocess.run(
        ["git", "-C", str(repo), "show", f"{fixtures.CANARY_COMMIT}:{fixtures.CANARY_PATH}"],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if blob.returncode != 0:
        return {"disposition": "NOT_SUPPORTED", "reason": "path not present at that commit"}
    observed = hashlib.sha256(blob.stdout).hexdigest()
    return {
        "disposition": "MATCHES" if blob.stdout == fixtures.CANARY_TEXT else "DIVERGED",
        "commit": fixtures.CANARY_COMMIT,
        "path": fixtures.CANARY_PATH,
        "observed_sha256": observed,
        "observed_bytes": len(blob.stdout),
        "embedded_sha256": fixtures.CANARY_SHA256,
        "embedded_bytes": fixtures.CANARY_BYTES,
    }
