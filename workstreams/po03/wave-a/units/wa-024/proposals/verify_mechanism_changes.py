#!/usr/bin/env python3
"""Independently verify the PO03-WA-024 mechanism changes.

Each proposed change is a patch against a read-only path.  This verifier never
writes to the repository under test: it clones it into a scratch directory, and
for every mechanism change it establishes three things.

  1. the patch applies to the pinned tree,
  2. the defect is observable before the patch, and
  3. the defect is gone after it, without breaking the seeded contract tests.

Point 2 is what makes the change falsifiable rather than cosmetic.  A check that
only passes after the patch proves nothing unless the same check fails before
it, so every mechanism change here carries a matched before/after pair, and at
least one adversarial case establishing that the new guard is not vacuous.

Usage:
    python3 verify_mechanism_changes.py --repo <path-or-url> [--commit <sha>]
                                        [--json <out>] [--keep]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

UNIT_REL = "workstreams/po03/wave-a/units/wa-024"
PATCH_DIR_REL = f"{UNIT_REL}/proposals/patches"

MC01 = "MC-01-CONTRACT-TESTS-LEAVE-NO-BYTECODE"
MC02 = "MC-02-VERIFY-FROZEN-OBJECT-IDS"
MC03 = "MC-03-CUSTODY-READBACK-NEEDS-A-FETCHABLE-REF"

PATCHES = {
    MC01: "mc-01-contract-tests-leave-no-bytecode.diff",
    MC02: "mc-02-verify-frozen-object-ids.diff",
    MC03: "mc-03-custody-readback-needs-a-fetchable-ref.diff",
}

WORKFLOW_REL = ".github/workflows/po03-contracts.yml"
PREPARE_REL = "workstreams/po03/tools/prepare_wave_a.py"
VALIDATOR_REL = "workstreams/po03/tools/validate_contracts.py"
SCHEMA_REL = "workstreams/po03/contracts/transactional-result.schema.json"
CONTROL_RESULTS = (
    "workstreams/po03/control/results/wa-canary-000.json",
    "workstreams/po03/control/results/wa-isolation-canary-001.json",
)

# The declared contract-test command, with the interpreter left as a placeholder
# so the harness can run it on a host where the bare name "python" is absent.
DECLARED_TEST_ARGS = ["-I", "-m", "unittest", "discover", "-s", "workstreams/po03/tests", "-p", "test_*.py"]

SCRUBBED_KEEP = {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TZ", "SHELL", "USER"}


class Failure(Exception):
    """A verification check did not hold."""

    def __init__(self, message: str, checks: list[dict[str, object]] | None = None) -> None:
        super().__init__(message)
        self.checks = checks or []


def scrubbed_env(home: Path) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name in SCRUBBED_KEEP}
    env["HOME"] = str(home)
    env["GIT_CONFIG_GLOBAL"] = str(home / "gitconfig-absent")
    env["GIT_CONFIG_SYSTEM"] = str(home / "gitconfig-absent")
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)


def git(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, env)


def dirt(cwd: Path, env: dict[str, str]) -> list[str]:
    out = git(["status", "--porcelain", "--untracked-files=all"], cwd, env).stdout
    return [line for line in out.splitlines() if line.strip()]


def load_module(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Failure(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Recorder:
    """Collects named check outcomes for one mechanism change."""

    def __init__(self, change_id: str) -> None:
        self.change_id = change_id
        self.checks: list[dict[str, object]] = []

    def check(self, name: str, phase: str, holds: bool, evidence: str) -> None:
        self.checks.append(
            {
                "check": name,
                "phase": phase,
                "disposition": "PASS" if holds else "FAIL",
                "evidence": evidence,
            }
        )
        if not holds:
            raise Failure(f"{self.change_id}/{name}: {evidence}", self.checks)

    @property
    def disposition(self) -> str:
        return "FAIL" if any(row["disposition"] == "FAIL" for row in self.checks) else "PASS"


def clone_url(source: str) -> str:
    """Normalise a local path to a file:// URL.

    A bare local path makes git use the local transport, which copies the whole
    object database regardless of --single-branch.  That would hand the clone
    commits from other branches and quietly invalidate every reachability check.
    """
    if "://" in source or source.startswith("git@"):
        return source
    return f"file://{Path(source).resolve()}"


class Scratch:
    """A disposable clone of the repository under test."""

    def __init__(self, source: str, commit: str | None, base: Path, name: str) -> None:
        self.root = base / name
        self.home = base / f"{name}-home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = scrubbed_env(self.home)
        # --single-branch mirrors actions/checkout, which materialises exactly one
        # ref.  Cloning every branch would make producer result commits reachable
        # and would silently invalidate the custody checks below.
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--single-branch", clone_url(source), str(self.root)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise Failure(f"clone failed: {proc.stderr.strip()}")
        if commit:
            checkout = git(["-c", "advice.detachedHead=false", "checkout", "--quiet", commit], self.root, self.env)
            if checkout.returncode != 0:
                raise Failure(f"checkout {commit} failed: {checkout.stderr.strip()}")
        self.commit = git(["rev-parse", "HEAD"], self.root, self.env).stdout.strip()

    def reset(self) -> None:
        git(["checkout", "--quiet", "--force", self.commit], self.root, self.env)
        git(["clean", "-qfdx"], self.root, self.env)

    def commit_applied_patch(self, message: str) -> None:
        """Commit a staged mechanism change, so a cleanliness gate sees a clean tree.

        In production the change is committed before CI runs it, so leaving the
        patch as a working-tree edit would make every dirt check trivially fail.
        """
        git(["add", "--all"], self.root, self.env)
        committed = git(
            [
                "-c",
                "user.name=wa-024 verifier",
                "-c",
                "user.email=wa-024@localhost",
                "commit",
                "--quiet",
                "--no-verify",
                "-m",
                message,
            ],
            self.root,
            self.env,
        )
        if committed.returncode != 0:
            raise Failure(f"could not commit the applied patch: {committed.stderr.strip()}")

    def apply(self, patch: Path) -> subprocess.CompletedProcess[str]:
        return git(["apply", str(patch)], self.root, self.env)

    def check_apply(self, patch: Path) -> subprocess.CompletedProcess[str]:
        return git(["apply", "--check", str(patch)], self.root, self.env)


# --------------------------------------------------------------------------- #
# MC-01: the declared contract-test command must leave the checkout unchanged.
# --------------------------------------------------------------------------- #


def workflow_test_command(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("run:") and "unittest" in stripped:
            return stripped[len("run:") :].strip()
    raise Failure("no contract-test run line found in the workflow")


def verify_mc01(scratch: Scratch, patch: Path) -> Recorder:
    rec = Recorder(MC01)
    root, env = scratch.root, scratch.env
    scratch.reset()

    rec.check(
        "patch_applies_to_pinned_tree",
        "patch",
        scratch.check_apply(patch).returncode == 0,
        f"git apply --check succeeds against {scratch.commit}",
    )

    rec.check("tree_is_clean_before_workload", "before", not dirt(root, env), "no untracked or modified paths")

    before = run([sys.executable, *DECLARED_TEST_ARGS], root, env)
    before_dirt = dirt(root, env)
    caches = [line for line in before_dirt if "__pycache__" in line]
    rec.check(
        "declared_command_passes_before",
        "before",
        before.returncode == 0,
        f"declared command exits {before.returncode}",
    )
    rec.check(
        "declared_command_contaminates_checkout_before",
        "before",
        bool(caches),
        f"{len(before_dirt)} dirty paths, {len(caches)} of them bytecode caches, e.g. {caches[0] if caches else 'none'}",
    )

    # The widely recommended environment-variable remediation is ineffective
    # here, because the declared command runs CPython in isolated mode.
    scratch.reset()
    naive_env = dict(env, PYTHONDONTWRITEBYTECODE="1")
    run([sys.executable, *DECLARED_TEST_ARGS], root, naive_env)
    naive_caches = [line for line in dirt(root, env) if "__pycache__" in line]
    rec.check(
        "environment_variable_remediation_is_ineffective_under_isolation",
        "adversarial",
        bool(naive_caches),
        f"PYTHONDONTWRITEBYTECODE=1 with -I still leaves {len(naive_caches)} bytecode caches",
    )

    scratch.reset()
    rec.check("patch_applies", "patch", scratch.apply(patch).returncode == 0, "patch applied to the scratch clone")
    scratch.commit_applied_patch("apply MC-01 for verification")

    command = workflow_test_command((root / WORKFLOW_REL).read_text(encoding="utf-8"))
    rec.check(
        "patched_workflow_command_suppresses_bytecode",
        "after",
        re.search(r"\bpython\s+-B\b", command) is not None,
        f"patched contract-test command is {command!r}",
    )

    patched_args = command.split()
    if patched_args and patched_args[0] == "python":
        patched_args[0] = sys.executable
    patched_args = [arg.strip("'") for arg in patched_args]
    after = run(patched_args, root, env)
    after_dirt = dirt(root, env)
    rec.check(
        "patched_command_still_passes",
        "after",
        after.returncode == 0,
        f"patched command exits {after.returncode}; tail: {after.stderr.strip().splitlines()[-1] if after.stderr.strip() else ''}",
    )
    rec.check(
        "patched_command_leaves_checkout_unchanged",
        "after",
        not after_dirt,
        f"the patched command leaves no dirty path (saw {after_dirt})",
    )

    workflow_text = (root / WORKFLOW_REL).read_text(encoding="utf-8")
    rec.check(
        "patched_workflow_adds_a_cleanliness_gate",
        "after",
        "left the checkout dirty" in workflow_text,
        "the workflow gains a post-test step that fails on a dirty checkout",
    )

    # A gate that can never fail would be worthless, so provoke it.
    gate = (
        'dirty="$(git status --porcelain --untracked-files=all)"\n'
        'if [ -n "$dirty" ]; then exit 1; fi\n'
    )
    clean_gate = run(["bash", "-c", gate], root, env)
    (root / "workstreams" / "po03" / "tests" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (root / "workstreams" / "po03" / "tests" / "__pycache__" / "probe.pyc").write_bytes(b"\x00")
    dirty_gate = run(["bash", "-c", gate], root, env)
    rec.check(
        "cleanliness_gate_is_not_vacuous",
        "adversarial",
        clean_gate.returncode == 0 and dirty_gate.returncode == 1,
        f"gate exits {clean_gate.returncode} on a clean tree and {dirty_gate.returncode} once a bytecode cache is planted",
    )

    scratch.reset()
    return rec


# --------------------------------------------------------------------------- #
# MC-02: frozen provenance identifiers must name real objects.
# --------------------------------------------------------------------------- #


def read_literal(path: Path, name: str) -> str:
    match = re.search(rf'^{name} = "([0-9a-f]+)"$', path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise Failure(f"{name} literal not found in {path.name}")
    return match.group(1)


def verify_mc02(scratch: Scratch, patch: Path, base: Path) -> Recorder:
    rec = Recorder(MC02)
    root, env = scratch.root, scratch.env
    scratch.reset()

    rec.check(
        "patch_applies_to_pinned_tree",
        "patch",
        scratch.check_apply(patch).returncode == 0,
        f"git apply --check succeeds against {scratch.commit}",
    )

    recorded = read_literal(root / PREPARE_REL, "PROTOCOL_ANCESTOR")
    exact = git(["cat-file", "-e", f"{recorded}^{{commit}}"], root, env)
    prefix = git(["rev-parse", "--verify", "--quiet", f"{recorded[:7]}^{{commit}}"], root, env)
    rec.check(
        "recorded_identifier_is_prefix_only_correct_before",
        "before",
        exact.returncode != 0 and prefix.returncode == 0,
        f"{recorded} names no commit, yet {recorded[:7]} resolves to {prefix.stdout.strip()}",
    )
    rec.check(
        "generator_has_no_object_id_guard_before",
        "before",
        "cat-file" not in (root / PREPARE_REL).read_text(encoding="utf-8"),
        "the unpatched generator performs no object-existence check",
    )

    scratch.reset()
    rec.check("patch_applies", "patch", scratch.apply(patch).returncode == 0, "patch applied to the scratch clone")

    fixed = read_literal(root / PREPARE_REL, "PROTOCOL_ANCESTOR")
    resolves = git(["cat-file", "-e", f"{fixed}^{{commit}}"], root, env)
    rec.check(
        "patched_identifier_names_a_real_commit",
        "after",
        resolves.returncode == 0,
        f"{fixed} names a commit in the repository",
    )
    ancestry = git(["merge-base", "--is-ancestor", fixed, "HEAD"], root, env)
    rec.check(
        "patched_identifier_is_an_ancestor_of_the_pinned_commit",
        "after",
        ancestry.returncode == 0,
        f"{fixed} is an ancestor of {scratch.commit}",
    )
    rec.check(
        "idempotency_keys_are_unaffected",
        "after",
        fixed[:7] == recorded[:7],
        f"the seven-character prefix stays {fixed[:7]}, so every po03:<prefix>:<slug>:a01 key is byte-identical",
    )

    module = load_module(root / PREPARE_REL, "wa024_prepare_patched")
    rec.check(
        "guard_accepts_the_corrected_identifiers",
        "after",
        _guard_outcome(module) is None,
        "verify_frozen_object_ids() returns without raising on the corrected literals",
    )

    module.PROTOCOL_ANCESTOR = recorded
    reintroduced = _guard_outcome(module)
    rec.check(
        "guard_refuses_the_original_defect",
        "adversarial",
        reintroduced is not None and "prefix-only-correct" in reintroduced,
        f"reinstating {recorded} raises: {reintroduced}",
    )

    module.PROTOCOL_ANCESTOR = "0" * 40
    absent = _guard_outcome(module)
    rec.check(
        "guard_refuses_an_identifier_with_no_resolvable_prefix",
        "adversarial",
        absent is not None and "names no commit" in absent,
        f"an all-zero identifier raises: {absent}",
    )

    module.PROTOCOL_ANCESTOR = recorded[:7]
    abbreviated = _guard_outcome(module)
    rec.check(
        "guard_refuses_an_abbreviation",
        "adversarial",
        abbreviated is not None and "full lowercase commit id" in abbreviated,
        f"a seven-character identifier raises: {abbreviated}",
    )

    shallow = base / "mc02-shallow"
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", clone_url(str(root)), str(shallow)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise Failure(f"shallow clone failed: {clone.stderr.strip()}")
    shutil.copy2(root / PREPARE_REL, shallow / PREPARE_REL)
    shallow_module = load_module(shallow / PREPARE_REL, "wa024_prepare_shallow")
    shallow_outcome = _guard_outcome(shallow_module)
    rec.check(
        "guard_refuses_to_freeze_provenance_from_a_shallow_checkout",
        "adversarial",
        shallow_outcome is not None and "shallow" in shallow_outcome,
        f"a depth-1 clone raises rather than silently skipping: {shallow_outcome}",
    )

    scratch.reset()
    return rec


def _guard_outcome(module: types.ModuleType) -> str | None:
    try:
        module.verify_frozen_object_ids()
    except ValueError as exc:
        return str(exc)
    return None


# --------------------------------------------------------------------------- #
# MC-03: an ingested result commit must carry a ref a verifier can fetch.
# --------------------------------------------------------------------------- #


def verify_mc03(scratch: Scratch, patch: Path) -> Recorder:
    rec = Recorder(MC03)
    root, env = scratch.root, scratch.env
    scratch.reset()

    rec.check(
        "patch_applies_to_pinned_tree",
        "patch",
        scratch.check_apply(patch).returncode == 0,
        f"git apply --check succeeds against {scratch.commit}",
    )

    sample = json.loads((root / CONTROL_RESULTS[0]).read_text(encoding="utf-8"))
    locator = sample["result_transaction"]["manifest_uri"]
    match = re.fullmatch(r"git:(?P<ref>[^@\s]+)@(?P<commit>[0-9a-f]{40}):(?P<path>\S+)", locator)
    rec.check(
        "control_files_already_embed_a_ref_in_the_manifest_locator",
        "before",
        match is not None,
        f"manifest_uri carries ref {match.group('ref') if match else None}",
    )

    commit_id = sample["result_transaction"]["result_commit_id"]
    reachable = git(["cat-file", "-e", f"{commit_id}^{{commit}}"], root, env)
    rec.check(
        "recorded_result_commit_is_unreachable_from_this_checkout",
        "before",
        reachable.returncode != 0,
        f"{commit_id} is not an object in a clone of {scratch.commit}, so read-back needs its ref fetched first",
    )

    refless = json.loads(json.dumps(sample))
    refless["result_transaction"]["manifest_uri"] = match.group("path") if match else "some/path.json"

    unpatched = load_module(root / VALIDATOR_REL, "wa024_validator_unpatched")
    rec.check(
        "unpatched_validator_accepts_a_refless_ingested_result",
        "before",
        unpatched.validate_result(refless) == [],
        "the unpatched validator reports no error for an ingested result carrying no fetchable ref",
    )
    rec.check(
        "unpatched_validator_accepts_a_locator_whose_commit_disagrees",
        "before",
        unpatched.validate_result(_mismatched(sample)) == [],
        "the unpatched validator reports no error when the locator commit differs from result_commit_id",
    )

    scratch.reset()
    rec.check("patch_applies", "patch", scratch.apply(patch).returncode == 0, "patch applied to the scratch clone")

    patched = load_module(root / VALIDATOR_REL, "wa024_validator_patched")
    refless_errors = patched.validate_result(refless)
    rec.check(
        "patched_validator_rejects_a_refless_ingested_result",
        "after",
        any("fetchable ref" in error for error in refless_errors),
        f"patched validator reports {refless_errors}",
    )
    mismatch_errors = patched.validate_result(_mismatched(sample))
    rec.check(
        "patched_validator_rejects_a_locator_commit_mismatch",
        "after",
        any("does not match result_commit_id" in error for error in mismatch_errors),
        f"patched validator reports {mismatch_errors}",
    )

    disagreeing = json.loads(json.dumps(sample))
    disagreeing["result_transaction"]["result_commit_ref"] = "refs/heads/some-other-branch"
    disagree_errors = patched.validate_result(disagreeing)
    rec.check(
        "patched_validator_rejects_a_ref_that_disagrees_with_the_locator",
        "after",
        any("disagrees with the manifest_uri locator" in error for error in disagree_errors),
        f"patched validator reports {disagree_errors}",
    )

    for rel in CONTROL_RESULTS:
        doc = json.loads((root / rel).read_text(encoding="utf-8"))
        errors = patched.validate_result(doc)
        rec.check(
            f"patched_validator_still_accepts_{Path(rel).stem}",
            "after",
            errors == [],
            f"{rel} validates with no error under the patched validator",
        )
        ref = patched.readback_ref(doc["result_transaction"])
        rec.check(
            f"readback_ref_is_recoverable_for_{Path(rel).stem}",
            "after",
            bool(ref),
            f"a verifier must fetch {ref} before reading {doc['result_transaction']['result_commit_id']}",
        )

    schema = json.loads((root / SCHEMA_REL).read_text(encoding="utf-8"))
    properties = schema["properties"]["result_transaction"]["properties"]
    rec.check(
        "schema_admits_the_new_field",
        "after",
        "result_commit_ref" in properties,
        "the schema declares result_commit_ref, which additionalProperties false would otherwise forbid",
    )

    before_count = seeded_test_count(scratch, unpatched_tree=True)
    seeded = run([sys.executable, "-B", *DECLARED_TEST_ARGS], root, env)
    rec.check(
        "seeded_contract_tests_still_pass",
        "after",
        seeded.returncode == 0,
        f"seeded suite exits {seeded.returncode}: {last_line(seeded.stderr)}",
    )
    after_count = parse_test_count(seeded.stderr)
    rec.check(
        "the_new_rule_is_enforced_by_the_repositorys_own_tests",
        "after",
        after_count > before_count,
        f"the seeded suite grows from {before_count} to {after_count} tests, so the guard is covered upstream rather than only here",
    )

    scratch.reset()
    return rec


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def parse_test_count(text: str) -> int:
    match = re.search(r"^Ran (\d+) tests?", text, re.MULTILINE)
    return int(match.group(1)) if match else -1


def seeded_test_count(scratch: Scratch, unpatched_tree: bool = False) -> int:
    """Count the seeded tests on the pinned tree, without any patch applied."""
    stash = scratch.root / ".wa024-stash"
    if unpatched_tree:
        shutil.copytree(scratch.root / "workstreams/po03/tests", stash, dirs_exist_ok=True)
        git(["checkout", "--quiet", scratch.commit, "--", "workstreams/po03/tests"], scratch.root, scratch.env)
    proc = run([sys.executable, "-B", *DECLARED_TEST_ARGS], scratch.root, scratch.env)
    if unpatched_tree:
        shutil.copytree(stash, scratch.root / "workstreams/po03/tests", dirs_exist_ok=True)
        shutil.rmtree(stash, ignore_errors=True)
    return parse_test_count(proc.stderr)


def verify_combined(scratch: Scratch, patch_dir: Path) -> Recorder:
    """Establish that the three changes compose, rather than only working alone."""
    rec = Recorder("MC-COMBINED")
    root, env = scratch.root, scratch.env
    scratch.reset()

    patches = [patch_dir / name for name in PATCHES.values()]
    combined = git(["apply", *[str(item) for item in patches]], root, env)
    rec.check(
        "all_three_patches_apply_together",
        "patch",
        combined.returncode == 0,
        f"a single git apply of all three patches succeeds: {combined.stderr.strip()}",
    )
    scratch.commit_applied_patch("apply MC-01, MC-02 and MC-03 for verification")

    suite = run([sys.executable, "-B", *DECLARED_TEST_ARGS], root, env)
    rec.check(
        "seeded_contract_tests_pass_under_all_three",
        "after",
        suite.returncode == 0,
        f"seeded suite exits {suite.returncode}: {last_line(suite.stderr)}",
    )

    taxonomy = run([sys.executable, "-B", "scripts/check_operator_taxonomy.py"], root, env)
    rec.check(
        "repository_taxonomy_check_passes_under_all_three",
        "after",
        taxonomy.returncode == 0,
        f"taxonomy check exits {taxonomy.returncode}: {last_line(taxonomy.stdout) or last_line(taxonomy.stderr)}",
    )

    rec.check(
        "no_workload_contaminates_the_checkout_under_all_three",
        "after",
        not dirt(root, env),
        "the tree is unchanged after the seeded suite and the taxonomy check",
    )

    scratch.reset()
    return rec


def _mismatched(sample: dict[str, object]) -> dict[str, object]:
    doc = json.loads(json.dumps(sample))
    txn = doc["result_transaction"]
    txn["manifest_uri"] = re.sub(r"@[0-9a-f]{40}:", "@" + "b" * 40 + ":", str(txn["manifest_uri"]))
    return doc


# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="path or URL of the repository under test")
    parser.add_argument("--commit", default=None, help="commit to verify against")
    parser.add_argument(
        "--patches",
        default=None,
        help="directory holding the patches; defaults to the clone's own proposals/patches",
    )
    parser.add_argument("--json", default=None, help="write the report to this path")
    parser.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = parser.parse_args(argv)

    base = Path(tempfile.mkdtemp(prefix="wa024-mechanism-"))
    report: dict[str, object] = {
        "protocol_version": "PO03-WA-024-MECHANISM-VERIFICATION-v1",
        "task_id": "PO03-WA-024",
        "state": "MECHANISM_CHANGE_VERIFICATION",
        "state_note": (
            "This file records only whether each proposed mechanism change applies and removes "
            "its defect. It is not a source claim, a hypothesis, a reproduction of the parent "
            "hypothesis, or a strategy proposal."
        ),
        "interpreter": sys.version.split()[0],
    }
    changes: list[dict[str, object]] = []
    try:
        scratch = Scratch(args.repo, args.commit, base, "under-test")
        report["repository_commit"] = scratch.commit
        patch_dir = Path(args.patches).resolve() if args.patches else scratch.root / PATCH_DIR_REL
        report["patch_source"] = "argument" if args.patches else "repository_commit"
        verifiers = {
            MC01: lambda s, p: verify_mc01(s, p),
            MC02: lambda s, p: verify_mc02(s, p, base),
            MC03: lambda s, p: verify_mc03(s, p),
        }
        for change_id, filename in PATCHES.items():
            patch = patch_dir / filename
            try:
                rec = verifiers[change_id](scratch, patch)
                changes.append(
                    {
                        "change_id": change_id,
                        "patch": f"{PATCH_DIR_REL}/{filename}",
                        "disposition": rec.disposition,
                        "checks": rec.checks,
                    }
                )
            except Failure as exc:
                changes.append(
                    {
                        "change_id": change_id,
                        "patch": f"{PATCH_DIR_REL}/{filename}",
                        "disposition": "FAIL",
                        "error": str(exc),
                        "checks": exc.checks,
                    }
                )
        try:
            rec = verify_combined(scratch, patch_dir)
            changes.append(
                {
                    "change_id": rec.change_id,
                    "patch": sorted(f"{PATCH_DIR_REL}/{name}" for name in PATCHES.values()),
                    "disposition": rec.disposition,
                    "checks": rec.checks,
                }
            )
        except Failure as exc:
            changes.append(
                {
                    "change_id": "MC-COMBINED",
                    "patch": sorted(f"{PATCH_DIR_REL}/{name}" for name in PATCHES.values()),
                    "disposition": "FAIL",
                    "error": str(exc),
                    "checks": exc.checks,
                }
            )
    finally:
        report["mechanism_changes"] = changes
        total = sum(len(item.get("checks", [])) for item in changes)
        failed = [item["change_id"] for item in changes if item["disposition"] != "PASS"]
        report["summary"] = {
            "change_count": len(changes),
            "check_count": total,
            "failed_changes": failed,
            "disposition": "PASS" if changes and not failed else "FAIL",
        }
        payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.json:
            Path(args.json).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)

    summary = report["summary"]
    assert isinstance(summary, dict)
    sys.stderr.write(
        "MECHANISM CHANGES: {change_count} changes, {check_count} checks, {disposition}\n".format(**summary)
    )
    return 0 if summary["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
