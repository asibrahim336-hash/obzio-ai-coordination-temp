#!/usr/bin/env python3
"""Clean-clone runtime harness and contamination gate for PO-03.

Executes a declared suite from a pristine clone of an immutable commit and
asserts that the run needs no warm checkout, no uncommitted file, no provider or
session environment memory, no home-directory state and no system temporary
directory.  The gate is standard-library only so that it runs unchanged inside
the clean runtimes it certifies.

Every assertion is emitted as a machine-readable check with an identifier, a
disposition and evidence.  A caller may run the gate as a CLI (exit 0 on PASS,
1 on FAIL, 2 on harness error) or import ``run_harness`` for tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_SUPPORTED = "NOT_SUPPORTED"
INFO = "INFO"

SCHEMA_VERSION = "OBZIO-PO03-CLEAN-CLONE-HARNESS-v1"

# Only these names survive from the invoking environment.  Everything else -
# provider run identifiers, agent session state, injected secrets - is dropped.
ENV_PASSTHROUGH: tuple[str, ...] = ("PATH", "TZ", "SYSTEMROOT")

PROVIDER_ENV_RE = re.compile(
    r"(?i)^(cursor|claude|anthropic|openai|gemini|copilot|codex|composer|agent|cloud_agent"
    r"|exec_daemon|aurea|nvm|rustup|cargo|gh)[_A-Z0-9]*$"
)
SECRET_ENV_RE = re.compile(
    r"(?i)(token|secret|password|passwd|api[_-]?key|apikey|credential|cookie|session|private[_-]?key)"
)

# Residue that a warm checkout accumulates and a pristine clone never has.
WARM_RESIDUE_GLOBS: tuple[str, ...] = (
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/node_modules",
    "**/.venv",
    "**/*.egg-info",
    "**/.tox",
)

NON_PORTABLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("system_tmp", re.compile(r"(?<![\w./$-])/tmp(?:/|\Z|\b)")),
    ("var_tmp", re.compile(r"(?<![\w./$-])/var/tmp(?:/|\Z|\b)")),
    ("dev_shm", re.compile(r"(?<![\w./$-])/dev/shm(?:/|\Z|\b)")),
    ("workspace_root", re.compile(r"(?<![\w./$-])/workspace(?:/|\Z|\b)")),
    ("posix_home", re.compile(r"(?<![\w./$-])/(?:home|Users)/[A-Za-z0-9._-]+")),
    ("windows_drive", re.compile(r"(?<![\w])[A-Za-z]:\\\\?[A-Za-z0-9._\\-]")),
    ("tilde_home", re.compile(r"(?:\A|[\s\"'(=:,])~/")),
)

DEFAULT_SCAN_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".sh",
    ".bash",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".mk",
    ".json",
)

BYTECODE_SUFFIXES = (".pyc", ".pyo")

UNITTEST_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.M)
UNITTEST_VERDICT_RE = re.compile(r"^(OK|FAILED)\b", re.M)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

CLOSED_PROXY = "http://127.0.0.1:1"


class HarnessError(RuntimeError):
    """Raised when the harness itself cannot run, as distinct from a FAIL."""


@dataclass
class Check:
    id: str
    name: str
    disposition: str
    evidence: str
    detail: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "disposition": self.disposition,
            "blocking": self.blocking,
            "evidence": self.evidence,
            "detail": self.detail,
        }


@dataclass
class HarnessConfig:
    source_repo: str
    commit: str
    work_root: str
    suite_command: str
    scan_paths: Sequence[str] = ()
    scan_suffixes: Sequence[str] = DEFAULT_SCAN_SUFFIXES
    scan_exclude: Sequence[str] = ()
    require_pins: Sequence[str] = ()
    expect_sha256: Mapping[str, str] = field(default_factory=dict)
    warm_baseline_dir: str | None = None
    recurrence_clones: int = 2
    timeout_seconds: int = 900
    python_executable: str = sys.executable
    base_env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    label: str = "clean-clone"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(131072), b""):
            digest.update(block)
    return digest.hexdigest()


def build_redactor(base_env: Mapping[str, str]) -> "re.Pattern[str] | None":
    """Compile a pattern over secret-shaped environment values.

    Warm-baseline execution inherits the caller environment, so captured output
    is filtered before it reaches any receipt.  Names are never emitted with
    their values.
    """
    values: list[tuple[str, str]] = []
    for name, value in base_env.items():
        if not value or len(value) < 8:
            continue
        if SECRET_ENV_RE.search(name):
            values.append((name, value))
    if not values:
        return None
    values.sort(key=lambda item: len(item[1]), reverse=True)
    alternation = "|".join(re.escape(value) for _, value in values)
    return re.compile(alternation)


def redact(text: str, pattern: "re.Pattern[str] | None") -> str:
    if not text or pattern is None:
        return text
    return pattern.sub("[REDACTED]", text)


def parse_unittest_summary(text: str) -> dict[str, Any]:
    ran = UNITTEST_RAN_RE.search(text or "")
    verdict = UNITTEST_VERDICT_RE.search(text or "")
    return {
        "tests_ran": int(ran.group(1)) if ran else None,
        "verdict": verdict.group(1) if verdict else None,
    }


def build_scrubbed_env(
    base_env: Mapping[str, str],
    home: Path,
    tmpdir: Path,
    *,
    block_network: bool = True,
) -> dict[str, str]:
    env = {name: base_env[name] for name in ENV_PASSTHROUGH if name in base_env}
    env.setdefault("PATH", os.defpath)
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmpdir)
    env["TEMP"] = str(tmpdir)
    env["TMP"] = str(tmpdir)
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONNOUSERSITE"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    if block_network:
        env["http_proxy"] = CLOSED_PROXY
        env["https_proxy"] = CLOSED_PROXY
        env["HTTP_PROXY"] = CLOSED_PROXY
        env["HTTPS_PROXY"] = CLOSED_PROXY
        env["ALL_PROXY"] = CLOSED_PROXY
        env["no_proxy"] = ""
        env["NO_PROXY"] = ""
    return env


def env_leaks(env: Mapping[str, str]) -> dict[str, list[str]]:
    injected = {
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
        "PYTHONNOUSERSITE",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_TERMINAL_PROMPT",
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
    }
    allowed = set(ENV_PASSTHROUGH) | injected
    unexpected = sorted(name for name in env if name not in allowed)
    provider = sorted(name for name in env if PROVIDER_ENV_RE.match(name))
    secretish = sorted(name for name in env if SECRET_ENV_RE.search(name))
    return {"unexpected": unexpected, "provider": provider, "secret_shaped": secretish}


def local_git_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for git operations on a local repository.

    Ambient global and system configuration is neutralised so that inspection and
    fixture commits do not inherit signing programs, file-system monitors or URL
    rewrites from the warm runtime.  Clone and fetch deliberately keep the caller
    environment, because remote transports may legitimately need its credentials.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(repo: Path, *args: str, check: bool = True, env: Mapping[str, str] | None = None) -> str:
    run_env = local_git_env(env)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=run_env,
    )
    if check and result.returncode != 0:
        raise HarnessError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def clone_immutable(source: str, commit: str, dest: Path) -> None:
    """Clone ``source`` into ``dest`` and detach at ``commit``.

    ``--no-hardlinks`` prevents a local clone from sharing object files with a
    warm repository, so the clone cannot silently depend on the source checkout.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", source, str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HarnessError(f"clone failed: {result.stderr.strip()}")
    checkout = subprocess.run(
        ["git", "-C", str(dest), "checkout", "--quiet", "--detach", commit],
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        fetch = subprocess.run(
            ["git", "-C", str(dest), "fetch", "--quiet", "origin", commit],
            capture_output=True,
            text=True,
        )
        if fetch.returncode != 0:
            raise HarnessError(
                f"commit {commit} unreachable in clone: {checkout.stderr.strip()}"
            )
        _git(dest, "checkout", "--quiet", "--detach", commit)


def tracked_paths(repo: Path) -> set[str]:
    listing = _git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    return {line for line in listing.splitlines() if line}


def worktree_paths(repo: Path) -> set[str]:
    found: set[str] = set()
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(repo)
        if relative.parts and relative.parts[0] == ".git":
            continue
        found.add(relative.as_posix())
    return found


def find_warm_residue(repo: Path) -> list[str]:
    hits: list[str] = []
    for pattern in WARM_RESIDUE_GLOBS:
        for path in repo.glob(pattern):
            relative = path.relative_to(repo)
            if relative.parts and relative.parts[0] == ".git":
                continue
            hits.append(relative.as_posix())
    return sorted(set(hits))


def _excluded(relative: str, excludes: Sequence[str]) -> bool:
    return any(glob_match(relative, pattern) for pattern in excludes)


def scan_non_portable_literals(
    repo: Path,
    scan_paths: Sequence[str],
    suffixes: Sequence[str],
    excludes: Sequence[str],
) -> tuple[list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    scanned = 0
    suffix_set = {suffix.lower() for suffix in suffixes}
    for entry in scan_paths:
        target = repo / entry
        if not target.exists():
            findings.append({"path": entry, "pattern": "missing_scan_path", "line": 0, "text": ""})
            continue
        candidates = [target] if target.is_file() else sorted(target.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(repo).as_posix()
            if relative.startswith(".git/") or _excluded(relative, excludes):
                continue
            if candidate.suffix.lower() not in suffix_set:
                continue
            raw = candidate.read_bytes()
            if b"\0" in raw[:8192]:
                continue
            scanned += 1
            text = raw.decode("utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                for name, pattern in NON_PORTABLE_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            {
                                "path": relative,
                                "pattern": name,
                                "line": number,
                                "text": line.strip()[:200],
                            }
                        )
    return findings, scanned


def is_bytecode_residue(path: str) -> bool:
    return "__pycache__" in path or path.endswith(BYTECODE_SUFFIXES)


def porcelain_paths(lines: Sequence[str]) -> list[str]:
    """Extract paths from ``git status --porcelain`` lines."""
    paths: list[str] = []
    for line in lines:
        candidate = line[3:] if len(line) > 3 else line
        candidate = candidate.strip().strip('"')
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        if candidate:
            paths.append(candidate)
    return paths


def isolated_suite_command(command: str) -> bool:
    """True when the declared command runs Python with ``-I`` or ``-E``.

    Both flags make the interpreter ignore ``PYTHON*`` variables, so environment
    based hardening such as ``PYTHONDONTWRITEBYTECODE`` is inert for them.
    """
    for token in shlex.split(command):
        if not token.startswith("-") or token.startswith("--"):
            continue
        letters = token[1:]
        if letters and all(char.isalpha() for char in letters) and ("I" in letters or "E" in letters):
            return True
    return False


def glob_match(path: str, pattern: str) -> bool:
    """Match a POSIX path against a git-style glob.

    ``*`` stops at a separator, ``**`` crosses separators and a trailing ``/**``
    matches everything beneath the prefix.  ``fnmatch`` is unusable here because
    its ``*`` also crosses separators.
    """
    regex: list[str] = ["^"]
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**", index):
                index += 2
                if pattern.startswith("/", index):
                    index += 1
                    regex.append("(?:.*/)?")
                else:
                    regex.append(".*")
                continue
            regex.append("[^/]*")
            index += 1
            continue
        if char == "?":
            regex.append("[^/]")
            index += 1
            continue
        regex.append(re.escape(char))
        index += 1
    regex.append("$")
    compiled = re.compile("".join(regex))
    if compiled.match(path):
        return True
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return False


def run_suite(
    repo: Path,
    command: str,
    env: Mapping[str, str],
    timeout: int,
    redactor: "re.Pattern[str] | None",
) -> dict[str, Any]:
    argv = shlex.split(command)
    started = time.time()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(repo),
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code: int | None = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as expired:
        exit_code = None
        stdout = expired.stdout or ""
        stderr = expired.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        timed_out = True
    duration = round(time.time() - started, 3)
    combined = f"{stdout}\n{stderr}"
    return {
        "command": command,
        "cwd": str(repo),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "summary": parse_unittest_summary(combined),
        "stdout_tail": redact(stdout[-4000:], redactor),
        "stderr_tail": redact(stderr[-4000:], redactor),
    }


def probe_runtime(
    repo: Path,
    python_executable: str,
    env: Mapping[str, str],
    *,
    isolated: bool = True,
) -> dict[str, Any]:
    """Report what the scrubbed environment looks like from inside the suite."""
    script = (
        "import json,os,sys,tempfile;"
        "from pathlib import Path;"
        "print(json.dumps({"
        "'tempdir': tempfile.gettempdir(),"
        "'home': str(Path.home()),"
        "'isolated': bool(sys.flags.isolated),"
        "'ignore_environment': bool(sys.flags.ignore_environment),"
        "'dont_write_bytecode': bool(sys.flags.dont_write_bytecode),"
        "'no_user_site': bool(sys.flags.no_user_site),"
        "'env_names': sorted(os.environ),"
        "'cwd': os.getcwd(),"
        "}))"
    )
    argv = [python_executable, "-c", script]
    if isolated:
        argv.insert(1, "-I")
    completed = subprocess.run(
        argv,
        cwd=str(repo),
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise HarnessError(f"runtime probe failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _system_temp_entries() -> tuple[str, set[str]]:
    system_tmp = Path(os.environ.get("__PO03_SYSTEM_TMP__", "/tmp"))
    try:
        return str(system_tmp), set(os.listdir(system_tmp))
    except OSError:
        return str(system_tmp), set()


def _sandbox(work_root: Path, name: str) -> tuple[Path, Path]:
    home = work_root / name / "home"
    tmp = work_root / name / "tmp"
    home.mkdir(parents=True, exist_ok=False)
    tmp.mkdir(parents=True, exist_ok=False)
    return home, tmp


def run_harness(config: HarnessConfig) -> dict[str, Any]:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wall_start = time.time()
    work_root = Path(config.work_root).resolve()
    redactor = build_redactor(config.base_env)
    checks: list[Check] = []
    created_paths: list[str] = []
    runs: dict[str, Any] = {}

    if not FULL_SHA_RE.match(config.commit):
        raise HarnessError("commit must be a full 40-character lowercase SHA-1")

    clone_targets = [work_root / f"clone-{index + 1}" for index in range(max(1, config.recurrence_clones))]
    pre_existing = [str(target) for target in clone_targets if target.exists()]
    checks.append(
        Check(
            "CC-01",
            "no_warm_checkout_reuse",
            FAIL if pre_existing else PASS,
            (
                f"clone targets already present: {pre_existing}"
                if pre_existing
                else f"{len(clone_targets)} clone target(s) under {work_root} did not pre-exist"
            ),
            {"clone_targets": [str(target) for target in clone_targets]},
        )
    )
    if pre_existing:
        raise HarnessError(f"refusing to reuse existing clone targets: {pre_existing}")

    work_root.mkdir(parents=True, exist_ok=True)
    created_paths.append(str(work_root))

    system_tmp_path, system_tmp_before = _system_temp_entries()

    primary = clone_targets[0]
    clone_immutable(config.source_repo, config.commit, primary)
    created_paths.append(str(primary))

    head = _git(primary, "rev-parse", "HEAD").strip()
    tree = _git(primary, "rev-parse", "HEAD^{tree}").strip()
    checks.append(
        Check(
            "CC-02",
            "clone_at_immutable_commit",
            PASS if head == config.commit else FAIL,
            f"clone HEAD {head} vs requested {config.commit}; tree {tree}",
            {"head": head, "tree": tree, "requested": config.commit},
        )
    )

    alternates = primary / ".git" / "objects" / "info" / "alternates"
    checks.append(
        Check(
            "CC-03",
            "no_borrowed_object_store",
            FAIL if alternates.exists() else PASS,
            (
                f"clone borrows objects via {alternates}"
                if alternates.exists()
                else "no .git/objects/info/alternates; object store is self-contained"
            ),
            {"alternates_path": str(alternates)},
        )
    )

    tracked = tracked_paths(primary)
    on_disk = worktree_paths(primary)
    untracked = sorted(on_disk - tracked)
    missing = sorted(tracked - on_disk)
    porcelain = [line for line in _git(primary, "status", "--porcelain").splitlines() if line]
    tree_ok = not untracked and not missing and not porcelain
    checks.append(
        Check(
            "CC-04",
            "worktree_equals_committed_tree",
            PASS if tree_ok else FAIL,
            (
                f"{len(tracked)} tracked paths reproduce the working tree exactly"
                if tree_ok
                else f"untracked={untracked[:20]} missing={missing[:20]} porcelain={porcelain[:20]}"
            ),
            {
                "tracked_count": len(tracked),
                "untracked": untracked[:50],
                "missing": missing[:50],
                "porcelain": porcelain[:50],
            },
        )
    )

    residue = find_warm_residue(primary)
    checks.append(
        Check(
            "CC-05",
            "no_warm_build_residue",
            FAIL if residue else PASS,
            (
                f"pristine clone already carries build residue: {residue[:20]}"
                if residue
                else "no bytecode, cache, vendored-dependency or virtualenv residue in the clone"
            ),
            {"residue": residue[:50], "patterns": list(WARM_RESIDUE_GLOBS)},
        )
    )

    pin_results: list[dict[str, Any]] = []
    for pin in config.require_pins:
        spec, _, mode = pin.partition(":")
        object_type = subprocess.run(
            ["git", "-C", str(primary), "cat-file", "-t", spec],
            capture_output=True,
            text=True,
            env=local_git_env(),
        )
        resolved = object_type.returncode == 0
        record: dict[str, Any] = {
            "pin": spec,
            "mode": mode or "resolve",
            "resolves": resolved,
            "object_type": object_type.stdout.strip() or None,
            "ancestor_of_head": None,
        }
        if resolved and record["object_type"] == "commit" and (mode or "resolve") == "ancestor":
            record["ancestor_of_head"] = (
                subprocess.run(
                    ["git", "-C", str(primary), "merge-base", "--is-ancestor", spec, "HEAD"],
                    capture_output=True,
                    env=local_git_env(),
                ).returncode
                == 0
            )
        if not resolved:
            abbreviated = subprocess.run(
                ["git", "-C", str(primary), "rev-parse", "--verify", f"{spec[:7]}^{{commit}}"],
                capture_output=True,
                text=True,
                env=local_git_env(),
            )
            record["prefix_resolves_to"] = (
                abbreviated.stdout.strip() if abbreviated.returncode == 0 else None
            )
        pin_results.append(record)
    unresolved = [item for item in pin_results if not item["resolves"]]
    non_ancestor = [item for item in pin_results if item["ancestor_of_head"] is False]
    if not config.require_pins:
        pin_check = Check("CC-06", "provenance_pins_resolve", NOT_SUPPORTED, "no pins declared", {}, blocking=False)
    else:
        pin_check = Check(
            "CC-06",
            "provenance_pins_resolve",
            FAIL if unresolved or non_ancestor else PASS,
            (
                f"unresolved={[item['pin'] for item in unresolved]} "
                f"non_ancestor={[item['pin'] for item in non_ancestor]}"
                if unresolved or non_ancestor
                else f"all {len(pin_results)} declared provenance pins resolve in the pristine clone"
            ),
            {"pins": pin_results},
        )
    checks.append(pin_check)

    hash_results: list[dict[str, Any]] = []
    for relative, expected in dict(config.expect_sha256).items():
        target = primary / relative
        actual = sha256_file(target) if target.is_file() else None
        hash_results.append(
            {
                "path": relative,
                "expected_sha256": expected,
                "observed_sha256": actual,
                "match": actual == expected,
            }
        )
    hash_mismatch = [item for item in hash_results if not item["match"]]
    if not hash_results:
        checks.append(
            Check("CC-07", "declared_source_hashes_match", NOT_SUPPORTED, "no hash expectations declared", {}, blocking=False)
        )
    else:
        checks.append(
            Check(
                "CC-07",
                "declared_source_hashes_match",
                FAIL if hash_mismatch else PASS,
                (
                    f"hash mismatch for {[item['path'] for item in hash_mismatch]}"
                    if hash_mismatch
                    else f"all {len(hash_results)} declared source hashes match the clean clone"
                ),
                {"expectations": hash_results},
            )
        )

    findings, scanned_files = scan_non_portable_literals(
        primary, config.scan_paths, config.scan_suffixes, config.scan_exclude
    )
    checks.append(
        Check(
            "CC-08",
            "no_non_portable_path_literals",
            FAIL if findings else PASS,
            (
                f"{len(findings)} non-portable path literal(s) in the declared suite closure: "
                f"{[(item['path'], item['pattern'], item['line']) for item in findings[:10]]}"
                if findings
                else f"{scanned_files} scanned file(s) in the declared closure carry no absolute, "
                "home-relative or system-temporary path literal"
            ),
            {
                "scanned_files": scanned_files,
                "scan_paths": list(config.scan_paths),
                "findings": findings[:50],
            },
        )
    )

    home, tmpdir = _sandbox(work_root, "sandbox-1")
    created_paths.extend([str(home), str(tmpdir)])
    scrubbed = build_scrubbed_env(config.base_env, home, tmpdir)
    leaks = env_leaks(scrubbed)
    leaked = leaks["unexpected"] + leaks["provider"] + leaks["secret_shaped"]
    checks.append(
        Check(
            "CC-09",
            "scrubbed_environment_admitted",
            FAIL if leaked else PASS,
            (
                f"environment leak: {leaked}"
                if leaked
                else f"{len(scrubbed)} admitted variables; "
                f"{len(config.base_env) - len(set(config.base_env) & set(scrubbed))} caller variables dropped, "
                f"including {len([name for name in config.base_env if PROVIDER_ENV_RE.match(name)])} "
                f"provider/runtime and {len([name for name in config.base_env if SECRET_ENV_RE.search(name)])} "
                "secret-shaped names"
            ),
            {
                "admitted_names": sorted(scrubbed),
                "dropped_count": len(set(config.base_env) - set(scrubbed)),
                "dropped_provider_names": sorted(
                    name for name in config.base_env if PROVIDER_ENV_RE.match(name)
                ),
                "dropped_secret_shaped_count": len(
                    [name for name in config.base_env if SECRET_ENV_RE.search(name)]
                ),
                "leaks": leaks,
            },
        )
    )

    suite_is_isolated = isolated_suite_command(config.suite_command)
    probe = probe_runtime(primary, config.python_executable, scrubbed, isolated=suite_is_isolated)
    probe_plain = probe_runtime(primary, config.python_executable, scrubbed, isolated=False)
    temp_ok = Path(probe["tempdir"]).resolve() == tmpdir.resolve()
    home_ok = Path(probe["home"]).resolve() == home.resolve()
    checks.append(
        Check(
            "CC-10",
            "temp_and_home_redirected_into_sandbox",
            PASS if temp_ok and home_ok else FAIL,
            (
                f"suite runtime sees tempdir={probe['tempdir']} home={probe['home']} "
                f"isolated={probe['isolated']}; tempfile silently falls back to the system "
                "temporary directory when TMPDIR is unset or absent, so this is measured "
                "from inside the runtime rather than assumed from the environment"
            ),
            {"probe": probe, "expected_tempdir": str(tmpdir), "expected_home": str(home)},
        )
    )

    hardening_inert = probe["ignore_environment"] and not probe["dont_write_bytecode"]
    checks.append(
        Check(
            "CC-20",
            "python_environment_hardening_effective",
            INFO if hardening_inert else PASS,
            (
                "the declared suite command runs Python in isolated mode, which implies -E; "
                "PYTHONDONTWRITEBYTECODE and PYTHONHASHSEED are therefore ignored "
                f"(observed dont_write_bytecode={probe['dont_write_bytecode']} under the suite's "
                f"own flags versus {probe_plain['dont_write_bytecode']} without them). "
                "HOME and TMPDIR are OS-level and remain honoured, so environment scrubbing "
                "still holds; only PYTHON* hardening is inert"
                if hardening_inert
                else "the suite runtime honours the requested PYTHON* hardening "
                f"(dont_write_bytecode={probe['dont_write_bytecode']})"
            ),
            {
                "suite_command_isolated": suite_is_isolated,
                "probe_suite_flags": {
                    "isolated": probe["isolated"],
                    "ignore_environment": probe["ignore_environment"],
                    "dont_write_bytecode": probe["dont_write_bytecode"],
                },
                "probe_without_isolation": {
                    "isolated": probe_plain["isolated"],
                    "ignore_environment": probe_plain["ignore_environment"],
                    "dont_write_bytecode": probe_plain["dont_write_bytecode"],
                },
            },
            blocking=False,
        )
    )

    clean_run = run_suite(primary, config.suite_command, scrubbed, config.timeout_seconds, redactor)
    runs["clean_primary"] = clean_run
    checks.append(
        Check(
            "CC-11",
            "suite_passes_in_pristine_clone",
            PASS if clean_run["exit_code"] == 0 else FAIL,
            (
                f"exit={clean_run['exit_code']} timed_out={clean_run['timed_out']} "
                f"summary={clean_run['summary']} duration={clean_run['duration_seconds']}s"
            ),
            {"run": "clean_primary"},
        )
    )

    post_porcelain = [line for line in _git(primary, "status", "--porcelain").splitlines() if line]
    post_paths = porcelain_paths(post_porcelain)
    semantic_mutations = [path for path in post_paths if not is_bytecode_residue(path)]
    bytecode_written = sorted(
        set([path for path in post_paths if is_bytecode_residue(path)])
        | {path for path in find_warm_residue(primary) if is_bytecode_residue(path)}
    )
    checks.append(
        Check(
            "CC-12",
            "no_semantic_checkout_mutation_by_suite",
            FAIL if semantic_mutations else PASS,
            (
                f"suite wrote non-bytecode changes into its own checkout: {semantic_mutations[:20]}"
                if semantic_mutations
                else "no semantic change to the checkout after execution; only interpreter "
                "bytecode caches may differ and those are reported separately by CC-19"
            ),
            {"porcelain": post_porcelain[:50], "semantic_mutations": semantic_mutations[:50]},
        )
    )
    checks.append(
        Check(
            "CC-19",
            "bytecode_residue_written_into_checkout",
            INFO if bytecode_written else PASS,
            (
                f"the suite wrote {len(bytecode_written)} bytecode cache path(s) into its own "
                f"checkout, for example {bytecode_written[:5]}. This is the mechanism by which a "
                "warm checkout accumulates the residue CC-05 rejects; suppressing it requires the "
                "interpreter flag -B in the suite command, because PYTHONDONTWRITEBYTECODE is "
                "ignored under isolated mode (see CC-20)"
                if bytecode_written
                else "the suite wrote no bytecode cache into its checkout"
            ),
            {"bytecode_paths": bytecode_written[:50]},
            blocking=False,
        )
    )

    _, system_tmp_after = _system_temp_entries()
    work_root_name = work_root.name
    new_tmp_entries = sorted(
        entry
        for entry in (system_tmp_after - system_tmp_before)
        if work_root_name not in entry
    )
    checks.append(
        Check(
            "CC-13",
            "no_system_temp_residue",
            PASS if not new_tmp_entries else INCONCLUSIVE,
            (
                f"no new entries in {system_tmp_path} across the run"
                if not new_tmp_entries
                else f"new entries in shared {system_tmp_path}: {new_tmp_entries[:20]}; "
                "the system temporary directory has concurrent writers so per-process "
                "attribution is NOT_SUPPORTED by this mechanism"
            ),
            {
                "system_tmp": system_tmp_path,
                "new_entries": new_tmp_entries[:50],
                "sandbox_tmp_entries_after": sorted(
                    path.name for path in tmpdir.iterdir()
                )[:50],
            },
            blocking=False,
        )
    )

    if clean_run["exit_code"] == 0:
        network_disposition, network_evidence = (
            PASS,
            f"suite exited 0 with every proxy variable pinned to {CLOSED_PROXY} and no_proxy empty",
        )
    else:
        network_disposition, network_evidence = (
            INCONCLUSIVE,
            "suite did not pass, so proxy-blocked execution proves nothing about egress need",
        )
    checks.append(
        Check(
            "CC-14",
            "no_proxy_aware_network_egress_required",
            network_disposition,
            network_evidence
            + "; raw-socket and DNS egress are NOT_SUPPORTED by this mechanism",
            {"closed_proxy": CLOSED_PROXY},
            blocking=False,
        )
    )

    warm_run: dict[str, Any] | None = None
    if config.warm_baseline_dir:
        warm_dir = Path(config.warm_baseline_dir).resolve()
        if not warm_dir.is_dir():
            raise HarnessError(f"warm baseline directory not found: {warm_dir}")
        # Read the warm tree's dirtiness before executing anything in it: the
        # inherited environment writes bytecode caches, and that residue would
        # otherwise be misread as a pre-existing uncommitted dependency.
        warm_porcelain: list[str] = []
        if (warm_dir / ".git").exists():
            warm_porcelain = [
                line for line in _git(warm_dir, "status", "--porcelain", check=False).splitlines() if line
            ]
        warm_env = dict(config.base_env)
        warm_run = run_suite(warm_dir, config.suite_command, warm_env, config.timeout_seconds, redactor)
        runs["warm_baseline"] = warm_run
        warm_ok = warm_run["exit_code"] == 0
        clean_ok = clean_run["exit_code"] == 0
        if warm_ok and not clean_ok:
            disposition = FAIL
            evidence = (
                "warm-only green: the suite passes in the warm checkout with the inherited "
                "environment and fails in the pristine clone, so warm success is contaminated"
            )
        elif warm_ok == clean_ok:
            disposition = PASS
            evidence = (
                f"warm and clean outcomes agree (warm exit={warm_run['exit_code']}, "
                f"clean exit={clean_run['exit_code']})"
            )
        else:
            disposition = INCONCLUSIVE
            evidence = (
                f"clean clone passes while the warm checkout fails (warm exit={warm_run['exit_code']}); "
                "the warm baseline is broken independently of portability"
            )
        checks.append(
            Check(
                "CC-15",
                "warm_versus_clean_divergence",
                disposition,
                evidence,
                {"warm_dir": str(warm_dir), "warm_summary": warm_run["summary"]},
            )
        )
        checks.append(
            Check(
                "CC-16",
                "warm_source_uncommitted_files",
                PASS if not warm_porcelain else INCONCLUSIVE,
                (
                    "warm baseline tree had no uncommitted files before execution"
                    if not warm_porcelain
                    else f"warm baseline carried {len(warm_porcelain)} uncommitted path(s) before execution: "
                    f"{warm_porcelain[:20]}; any green result there is not clean-clone evidence"
                ),
                {"porcelain": warm_porcelain[:50]},
                blocking=False,
            )
        )
    else:
        checks.append(
            Check("CC-15", "warm_versus_clean_divergence", NOT_SUPPORTED, "no warm baseline declared", {}, blocking=False)
        )
        checks.append(
            Check("CC-16", "warm_source_uncommitted_files", NOT_SUPPORTED, "no warm baseline declared", {}, blocking=False)
        )

    recurrence: list[dict[str, Any]] = [
        {
            "clone": primary.name,
            "head": head,
            "tree": tree,
            "exit_code": clean_run["exit_code"],
            "summary": clean_run["summary"],
        }
    ]
    for index, target in enumerate(clone_targets[1:], start=2):
        clone_immutable(config.source_repo, config.commit, target)
        created_paths.append(str(target))
        repeat_home, repeat_tmp = _sandbox(work_root, f"sandbox-{index}")
        created_paths.extend([str(repeat_home), str(repeat_tmp)])
        repeat_env = build_scrubbed_env(config.base_env, repeat_home, repeat_tmp)
        repeat_run = run_suite(target, config.suite_command, repeat_env, config.timeout_seconds, redactor)
        runs[f"clean_recurrence_{index}"] = repeat_run
        recurrence.append(
            {
                "clone": target.name,
                "head": _git(target, "rev-parse", "HEAD").strip(),
                "tree": _git(target, "rev-parse", "HEAD^{tree}").strip(),
                "exit_code": repeat_run["exit_code"],
                "summary": repeat_run["summary"],
            }
        )
    if len(recurrence) < 2:
        checks.append(
            Check(
                "CC-17",
                "recurrence_across_independent_clean_clones",
                NOT_SUPPORTED,
                "recurrence_clones < 2",
                {"observations": recurrence},
                blocking=False,
            )
        )
    else:
        signatures = {
            (item["head"], item["tree"], item["exit_code"], json.dumps(item["summary"], sort_keys=True))
            for item in recurrence
        }
        checks.append(
            Check(
                "CC-17",
                "recurrence_across_independent_clean_clones",
                PASS if len(signatures) == 1 else FAIL,
                (
                    f"{len(recurrence)} independent clean clones produced one identical "
                    f"tree/exit/summary signature"
                    if len(signatures) == 1
                    else f"clean clones diverged: {recurrence}"
                ),
                {"observations": recurrence},
            )
        )

    escaped = sorted(
        path for path in created_paths if not Path(path).resolve().is_relative_to(work_root)
    )
    checks.append(
        Check(
            "CC-18",
            "harness_writes_confined_to_work_root",
            FAIL if escaped else PASS,
            (
                f"harness created paths outside the declared work root: {escaped}"
                if escaped
                else f"all {len(created_paths)} harness-created paths are under {work_root}"
            ),
            {"work_root": str(work_root), "created_paths": created_paths},
        )
    )

    blocking_failures = [check.id for check in checks if check.blocking and check.disposition == FAIL]
    non_blocking_failures = [
        check.id for check in checks if not check.blocking and check.disposition == FAIL
    ]
    overall = FAIL if blocking_failures else PASS
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return {
        "schema_version": SCHEMA_VERSION,
        "label": config.label,
        "overall": overall,
        "hypothesis_outcome": "SUPPORTED" if overall == PASS else "REFUTED",
        "blocking_failures": blocking_failures,
        "non_blocking_failures": non_blocking_failures,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_time_seconds": round(time.time() - wall_start, 3),
        "config": {
            "source_repo": config.source_repo,
            "commit": config.commit,
            "work_root": str(work_root),
            "suite_command": config.suite_command,
            "scan_paths": list(config.scan_paths),
            "scan_suffixes": list(config.scan_suffixes),
            "scan_exclude": list(config.scan_exclude),
            "require_pins": list(config.require_pins),
            "expect_sha256": dict(config.expect_sha256),
            "warm_baseline_dir": config.warm_baseline_dir,
            "recurrence_clones": config.recurrence_clones,
            "python_executable": config.python_executable,
            "base_env_variable_count": len(config.base_env),
        },
        "checks": [check.as_dict() for check in checks],
        "runs": runs,
        "counts": {
            "checks": len(checks),
            "pass": len([c for c in checks if c.disposition == PASS]),
            "fail": len([c for c in checks if c.disposition == FAIL]),
            "inconclusive": len([c for c in checks if c.disposition == INCONCLUSIVE]),
            "not_supported": len([c for c in checks if c.disposition == NOT_SUPPORTED]),
            "info": len([c for c in checks if c.disposition == INFO]),
        },
    }


def _parse_key_value(values: Iterable[str], flag: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise SystemExit(f"{flag} expects PATH=SHA256, got {item!r}")
        parsed[key] = value
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clean_clone_harness",
        description="Run a declared suite from a pristine clone and assert no warm-runtime contamination.",
    )
    parser.add_argument("--source-repo", required=True, help="path or URL of the repository to clone")
    parser.add_argument("--commit", required=True, help="full 40-character commit SHA to certify")
    parser.add_argument("--work-root", required=True, help="directory the harness may create and own")
    parser.add_argument("--suite-command", required=True, help="command executed inside the pristine clone")
    parser.add_argument("--scan-path", action="append", default=[], dest="scan_paths")
    parser.add_argument("--scan-suffix", action="append", default=[], dest="scan_suffixes")
    parser.add_argument("--scan-exclude", action="append", default=[], dest="scan_exclude")
    parser.add_argument(
        "--require-pin",
        action="append",
        default=[],
        dest="require_pins",
        help="SHA[:ancestor] that must resolve inside the pristine clone",
    )
    parser.add_argument("--expect-sha256", action="append", default=[], dest="expect_sha256")
    parser.add_argument("--warm-baseline-dir", default=None)
    parser.add_argument("--recurrence-clones", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--label", default="clean-clone")
    parser.add_argument("--receipt", default=None, help="write the JSON receipt to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = HarnessConfig(
        source_repo=args.source_repo,
        commit=args.commit,
        work_root=args.work_root,
        suite_command=args.suite_command,
        scan_paths=tuple(args.scan_paths),
        scan_suffixes=tuple(args.scan_suffixes) or DEFAULT_SCAN_SUFFIXES,
        scan_exclude=tuple(args.scan_exclude),
        require_pins=tuple(args.require_pins),
        expect_sha256=_parse_key_value(args.expect_sha256, "--expect-sha256"),
        warm_baseline_dir=args.warm_baseline_dir,
        recurrence_clones=args.recurrence_clones,
        timeout_seconds=args.timeout_seconds,
        label=args.label,
    )
    try:
        report = run_harness(config)
    except HarnessError as error:
        print(f"HARNESS-ERROR: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        receipt_path = Path(args.receipt)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(payload, encoding="utf-8")
    for check in report["checks"]:
        print(f"{check['disposition']:<14} {check['id']} {check['name']}: {check['evidence']}")
    print(f"OVERALL {report['overall']} ({json.dumps(report['counts'], sort_keys=True)})")
    return 0 if report["overall"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
