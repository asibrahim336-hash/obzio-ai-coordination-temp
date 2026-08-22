#!/usr/bin/env python3
"""Run the PO-03 validator suite from a clean, dependency-isolated clone."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


TASK_ID = "wave-a-002-clean-clone-smoke"
HYPOTHESIS = (
    "The PO-03 validator suite can run in a fresh checkout using only "
    "Python standard library dependencies."
)


class SmokeFailure(RuntimeError):
    """A classified clean-clone precondition or execution failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
    )


def _canonical_relative(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise SmokeFailure(
            "NON_PORTABLE_TEST_SELECTOR",
            f"{field} must be a canonical relative POSIX path",
            field=field,
        )
    return value


def checkout_state(repository: Path) -> list[str]:
    """Return tracked, untracked, and ignored worktree entries."""
    try:
        result = _git(
            repository,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
        )
    except subprocess.CalledProcessError as exc:
        raise SmokeFailure(
            "NOT_A_GIT_CHECKOUT",
            "source is not a readable Git checkout",
            git_returncode=exc.returncode,
        ) from exc
    return sorted(
        entry.decode("utf-8", errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    )


def assert_clean_checkout(repository: Path, phase: str) -> None:
    entries = checkout_state(repository)
    if entries:
        raise SmokeFailure(
            "HIDDEN_CHECKOUT_STATE",
            f"{phase} checkout contains state absent from its immutable commit",
            phase=phase,
            entries=entries,
        )


def resolve_revision(repository: Path, revision: str) -> str:
    try:
        resolved = _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SmokeFailure(
            "INVALID_REVISION",
            "revision does not resolve to an immutable commit",
            revision=revision,
        ) from exc
    commit = resolved.stdout.decode("ascii").strip()
    if len(commit) not in {40, 64} or any(character not in "0123456789abcdef" for character in commit):
        raise SmokeFailure(
            "INVALID_REVISION",
            "resolved revision is not a full lowercase Git object identifier",
        )
    return commit


def _sanitized_environment(home: Path, temporary: Path) -> dict[str, str]:
    environment = {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(temporary),
    }
    return environment


def run_clean_clone_smoke(
    repository: Path,
    revision: str,
    *,
    test_start_dir: str = "workstreams/po03/tests",
    pattern: str = "test_*.py",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Clone one clean commit and run unittest without site-package loading."""
    source = repository.resolve()
    test_start_dir = _canonical_relative(test_start_dir, "test_start_dir")
    if not pattern or "/" in pattern or "\\" in pattern or "\x00" in pattern:
        raise SmokeFailure(
            "NON_PORTABLE_TEST_SELECTOR",
            "pattern must be a non-empty filename pattern",
            field="pattern",
        )
    if timeout_seconds < 1:
        raise SmokeFailure(
            "INVALID_TIMEOUT",
            "timeout_seconds must be positive",
        )

    assert_clean_checkout(source, "source-preflight")
    commit = resolve_revision(source, revision)
    command = [
        "python3",
        "-I",
        "-S",
        "-B",
        "-m",
        "unittest",
        "discover",
        "-s",
        test_start_dir,
        "-p",
        pattern,
        "-v",
    ]

    with tempfile.TemporaryDirectory(prefix="po03-clean-clone-") as temporary_name:
        temporary = Path(temporary_name)
        clone = temporary / "checkout"
        home = temporary / "home"
        runtime_tmp = temporary / "tmp"
        home.mkdir()
        runtime_tmp.mkdir()
        try:
            subprocess.run(
                (
                    "git",
                    "clone",
                    "--quiet",
                    "--no-local",
                    "--no-hardlinks",
                    "--no-checkout",
                    "--",
                    str(source),
                    str(clone),
                ),
                check=True,
                capture_output=True,
            )
            _git(clone, "checkout", "--quiet", "--detach", commit)
        except subprocess.CalledProcessError as exc:
            raise SmokeFailure(
                "FRESH_CLONE_FAILED",
                "the immutable revision could not be materialized in a fresh clone",
                git_returncode=exc.returncode,
            ) from exc

        observed_head = _git(clone, "rev-parse", "HEAD").stdout.decode("ascii").strip()
        if observed_head != commit:
            raise SmokeFailure(
                "REVISION_MISMATCH",
                "fresh clone did not check out the requested immutable commit",
                expected=commit,
                observed=observed_head,
            )
        assert_clean_checkout(clone, "fresh-clone-preflight")

        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                cwd=clone,
                env=_sanitized_environment(home, runtime_tmp),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(
                "VALIDATOR_TIMEOUT",
                "validator suite exceeded its frozen timeout",
                timeout_seconds=timeout_seconds,
            ) from exc
        elapsed_ms = round((time.monotonic() - started) * 1000)
        post_run_state = checkout_state(clone)

    outcome = "PASS" if process.returncode == 0 and not post_run_state else "FAIL"
    failure_reasons: list[str] = []
    if process.returncode != 0:
        failure_reasons.append("VALIDATOR_NONZERO_EXIT")
    if post_run_state:
        failure_reasons.append("VALIDATOR_LEFT_HIDDEN_CHECKOUT_STATE")
    return {
        "evidence_version": "PO03-CLEAN-CLONE-SMOKE-v1",
        "task_id": TASK_ID,
        "hypothesis": HYPOTHESIS,
        "outcome": outcome,
        "failure_reasons": failure_reasons,
        "revision_commit": commit,
        "source_preflight": "CLEAN_TRACKED_UNTRACKED_AND_IGNORED",
        "clone_method": "git clone --no-local --no-hardlinks --no-checkout",
        "fresh_clone_preflight": "CLEAN_TRACKED_UNTRACKED_AND_IGNORED",
        "post_run_checkout_state": post_run_state,
        "runtime_isolation": {
            "python_flags": ["-I", "-S", "-B"],
            "site_packages_loaded": False,
            "pythonpath_admitted": False,
            "home": "EPHEMERAL_ISOLATED",
            "tmpdir": "EPHEMERAL_ISOLATED",
        },
        "command": command,
        "returncode": process.returncode,
        "elapsed_ms": elapsed_ms,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "recorded_at": _utc_now(),
        "decision_changed": [],
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    payload = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--test-start-dir", default="workstreams/po03/tests")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = run_clean_clone_smoke(
            args.repository,
            args.revision,
            test_start_dir=args.test_start_dir,
            pattern=args.pattern,
            timeout_seconds=args.timeout_seconds,
        )
    except SmokeFailure as exc:
        document = {
            "evidence_version": "PO03-CLEAN-CLONE-SMOKE-v1",
            "task_id": TASK_ID,
            "hypothesis": HYPOTHESIS,
            "outcome": "FAIL",
            "failure_reasons": [exc.code],
            "message": str(exc),
            "details": exc.details,
            "recorded_at": _utc_now(),
            "decision_changed": [],
        }
    _write_json(args.output, document)
    print(json.dumps({"outcome": document["outcome"], "output": str(args.output)}))
    return 0 if document["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
