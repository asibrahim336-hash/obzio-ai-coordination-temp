#!/usr/bin/env python3
"""CI-equivalent differential harness for PO03-WA-024.

Hypothesis under test: a clean Actions runner exposes hidden local-state
assumptions that a warm checkout misses.

The harness runs the same declared workload in three environments and diffs the
outcomes:

``warm``
    the caller's existing working tree with the caller's environment, i.e. the
    long-lived checkout a coordinator or agent reuses between runs.

``clean_full``
    a fresh clone carrying complete history and only committed content, run with
    a scrubbed environment, a private ``HOME`` and a private ``TMPDIR``.  This is
    the ``actions/checkout`` + ``fetch-depth: 0`` shape.

``clean_shallow``
    a fresh depth-1 clone, same scrubbed environment.  This is the *default*
    ``actions/checkout`` shape, where ``fetch-depth`` is ``1``.

Only the standard library is used, so the harness runs on a bare runner that has
nothing beyond git and CPython.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

MODES = ("warm", "clean_full", "clean_shallow")

# Environment variables a clean runner does provide.  Everything else is dropped
# so that inherited local state cannot leak into the clean runs.
ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ")

OUTPUT_TAIL_BYTES = 4096

CLASS_AGREE = "AGREE"
CLASS_WARM_ONLY_PASS = "WARM_ONLY_PASS"
CLASS_DEPTH_SENSITIVE = "DEPTH_SENSITIVE"
CLASS_CLEAN_ONLY_PASS = "CLEAN_ONLY_PASS"
CLASS_DIVERGENT = "DIVERGENT"


class ProbeError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and proc.returncode != 0:
        raise ProbeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc


def _tail(text: str) -> str:
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= OUTPUT_TAIL_BYTES:
        return text
    return "...<truncated>...\n" + encoded[-OUTPUT_TAIL_BYTES:].decode("utf-8", "replace")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def scrubbed_env(tree: Path, home: Path, tmp: Path) -> dict[str, str]:
    """Return the environment a GitHub-hosted runner step would see."""
    env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "TEMP": str(tmp),
            "TMP": str(tmp),
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "GITHUB_WORKSPACE": str(tree),
            "RUNNER_TEMP": str(tmp),
            "PYTHONDONTWRITEBYTECODE": "",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    # An empty PYTHONDONTWRITEBYTECODE is still "set" for CPython, which would
    # mask the bytecode-cache finding.  Remove it explicitly instead.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return env


def materialise_clean(source: Path, commit: str, ref: str, dest: Path, depth: int | None) -> dict[str, Any]:
    """Clone committed content only, from the git object store, into ``dest``."""
    url = source.resolve().as_uri()
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "--quiet"], dest)
    _git(["remote", "add", "origin", url], dest)
    fetch_strategy = "commit"
    if depth is None:
        proc = _git(["fetch", "--quiet", "origin", commit], dest, check=False)
        if proc.returncode != 0:
            fetch_strategy = "ref"
            _git(["fetch", "--quiet", "origin", ref], dest)
    else:
        proc = _git(["fetch", "--quiet", f"--depth={depth}", "origin", commit], dest, check=False)
        if proc.returncode != 0:
            fetch_strategy = "ref"
            _git(["fetch", "--quiet", f"--depth={depth}", "origin", ref], dest)
    _git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], dest)
    head = _git(["rev-parse", "HEAD"], dest).stdout.strip()
    if head != commit:
        raise ProbeError(f"clean tree HEAD {head} does not match requested commit {commit}")
    return {
        "fetch_strategy": fetch_strategy,
        "depth_requested": depth,
        "commits_present": int(_git(["rev-list", "--count", "HEAD"], dest).stdout.strip()),
        "shallow": (dest / ".git" / "shallow").exists(),
        "head": head,
    }


def worktree_dirt(tree: Path) -> list[str]:
    proc = _git(["status", "--porcelain", "--untracked-files=all"], tree, check=False)
    if proc.returncode != 0:
        return []
    return sorted(line.strip() for line in proc.stdout.splitlines() if line.strip())


def untracked_files(tree: Path) -> set[str]:
    proc = _git(["ls-files", "--others", "--exclude-standard"], tree, check=False)
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def reset_untracked_delta(tree: Path, baseline: set[str]) -> list[str]:
    """Remove only untracked files that appeared after the baseline snapshot.

    Files the caller already had are never touched, so pointing the harness at a
    working tree with uncommitted work cannot destroy it.
    """
    removed: list[str] = []
    for relative in sorted(untracked_files(tree) - baseline):
        target = tree / relative
        try:
            if target.is_file() or target.is_symlink():
                target.unlink()
                removed.append(relative)
        except OSError:
            continue
    for directory in sorted((path for path in tree.rglob("*") if path.is_dir()), reverse=True):
        if ".git" in directory.parts:
            continue
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
        except OSError:
            continue
    return removed


def run_probe(
    probe: dict[str, Any],
    tree: Path,
    env: dict[str, str] | None,
    baseline_untracked: set[str] | None = None,
) -> dict[str, Any]:
    cwd = tree / probe.get("cwd", ".")
    if not cwd.is_dir():
        return {
            "outcome": "ERROR",
            "exit_code": None,
            "error": f"cwd does not exist: {probe.get('cwd', '.')}",
            "stdout_tail": "",
            "stderr_tail": "",
            "output_sha256": _digest(""),
            "duration_ms": 0,
            "reset_removed": [],
            "worktree_dirt_before": [],
            "worktree_dirt_after": [],
            "worktree_mutated": False,
        }
    argv = list(probe["argv"])
    if argv and argv[0] == "PYTHON":
        argv[0] = sys.executable
    removed: list[str] = []
    if probe.get("reset_untracked_delta"):
        removed = reset_untracked_delta(tree, baseline_untracked or set())
    before = worktree_dirt(tree)
    effective_env = dict(os.environ) if env is None else dict(env)
    overlay = probe.get("env_overlay") or {}
    for name, value in overlay.items():
        if value is None:
            effective_env.pop(name, None)
        else:
            effective_env[name] = str(value)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=effective_env,
            timeout=probe.get("timeout_seconds", 300),
        )
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
        error = None
    except FileNotFoundError as exc:
        exit_code, stdout, stderr, error = None, "", str(exc), "EXECUTABLE_NOT_FOUND"
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr, error = None, "", "", "TIMEOUT"
    duration_ms = int((time.monotonic() - started) * 1000)
    after = worktree_dirt(tree)
    if error is not None:
        outcome = "ERROR"
    else:
        outcome = "PASS" if exit_code == 0 else "FAIL"
    return {
        "outcome": outcome,
        "exit_code": exit_code,
        "error": error,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "output_sha256": _digest(stdout + stderr),
        "duration_ms": duration_ms,
        "reset_removed": removed,
        "worktree_dirt_before": before,
        "worktree_dirt_after": after,
        "worktree_mutated": after != before,
    }


def classify(results: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """Classify one probe's cross-environment outcomes and name the state class."""
    warm = results.get("warm", {}).get("outcome")
    full = results.get("clean_full", {}).get("outcome")
    shallow = results.get("clean_shallow", {}).get("outcome")
    findings: list[str] = []

    observed = {mode: results[mode]["outcome"] for mode in results}
    if len(set(observed.values())) == 1:
        classification = CLASS_AGREE
    elif warm == "PASS" and "PASS" not in {full, shallow} - {None}:
        classification = CLASS_WARM_ONLY_PASS
    elif warm == "PASS" and full == "PASS" and shallow in {"FAIL", "ERROR"}:
        classification = CLASS_DEPTH_SENSITIVE
    elif warm in {"FAIL", "ERROR"} and "PASS" in {full, shallow}:
        classification = CLASS_CLEAN_ONLY_PASS
    else:
        classification = CLASS_DIVERGENT

    if classification == CLASS_WARM_ONLY_PASS:
        findings.append("HIDDEN_LOCAL_STATE_DEPENDENCE")
    if classification == CLASS_DEPTH_SENSITIVE:
        findings.append("SHALLOW_HISTORY_DEPENDENCE")
    for mode, result in results.items():
        if result.get("worktree_mutated"):
            findings.append(f"WORKTREE_MUTATED_BY_WORKLOAD:{mode}")
    return classification, sorted(set(findings))


def redact(value: str, replacements: dict[str, str]) -> str:
    for needle, token in replacements.items():
        if needle:
            value = value.replace(needle, token)
    return value


def redact_tree(node: Any, replacements: dict[str, str]) -> Any:
    if isinstance(node, str):
        return redact(node, replacements)
    if isinstance(node, list):
        return [redact_tree(item, replacements) for item in node]
    if isinstance(node, dict):
        return {key: redact_tree(item, replacements) for key, item in node.items()}
    return node


def probe_repository(
    repo: Path,
    probes: list[dict[str, Any]],
    commit: str | None = None,
    ref: str = "HEAD",
    modes: tuple[str, ...] = MODES,
    keep_sandbox: bool = False,
) -> dict[str, Any]:
    repo = repo.resolve()
    commit = commit or _git(["rev-parse", "HEAD"], repo).stdout.strip()
    sandbox = Path(tempfile.mkdtemp(prefix="wa024-probe-"))
    trees: dict[str, dict[str, Any]] = {}
    try:
        environments: dict[str, tuple[Path, dict[str, str] | None]] = {}
        baselines: dict[str, set[str]] = {}
        if "warm" in modes:
            environments["warm"] = (repo, None)
            baselines["warm"] = untracked_files(repo)
            trees["warm"] = {
                "kind": "existing_working_tree",
                "commits_present": int(_git(["rev-list", "--count", "HEAD"], repo).stdout.strip()),
                "shallow": (repo / ".git" / "shallow").exists(),
                "head": _git(["rev-parse", "HEAD"], repo).stdout.strip(),
                "preexisting_dirt": worktree_dirt(repo),
                "environment": "inherited",
            }
        for mode, depth in (("clean_full", None), ("clean_shallow", 1)):
            if mode not in modes:
                continue
            tree = sandbox / mode / "repo"
            home = sandbox / mode / "home"
            tmp = sandbox / mode / "tmp"
            home.mkdir(parents=True, exist_ok=True)
            tmp.mkdir(parents=True, exist_ok=True)
            info = materialise_clean(repo, commit, ref, tree, depth)
            info["kind"] = "fresh_clone"
            info["environment"] = "scrubbed"
            info["preexisting_dirt"] = worktree_dirt(tree)
            trees[mode] = info
            environments[mode] = (tree, scrubbed_env(tree, home, tmp))
            baselines[mode] = untracked_files(tree)

        probe_rows: list[dict[str, Any]] = []
        for probe in probes:
            results: dict[str, dict[str, Any]] = {}
            for mode, (tree, env) in environments.items():
                results[mode] = run_probe(probe, tree, env, baselines.get(mode))
            classification, findings = classify(results)
            expected_outcomes = probe.get("expected_outcomes")
            outcomes_met: bool | None = None
            if expected_outcomes:
                outcomes_met = all(
                    results[mode]["outcome"] == expected
                    for mode, expected in expected_outcomes.items()
                    if mode in results
                )
            expect_mutation = probe.get("expect_worktree_mutation")
            mutation_met: bool | None = None
            if expect_mutation is not None:
                mutation_met = all(
                    result["worktree_mutated"] is bool(expect_mutation) for result in results.values()
                )
            probe_rows.append(
                {
                    "probe_id": probe["probe_id"],
                    "workload": probe.get("workload", probe["probe_id"]),
                    "hypothesis_ids": probe.get("hypothesis_ids", []),
                    "argv": list(probe["argv"]),
                    "cwd": probe.get("cwd", "."),
                    "env_overlay": probe.get("env_overlay") or {},
                    "reset_untracked_delta": bool(probe.get("reset_untracked_delta")),
                    "role": probe.get("role", "differential"),
                    "expectation_binding": probe.get("expectation_binding", "binding"),
                    "expected_classification": probe.get("expected_classification"),
                    "expected_outcomes": expected_outcomes,
                    "expect_worktree_mutation": expect_mutation,
                    "observed_outcomes": {mode: results[mode]["outcome"] for mode in results},
                    "observed_worktree_mutation": {
                        mode: results[mode]["worktree_mutated"] for mode in results
                    },
                    "classification": classification,
                    "expectation_met": (
                        None
                        if probe.get("expected_classification") is None
                        else probe["expected_classification"] == classification
                    ),
                    "outcomes_expectation_met": outcomes_met,
                    "mutation_expectation_met": mutation_met,
                    "findings": findings,
                    "results": results,
                }
            )

        report = {
            "protocol_version": "PO03-WA-024-CLEAN-RUNNER-PROBE-v1",
            "repository_commit": commit,
            "ref": ref,
            "modes": list(environments.keys()),
            "interpreter": {
                "executable_basename": Path(sys.executable).name,
                "version": sys.version.split()[0],
            },
            "git_version": _git(["--version"], repo).stdout.strip(),
            "trees": trees,
            "probes": probe_rows,
            "summary": {
                "probe_count": len(probe_rows),
                "agree": sum(1 for row in probe_rows if row["classification"] == CLASS_AGREE),
                "warm_only_pass": sum(1 for row in probe_rows if row["classification"] == CLASS_WARM_ONLY_PASS),
                "depth_sensitive": sum(1 for row in probe_rows if row["classification"] == CLASS_DEPTH_SENSITIVE),
                "clean_only_pass": sum(1 for row in probe_rows if row["classification"] == CLASS_CLEAN_ONLY_PASS),
                "divergent": sum(1 for row in probe_rows if row["classification"] == CLASS_DIVERGENT),
                "worktree_mutating_probes": sorted(
                    row["probe_id"]
                    for row in probe_rows
                    if any(finding.startswith("WORKTREE_MUTATED_BY_WORKLOAD") for finding in row["findings"])
                ),
                "expectations_declared": sum(1 for row in probe_rows if row["expected_classification"]),
                "expectations_met": sum(1 for row in probe_rows if row["expectation_met"]),
                "outcome_expectations_declared": sum(1 for row in probe_rows if row["expected_outcomes"]),
                "outcome_expectations_met": sum(1 for row in probe_rows if row["outcomes_expectation_met"]),
                "mutation_expectations_declared": sum(
                    1 for row in probe_rows if row["expect_worktree_mutation"] is not None
                ),
                "mutation_expectations_met": sum(1 for row in probe_rows if row["mutation_expectation_met"]),
                "binding_expectation_failures": sorted(
                    row["probe_id"]
                    for row in probe_rows
                    if row["expectation_binding"] == "binding"
                    and False
                    in {
                        row["expectation_met"],
                        row["outcomes_expectation_met"],
                        row["mutation_expectation_met"],
                    }
                ),
                "advisory_expectation_failures": sorted(
                    row["probe_id"]
                    for row in probe_rows
                    if row["expectation_binding"] != "binding"
                    and False
                    in {
                        row["expectation_met"],
                        row["outcomes_expectation_met"],
                        row["mutation_expectation_met"],
                    }
                ),
            },
            "nondeterministic_fields": [
                "probes[].results[].duration_ms",
                "probes[].results[].stdout_tail",
                "probes[].results[].stderr_tail",
                "probes[].results[].output_sha256",
                "trees.warm.preexisting_dirt",
                "git_version",
                "interpreter.version",
            ],
        }
        return redact_tree(report, {str(sandbox): "<SANDBOX>", str(repo): "<REPO>"})
    finally:
        if not keep_sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)


def load_probes(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    probes = doc["probes"] if isinstance(doc, dict) else doc
    if not isinstance(probes, list) or not probes:
        raise ProbeError(f"{path}: expected a non-empty probes array")
    seen: set[str] = set()
    for probe in probes:
        if probe["probe_id"] in seen:
            raise ProbeError(f"duplicate probe_id: {probe['probe_id']}")
        seen.add(probe["probe_id"])
    return probes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--probes", type=Path, required=True)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    parser.add_argument(
        "--require-expectations",
        action="store_true",
        help="exit non-zero when a probe's observed classification differs from its declared expectation",
    )
    args = parser.parse_args(argv)

    modes = tuple(mode.strip() for mode in args.modes.split(",") if mode.strip())
    unknown = [mode for mode in modes if mode not in MODES]
    if unknown:
        print(f"unknown modes: {unknown}", file=sys.stderr)
        return 2

    try:
        report = probe_repository(
            args.repo, load_probes(args.probes), commit=args.commit, ref=args.ref, modes=modes
        )
    except (ProbeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"PROBE ERROR: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)

    summary = report["summary"]
    print(
        "CLEAN RUNNER PROBE: {probe_count} probes, agree={agree}, "
        "warm_only_pass={warm_only_pass}, depth_sensitive={depth_sensitive}, "
        "clean_only_pass={clean_only_pass}, divergent={divergent}".format(**summary),
        file=sys.stderr,
    )
    for row in report["probes"]:
        label = "UNEXPECTED" if row["expectation_binding"] == "binding" else "ADVISORY-UNEXPECTED"
        if row["expectation_met"] is False:
            print(
                f"{label} {row['probe_id']}: expected classification "
                f"{row['expected_classification']}, observed {row['classification']}",
                file=sys.stderr,
            )
        if row["outcomes_expectation_met"] is False:
            print(
                f"{label} {row['probe_id']}: expected outcomes "
                f"{row['expected_outcomes']}, observed {row['observed_outcomes']}",
                file=sys.stderr,
            )
        if row["mutation_expectation_met"] is False:
            print(
                f"{label} {row['probe_id']}: expected worktree mutation "
                f"{row['expect_worktree_mutation']}, observed {row['observed_worktree_mutation']}",
                file=sys.stderr,
            )
    if args.require_expectations and summary["binding_expectation_failures"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
