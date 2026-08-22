#!/usr/bin/env python3
"""Reproduce Git worktree isolation and fail closed on checkout drift."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


class ProbeError(RuntimeError):
    """Raised when the reproduction cannot be executed."""


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "LC_ALL": "C",
        }
    )
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        command = " ".join(args)
        raise ProbeError(
            f"{command!r} failed with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed


@dataclass(frozen=True)
class CheckoutIdentity:
    toplevel: str
    branch: str
    head: str
    git_dir: str
    common_dir: str


def capture_identity(repo: Path) -> CheckoutIdentity:
    """Capture the fields that must not drift during a guarded operation."""

    repo = repo.resolve()

    def git(*args: str) -> str:
        return _run(("git", *args), cwd=repo).stdout.strip()

    branch_result = _run(
        ("git", "symbolic-ref", "--quiet", "--short", "HEAD"),
        cwd=repo,
        check=False,
    )
    branch = (
        branch_result.stdout.strip()
        if branch_result.returncode == 0
        else "DETACHED"
    )
    return CheckoutIdentity(
        toplevel=git("rev-parse", "--show-toplevel"),
        branch=branch,
        head=git("rev-parse", "HEAD"),
        git_dir=str((repo / git("rev-parse", "--git-dir")).resolve())
        if not Path(git("rev-parse", "--git-dir")).is_absolute()
        else git("rev-parse", "--git-dir"),
        common_dir=str((repo / git("rev-parse", "--git-common-dir")).resolve())
        if not Path(git("rev-parse", "--git-common-dir")).is_absolute()
        else git("rev-parse", "--git-common-dir"),
    )


def identity_mismatches(
    actual: CheckoutIdentity,
    *,
    expected_toplevel: str,
    expected_branch: str,
    expected_head: str | None = None,
) -> list[dict[str, str]]:
    """Return exact identity differences suitable for a fail-closed guard."""

    expected = {
        "toplevel": str(Path(expected_toplevel).resolve()),
        "branch": expected_branch,
    }
    if expected_head is not None:
        expected["head"] = expected_head
    mismatches: list[dict[str, str]] = []
    actual_fields = asdict(actual)
    for field, wanted in expected.items():
        observed = actual_fields[field]
        if observed != wanted:
            mismatches.append(
                {"field": field, "expected": wanted, "actual": observed}
            )
    return mismatches


def guard_checkout(
    repo: Path,
    *,
    expected_toplevel: str,
    expected_branch: str,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Check checkout identity and return a machine-readable decision."""

    actual = capture_identity(repo)
    mismatches = identity_mismatches(
        actual,
        expected_toplevel=expected_toplevel,
        expected_branch=expected_branch,
        expected_head=expected_head,
    )
    return {
        "decision": "PASS" if not mismatches else "FAIL_CLOSED",
        "actual": asdict(actual),
        "mismatches": mismatches,
    }


def _write_repeated(path: Path, value: str, barrier: threading.Barrier) -> None:
    barrier.wait(timeout=10)
    for _ in range(250):
        path.write_text(value, encoding="utf-8")


def reproduce(scratch_root: Path | None = None) -> dict[str, Any]:
    """Run the sanitized Obzio worktree workload in a disposable repository."""

    if scratch_root is not None:
        scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="wa-023-worktree-", dir=scratch_root
    ) as temporary:
        root = Path(temporary).resolve()
        controller = root / "sanitized-obzio"
        worker_a = root / "worker-a"
        worker_b = root / "worker-b"
        controller.mkdir()

        _run(("git", "init", "-b", "controller"), cwd=controller)
        _run(("git", "config", "user.name", "Sanitized Obzio Probe"), cwd=controller)
        _run(
            ("git", "config", "user.email", "probe@invalid.example"),
            cwd=controller,
        )
        workload = controller / "workload.txt"
        workload.write_text("controller-baseline\n", encoding="utf-8")
        _run(("git", "add", "workload.txt"), cwd=controller)
        _run(("git", "commit", "-m", "sanitized baseline"), cwd=controller)

        controller_before = capture_identity(controller)
        _run(
            (
                "git",
                "worktree",
                "add",
                "-b",
                "worker-a",
                str(worker_a),
                "controller",
            ),
            cwd=controller,
        )
        _run(
            (
                "git",
                "worktree",
                "add",
                "-b",
                "worker-b",
                str(worker_b),
                "controller",
            ),
            cwd=controller,
        )

        _run(("git", "switch", "-c", "worker-a-switched"), cwd=worker_a)
        branch_guard_result = _run(
            ("git", "switch", "worker-a-switched"),
            cwd=worker_b,
            check=False,
        )

        barrier = threading.Barrier(2)
        a_thread = threading.Thread(
            target=_write_repeated,
            args=(worker_a / "workload.txt", "worker-a-sentinel\n", barrier),
        )
        b_thread = threading.Thread(
            target=_write_repeated,
            args=(worker_b / "workload.txt", "worker-b-sentinel\n", barrier),
        )
        a_thread.start()
        b_thread.start()
        a_thread.join(timeout=15)
        b_thread.join(timeout=15)
        if a_thread.is_alive() or b_thread.is_alive():
            raise ProbeError("concurrent writer did not terminate")

        controller_after = capture_identity(controller)
        worker_a_identity = capture_identity(worker_a)
        worker_b_identity = capture_identity(worker_b)
        assertions = {
            "distinct_toplevels": len(
                {
                    controller_after.toplevel,
                    worker_a_identity.toplevel,
                    worker_b_identity.toplevel,
                }
            )
            == 3,
            "distinct_git_dirs": len(
                {
                    controller_after.git_dir,
                    worker_a_identity.git_dir,
                    worker_b_identity.git_dir,
                }
            )
            == 3,
            "shared_common_dir_is_explicit": len(
                {
                    controller_after.common_dir,
                    worker_a_identity.common_dir,
                    worker_b_identity.common_dir,
                }
            )
            == 1,
            "worker_branch_switch_did_not_move_controller_identity": (
                controller_before == controller_after
            ),
            "concurrent_worker_a_write_isolated": (
                (worker_a / "workload.txt").read_text(encoding="utf-8")
                == "worker-a-sentinel\n"
            ),
            "concurrent_worker_b_write_isolated": (
                (worker_b / "workload.txt").read_text(encoding="utf-8")
                == "worker-b-sentinel\n"
            ),
            "controller_file_untouched": (
                workload.read_text(encoding="utf-8")
                == "controller-baseline\n"
            ),
            "occupied_branch_switch_rejected": (
                branch_guard_result.returncode != 0
                and "already used by worktree at"
                in branch_guard_result.stderr
            ),
            "controller_checkout_clean": (
                _run(("git", "status", "--porcelain"), cwd=controller).stdout
                == ""
            ),
        }

        def portable_identity(identity: CheckoutIdentity) -> dict[str, str]:
            values = asdict(identity)
            for field in ("toplevel", "git_dir", "common_dir"):
                values[field] = values[field].replace(
                    str(root), "$SANITIZED_ROOT"
                )
            return values

        return {
            "protocol_version": "PO03-WA-023-REPRODUCTION-v1",
            "workload": "sanitized repository with one controller and two workers",
            "git_version": _run(("git", "--version"), cwd=controller)
            .stdout.strip(),
            "identities": {
                "controller_before": portable_identity(controller_before),
                "controller_after": portable_identity(controller_after),
                "worker_a": portable_identity(worker_a_identity),
                "worker_b": portable_identity(worker_b_identity),
            },
            "occupied_branch_attempt": {
                "command": "git switch worker-a-switched",
                "returncode": branch_guard_result.returncode,
                "stderr": branch_guard_result.stderr.strip().replace(
                    str(root), "$SANITIZED_ROOT"
                ),
            },
            "assertions": assertions,
            "result": "PASS" if all(assertions.values()) else "FAIL",
            "sanitization": {
                "real_repository_content_used": False,
                "secrets_used": False,
                "external_mutation": False,
                "temporary_repository_removed_after_run": True,
            },
        }


def _emit(value: dict[str, Any], output: Path | None) -> None:
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(data, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(data, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    reproduce_parser = commands.add_parser("reproduce")
    reproduce_parser.add_argument("--scratch-root", type=Path)
    reproduce_parser.add_argument("--output", type=Path)

    identity_parser = commands.add_parser("identity")
    identity_parser.add_argument("--repo", type=Path, default=Path.cwd())

    guard_parser = commands.add_parser("guard")
    guard_parser.add_argument("--repo", type=Path, default=Path.cwd())
    guard_parser.add_argument("--expected-toplevel", required=True)
    guard_parser.add_argument("--expected-branch", required=True)
    guard_parser.add_argument("--expected-head")

    args = parser.parse_args(argv)
    if args.command == "reproduce":
        _emit(reproduce(args.scratch_root), args.output)
        return 0
    if args.command == "identity":
        _emit({"identity": asdict(capture_identity(args.repo))}, None)
        return 0

    result = guard_checkout(
        args.repo,
        expected_toplevel=args.expected_toplevel,
        expected_branch=args.expected_branch,
        expected_head=args.expected_head,
    )
    _emit(result, None)
    return 0 if result["decision"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
