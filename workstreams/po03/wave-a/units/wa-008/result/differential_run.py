#!/usr/bin/env python3
"""Two-checkout differential runner for hidden-state dependency detection.

PO-03 Wave A unit PO03-WA-008 (hypothesis H-PO03-WA-008).

The runner executes one command twice: once in a candidate ("warm") checkout as
it actually exists, and once in a freshly materialised checkout of the same
immutable commit under a sanitised environment. When the two outcomes diverge it
attributes the divergence to one of three disjoint hidden-state classes by
replaying the clean side with exactly one class of contamination re-applied.

Classes:

``UNTRACKED_FILE_DEPENDENCY``
    Working-tree files that are not in the commit tree and are not classified as
    cache paths.
``ENVIRONMENT_LEAKAGE``
    Ambient environment variables that are absent from, or differ from, the
    sanitised baseline environment.
``WARM_CACHE``
    Working-tree paths matching declared cache globs, plus the contents of the
    external cache root exposed as ``XDG_CACHE_HOME``.

Only the Python standard library is used, so the runner executes from a clean
clone with no installation step.

Environment variable *values* are never written to the report; only key names
and SHA-256 digests of values are recorded, so a contaminated ambient
environment carrying credentials cannot leak into a committed artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROTOCOL_VERSION = "OBZIO-DIFFERENTIAL-RUN-v1"

CLASS_UNTRACKED = "UNTRACKED_FILE_DEPENDENCY"
CLASS_ENVIRONMENT = "ENVIRONMENT_LEAKAGE"
CLASS_WARM_CACHE = "WARM_CACHE"
HIDDEN_STATE_CLASSES = (CLASS_UNTRACKED, CLASS_ENVIRONMENT, CLASS_WARM_CACHE)

VERDICT_CLEAN = "NO_HIDDEN_STATE_DEPENDENCY_DETECTED"
VERDICT_ATTRIBUTED = "HIDDEN_STATE_DEPENDENCY_ATTRIBUTED"
VERDICT_UNATTRIBUTED = "HIDDEN_STATE_DEPENDENCY_UNATTRIBUTED"
VERDICT_NONDETERMINISTIC = "NONDETERMINISTIC_COMMAND"

EXIT_BY_VERDICT = {
    VERDICT_CLEAN: 0,
    VERDICT_ATTRIBUTED: 3,
    VERDICT_UNATTRIBUTED: 4,
    VERDICT_NONDETERMINISTIC: 5,
}

DEFAULT_CACHE_GLOBS = (
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyo",
    "**/.cache/**",
    "**/.po03-cache/**",
    "**/.mypy_cache/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/node_modules/.cache/**",
)

# Variables the operating system or subprocess layer rewrites for every child;
# treating them as leakage would make every run report a false positive.
VOLATILE_ENVIRONMENT_KEYS = frozenset({"PWD", "OLDPWD", "SHLVL", "_"})

SANITISED_BASE_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "PYTHONHASHSEED",
)

DEFAULT_TIMEOUT_SECONDS = 120


class DifferentialRunError(RuntimeError):
    """Raised when the differential run cannot be set up honestly."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    return sha256_bytes(payload.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


class GlobSet:
    """Matches POSIX-style relative paths against a fixed glob list."""

    def __init__(self, patterns) -> None:
        self.patterns = tuple(patterns)
        self._regexes = tuple(glob_to_regex(pattern) for pattern in self.patterns)

    def matches(self, relative_path: str) -> bool:
        candidates = [relative_path]
        parts = relative_path.split("/")
        # A cache glob written as ``**/.cache/**`` must also claim the directory
        # entry itself and everything below it.
        for stop in range(1, len(parts)):
            candidates.append("/".join(parts[:stop]))
        for regex in self._regexes:
            for candidate in candidates:
                if regex.match(candidate):
                    return True
        return False


def run_git(args, cwd=None, check=True):
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=git_environment(),
    )
    if check and completed.returncode != 0:
        raise DifferentialRunError(
            "git {} failed in {}: {}".format(" ".join(args), cwd, completed.stderr.strip())
        )
    return completed


GIT_FIXED_DATE = "2026-08-22T00:00:00+00:00"


def git_environment() -> dict:
    """Deterministic environment for the runner's own git invocations.

    Author and committer identity and dates are pinned so that any repository
    built through this helper is byte-reproducible: two independent builds of the
    same fixture content yield the same commit id, which is what makes the
    recurrence assertions in the test suite meaningful.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "PO03 Differential Runner",
        "GIT_AUTHOR_EMAIL": "po03-differential@obzio.invalid",
        "GIT_AUTHOR_DATE": GIT_FIXED_DATE,
        "GIT_COMMITTER_NAME": "PO03 Differential Runner",
        "GIT_COMMITTER_EMAIL": "po03-differential@obzio.invalid",
        "GIT_COMMITTER_DATE": GIT_FIXED_DATE,
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    return env


def tracked_paths(repo: Path, commit: str) -> frozenset:
    completed = run_git(["ls-tree", "-r", "-z", "--name-only", commit], cwd=repo)
    entries = [entry for entry in completed.stdout.split("\0") if entry]
    return frozenset(entries)


def materialise_clean_checkout(repo: Path, commit: str, destination: Path) -> Path:
    """Create an independent checkout of ``commit`` with no working-tree extras.

    The destination is produced by a non-local, non-hardlinked clone so that it
    shares no inode and no object store with the source working copy.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_git(
        [
            "clone",
            "--no-hardlinks",
            "--no-local",
            "--quiet",
            "--no-checkout",
            str(repo.resolve()),
            str(destination),
        ]
    )
    if run_git(["cat-file", "-e", commit + "^{commit}"], cwd=destination, check=False).returncode != 0:
        run_git(["fetch", "--quiet", "--no-tags", str(repo.resolve()), "+refs/*:refs/imported/*"], cwd=destination)
    if run_git(["cat-file", "-e", commit + "^{commit}"], cwd=destination, check=False).returncode != 0:
        run_git(["fetch", "--quiet", "--no-tags", str(repo.resolve()), commit], cwd=destination)
    if run_git(["cat-file", "-e", commit + "^{commit}"], cwd=destination, check=False).returncode != 0:
        raise DifferentialRunError(
            "commit {} is not reachable in an independent clone of {}".format(commit, repo)
        )
    run_git(["checkout", "--quiet", "--detach", commit], cwd=destination)
    run_git(["clean", "-xdffq"], cwd=destination)
    residue = run_git(["status", "--porcelain", "--ignored"], cwd=destination).stdout.strip()
    if residue:
        raise DifferentialRunError("freshly materialised checkout is not pristine: " + residue)
    return destination


def inventory_worktree_extras(worktree: Path, tracked: frozenset, cache_globs: GlobSet):
    """Split working-tree files that are absent from the commit tree by class."""
    untracked = []
    cache = []
    worktree = Path(worktree)
    for root, directories, files in os.walk(worktree):
        root_path = Path(root)
        if root_path == worktree:
            directories[:] = [name for name in directories if name != ".git"]
        for name in sorted(files):
            absolute = root_path / name
            relative = absolute.relative_to(worktree).as_posix()
            if relative in tracked:
                continue
            record = {
                "path": relative,
                "bytes": absolute.stat().st_size if absolute.is_file() and not absolute.is_symlink() else 0,
                "sha256": sha256_file(absolute) if absolute.is_file() and not absolute.is_symlink() else None,
            }
            if cache_globs.matches(relative):
                cache.append(record)
            else:
                untracked.append(record)
        directories.sort()
    untracked.sort(key=lambda record: record["path"])
    cache.sort(key=lambda record: record["path"])
    return untracked, cache


def inventory_external_cache(cache_root):
    if cache_root is None:
        return []
    cache_root = Path(cache_root)
    if not cache_root.is_dir():
        return []
    records = []
    for root, directories, files in os.walk(cache_root):
        for name in sorted(files):
            absolute = Path(root) / name
            if absolute.is_symlink() or not absolute.is_file():
                continue
            records.append(
                {
                    "path": absolute.relative_to(cache_root).as_posix(),
                    "bytes": absolute.stat().st_size,
                    "sha256": sha256_file(absolute),
                }
            )
        directories.sort()
    records.sort(key=lambda record: record["path"])
    return records


def sanitised_environment(sandbox_home: Path, sandbox_tmp: Path, sandbox_cache: Path) -> dict:
    for directory in (sandbox_home, sandbox_tmp, sandbox_cache):
        Path(directory).mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(sandbox_home),
        "TMPDIR": str(sandbox_tmp),
        "XDG_CACHE_HOME": str(sandbox_cache),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
    }


def environment_delta(ambient: dict, baseline: dict) -> dict:
    """Ambient variables that a sanitised run would not see, or would see differently."""
    delta = {}
    for key, value in ambient.items():
        if key in VOLATILE_ENVIRONMENT_KEYS:
            continue
        if key in baseline and baseline[key] == value:
            continue
        if key in ("HOME", "TMPDIR", "XDG_CACHE_HOME"):
            # Redirected on purpose for every side; not a leakage finding.
            continue
        delta[key] = value
    return delta


def redact_environment_delta(delta: dict):
    return [
        {"key": key, "value_sha256": sha256_text(value), "value_bytes": len(value.encode("utf-8"))}
        for key, value in sorted(delta.items())
    ]


def copy_paths(source_root: Path, destination_root: Path, records) -> int:
    copied = 0
    for record in records:
        source = Path(source_root) / record["path"]
        destination = Path(destination_root) / record["path"]
        if not source.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def normalise_output(text: str, replacements) -> str:
    normalised = text
    # Longest first so that nested sandbox roots collapse to the outer token.
    for needle, token in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        if needle:
            normalised = normalised.replace(needle, token)
    normalised = "\n".join(line.rstrip() for line in normalised.splitlines())
    return normalised.strip()


def outcome_digest(exit_code: int, stdout: str, stderr: str) -> str:
    payload = json.dumps(
        {"exit_code": exit_code, "stdout": stdout, "stderr": stderr},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(payload)


def execute(command, cwd: Path, env: dict, timeout: int, replacements):
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as expired:
        exit_code = 124
        stdout = expired.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        stderr = expired.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        timed_out = True
    normalised_stdout = normalise_output(stdout, replacements)
    normalised_stderr = normalise_output(stderr, replacements)
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": normalised_stdout,
        "stderr": normalised_stderr,
        "digest": outcome_digest(exit_code, normalised_stdout, normalised_stderr),
        "wall_time_seconds": round(time.monotonic() - started, 6),
    }


def run_side(command, cwd: Path, env: dict, timeout: int, replacements, repeats: int):
    runs = [execute(command, cwd, env, timeout, replacements) for _ in range(repeats)]
    digests = sorted({run["digest"] for run in runs})
    return {
        "digest": runs[0]["digest"],
        "deterministic": len(digests) == 1,
        "distinct_digests": digests,
        "exit_code": runs[0]["exit_code"],
        "stdout": runs[0]["stdout"],
        "stderr": runs[0]["stderr"],
        "repeats": repeats,
        "wall_time_seconds": round(sum(run["wall_time_seconds"] for run in runs), 6),
    }


class DifferentialRun:
    """One differential comparison of a command across two checkouts."""

    def __init__(
        self,
        repo,
        commit,
        command,
        warm_checkout=None,
        warm_env=None,
        warm_cache_root=None,
        cache_globs=DEFAULT_CACHE_GLOBS,
        repeats=2,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        sandbox=None,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.commit = commit
        self.command = list(command)
        self.warm_checkout = Path(warm_checkout).resolve() if warm_checkout else self.repo
        self.warm_env = dict(os.environ if warm_env is None else warm_env)
        self.warm_cache_root = Path(warm_cache_root).resolve() if warm_cache_root else None
        self.cache_globs = GlobSet(cache_globs)
        self.repeats = max(1, int(repeats))
        self.timeout = int(timeout)
        self._sandbox = Path(sandbox).resolve() if sandbox else None
        self._owns_sandbox = sandbox is None
        self._checkout_serial = 0

    def _new_sandbox(self) -> Path:
        if self._sandbox is None:
            self._sandbox = Path(tempfile.mkdtemp(prefix="po03-wa-008-differential-")).resolve()
        return self._sandbox

    def _fresh_checkout(self, label: str):
        sandbox = self._new_sandbox()
        self._checkout_serial += 1
        base = sandbox / "{:02d}-{}".format(self._checkout_serial, label)
        checkout = base / "checkout"
        home = base / "home"
        tmp = base / "tmp"
        cache = base / "cache"
        materialise_clean_checkout(self.repo, self.commit, checkout)
        env = sanitised_environment(home, tmp, cache)
        return {"root": base, "checkout": checkout, "env": env, "cache_root": cache}

    def _side_replacements(self, checkout: Path, env: dict):
        """Per-side path tokens.

        Each side's own checkout, home, temporary and cache roots collapse to the
        *same* tokens, so two checkouts at different absolute locations do not
        manufacture a divergence. Longest-needle-first ordering in
        ``normalise_output`` keeps nested roots from shadowing each other.
        """
        replacements = [
            (str(checkout), "<CHECKOUT>"),
            (env.get("HOME", ""), "<HOME>"),
            (env.get("TMPDIR", ""), "<TMPDIR>"),
            (env.get("XDG_CACHE_HOME", ""), "<CACHE>"),
            (str(self.repo), "<REPO>"),
        ]
        if self._sandbox is not None:
            replacements.append((str(self._sandbox), "<SANDBOX>"))
        return [(needle, token) for needle, token in replacements if needle]

    def execute(self) -> dict:
        started_wall = time.monotonic()
        tracked = tracked_paths(self.repo, self.commit)
        warm_untracked, warm_cache = inventory_worktree_extras(
            self.warm_checkout, tracked, self.cache_globs
        )
        external_cache = inventory_external_cache(self.warm_cache_root)

        sandbox = self._new_sandbox()

        clean = self._fresh_checkout("clean")
        baseline_env = clean["env"]
        env_delta = environment_delta(self.warm_env, baseline_env)

        warm_env = dict(self.warm_env)
        if self.warm_cache_root is not None:
            warm_env["XDG_CACHE_HOME"] = str(self.warm_cache_root)
        warm_result = run_side(
            self.command,
            self.warm_checkout,
            warm_env,
            self.timeout,
            self._side_replacements(self.warm_checkout, warm_env),
            self.repeats,
        )
        clean_result = run_side(
            self.command,
            clean["checkout"],
            baseline_env,
            self.timeout,
            self._side_replacements(clean["checkout"], baseline_env),
            self.repeats,
        )

        inventory = {
            "untracked_paths": warm_untracked,
            "cache_paths": warm_cache,
            "external_cache_paths": external_cache,
            "external_cache_root_present": self.warm_cache_root is not None,
            "environment_delta": redact_environment_delta(env_delta),
            "environment_delta_key_count": len(env_delta),
            "class_present": {
                CLASS_UNTRACKED: bool(warm_untracked),
                CLASS_ENVIRONMENT: bool(env_delta),
                CLASS_WARM_CACHE: bool(warm_cache) or bool(external_cache),
            },
        }

        report = {
            "protocol_version": PROTOCOL_VERSION,
            "task_id": "PO03-WA-008",
            "hypothesis_id": "H-PO03-WA-008",
            "repo": "<REPO>",
            "commit": self.commit,
            "command": self.command,
            "repeats": self.repeats,
            "cache_globs": list(self.cache_globs.patterns),
            "warm": warm_result,
            "clean": clean_result,
            "divergent": warm_result["digest"] != clean_result["digest"],
            "hidden_state_inventory": inventory,
            "probes": [],
            "closure": None,
            "attributed_classes": [],
            "verdict": None,
        }

        if not (warm_result["deterministic"] and clean_result["deterministic"]):
            report["verdict"] = VERDICT_NONDETERMINISTIC
            report["nondeterministic_sides"] = [
                name for name in ("warm", "clean") if not report[name]["deterministic"]
            ]
            report["attribution_attempted"] = False
        elif not report["divergent"]:
            report["verdict"] = VERDICT_CLEAN
            report["attribution_attempted"] = False
        else:
            report["attribution_attempted"] = True
            self._attribute(report, warm_untracked, warm_cache, external_cache, env_delta)

        report["timing"] = {"wall_time_seconds": round(time.monotonic() - started_wall, 6)}
        report["classification_digest"] = classification_digest(report)
        report["sandbox_root"] = "<SANDBOX>"
        report["sandbox_root_actual_excluded_from_digest"] = str(sandbox)
        return report

    def _apply(self, target, classes, warm_untracked, warm_cache, external_cache, env_delta):
        env = dict(target["env"])
        applied = {}
        if CLASS_UNTRACKED in classes:
            applied[CLASS_UNTRACKED] = copy_paths(
                self.warm_checkout, target["checkout"], warm_untracked
            )
        if CLASS_WARM_CACHE in classes:
            copied = copy_paths(self.warm_checkout, target["checkout"], warm_cache)
            if self.warm_cache_root is not None:
                copied += copy_paths(self.warm_cache_root, target["cache_root"], external_cache)
            applied[CLASS_WARM_CACHE] = copied
        if CLASS_ENVIRONMENT in classes:
            env.update(env_delta)
            applied[CLASS_ENVIRONMENT] = len(env_delta)
        return env, applied

    def _probe(self, label, classes, warm_untracked, warm_cache, external_cache, env_delta):
        target = self._fresh_checkout(label)
        env, applied = self._apply(
            target, classes, warm_untracked, warm_cache, external_cache, env_delta
        )
        result = run_side(
            self.command,
            target["checkout"],
            env,
            self.timeout,
            self._side_replacements(target["checkout"], env),
            self.repeats,
        )
        return {
            "label": label,
            "applied_classes": sorted(classes),
            "applied_counts": applied,
            "digest": result["digest"],
            "exit_code": result["exit_code"],
            "deterministic": result["deterministic"],
        }

    def _attribute(self, report, warm_untracked, warm_cache, external_cache, env_delta):
        warm_digest = report["warm"]["digest"]
        present = [
            name
            for name in HIDDEN_STATE_CLASSES
            if report["hidden_state_inventory"]["class_present"][name]
        ]
        probes = []
        sufficient = []
        necessary = []
        for name in present:
            single = self._probe(
                "single-" + name.lower().replace("_", "-"),
                {name},
                warm_untracked,
                warm_cache,
                external_cache,
                env_delta,
            )
            single["reproduces_warm"] = single["digest"] == warm_digest
            single["role"] = "SUFFICIENT_ALONE" if single["reproduces_warm"] else "NOT_SUFFICIENT_ALONE"
            probes.append(single)
            if single["reproduces_warm"]:
                sufficient.append(name)

        if len(present) > 1:
            for name in present:
                complement = set(present) - {name}
                without = self._probe(
                    "without-" + name.lower().replace("_", "-"),
                    complement,
                    warm_untracked,
                    warm_cache,
                    external_cache,
                    env_delta,
                )
                without["reproduces_warm"] = without["digest"] == warm_digest
                without["role"] = (
                    "NECESSARY" if not without["reproduces_warm"] else "NOT_NECESSARY"
                )
                probes.append(without)
                if not without["reproduces_warm"]:
                    necessary.append(name)

        closure = None
        if present:
            closure = self._probe(
                "closure-all-classes",
                set(present),
                warm_untracked,
                warm_cache,
                external_cache,
                env_delta,
            )
            closure["reproduces_warm"] = closure["digest"] == warm_digest
            probes.append(closure)

        report["probes"] = probes
        report["closure"] = closure
        report["necessary_classes"] = sorted(set(necessary))

        if sufficient:
            report["attributed_classes"] = sorted(set(sufficient))
            report["verdict"] = VERDICT_ATTRIBUTED
            report["interaction_required"] = False
        elif closure is not None and closure["reproduces_warm"]:
            interaction = sorted(set(necessary)) or sorted(present)
            report["attributed_classes"] = interaction
            report["verdict"] = VERDICT_ATTRIBUTED
            report["interaction_required"] = True
        else:
            report["attributed_classes"] = []
            report["verdict"] = VERDICT_UNATTRIBUTED
            report["interaction_required"] = False
            report["unattributed_reason"] = (
                "no declared hidden-state class, alone or in combination, reproduced the warm "
                "outcome in an independently materialised checkout"
            )

    def cleanup(self) -> None:
        if self._owns_sandbox and self._sandbox is not None and self._sandbox.is_dir():
            shutil.rmtree(self._sandbox, ignore_errors=True)
            self._sandbox = None


def classification_digest(report: dict) -> str:
    """Digest over the classification-relevant subset of a report.

    Wall times, sandbox locations and byte-level file sizes of contaminating
    files are excluded so that two runs of the same fixture on the same commit
    produce the same digest. This is what the recurrence tests assert on.
    """
    inventory = report["hidden_state_inventory"]
    subset = {
        "protocol_version": report["protocol_version"],
        "commit": report["commit"],
        "command": report["command"],
        "repeats": report["repeats"],
        "cache_globs": report["cache_globs"],
        "warm": {
            "digest": report["warm"]["digest"],
            "exit_code": report["warm"]["exit_code"],
            "deterministic": report["warm"]["deterministic"],
        },
        "clean": {
            "digest": report["clean"]["digest"],
            "exit_code": report["clean"]["exit_code"],
            "deterministic": report["clean"]["deterministic"],
        },
        "divergent": report["divergent"],
        "verdict": report["verdict"],
        "attributed_classes": report["attributed_classes"],
        "class_present": inventory["class_present"],
        "untracked_paths": [record["path"] for record in inventory["untracked_paths"]],
        "cache_paths": [record["path"] for record in inventory["cache_paths"]],
        "external_cache_paths": [record["path"] for record in inventory["external_cache_paths"]],
        "environment_delta_keys": [record["key"] for record in inventory["environment_delta"]],
        "probes": [
            {
                "applied_classes": probe["applied_classes"],
                "reproduces_warm": probe.get("reproduces_warm"),
                "role": probe.get("role"),
                "exit_code": probe["exit_code"],
            }
            for probe in report["probes"]
        ],
    }
    return sha256_text(json.dumps(subset, sort_keys=True, separators=(",", ":")))


def differential_run(**kwargs) -> dict:
    runner = DifferentialRun(**kwargs)
    try:
        return runner.execute()
    finally:
        runner.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect hidden-state dependencies with a two-checkout differential run."
    )
    parser.add_argument("--repo", required=True, help="repository that owns the commit")
    parser.add_argument("--commit", required=True, help="immutable commit to materialise")
    parser.add_argument(
        "--command", required=True, help="command to run in both checkouts (shell-quoted)"
    )
    parser.add_argument(
        "--warm-checkout",
        default=None,
        help="candidate checkout to compare; defaults to the repository working tree",
    )
    parser.add_argument("--warm-cache-root", default=None, help="external cache root of the warm side")
    parser.add_argument("--cache-glob", action="append", default=None, help="additional cache glob")
    parser.add_argument("--repeats", type=int, default=2, help="runs per side for the determinism control")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", dest="json_path", default=None, help="write the report to this path")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cache_globs = list(DEFAULT_CACHE_GLOBS) + list(args.cache_glob or [])
    report = differential_run(
        repo=args.repo,
        commit=args.commit,
        command=shlex.split(args.command),
        warm_checkout=args.warm_checkout,
        warm_cache_root=args.warm_cache_root,
        cache_globs=cache_globs,
        repeats=args.repeats,
        timeout=args.timeout,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_path:
        Path(args.json_path).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return EXIT_BY_VERDICT[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
