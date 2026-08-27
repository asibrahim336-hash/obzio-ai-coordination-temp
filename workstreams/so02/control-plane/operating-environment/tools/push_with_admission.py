#!/usr/bin/env python3
"""An explicit, invoked push-path wrapper around `write_admission.py`.

## The defect this exists to close (`INSTALLED_NOT_EFFECTIVE`)

FOUNDER_AUTHORED, named in writing 2026-08-27 (SCP-SI-01 baseline). Three
defects in this estate turned out to be one class: a control passed its own
check while measuring or guarding the wrong thing. This lane's instance:

    DIRECTLY_REPRODUCED, SCP-SI-01-BASELINE.yaml `hook_firing_verdict`, armed
    2026-08-27T04:56:41Z, checked 2026-08-27T04:57:11Z: two commands that
    `guard_write_scope.py` refuses when invoked by hand both EXECUTED when
    sent through the agent shell tool, and the guard's own append-only audit
    log gained no line. Cursor loads `.cursor/hooks.json` from a project root
    fixed at run start; every lane works in a `git worktree` under `/tmp`, so
    the `beforeShellExecution` hook that would call `write_admission.py`
    never fires there. `require_write_declaration: true` in the shipped
    `.cursor/write-scope.json` is consequently DOCUMENTATION in that topology,
    not enforcement — the guard script is correct and unreached.

## The wrong fix, named and rejected

Moving lanes into `/workspace` so the ambient hook's project root lines up
with the working directory would trade `INSTALLED_NOT_EFFECTIVE` for
`SHARED_WORKTREE_COLLISION` — DIRECTLY_REPRODUCED, live, within two minutes of
a prior dispatch (lanes sharing one checkout committed onto a detached HEAD
and silently published a stale ref). Worktree isolation is EARNED mechanism
and stays. The correct fix is to stop depending on the ambient hook at all.

## What this script is

A lane invokes this explicitly, in its own push step, instead of running
`git push` directly. It runs the exact same `write_admission.admit()` gates
the ambient hook was supposed to trigger, and refuses the push when admission
refuses. Nothing here is registered in `.cursor/hooks.json`; nothing here
fires on its own. It has to be called.

## What this script is honestly NOT

* It is **not dispatch-time enforcement**. A lane that never calls this
  script is exactly as unstopped as one that never went through the ambient
  hook. Voluntary-but-explicit is stronger than ambient-and-absent — a lane
  that reads its own push-path documentation will hit this call — but it is
  not a gate the platform inserts on its own.
* It is **not a replacement for `lane_guard.py`**. The founder's own
  statement stands: the only thing in this estate that is genuinely
  enforcing is `lane_guard.py` at integration time, because it reads remote
  bytes and the coordinator runs it regardless of what any lane chooses to
  do. This wrapper narrows the gap on the lane side; it does not close it.

## Why "works from any cwd" is load-bearing, not decorative

A gate that only works when you happen to be standing in the right directory
is the same defect shape as a hook that only fires when the project root
happens to match your cwd — a control whose effectiveness is contingent on
an ambient fact nobody is required to satisfy. So every path this script
needs is resolved from the SCRIPT'S OWN location and from `git`, never from
`os.getcwd()`:

* `write_admission.py` is loaded from `Path(__file__).resolve().parent`, the
  directory this file actually lives in on disk — not a path built by
  assuming some project root and walking down from it.
* The repository root is resolved by running `git rev-parse --show-toplevel`
  with `cwd` pinned to that same script directory, never to the caller's
  cwd. Because `git worktree` gives every lane its own independent root, this
  is also what keeps the wrapper inside its own lane's worktree rather than
  reaching into another one — worktree isolation is preserved, not routed
  around.
* The actual `git push` this wrapper runs is executed with `cwd` pinned to
  that resolved repository root, never to the caller's cwd.
* The declaration file the caller names is the only input resolved against
  the caller's cwd (an explicit `--declaration PATH`, exactly like naming any
  other file on a command line) — and even there, admission recomputes
  everything the declaration claims rather than trusting it, so standing in
  a directory that happens to contain a friendly-looking file buys nothing.

There is therefore no cwd from which "being in the wrong directory" makes
this wrapper admit a write it would otherwise refuse, and no cwd from which
it can be invoked but silently no-op instead of running the gates.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent

REFUSED_EXIT = 1
SETUP_ERROR_EXIT = 2


def _load_write_admission():
    """Load write_admission.py from beside this file, never from sys.path.

    Using `importlib.util.spec_from_file_location` against an absolute path
    derived from `__file__` means this import cannot be shadowed by a
    same-named module earlier on `sys.path`, and cannot silently resolve to a
    different `write_admission.py` because the caller's cwd changed.
    """
    target = SCRIPT_DIR / "write_admission.py"
    if not target.is_file():
        print(
            f"SETUP ERROR: write_admission.py not found beside this wrapper at {target}. "
            "This wrapper refuses rather than proceeding without the gate it exists to call.",
            file=sys.stderr,
        )
        return None
    spec = importlib.util.spec_from_file_location("write_admission", target)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["write_admission"] = module
    spec.loader.exec_module(module)
    return module


def _git(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def resolve_repo_root(repo_override: str | None) -> Path | None:
    """The repository root, derived from this script's own location or an
    explicit override — never from the caller's ambient cwd.

    `repo_override` is an operator's deliberate, explicit choice (useful for
    a fixture repo in a test, or a vendored copy of these tools elsewhere).
    It is not a cwd side effect: nothing here defaults to it, and nothing
    here infers it from where the process happens to be standing.
    """
    if repo_override:
        candidate = Path(repo_override).resolve()
        code, out, err = _git(["rev-parse", "--show-toplevel"], cwd=candidate)
        if code != 0:
            print(f"SETUP ERROR: --repo {candidate} is not inside a git repository: {err.strip()}",
                  file=sys.stderr)
            return None
        return Path(out.strip())

    code, out, err = _git(["rev-parse", "--show-toplevel"], cwd=SCRIPT_DIR)
    if code != 0:
        print(
            f"SETUP ERROR: could not resolve a repository root from this script's own "
            f"location ({SCRIPT_DIR}): {err.strip()}. Refusing rather than falling back to cwd.",
            file=sys.stderr,
        )
        return None
    return Path(out.strip())


def load_declaration(path_arg: str) -> tuple[dict[str, Any] | None, str | None]:
    import json

    path = Path(path_arg).resolve()
    if not path.is_file():
        return None, f"no declaration file at {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read/parse declaration at {path}: {exc}"


def push_argv_for(declaration: dict[str, Any], remote: str, extra_argv: list[str] | None) -> list[str] | None:
    """The exact push argv this wrapper will run, verified against the declaration.

    If the caller supplies argv after `--`, it must be a `git push` naming
    the same ref the declaration declares — a lane cannot declare one ref and
    push a different one through this wrapper. If the caller supplies
    nothing, the wrapper constructs the ordinary publishing push itself.
    """
    target = declaration.get("target") if isinstance(declaration, dict) else None
    ref = (target or {}).get("ref")
    if not ref:
        return None

    if not extra_argv:
        return ["git", "push", "-u", remote, f"HEAD:refs/heads/{ref}"]

    if extra_argv[0] != "git" or "push" not in extra_argv:
        print("SETUP ERROR: --  must be followed by a `git push ...` command.", file=sys.stderr)
        return None
    if ref not in " ".join(extra_argv):
        print(
            f"SETUP ERROR: the supplied push command does not name declared ref {ref!r}; "
            "a wrapper that ran a different push than the one it admitted would not be a gate.",
            file=sys.stderr,
        )
        return None
    return extra_argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Explicit push-path wrapper: run write_admission.py's gates and refuse the push "
            "when admission refuses. Works from any cwd; see module docstring for how."
        )
    )
    parser.add_argument("--declaration", required=True,
                        help="path to the write declaration covering this push")
    parser.add_argument("--repo", default=None,
                        help="explicit repository root override (default: derived from this "
                             "script's own on-disk location via git, never from cwd)")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--remote-url", default=None,
                        help="passed through to the evidence gate for READBACK recomputation")
    parser.add_argument("--ratified", nargs="*", default=[])
    parser.add_argument("--no-rehearsal", action="store_true")
    parser.add_argument("--no-ref-movement", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every gate and report the verdict, but never run git push")
    parser.add_argument("push_argv", nargs="*",
                        help="optional: the exact `git push ...` to run if admitted, after --")
    args = parser.parse_args(argv)

    write_admission = _load_write_admission()
    if write_admission is None:
        return SETUP_ERROR_EXIT

    repo_root = resolve_repo_root(args.repo)
    if repo_root is None:
        return SETUP_ERROR_EXIT

    declaration, error = load_declaration(args.declaration)
    if error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return REFUSED_EXIT

    report = write_admission.admit(
        declaration,
        repo_root,
        ratified_assistant_checks=args.ratified,
        rehearse_reversal=not args.no_rehearsal,
        check_ref_movement=not args.no_ref_movement,
        remote_url=args.remote_url,
    )
    print(write_admission.summarise(report))

    if not report["admitted"]:
        print(
            "\nREFUSED: push blocked by this wrapper before any git command ran. "
            "This is the explicit gate the ambient hook cannot currently provide "
            "(INSTALLED_NOT_EFFECTIVE, DIRECTLY_REPRODUCED 2026-08-27); it is voluntary "
            "and lane-side, and it refused here because it ran.",
            file=sys.stderr,
        )
        return REFUSED_EXIT

    push_argv = push_argv_for(declaration, args.remote, args.push_argv or None)
    if push_argv is None:
        return SETUP_ERROR_EXIT

    if args.dry_run:
        print(f"\nADMITTED (dry run, not executed): {' '.join(push_argv)}")
        return 0

    print(f"\nADMITTED. Running: {' '.join(push_argv)}  (cwd={repo_root})")
    result = subprocess.run(push_argv, cwd=repo_root)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
