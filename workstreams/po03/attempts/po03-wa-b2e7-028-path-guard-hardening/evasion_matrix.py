#!/usr/bin/env python3
"""Run the legacy and hardened path-scope guards over one evasion corpus.

Each case states what the commissioned allowlist requires, then both guards are
executed as separate processes and their real exit statuses are recorded.  The
point of the matrix is to be honest in both directions: most name-only evasions
are already refused by the legacy guard and the matrix says so, while the cases
the legacy guard admits are shown as `ADMITS` with the hardened guard's answer
beside them.

Exit codes: 0 the hardened guard satisfied every expectation, 1 it did not,
2 harness error.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
LEGACY_GUARD = REPO_ROOT / "workstreams/po03/tools/check_path_scope.py"
HARDENED_GUARD = UNIT_ROOT / "hardened_path_scope.py"

REFUSE = "refuse"
ALLOW = "allow"

# (case name, path, what the commissioned allowlist requires, why it matters)
NAME_ONLY_CORPUS = (
    ("in-allowlist-workstreams", "workstreams/po03/attempts/x/y.py", ALLOW, "control"),
    ("in-allowlist-receipts", "receipts/po03/2026-08-22/r.json", ALLOW, "control"),
    ("in-allowlist-workflow", ".github/workflows/po03-suite.yml", ALLOW, "control"),
    ("dotdot-traversal", "workstreams/po03/../state/x", REFUSE, "traversal"),
    ("dotdot-only", "..", REFUSE, "traversal"),
    ("absolute-path", "/workstreams/po03/x", REFUSE, "absolute path"),
    ("backslash-separator", "workstreams\\po03\\x", REFUSE, "backslash"),
    ("nul-byte", "workstreams/po03/x\x00.py", REFUSE, "NUL"),
    ("cyrillic-o-confusable", "workstreams/p\u043e03/x", REFUSE, "unicode confusable"),
    ("fullwidth-w-confusable", "\uff57orkstreams/po03/x", REFUSE, "unicode confusable"),
    ("case-variant-prefix", "WORKSTREAMS/PO03/x", REFUSE, "case variation"),
    ("case-variant-workflow", ".github/workflows/PO03-a.yml", REFUSE, "case variation"),
    ("trailing-dot-directory", "workstreams/po03./x", REFUSE, "trailing dot"),
    ("single-dot-component", "workstreams/po03/./x", REFUSE, "non-canonical spelling"),
    ("double-slash", "workstreams/po03//x", REFUSE, "non-canonical spelling"),
    ("trailing-slash", "workstreams/po03/x/", REFUSE, "non-canonical spelling"),
    ("prefix-sibling-directory", "workstreams/po03-evil/x", REFUSE, "prefix boundary"),
    ("receipts-sibling-directory", "receipts/po03-evil/x", REFUSE, "prefix boundary"),
    ("nested-workflow-path", ".github/workflows/po03-a/b.yml", REFUSE,
     "the allowlist glob .github/workflows/po03-*.yml does not cross a directory boundary"),
    ("workflow-wrong-suffix", ".github/workflows/po03-a.yaml", REFUSE, "suffix"),
    ("lookalike-workflow", ".github/workflows/not-po03.yml", REFUSE, "prefix"),
    ("trailing-dot-file", "workstreams/po03/x.", REFUSE,
     "deliberate narrowing: collides with workstreams/po03/x on Windows"),
    ("trailing-space-file", "workstreams/po03/x ", REFUSE,
     "deliberate narrowing: collides with workstreams/po03/x on Windows"),
    ("bidi-override-in-allowlist", "workstreams/po03/\u202egnp.txt", REFUSE,
     "deliberate narrowing: a right-to-left override makes review display a different name"),
    ("non-ascii-in-allowlist", "workstreams/po03/caf\u00e9.txt", REFUSE,
     "deliberate narrowing: NFC and NFD spellings collide on case-insensitive filesystems"),
    ("protected-state-path", "state/PO03-SHOULD-NOT-WRITE.json", REFUSE, "out of scope"),
    ("po01-path", "workstreams/po01/producer-result.json", REFUSE, "out of scope"),
    ("environment-json", ".cursor/environment.json", REFUSE, "out of scope"),
)


class HarnessError(Exception):
    """Raised when a guard or git cannot be run at all."""


def run(command: tuple[str, ...], cwd: Path) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise HarnessError(f"cannot run {command[:3]}: {exc}") from exc
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def verdict(exit_code: int) -> str:
    if exit_code == 0:
        return "ADMITS"
    if exit_code == 1:
        return "REFUSES"
    return f"ERRORS({exit_code})"


def load(module_path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, module_path)
    if specification is None or specification.loader is None:
        raise HarnessError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def in_process_verdicts(path: str) -> tuple[int, int, str]:
    """Judge a path both guards cannot receive through argv.

    A NUL byte cannot cross an `execve` boundary, and `git diff -z` uses NUL as
    its own field separator, so no real change set can deliver this path to
    either guard's command line.  Both guards are therefore called directly.
    """
    legacy = load(LEGACY_GUARD, "po03_legacy_guard")
    hardened = load(HARDENED_GUARD, "po03_hardened_guard")
    legacy_exit = 1 if legacy.violations([path]) else 0
    findings = hardened.evaluate([hardened.ChangedEntry(status="A", path=path)])
    return legacy_exit, (1 if findings else 0), "; ".join(findings)


def name_only_rows() -> list[dict]:
    rows = []
    for name, path, requirement, rationale in NAME_ONLY_CORPUS:
        if "\x00" in path:
            channel = "in-process (argv cannot carry a NUL byte)"
            legacy_exit, hardened_exit, hardened_output = in_process_verdicts(path)
        else:
            channel = "argv"
            legacy_exit, _ = run((sys.executable, "-I", str(LEGACY_GUARD), "--path", path), REPO_ROOT)
            hardened_exit, hardened_output = run(
                (sys.executable, "-I", str(HARDENED_GUARD), "--path", path), REPO_ROOT
            )
        expected_admit = requirement == ALLOW
        rows.append(
            {
                "case": name,
                "kind": "name-only",
                "channel": channel,
                "subject": path,
                "requirement": requirement,
                "rationale": rationale,
                "legacy": verdict(legacy_exit),
                "hardened": verdict(hardened_exit),
                "hardened_satisfies_requirement": (hardened_exit == 0) == expected_admit,
                "legacy_satisfies_requirement": (legacy_exit == 0) == expected_admit,
                "hardened_detail": hardened_output.strip().splitlines()[:1],
            }
        )
    return rows


def git(repo: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HarnessError(f"git {' '.join(arguments)} failed: {exc}") from exc


def new_repository(root: Path, name: str) -> tuple[Path, str]:
    """A throwaway repository with one in-allowlist file and one outside it."""
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "scratch", ".")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "po03-evasion-matrix")
    (repo / "workstreams/po03/attempts/scratch").mkdir(parents=True)
    (repo / "workstreams/po03/attempts/scratch/a.txt").write_text("a\n", encoding="utf-8")
    (repo / "state").mkdir(parents=True)
    (repo / "state/PROTECTED.json").write_text('{"owner": "not po03"}\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "scratch base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def repository_rows(scratch_root: Path) -> list[dict]:
    rows: list[dict] = []

    def judge(case: str, repo: Path, base: str, requirement: str, rationale: str) -> None:
        legacy_exit, _ = run(
            (sys.executable, "-I", str(LEGACY_GUARD), "--base", base, "--head", "HEAD"), repo
        )
        hardened_exit, hardened_output = run(
            (sys.executable, "-I", str(HARDENED_GUARD), "--repo", ".", "--base", base, "--head", "HEAD"),
            repo,
        )
        expected_admit = requirement == ALLOW
        rows.append(
            {
                "case": case,
                "kind": "repository",
                "channel": "git diff",
                "subject": f"{base[:12]}..HEAD",
                "requirement": requirement,
                "rationale": rationale,
                "legacy": verdict(legacy_exit),
                "hardened": verdict(hardened_exit),
                "hardened_satisfies_requirement": (hardened_exit == 0) == expected_admit,
                "legacy_satisfies_requirement": (legacy_exit == 0) == expected_admit,
                "hardened_detail": hardened_output.strip().splitlines()[:1],
            }
        )

    repo, base = new_repository(scratch_root, "control")
    (repo / "workstreams/po03/attempts/scratch/b.txt").write_text("b\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "in-allowlist addition")
    judge("repo-in-allowlist-control", repo, base, ALLOW, "control")

    repo, base = new_repository(scratch_root, "out-of-allowlist")
    (repo / "state/NEW.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "out-of-allowlist addition")
    judge("repo-out-of-allowlist-add", repo, base, REFUSE, "out of scope")

    repo, base = new_repository(scratch_root, "rename-in")
    git(repo, "mv", "state/PROTECTED.json", "workstreams/po03/attempts/scratch/imported.json")
    git(repo, "commit", "-qm", "rename an out-of-allowlist file into the allowlist")
    judge(
        "repo-rename-out-of-allowlist-into-allowlist", repo, base, REFUSE,
        "the rename deletes state/PROTECTED.json, which git diff --name-only never shows",
    )

    repo, base = new_repository(scratch_root, "rename-out")
    git(repo, "mv", "workstreams/po03/attempts/scratch/a.txt", "state/exported.txt")
    git(repo, "commit", "-qm", "rename an in-allowlist file out of the allowlist")
    judge("repo-rename-allowlist-into-out-of-allowlist", repo, base, REFUSE, "out of scope destination")

    repo, base = new_repository(scratch_root, "symlink-escape")
    (repo / "workstreams/po03/attempts/scratch/link-to-state").symlink_to("../../../../state")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add an in-allowlist symlink pointing outside the allowlist")
    judge(
        "repo-symlink-target-out-of-allowlist", repo, base, REFUSE,
        "an in-allowlist name whose blob is a mode 120000 handle to state/",
    )

    repo, base = new_repository(scratch_root, "symlink-absolute")
    (repo / "workstreams/po03/attempts/scratch/passwd").symlink_to("/etc/passwd")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add an absolute symlink inside the allowlist")
    judge("repo-symlink-target-absolute", repo, base, REFUSE, "absolute symlink target")

    repo, base = new_repository(scratch_root, "symlink-internal")
    (repo / "workstreams/po03/attempts/scratch/alias.txt").symlink_to("a.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add a symlink that stays inside the allowlist")
    judge(
        "repo-symlink-target-in-allowlist", repo, base, ALLOW,
        "a symlink whose target stays in scope is legitimate and must not be blocked",
    )

    repo, base = new_repository(scratch_root, "typechange")
    target = repo / "workstreams/po03/attempts/scratch/a.txt"
    target.unlink()
    target.symlink_to("../../../../state/PROTECTED.json")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "replace an in-allowlist file with a symlink out of the allowlist")
    judge(
        "repo-typechange-file-to-escaping-symlink", repo, base, REFUSE,
        "a type change from regular file to symlink keeps the same in-allowlist name",
    )

    repo, base = new_repository(scratch_root, "gitlink")
    commit = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},workstreams/po03/attempts/scratch/sub")
    tree = git(repo, "write-tree").strip()
    new_commit = git(repo, "commit-tree", tree, "-p", commit, "-m", "add a gitlink inside the allowlist").strip()
    git(repo, "update-ref", "refs/heads/scratch", new_commit)
    git(repo, "reset", "-q", "--hard", "refs/heads/scratch")
    judge(
        "repo-gitlink-inside-allowlist", repo, base, REFUSE,
        "a mode 160000 pointer imports an entire foreign repository under an allowlisted name",
    )
    return rows


def build(scratch_root: Path) -> list[dict]:
    return name_only_rows() + repository_rows(scratch_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--scratch-root")
    args = parser.parse_args(argv)
    if not LEGACY_GUARD.is_file() or not HARDENED_GUARD.is_file():
        print("PO03_MATRIX_ERROR: a guard is missing", file=sys.stderr)
        return 2
    holder = Path(tempfile.mkdtemp(prefix="po03-matrix-", dir=args.scratch_root or None))
    try:
        rows = build(holder)
    except HarnessError as exc:
        print(f"PO03_MATRIX_ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(holder, ignore_errors=True)

    if args.json:
        print(json.dumps({"rows": rows}, indent=2, sort_keys=True))
    else:
        width = max(len(row["case"]) for row in rows)
        print(f"{'case'.ljust(width)}  requires  legacy      hardened    subject")
        print("-" * (width + 46))
        for row in rows:
            print(
                f"{row['case'].ljust(width)}  {row['requirement'].ljust(8)}  "
                f"{row['legacy'].ljust(10)}  {row['hardened'].ljust(10)}  {row['subject']}"
            )
    legacy_gaps = [row for row in rows if not row["legacy_satisfies_requirement"]]
    hardened_gaps = [row for row in rows if not row["hardened_satisfies_requirement"]]
    print()
    print(f"cases={len(rows)} legacy_unsatisfied={len(legacy_gaps)} hardened_unsatisfied={len(hardened_gaps)}")
    for row in legacy_gaps:
        print(f"LEGACY_GAP: {row['case']} ({row['rationale']}) legacy={row['legacy']} hardened={row['hardened']}")
    for row in hardened_gaps:
        print(f"HARDENED_GAP: {row['case']} ({row['rationale']}) hardened={row['hardened']}", file=sys.stderr)
    if hardened_gaps:
        return 1
    print("PO03_MATRIX_PASS the hardened guard satisfied every stated requirement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
