#!/usr/bin/env python3
"""The reversibility gate: a rollback that was executed, not one that was described.

Ahmed Sadek, standing amendment 2026-08-23:

    "Reversibility. Snapshot before an irreversible write: tag, archive, recorded
    SHA. That is custody, not protection."

    "You do not need my permission for any of it — you need a reason and a rollback."

EARNED, and this is the defect that shaped the module: a prior lane published a
documented revert procedure that did not work when it was executed. Prose cannot
be run, so it was never tested until the moment it was needed, which is the worst
possible moment to discover a rollback is wrong. Every reversal here is therefore
constructed as argv and rehearsed against a real git remote before it is offered.

## Three things this checks that a naive rehearsal would not

**1. The tree, not the exit code.** `git revert` exits 0 on a conflict it
auto-resolved into something wrong, and `git push` exits 0 having done nothing
at all — the silent no-op this estate has already been bitten by. So the verdict
is recomputed from the git tree object the fixture remote serves after the
reversal ran, never from the command's return code. This is the same inversion
`evidence_integrity.verify_readback_truth` made after a fabricated read-back
record passed shape validation: recompute, do not trust.

**2. The tree, not the commit SHA.** A reverting commit is a NEW commit with a
DIFFERENT SHA and the SAME tree. Comparing commit SHAs would fail every correct
`REVERT_COMMIT_RANGE` reversal and would be a wrong test that looked strict.

**3. That the write it reverses actually changed something.** A reversal passes
trivially if the write was a no-op, so a rehearsal whose write did not move the
tree is reported as `REHEARSAL_PROVED_NOTHING` rather than as a pass.

## Why rehearsing on a fixture is honest

The rehearsal runs against a real bare git remote in a disposable directory,
optionally seeded with this repository's real history. It never touches `origin`.
What it proves is that the reversal CONSTRUCTOR produces argv that restores the
tree. `build_reversal` is the single source of that argv for both the rehearsal
and the declaration, and `command_matches_constructor` refuses a declaration
whose recorded command has been hand-edited away from what the constructor
emits — so what was rehearsed is the same program that will run.

What it does NOT prove, stated rather than glossed: that the real remote will
accept the push at the moment of rollback. Server-side ref rules, credentials and
a concurrent writer are outside a local fixture's reach.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXECUTED_AND_VERIFIED = "REVERSAL_EXECUTED_AND_VERIFIED"
DID_NOT_RESTORE = "REVERSAL_DID_NOT_RESTORE"
PROVED_NOTHING = "REHEARSAL_PROVED_NOTHING"
REHEARSAL_FAILED = "REHEARSAL_FAILED"

#: Applied to every fixture repository. A fixture with no identity cannot commit,
#: and a fixture that inherits ambient git config is not reproducible.
FIXTURE_CONFIG = (
    ("user.email", "rehearsal@obzio.invalid"),
    ("user.name", "Reversal Rehearsal"),
    ("commit.gpgsign", "false"),
    ("gc.auto", "0"),
)


def run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# The constructor: the one place a reversal argv is produced
# ---------------------------------------------------------------------------

def build_reversal(
    method: str,
    ref: str,
    *,
    recorded_sha: str | None = None,
    post_write_sha: str | None = None,
    remote: str = "origin",
    custody_ref: str | None = None,
    archive_path: str | None = None,
) -> dict[str, Any]:
    """Produce the exact argv that undoes a write, plus the custody it depends on.

    Both the declaration and the rehearsal call this, so the rehearsed program
    and the recorded program are the same program with different arguments.
    """
    if method == "RESTORE_REF_TO_RECORDED_SHA":
        if not recorded_sha:
            raise ValueError("RESTORE_REF_TO_RECORDED_SHA needs the SHA the ref held before the write")
        # --force-with-lease pinned to the expected post-write value: if anyone
        # else moved the ref after this write, the rollback refuses rather than
        # silently discarding their work. A bare --force would not.
        lease = f"--force-with-lease={ref}:{post_write_sha}" if post_write_sha else "--force-with-lease"
        return {
            "method": method,
            "command": ["git", "push", lease, remote, f"{recorded_sha}:refs/heads/{ref}"],
            "custody_required": ["recorded_sha", "custody_ref"],
            "restores": "the ref to its pre-write commit, discarding the written commits from the ref",
        }

    if method == "REVERT_COMMIT_RANGE":
        if not (recorded_sha and post_write_sha):
            raise ValueError("REVERT_COMMIT_RANGE needs both the pre-write and post-write SHAs")
        # Deliberately NOT --no-commit. The first draft of this constructor used
        # it, and the rehearsal caught it: --no-commit leaves the revert staged
        # but uncommitted, so the follow-up push published the unchanged
        # post-write commit, exited 0, and restored nothing. That is the exact
        # class of defect this gate exists to catch, found in its own output.
        return {
            "method": method,
            "command": ["git", "revert", "--no-edit", f"{recorded_sha}..{post_write_sha}"],
            "follow_up_command": ["git", "push", remote, f"HEAD:refs/heads/{ref}"],
            "custody_required": ["recorded_sha", "custody_ref"],
            "restores": "the tree to its pre-write content by a new forward commit, preserving history",
        }

    if method == "DELETE_CREATED_REF":
        return {
            "method": method,
            "command": ["git", "push", remote, "--delete", ref],
            "custody_required": ["created_ref"],
            "restores": "the remote to not having this ref, which is where it was before the write",
        }

    if method == "RESTORE_FROM_ARCHIVE":
        if not archive_path:
            raise ValueError("RESTORE_FROM_ARCHIVE needs the archive path holding the custody copy")
        return {
            "method": method,
            "command": ["git", "bundle", "unbundle", archive_path],
            "follow_up_command": ["git", "push", remote, f"{recorded_sha or 'FETCH_HEAD'}:refs/heads/{ref}"],
            "custody_required": ["archive_path", "archive_sha256"],
            "restores": "the ref from a bundle taken before the write",
        }

    raise ValueError(f"unknown reversal method {method!r}")


def command_matches_constructor(declaration: dict[str, Any]) -> list[str]:
    """Refuse a reversal command that has drifted from what the constructor emits.

    Without this the rehearsal proves something other than what will run: a
    declaration could carry a rehearsed constructor output in one field and a
    hand-written command in the other.
    """
    reversal = declaration.get("reversal") if isinstance(declaration.get("reversal"), dict) else {}
    target = declaration.get("target") if isinstance(declaration.get("target"), dict) else {}
    method, ref = reversal.get("method"), target.get("ref")
    if not method or not ref:
        return ["reversal.method or target.ref missing; the command cannot be re-derived"]
    try:
        expected = build_reversal(
            method, ref,
            recorded_sha=reversal.get("recorded_sha"),
            post_write_sha=reversal.get("post_write_sha"),
            remote=reversal.get("remote") or "origin",
            custody_ref=reversal.get("custody_ref"),
            archive_path=reversal.get("archive_path"),
        )
    except ValueError as exc:
        return [f"reversal cannot be re-derived: {exc}"]

    if list(reversal.get("command") or []) != expected["command"]:
        return [
            "reversal.command is not what the constructor produces for these parameters; "
            f"declared {reversal.get('command')!r}, constructor {expected['command']!r}. "
            "A hand-edited command was never the command that was rehearsed."
        ]
    return []


# ---------------------------------------------------------------------------
# The fixture: a real git remote, disposable, never `origin`
# ---------------------------------------------------------------------------

def _configure(repo: Path) -> None:
    for key, value in FIXTURE_CONFIG:
        run(["git", "config", key, value], cwd=repo)


def _tree_at(bare: Path, rev: str) -> str | None:
    code, out, _ = run(["git", "rev-parse", f"{rev}^{{tree}}"], cwd=bare)
    return out.strip() if code == 0 and out.strip() else None


def _commit_at(bare: Path, rev: str) -> str | None:
    code, out, _ = run(["git", "rev-parse", rev], cwd=bare)
    return out.strip() if code == 0 and out.strip() else None


def _build_fixture(workdir: Path, ref: str, seed_from: Path | None, seed_ref: str | None) -> tuple[Path, Path]:
    """A bare remote plus a working clone. Seeded from real history when asked."""
    origin = workdir / "origin.git"
    work = workdir / "work"
    code, _, err = run(["git", "init", "--quiet", "--bare", str(origin)])
    if code != 0:
        raise RuntimeError(f"fixture bare init failed: {err}")

    code, _, err = run(["git", "init", "--quiet", "-b", ref, str(work)])
    if code != 0:
        raise RuntimeError(f"fixture work init failed: {err}")
    _configure(work)
    run(["git", "remote", "add", "origin", str(origin)], cwd=work)

    if seed_from is not None:
        code, _, err = run(["git", "fetch", "--quiet", "--no-tags", str(seed_from), seed_ref or "HEAD"],
                           cwd=work, timeout=300)
        if code != 0:
            raise RuntimeError(f"fixture seed fetch failed: {err}")
        code, _, err = run(["git", "checkout", "--quiet", "-B", ref, "FETCH_HEAD"], cwd=work)
        if code != 0:
            raise RuntimeError(f"fixture seed checkout failed: {err}")
    else:
        (work / "content.txt").write_text("pre-write content\n", encoding="utf-8")
        (work / "nested").mkdir(exist_ok=True)
        (work / "nested" / "kept.txt").write_text("untouched by the write\n", encoding="utf-8")
        run(["git", "add", "-A"], cwd=work)
        code, _, err = run(["git", "commit", "--quiet", "-m", "fixture: pre-write state"], cwd=work)
        if code != 0:
            raise RuntimeError(f"fixture seed commit failed: {err}")

    code, _, err = run(["git", "push", "--quiet", "origin", f"{ref}:refs/heads/{ref}"], cwd=work, timeout=300)
    if code != 0:
        raise RuntimeError(f"fixture publish failed: {err}")
    return origin, work


def _apply_write(work: Path, ref: str, origin: Path, message: str) -> None:
    marker = work / "written-by-the-rehearsed-write.txt"
    marker.write_text(f"written at {_now()}\n", encoding="utf-8")
    existing = work / "content.txt"
    if existing.exists():
        existing.write_text("post-write content\n", encoding="utf-8")
    run(["git", "add", "-A"], cwd=work)
    code, _, err = run(["git", "commit", "--quiet", "-m", message], cwd=work)
    if code != 0:
        raise RuntimeError(f"rehearsed write commit failed: {err}")
    code, _, err = run(["git", "push", "--quiet", "origin", f"{ref}:refs/heads/{ref}"], cwd=work, timeout=300)
    if code != 0:
        raise RuntimeError(f"rehearsed write push failed: {err}")


def rehearse_reversal(
    method: str,
    *,
    ref: str = "rehearsal-target",
    seed_from: Path | None = None,
    seed_ref: str | None = None,
    sabotage: str | None = None,
    keep_fixture: Path | None = None,
) -> dict[str, Any]:
    """Execute a reversal against a real disposable remote and verify by recomputation.

    `sabotage` deliberately breaks the reversal so the tests can prove this
    rehearsal is a real test rather than a rubber stamp. A rehearsal that cannot
    fail is not evidence of anything.
    """
    started = _now()
    workdir = Path(tempfile.mkdtemp(prefix="reversal-rehearsal-"))
    receipt: dict[str, Any] = {
        "method": method,
        "ref": ref,
        "rehearsed_at": started,
        "sabotage": sabotage,
        "fixture_kind": "seeded_from_real_history" if seed_from else "synthetic",
        "touches_origin": False,
        "verified_by": (
            "recomputation of the git tree object served by the fixture remote after the reversal "
            "ran; the reversal command's exit code is recorded but is not the verdict"
        ),
    }
    try:
        origin, work = _build_fixture(workdir, ref, seed_from, seed_ref)
        receipt["fixture_remote"] = str(origin)

        pre_commit = _commit_at(origin, ref)
        pre_tree = _tree_at(origin, ref)
        receipt["pre_write"] = {"commit": pre_commit, "tree": pre_tree}

        if method == "DELETE_CREATED_REF":
            return _rehearse_delete(receipt, origin, work, ref, sabotage, workdir, keep_fixture)

        _apply_write(work, ref, origin, "rehearsed write under test")
        post_commit = _commit_at(origin, ref)
        post_tree = _tree_at(origin, ref)
        receipt["post_write"] = {"commit": post_commit, "tree": post_tree}

        # A reversal passes trivially if the write changed nothing.
        if not post_tree or post_tree == pre_tree:
            receipt["result"] = PROVED_NOTHING
            receipt["detail"] = (
                "the rehearsed write did not change the tree, so restoring it demonstrates nothing"
            )
            return receipt
        receipt["write_changed_the_tree"] = True

        plan = build_reversal(method, ref, recorded_sha=pre_commit, post_write_sha=post_commit)
        commands = [plan["command"]] + ([plan["follow_up_command"]] if plan.get("follow_up_command") else [])
        if sabotage:
            commands = _sabotage(commands, method, ref, pre_commit, post_commit, sabotage)
        receipt["reversal_commands"] = commands

        exits = []
        for command in commands:
            code, out, err = run(command, cwd=work, timeout=300)
            exits.append({"command": command, "exit_code": code,
                          "stderr_tail": err.strip()[-400:]})
            if code != 0:
                break
        receipt["execution"] = exits

        final_commit = _commit_at(origin, ref)
        final_tree = _tree_at(origin, ref)
        receipt["post_reversal"] = {"commit": final_commit, "tree": final_tree}
        receipt["tree_restored"] = bool(final_tree) and final_tree == pre_tree
        receipt["commit_restored"] = final_commit == pre_commit
        receipt["result"] = EXECUTED_AND_VERIFIED if receipt["tree_restored"] else DID_NOT_RESTORE
        if not receipt["tree_restored"]:
            receipt["detail"] = (
                f"after the reversal the remote serves tree {final_tree}, but the pre-write tree was "
                f"{pre_tree}; the rollback did not restore the state it claims to restore"
            )
        elif not receipt["commit_restored"]:
            receipt["detail"] = (
                "the tree is restored under a different commit SHA, which is correct for a forward "
                "revert and is why the verdict compares trees rather than commits"
            )
        return receipt
    except (RuntimeError, ValueError) as exc:
        receipt["result"] = REHEARSAL_FAILED
        receipt["detail"] = str(exc)
        return receipt
    finally:
        if keep_fixture:
            try:
                shutil.move(str(workdir), str(keep_fixture))
            except OSError:
                shutil.rmtree(workdir, ignore_errors=True)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def _rehearse_delete(receipt, origin: Path, work: Path, ref: str, sabotage, workdir, keep_fixture) -> dict[str, Any]:
    """A created ref is undone by removing it; the check is that it is gone.

    The pre-write state here is the ref's absence, not the fixture's content, so
    the receipt is corrected to say so rather than reporting the created state
    as though it predated the write.
    """
    created_commit = _commit_at(origin, ref)
    receipt["pre_write"] = {"commit": None, "tree": None,
                            "note": "the ref did not exist before the write that created it"}
    receipt["post_write"] = {"commit": created_commit, "tree": _tree_at(origin, ref)}
    plan = build_reversal("DELETE_CREATED_REF", ref)
    commands = [plan["command"]]
    if sabotage:
        commands = _sabotage(commands, "DELETE_CREATED_REF", ref, None, None, sabotage)
    receipt["reversal_commands"] = commands
    receipt["write_changed_the_tree"] = created_commit is not None
    exits = []
    for command in commands:
        code, _, err = run(command, cwd=work, timeout=300)
        exits.append({"command": command, "exit_code": code, "stderr_tail": err.strip()[-400:]})
    receipt["execution"] = exits
    still_there = _commit_at(origin, ref)
    receipt["post_reversal"] = {"commit": still_there, "tree": _tree_at(origin, ref)}
    receipt["tree_restored"] = still_there is None
    receipt["result"] = EXECUTED_AND_VERIFIED if still_there is None else DID_NOT_RESTORE
    if still_there is not None:
        receipt["detail"] = f"the ref still resolves to {still_there} after the deletion was executed"
    return receipt


def _sabotage(commands, method, ref, pre, post, mode: str):
    """Deliberately broken reversals, so the rehearsal can be shown able to fail."""
    if mode == "noop":
        return [["git", "--version"]]
    if mode == "wrong_sha":
        return [["git", "push", f"--force-with-lease={ref}:{post}", "origin", f"{post}:refs/heads/{ref}"]]
    if mode == "unrelated_command":
        return [["git", "status", "--porcelain"]]
    if mode == "partial_restore":
        return [["git", "checkout", "--quiet", str(pre), "--", "content.txt"],
                ["git", "commit", "--quiet", "-m", "partial restore"],
                ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{ref}"]]
    raise ValueError(f"unknown sabotage mode {mode!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute a reversal against a disposable remote and verify it")
    parser.add_argument("method", choices=sorted(
        {"RESTORE_REF_TO_RECORDED_SHA", "REVERT_COMMIT_RANGE", "DELETE_CREATED_REF"}))
    parser.add_argument("--ref", default="rehearsal-target")
    parser.add_argument("--seed-from", default=None,
                        help="repository to seed the fixture from, for a rehearsal on real history")
    parser.add_argument("--seed-ref", default=None)
    parser.add_argument("--sabotage", default=None,
                        choices=["noop", "wrong_sha", "unrelated_command", "partial_restore"])
    parser.add_argument("--out", default=None, help="write the receipt here")
    args = parser.parse_args(argv)

    receipt = rehearse_reversal(
        args.method, ref=args.ref,
        seed_from=Path(args.seed_from) if args.seed_from else None,
        seed_ref=args.seed_ref, sabotage=args.sabotage,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if receipt.get("result") == EXECUTED_AND_VERIFIED else 1


if __name__ == "__main__":
    sys.exit(main())
