#!/usr/bin/env python3
"""Reproduce overlapping-subordinate-write prevention on a sanitized workload.

The hypothesis under test is that ownership grants plus deny globs prevent
overlapping subordinate writes *before* commit.  A unit test that only calls the
engine cannot establish the "before commit" half, because nothing stops the
writer from committing anyway.  This reproduction therefore installs the engine
as a real ``pre-commit`` hook in a throwaway repository and lets git enforce the
decision: a refused write leaves ``HEAD`` and the committed bytes untouched.

The workload mirrors the shape of ``workstreams/po03/control/path-ownership.json``
with sanitized identifiers.  It creates a temporary repository, has no network
access, contains no secrets and produces no external effect.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent

CONTROLLER_BRANCH = "sanitized/controller"
WRITER_A = "lease-sanitized-unit-a-a02"
WRITER_B = "lease-sanitized-unit-b-a02"
FENCE_A = 2
FENCE_B = 2

DISJOINT_REGISTRY: dict[str, Any] = {
    "schema_version": "1.0",
    "controller": {
        "branch": CONTROLLER_BRANCH,
        "run_id": "sanitized-run",
        "owned_globs": ["control/**"],
    },
    "global_deny_globs": ["state/**", "dispatch/**"],
    "subordinate_owners": [
        {
            "task_id": "SANITIZED-UNIT-A",
            "attempt_id": "SANITIZED-UNIT-A-A02",
            "lease_id": WRITER_A,
            "fence_token": FENCE_A,
            "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
            "owned_globs": ["units/unit-a/**"],
        },
        {
            "task_id": "SANITIZED-UNIT-B",
            "attempt_id": "SANITIZED-UNIT-B-A02",
            "lease_id": WRITER_B,
            "fence_token": FENCE_B,
            "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
            "owned_globs": ["units/unit-b/**"],
        },
    ],
}

# The proposal a coordinator might accept without checking: unit-b is also
# handed a slice of unit-a's subtree so it can drop a shared summary there.
OVERLAPPING_REGISTRY: dict[str, Any] = json.loads(json.dumps(DISJOINT_REGISTRY))
OVERLAPPING_REGISTRY["subordinate_owners"][1]["owned_globs"] = [
    "units/unit-b/**",
    "units/unit-?/result/shared-summary.json",
]

SHARED_PATH = "units/unit-a/result/shared-summary.json"
A_CONTENT = "written by unit-a\n"
B_CONTENT = "overwritten by unit-b\n"


class ReproductionError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True, env: dict[str, str] | None = None):
    merged = dict(os.environ)
    merged.update(
        {
            "GIT_AUTHOR_NAME": "PO-03 WA-010",
            "GIT_AUTHOR_EMAIL": "po03@obzio.invalid",
            "GIT_COMMITTER_NAME": "PO-03 WA-010",
            "GIT_COMMITTER_EMAIL": "po03@obzio.invalid",
        }
    )
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=merged,
    )


def _write(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _install_gate(repo: Path) -> Path:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        "set -e\n"
        f'exec "{sys.executable}" -I "{ENGINE_DIR / "ownership.py"}" check \\\n'
        f'  "{repo / "control" / "path-ownership.json"}" \\\n'
        '  --owner "$PO03_OWNER" --fence "$PO03_FENCE" --staged \\\n'
        f'  --repo "{repo}" --out "{repo / ".git" / "po03-gate.json"}"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return hook


def _attempt_commit(
    repo: Path, writer: str, fence: int, message: str
) -> dict[str, Any]:
    completed = _git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        check=False,
        env={"PO03_OWNER": writer, "PO03_FENCE": str(fence)},
    )
    gate_path = repo / ".git" / "po03-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else None
    return {
        "writer": writer,
        "fence": fence,
        "commit_exit_code": completed.returncode,
        "committed": completed.returncode == 0,
        "gate_outcome": gate["report"]["outcome"] if gate else None,
        "gate_reasons": gate["report"]["reason_counts"] if gate else None,
        "gate_denied_sides": gate["report"]["denied_sides"] if gate else None,
    }


def _reset(repo: Path) -> None:
    _git(repo, "reset", "-q", "--hard", "HEAD")
    _git(repo, "clean", "-qfd")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _blob_at_head(repo: Path, relative: str) -> str | None:
    completed = _git(repo, "show", f"HEAD:{relative}", check=False)
    return completed.stdout if completed.returncode == 0 else None


def run_reproduction(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(ENGINE_DIR))
    from ownership import OwnershipEngine  # noqa: PLC0415

    repo = root / "sanitized-repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "po03@obzio.invalid")
    _git(repo, "config", "user.name", "PO-03 WA-010")
    _git(repo, "config", "commit.gpgsign", "false")

    steps: list[dict[str, Any]] = []

    proposed = OwnershipEngine.from_ownership_document(OVERLAPPING_REGISTRY)
    proposed_overlaps = proposed.detect_grant_overlaps()
    witnesses = sorted({finding.witness_path for finding in proposed_overlaps})
    steps.append(
        {
            "step": "R1_static_audit_of_the_proposed_registry",
            "expectation": "The overlap is reported from the patterns alone, before any file exists.",
            "observed": {
                "overlap_count": len(proposed_overlaps),
                "witness_paths": witnesses,
                "witness_paths_present_in_tree": [
                    str(path) for path in witnesses if (repo / path).exists()
                ],
                "repository_file_count": len(list(repo.rglob("*.json"))),
            },
            "outcome": "OVERLAP_DETECTED" if proposed_overlaps else "DISJOINT",
        }
    )

    repaired = OwnershipEngine.from_ownership_document(DISJOINT_REGISTRY)
    steps.append(
        {
            "step": "R2_static_audit_of_the_repaired_registry",
            "expectation": "Removing the shared slice makes the grants provably disjoint.",
            "observed": {
                "overlap_count": len(repaired.detect_grant_overlaps()),
                "blocking_finding_count": len(repaired.blocking_findings()),
            },
            "outcome": "DISJOINT" if not repaired.detect_grant_overlaps() else "OVERLAP_DETECTED",
        }
    )

    _write(repo, "control/path-ownership.json", json.dumps(DISJOINT_REGISTRY, indent=2) + "\n")
    _write(repo, "README.md", "sanitized reproduction workload\n")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-q",
        "-m",
        "sanitized baseline",
    )
    baseline = _head(repo)
    _install_gate(repo)

    _write(repo, SHARED_PATH, A_CONTENT)
    _git(repo, "add", "-A")
    admitted = _attempt_commit(repo, WRITER_A, FENCE_A, "unit-a writes inside its grant")
    admitted["head_moved"] = _head(repo) != baseline
    admitted["committed_bytes"] = _blob_at_head(repo, SHARED_PATH)
    steps.append(
        {
            "step": "R3_owner_writes_inside_its_grant",
            "expectation": "The gate admits the write and git records the commit.",
            "observed": admitted,
            "outcome": "ADMITTED" if admitted["committed"] else "BLOCKED",
        }
    )
    if not admitted["committed"]:
        raise ReproductionError("the owner's own write was refused")
    after_a = _head(repo)

    _write(repo, SHARED_PATH, B_CONTENT)
    _git(repo, "add", "-A")
    blocked = _attempt_commit(repo, WRITER_B, FENCE_B, "unit-b overwrites unit-a's result")
    blocked["head_moved"] = _head(repo) != after_a
    blocked["committed_bytes"] = _blob_at_head(repo, SHARED_PATH)
    blocked["bytes_preserved"] = blocked["committed_bytes"] == A_CONTENT
    steps.append(
        {
            "step": "R4_foreign_writer_overwrites_the_owner",
            "expectation": (
                "The gate refuses before the commit object exists, so HEAD does not move and the "
                "owner's committed bytes survive."
            ),
            "observed": blocked,
            "outcome": "BLOCKED" if not blocked["committed"] else "ADMITTED",
        }
    )
    _reset(repo)

    _write(repo, "units/unit-b/result/own.json", '{"unit": "b"}\n')
    _git(repo, "add", "-A")
    own = _attempt_commit(repo, WRITER_B, FENCE_B, "unit-b writes inside its own grant")
    steps.append(
        {
            "step": "R5_refused_writer_still_owns_its_own_subtree",
            "expectation": "The refusal is scoped to the path, not a blanket ban on the writer.",
            "observed": own,
            "outcome": "ADMITTED" if own["committed"] else "BLOCKED",
        }
    )
    if not own["committed"]:
        raise ReproductionError("unit-b was refused inside its own grant")
    after_b = _head(repo)

    _write(repo, "units/unit-a/result/stale.json", '{"stale": true}\n')
    _git(repo, "add", "-A")
    stale = _attempt_commit(repo, WRITER_A, FENCE_A - 1, "unit-a writes with a superseded lease")
    stale["head_moved"] = _head(repo) != after_b
    steps.append(
        {
            "step": "R6_stale_fence_token_cannot_commit",
            "expectation": "A writer whose lease was superseded is refused inside its own subtree.",
            "observed": stale,
            "outcome": "BLOCKED" if not stale["committed"] else "ADMITTED",
        }
    )
    _reset(repo)

    _git(repo, "mv", SHARED_PATH, "units/unit-b/result/stolen.json")
    renamed = _attempt_commit(repo, WRITER_B, FENCE_B, "unit-b renames unit-a's result away")
    renamed["head_moved"] = _head(repo) != after_b
    renamed["owner_bytes_intact"] = _blob_at_head(repo, SHARED_PATH) == A_CONTENT
    steps.append(
        {
            "step": "R7_rename_cannot_carry_a_foreign_file_away",
            "expectation": "A rename is refused on its source side, so the owner keeps the file.",
            "observed": renamed,
            "outcome": "BLOCKED" if not renamed["committed"] else "ADMITTED",
        }
    )
    _reset(repo)

    _write(repo, "state/pointer.json", '{"tampered": true}\n')
    _git(repo, "add", "-A")
    denied = _attempt_commit(repo, WRITER_A, FENCE_A, "unit-a writes shared state")
    denied["head_moved"] = _head(repo) != after_b
    steps.append(
        {
            "step": "R8_deny_glob_stops_a_shared_state_write",
            "expectation": "A deny glob refuses a path no grant covers, independently of ownership.",
            "observed": denied,
            "outcome": "BLOCKED" if not denied["committed"] else "ADMITTED",
        }
    )
    _reset(repo)

    _write(repo, SHARED_PATH, B_CONTENT)
    _git(repo, "add", "-A")
    ungated = _git(
        repo,
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-q",
        "-m",
        "unit-b overwrites unit-a with the gate removed",
        check=False,
    )
    ungated_head = _head(repo)
    steps.append(
        {
            "step": "R9_negative_control_without_the_gate",
            "expectation": (
                "With the hook bypassed the same overwrite succeeds, so the earlier refusals are "
                "attributable to the engine rather than to git."
            ),
            "observed": {
                "commit_exit_code": ungated.returncode,
                "committed": ungated.returncode == 0,
                "head_moved": ungated_head != after_b,
                "committed_bytes": _blob_at_head(repo, SHARED_PATH),
            },
            "outcome": "ADMITTED" if ungated.returncode == 0 else "BLOCKED",
        }
    )

    blocked_steps = [step for step in steps if step["step"].startswith(("R4", "R6", "R7", "R8"))]
    return {
        "reproduction_id": "R-PO03-WA-010-001",
        "hypothesis_id": "H-PO03-WA-010",
        "workload": "sanitized repository-native ownership registry with two subordinate writers",
        "enforcement_point": "git pre-commit hook invoking the engine on the staged index",
        "external_effects": "none: temporary local repository, no network, no secrets",
        "steps": steps,
        "summary": {
            "prevented_before_commit": all(
                step["outcome"] == "BLOCKED" for step in blocked_steps
            ),
            "owner_writes_admitted": all(
                step["outcome"] == "ADMITTED"
                for step in steps
                if step["step"].startswith(("R3", "R5"))
            ),
            "negative_control_confirms_attribution": steps[-1]["outcome"] == "ADMITTED",
            "static_overlap_detected_before_any_write": steps[0]["outcome"] == "OVERLAP_DETECTED",
        },
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[0]) if argv else None
    with tempfile.TemporaryDirectory() as tmp:
        record = run_reproduction(Path(tmp))
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
        print(json.dumps(record["summary"], indent=2, sort_keys=True))
    return 0 if all(record["summary"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
