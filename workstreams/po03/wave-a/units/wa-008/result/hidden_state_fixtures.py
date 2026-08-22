#!/usr/bin/env python3
"""Sanitized hidden-state fixtures for PO03-WA-008.

Each fixture builds a self-contained, secret-free Git repository, commits a
deterministic workload, materialises a candidate ("warm") checkout of the same
commit and contaminates that checkout with exactly one known class of hidden
state — or, for the adversarial fixtures, with none, with several, or with state
outside the declared classes.

Fixture roles:

* ``warm_only_green`` fixtures are green (exit 0) in the warm checkout and red
  in a clean checkout of the same commit. They are the positive mutants.
* ``clean control`` fixtures must stay green on both sides, including the case
  where hidden state is present but genuinely unused, so a false positive is
  detectable.
* the nondeterminism, false-negative and unattributed fixtures bound what the
  detector may claim.

Only the Python standard library is used, and no fixture reads the ambient
environment, the network, or anything outside its own temporary directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from differential_run import (  # noqa: E402
    CLASS_ENVIRONMENT,
    CLASS_UNTRACKED,
    CLASS_WARM_CACHE,
    VERDICT_ATTRIBUTED,
    VERDICT_CLEAN,
    VERDICT_NONDETERMINISTIC,
    VERDICT_UNATTRIBUTED,
    DifferentialRun,
    materialise_clean_checkout,
    run_git,
    sanitised_environment,
)

FIXTURE_PROTOCOL_VERSION = "OBZIO-HIDDEN-STATE-FIXTURES-v1"

# Sanitized, non-secret fixture constants.
FIXTURE_TOKEN_VALUE = "po03-wa-008-sanitized-fixture-token-not-a-secret"
FIXTURE_TOKEN_KEY = "PO03_WA_008_FIXTURE_TOKEN"


WORKLOAD_UNTRACKED = '''\
import json
import pathlib
import sys

overrides = pathlib.Path("local_overrides.json")
if not overrides.is_file():
    sys.stdout.write("MISSING local_overrides.json\\n")
    raise SystemExit(1)
payload = json.loads(overrides.read_text(encoding="utf-8"))
sys.stdout.write("OVERRIDE mode={}\\n".format(payload["mode"]))
raise SystemExit(0)
'''

WORKLOAD_ENVIRONMENT = '''\
import os
import sys

expected = "po03-wa-008-sanitized-fixture-token-not-a-secret"
observed = os.environ.get("PO03_WA_008_FIXTURE_TOKEN")
if observed is None:
    sys.stdout.write("MISSING PO03_WA_008_FIXTURE_TOKEN\\n")
    raise SystemExit(1)
if observed != expected:
    sys.stdout.write("UNEXPECTED TOKEN\\n")
    raise SystemExit(2)
sys.stdout.write("TOKEN ACCEPTED\\n")
raise SystemExit(0)
'''

# The cached verdict is trusted without re-deriving it, so a stale repo-local
# cache keeps reporting the pre-change answer.
WORKLOAD_REPO_CACHE = '''\
import hashlib
import json
import pathlib
import sys

cache = pathlib.Path(".po03-cache/verify.json")
data = pathlib.Path("data.txt").read_bytes()
expected = pathlib.Path("expected.sha256").read_text(encoding="utf-8").strip()
if cache.is_file():
    cached = json.loads(cache.read_text(encoding="utf-8"))
    sys.stdout.write("CACHED verdict={}\\n".format(cached["verdict"]))
    raise SystemExit(0 if cached["verdict"] == "MATCH" else 1)
actual = hashlib.sha256(data).hexdigest()
verdict = "MATCH" if actual == expected else "MISMATCH"
sys.stdout.write("COMPUTED verdict={}\\n".format(verdict))
raise SystemExit(0 if verdict == "MATCH" else 1)
'''

WORKLOAD_EXTERNAL_CACHE = '''\
import json
import os
import pathlib
import sys

cache_root = os.environ.get("XDG_CACHE_HOME")
if not cache_root:
    sys.stdout.write("NO CACHE ROOT\\n")
    raise SystemExit(3)
entitlement = pathlib.Path(cache_root) / "po03-wa-008" / "entitlement.json"
if not entitlement.is_file():
    sys.stdout.write("NO WARM ENTITLEMENT\\n")
    raise SystemExit(1)
payload = json.loads(entitlement.read_text(encoding="utf-8"))
sys.stdout.write("ENTITLED tier={}\\n".format(payload["tier"]))
raise SystemExit(0)
'''

WORKLOAD_PURE = '''\
import hashlib
import pathlib
import sys

data = pathlib.Path("data.txt").read_bytes()
sys.stdout.write("PURE digest={}\\n".format(hashlib.sha256(data).hexdigest()))
raise SystemExit(0)
'''

# Emits a fresh duration and wall-clock timestamp on every run. Neither is
# hidden state, so the runner must not report a dependency.
WORKLOAD_VOLATILE_OUTPUT = '''\
import datetime
import sys
import time

start = time.perf_counter()
total = sum(range(2000))
sys.stdout.write("started at {}\\n".format(datetime.datetime.now().isoformat()))
sys.stdout.write("total={} elapsed {:.6f}s\\n".format(total, time.perf_counter() - start))
raise SystemExit(0)
'''

WORKLOAD_INTERACTION = '''\
import json
import os
import pathlib
import sys

overrides = pathlib.Path("local_overrides.json")
token = os.environ.get("PO03_WA_008_FIXTURE_TOKEN")
if not overrides.is_file():
    sys.stdout.write("NEED OVERRIDES\\n")
    raise SystemExit(1)
if token is None:
    sys.stdout.write("NEED TOKEN\\n")
    raise SystemExit(2)
payload = json.loads(overrides.read_text(encoding="utf-8"))
sys.stdout.write("PAIRED mode={} token_len={}\\n".format(payload["mode"], len(token)))
raise SystemExit(0)
'''

WORKLOAD_NONDETERMINISTIC = '''\
import os
import sys

sys.stdout.write("NONCE {}\\n".format(os.urandom(8).hex()))
raise SystemExit(0)
'''

# Reads hidden state but reports an identical outcome either way, so a
# differential comparison of the observable outcome cannot see it.
WORKLOAD_SILENT_DEPENDENCY = '''\
import pathlib
import sys

overrides = pathlib.Path("local_overrides.json")
if overrides.is_file():
    pathlib.Path("scratch-consumed.txt").write_text(overrides.read_text(encoding="utf-8"), encoding="utf-8")
sys.stdout.write("OK\\n")
raise SystemExit(0)
'''

WORKLOAD_GIT_REF_STATE = '''\
import subprocess
import sys

completed = subprocess.run(
    ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
    capture_output=True,
    text=True,
)
name = completed.stdout.strip()
if not name:
    sys.stdout.write("DETACHED HEAD\\n")
    raise SystemExit(1)
sys.stdout.write("ON BRANCH {}\\n".format(name))
raise SystemExit(0)
'''


def _init_repo(root: Path, files) -> str:
    root.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--quiet", "--initial-branch=fixture-main", str(root)])
    run_git(["config", "commit.gpgsign", "false"], cwd=root)
    for relative, content in sorted(files.items()):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (root / ".gitignore").write_text(
        "local_overrides.json\n.po03-cache/\nscratch-consumed.txt\n", encoding="utf-8"
    )
    run_git(["add", "--all"], cwd=root)
    run_git(
        [
            "-c",
            "user.name=PO03 Fixture",
            "-c",
            "user.email=po03-fixture@obzio.invalid",
            "commit",
            "--quiet",
            "--date=2026-08-22T00:00:00+00:00",
            "-m",
            "fixture: sanitized hidden-state workload",
        ],
        cwd=root,
    )
    return run_git(["rev-parse", "HEAD"], cwd=root).stdout.strip()


class FixtureFactory:
    """Builds one sanitized fixture per hidden-state class or adversarial case."""

    def __init__(self, root=None) -> None:
        self.root = Path(root).resolve() if root else Path(
            tempfile.mkdtemp(prefix="po03-wa-008-fixtures-")
        ).resolve()
        self._owns_root = root is None

    def cleanup(self) -> None:
        if self._owns_root and self.root.is_dir():
            shutil.rmtree(self.root, ignore_errors=True)

    def _space(self, fixture_id: str):
        base = self.root / fixture_id
        repo = base / "source"
        warm = base / "warm-checkout"
        home = base / "warm-home"
        tmp = base / "warm-tmp"
        cache = base / "warm-cache"
        return base, repo, warm, home, tmp, cache

    def _warm_env(self, home: Path, tmp: Path, cache: Path, extra=None) -> dict:
        env = sanitised_environment(home, tmp, cache)
        if extra:
            env.update(extra)
        return env

    def build(self, fixture_id: str) -> dict:
        builder = getattr(self, "_build_" + fixture_id.replace("-", "_"), None)
        if builder is None:
            raise KeyError("unknown fixture: " + fixture_id)
        return builder(fixture_id)

    def build_all(self):
        return [self.build(fixture_id) for fixture_id in FIXTURE_IDS]

    # --- class fixtures -------------------------------------------------

    def _build_untracked_file_dependency(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_UNTRACKED})
        materialise_clean_checkout(repo, commit, warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "warm-local"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Untracked working-tree file the workload requires",
            "class_under_test": CLASS_UNTRACKED,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_ATTRIBUTED,
            "expected_classes": [CLASS_UNTRACKED],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "local_overrides.json is gitignored and absent from the commit tree.",
        }

    def _build_environment_leakage(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_ENVIRONMENT})
        materialise_clean_checkout(repo, commit, warm)
        return {
            "fixture_id": fixture_id,
            "title": "Ambient environment variable the workload requires",
            "class_under_test": CLASS_ENVIRONMENT,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache, {FIXTURE_TOKEN_KEY: FIXTURE_TOKEN_VALUE}),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_ATTRIBUTED,
            "expected_classes": [CLASS_ENVIRONMENT],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "The token is a sanitized non-secret constant; only its digest is reported.",
        }

    def _build_warm_cache_repo_local(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(
            repo,
            {
                "workload.py": WORKLOAD_REPO_CACHE,
                "data.txt": "po03-wa-008 revised payload\n",
                "expected.sha256": "0" * 64 + "\n",
            },
        )
        materialise_clean_checkout(repo, commit, warm)
        stale = warm / ".po03-cache" / "verify.json"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(
            json.dumps({"verdict": "MATCH", "source": "pre-change run"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "fixture_id": fixture_id,
            "title": "Stale repository-local cache masking a source change",
            "class_under_test": CLASS_WARM_CACHE,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_ATTRIBUTED,
            "expected_classes": [CLASS_WARM_CACHE],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "expected.sha256 never matches data.txt, so only the stale cache can pass.",
        }

    def _build_warm_cache_external_home(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_EXTERNAL_CACHE})
        materialise_clean_checkout(repo, commit, warm)
        entitlement = cache / "po03-wa-008" / "entitlement.json"
        entitlement.parent.mkdir(parents=True, exist_ok=True)
        entitlement.write_text(
            json.dumps({"tier": "sanitized-fixture"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Warm user-level cache outside the checkout",
            "class_under_test": CLASS_WARM_CACHE,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_ATTRIBUTED,
            "expected_classes": [CLASS_WARM_CACHE],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "XDG_CACHE_HOME points at a per-side root, so cache presence is not env leakage.",
        }

    # --- clean controls ------------------------------------------------

    def _build_clean_control_pure(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(
            repo, {"workload.py": WORKLOAD_PURE, "data.txt": "po03-wa-008 deterministic payload\n"}
        )
        materialise_clean_checkout(repo, commit, warm)
        return {
            "fixture_id": fixture_id,
            "title": "Clean control with no hidden state present",
            "class_under_test": None,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_CLEAN,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": False,
            "notes": "No class may be reported present and no divergence may be observed.",
        }

    def _build_clean_control_contaminated_but_unused(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(
            repo, {"workload.py": WORKLOAD_PURE, "data.txt": "po03-wa-008 deterministic payload\n"}
        )
        materialise_clean_checkout(repo, commit, warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "ignored"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        stale = warm / ".po03-cache" / "verify.json"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(json.dumps({"verdict": "IRRELEVANT"}, sort_keys=True) + "\n", encoding="utf-8")
        entitlement = cache / "po03-wa-008" / "entitlement.json"
        entitlement.parent.mkdir(parents=True, exist_ok=True)
        entitlement.write_text(json.dumps({"tier": "ignored"}, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "fixture_id": fixture_id,
            "title": "Clean control with all three classes present but unused",
            "class_under_test": None,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache, {FIXTURE_TOKEN_KEY: FIXTURE_TOKEN_VALUE}),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_CLEAN,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": False,
            "notes": "Presence of hidden state must not by itself produce a dependency finding.",
        }

    def _build_clean_control_volatile_output(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_VOLATILE_OUTPUT})
        materialise_clean_checkout(repo, commit, warm)
        return {
            "fixture_id": fixture_id,
            "title": "Clean control whose output carries a fresh duration and timestamp",
            "class_under_test": None,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_CLEAN,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": False,
            "notes": "Volatile durations and timestamps must be scrubbed, not treated as divergence.",
        }

    # --- adversarial fixtures ------------------------------------------

    def _build_interaction_untracked_and_environment(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_INTERACTION})
        materialise_clean_checkout(repo, commit, warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "paired"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Two classes required jointly; neither is sufficient alone",
            "class_under_test": "INTERACTION",
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache, {FIXTURE_TOKEN_KEY: FIXTURE_TOKEN_VALUE}),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_ATTRIBUTED,
            "expected_classes": [CLASS_ENVIRONMENT, CLASS_UNTRACKED],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "Single-class probes must fail and the closure probe must reproduce the warm outcome.",
        }

    def _build_nondeterministic_command(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_NONDETERMINISTIC})
        materialise_clean_checkout(repo, commit, warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "decoy"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Intrinsically nondeterministic command with decoy hidden state",
            "class_under_test": "NONE_NONDETERMINISTIC",
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_NONDETERMINISTIC,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": False,
            "notes": "Flakiness must never be attributed to a hidden-state class.",
        }

    def _build_silent_hidden_state_dependency(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_SILENT_DEPENDENCY})
        materialise_clean_checkout(repo, commit, warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "silent"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Real untracked-file read with identical observable outcome",
            "class_under_test": CLASS_UNTRACKED,
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_CLEAN,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": True,
            "notes": "Bounds the detector: outcome-differential detection cannot see silent reads.",
        }

    def _build_unattributed_git_ref_state(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(repo, {"workload.py": WORKLOAD_GIT_REF_STATE})
        materialise_clean_checkout(repo, commit, warm)
        run_git(["checkout", "--quiet", "-b", "warm-branch", commit], cwd=warm)
        (warm / "local_overrides.json").write_text(
            json.dumps({"mode": "decoy"}, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "fixture_id": fixture_id,
            "title": "Divergence from checkout ref state, outside the declared classes",
            "class_under_test": "OUTSIDE_DECLARED_CLASSES",
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_UNATTRIBUTED,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 1,
            "warm_only_green": True,
            "known_false_negative": False,
            "notes": "The runner must refuse to attribute a divergence it cannot reproduce.",
        }


    def _build_unattributed_modified_tracked_file(self, fixture_id):
        base, repo, warm, home, tmp, cache = self._space(fixture_id)
        commit = _init_repo(
            repo, {"workload.py": WORKLOAD_PURE, "data.txt": "po03-wa-008 committed payload\n"}
        )
        materialise_clean_checkout(repo, commit, warm)
        (warm / "data.txt").write_text("po03-wa-008 locally edited payload\n", encoding="utf-8")
        return {
            "fixture_id": fixture_id,
            "title": "Uncommitted edit to tracked content, outside the declared classes",
            "class_under_test": "OUTSIDE_DECLARED_CLASSES",
            "repo": repo,
            "commit": commit,
            "command": [sys.executable, "workload.py"],
            "warm_checkout": warm,
            "warm_env": self._warm_env(home, tmp, cache),
            "warm_cache_root": cache,
            "expected_verdict": VERDICT_UNATTRIBUTED,
            "expected_classes": [],
            "expected_warm_exit_code": 0,
            "expected_clean_exit_code": 0,
            "warm_only_green": False,
            "known_false_negative": False,
            "notes": "Must be reported as out-of-scope modified tracked content, not attributed.",
        }


FIXTURE_IDS = (
    "untracked-file-dependency",
    "environment-leakage",
    "warm-cache-repo-local",
    "warm-cache-external-home",
    "clean-control-pure",
    "clean-control-contaminated-but-unused",
    "clean-control-volatile-output",
    "interaction-untracked-and-environment",
    "nondeterministic-command",
    "silent-hidden-state-dependency",
    "unattributed-git-ref-state",
    "unattributed-modified-tracked-file",
)


def run_fixture(spec: dict, repeats: int = 2, sandbox=None) -> dict:
    runner = DifferentialRun(
        repo=spec["repo"],
        commit=spec["commit"],
        command=spec["command"],
        warm_checkout=spec["warm_checkout"],
        warm_env=spec["warm_env"],
        warm_cache_root=spec["warm_cache_root"],
        repeats=repeats,
        sandbox=sandbox,
    )
    try:
        return runner.execute()
    finally:
        if sandbox is None:
            runner.cleanup()


def evaluate(spec: dict, report: dict) -> dict:
    checks = []

    def record(name, passed, detail):
        checks.append({"check": name, "outcome": "PASS" if passed else "FAIL", "detail": detail})

    record(
        "verdict_matches_expectation",
        report["verdict"] == spec["expected_verdict"],
        "expected {} observed {}".format(spec["expected_verdict"], report["verdict"]),
    )
    record(
        "attributed_classes_match_expectation",
        sorted(report["attributed_classes"]) == sorted(spec["expected_classes"]),
        "expected {} observed {}".format(
            sorted(spec["expected_classes"]), sorted(report["attributed_classes"])
        ),
    )
    if spec["expected_verdict"] != VERDICT_NONDETERMINISTIC:
        record(
            "warm_exit_code_matches_expectation",
            report["warm"]["exit_code"] == spec["expected_warm_exit_code"],
            "expected {} observed {}".format(
                spec["expected_warm_exit_code"], report["warm"]["exit_code"]
            ),
        )
        record(
            "clean_exit_code_matches_expectation",
            report["clean"]["exit_code"] == spec["expected_clean_exit_code"],
            "expected {} observed {}".format(
                spec["expected_clean_exit_code"], report["clean"]["exit_code"]
            ),
        )
    if spec["warm_only_green"]:
        record(
            "warm_only_green_mutant",
            report["warm"]["exit_code"] == 0 and report["clean"]["exit_code"] != 0,
            "warm={} clean={}".format(report["warm"]["exit_code"], report["clean"]["exit_code"]),
        )
    record(
        "no_environment_value_in_report",
        FIXTURE_TOKEN_VALUE not in json.dumps(report),
        "report must carry environment value digests only",
    )
    outcome = "PASS" if all(check["outcome"] == "PASS" for check in checks) else "FAIL"
    return {
        "fixture_id": spec["fixture_id"],
        "title": spec["title"],
        "class_under_test": spec["class_under_test"],
        "expected_verdict": spec["expected_verdict"],
        "observed_verdict": report["verdict"],
        "expected_classes": sorted(spec["expected_classes"]),
        "observed_classes": sorted(report["attributed_classes"]),
        "warm_exit_code": report["warm"]["exit_code"],
        "clean_exit_code": report["clean"]["exit_code"],
        "warm_only_green": spec["warm_only_green"],
        "known_false_negative": spec["known_false_negative"],
        "classification_digest": report["classification_digest"],
        "checks": checks,
        "outcome": outcome,
        "notes": spec["notes"],
    }


def run_matrix(repeats: int = 2) -> dict:
    factory = FixtureFactory()
    results = []
    try:
        for fixture_id in FIXTURE_IDS:
            spec = factory.build(fixture_id)
            report = run_fixture(spec, repeats=repeats)
            results.append(evaluate(spec, report))
    finally:
        factory.cleanup()
    return {
        "protocol_version": FIXTURE_PROTOCOL_VERSION,
        "task_id": "PO03-WA-008",
        "hypothesis_id": "H-PO03-WA-008",
        "fixture_count": len(results),
        "warm_only_green_mutant_count": sum(1 for row in results if row["warm_only_green"]),
        "clean_control_count": sum(
            1 for row in results if row["expected_verdict"] == VERDICT_CLEAN and not row["known_false_negative"]
        ),
        "known_false_negative_count": sum(1 for row in results if row["known_false_negative"]),
        "outcome": "PASS" if all(row["outcome"] == "PASS" for row in results) else "FAIL",
        "fixtures": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the PO03-WA-008 hidden-state fixture matrix.")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)
    summary = run_matrix(repeats=args.repeats)
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.json_path:
        Path(args.json_path).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0 if summary["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
