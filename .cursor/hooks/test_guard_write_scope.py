"""Tests for the re-founded write-scope guard.

The point of this suite is to separate two things that looked identical while
the protected-surface category was in force: a refusal because of what a command
DOES, and a refusal because of the NAME of the ref it touches. The second class
is gone. Every remaining refusal here is EARNED and is demonstrated to fire on a
ref with no special name at all.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parent / "guard_write_scope.py"
CONFIG = Path(__file__).resolve().parents[1] / "write-scope.json"


def _git(args, cwd, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def decide(command: str, cwd: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"command": command, "cwd": str(cwd)}),
        capture_output=True, text=True, timeout=180,
    )
    return json.loads(result.stdout)


class FixtureRepo:
    """A real repository with a real remote, so the guard is exercised, not mocked."""

    def __init__(self, config: dict):
        self.dir = Path(tempfile.mkdtemp(prefix="guard-hook-test-"))
        self.remote = self.dir / "origin.git"
        self.repo = self.dir / "repo"
        _git(["init", "--quiet", "--bare", str(self.remote)], cwd=self.dir)
        _git(["init", "--quiet", "-b", "main", str(self.repo)], cwd=self.dir)
        for key, value in (("user.email", "t@obzio.invalid"), ("user.name", "T"),
                           ("commit.gpgsign", "false")):
            _git(["config", key, value], cwd=self.repo)
        _git(["remote", "add", "origin", str(self.remote)], cwd=self.repo)
        (self.repo / "file.txt").write_text("x\n", encoding="utf-8")
        _git(["add", "-A"], cwd=self.repo)
        _git(["commit", "--quiet", "-m", "initial"], cwd=self.repo)
        _git(["push", "--quiet", "origin", "main"], cwd=self.repo)
        (self.repo / ".cursor").mkdir(parents=True, exist_ok=True)
        (self.repo / ".cursor" / "write-scope.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8")

    def declare(self, declaration: dict, name: str = "wd.json") -> None:
        directory = self.repo / ".cursor" / "write-declarations"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(declaration, indent=2), encoding="utf-8")

    def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)


BASE_CONFIG = {
    "refused_commands": [
        {"id": "FORCE-PUSH", "pattern": "git\\s+push\\b.*(--force(?!-with-lease)|(^|\\s)-f(\\s|$))",
         "reason": "force push destroys immutable-SHA custody"},
    ],
    "require_currentness_check_before_commit": False,
    "refuse_detached_head": True,
    "refuse_stale_ref_push": True,
    "require_write_declaration": False,
    "write_declarations_dir": ".cursor/write-declarations",
}


class NoProtectedCategoryTests(unittest.TestCase):
    """The refusals that keyed on a ref's name are gone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = FixtureRepo(BASE_CONFIG)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_pushing_to_main_is_allowed(self) -> None:
        """'Write to main.' — nothing about the name refuses this any more."""
        self.assertEqual("allow", decide("git push origin main", self.fixture.repo)["permission"])

    def test_committing_on_main_is_allowed(self) -> None:
        self.assertEqual("allow", decide("git commit -m x", self.fixture.repo)["permission"])

    def test_previously_protected_names_are_all_ordinary(self) -> None:
        for ref in ("main", "so02/strategic-control-plane-migration-20260822-v001",
                    "po03/repository-engineering-portable-runtime-20260822-v001",
                    "cursor/po03-wave-a-factory-6e19", "soo/v003-currentness-repair-20260820",
                    "packs/operator-fleet-v1-20260820", "cursor/so02-cur-orch-qual-01"):
            verdict = decide(f"git push origin HEAD:{ref}", self.fixture.repo)
            self.assertEqual("allow", verdict["permission"], f"{ref}: {verdict}")

    def test_the_hook_no_longer_reads_a_branch_glob_list(self) -> None:
        # The module docstring records what was retired and so names it. What
        # must not survive is executable use, so the docstring is stripped first.
        tree = ast.parse(HOOK.read_text(encoding="utf-8"))
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            tree.body.pop(0)
        code_only = ast.unparse(tree)
        for retired in ("protected_branch_globs", "protected_path_globs", "is_protected",
                        "PROTECTED-BRANCH-PUSH", "PROTECTED-BRANCH-COMMIT", "fnmatch"):
            self.assertNotIn(retired, code_only, f"{retired} survives in executable code")

    def test_the_shipped_config_declares_no_protected_targets(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertNotIn("protected_branch_globs", config)
        self.assertNotIn("protected_path_globs", config)

    def test_every_shipped_refusal_states_its_provenance_and_defect(self) -> None:
        """'An unclassified constraint is not in force.'"""
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertTrue(config["refused_commands"])
        for rule in config["refused_commands"]:
            self.assertIn(rule.get("provenance"), {"FOUNDER_AUTHORED", "EARNED"}, rule["id"])
            self.assertTrue(rule.get("defect_cited", "").strip(), rule["id"])


class EarnedRefusalsStillFireTests(unittest.TestCase):
    """Kept because each caught a real defect, and demonstrated on an ordinary ref."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = FixtureRepo(BASE_CONFIG)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def test_force_push_is_refused_even_to_a_scratch_branch(self) -> None:
        verdict = decide("git push --force origin scratch", self.fixture.repo)
        self.assertEqual("deny", verdict["permission"])
        self.assertIn("FORCE-PUSH", verdict["user_message"])

    def test_force_with_lease_is_not_refused(self) -> None:
        """The constructed reversal uses the leased form and must remain runnable."""
        verdict = decide("git push --force-with-lease=main:abc origin sha:refs/heads/main",
                         self.fixture.repo)
        self.assertEqual("allow", verdict["permission"])

    def test_a_commit_on_a_detached_head_is_refused(self) -> None:
        head = _git(["rev-parse", "HEAD"], cwd=self.fixture.repo).stdout.strip()
        _git(["checkout", "--quiet", "--detach", head], cwd=self.fixture.repo)
        try:
            verdict = decide("git commit -m x", self.fixture.repo)
            self.assertEqual("deny", verdict["permission"])
            self.assertIn("detached", verdict["user_message"].lower())
        finally:
            _git(["checkout", "--quiet", "main"], cwd=self.fixture.repo)

    def test_a_push_of_a_ref_behind_head_is_refused(self) -> None:
        _git(["branch", "-f", "behind", "HEAD"], cwd=self.fixture.repo)
        (self.fixture.repo / "file.txt").write_text("y\n", encoding="utf-8")
        _git(["add", "-A"], cwd=self.fixture.repo)
        _git(["commit", "--quiet", "-m", "advance"], cwd=self.fixture.repo)
        verdict = decide("git push origin behind", self.fixture.repo)
        self.assertEqual("deny", verdict["permission"])
        self.assertIn("behind", verdict["user_message"])


class DeclarationRequirementTests(unittest.TestCase):
    """The replacement: declared and reasoned, not target avoidance."""

    @classmethod
    def setUpClass(cls) -> None:
        tools = Path(__file__).resolve().parents[2] / (
            "workstreams/so02/control-plane/operating-environment/tools/write_admission.py")
        config = dict(BASE_CONFIG)
        config["require_write_declaration"] = True
        config["write_admission_tool"] = str(tools)
        config["refuse_stale_ref_push"] = False
        cls.fixture = FixtureRepo(config)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def setUp(self) -> None:
        # Declarations are files, so one test's declaration would otherwise still
        # be on disk for the next and silently change what it is testing.
        directory = self.fixture.repo / ".cursor" / "write-declarations"
        for stale in directory.glob("*.json") if directory.is_dir() else ():
            stale.unlink()

    def test_an_undeclared_push_is_refused(self) -> None:
        verdict = decide("git push origin main", self.fixture.repo)
        self.assertEqual("deny", verdict["permission"])
        self.assertIn("undeclared", verdict["user_message"].lower())

    def test_the_refusal_says_there_is_no_protected_category(self) -> None:
        verdict = decide("git push origin main", self.fixture.repo)
        self.assertIn("This is not a protected branch", verdict["agent_message"])
        self.assertIn("a reason and a rollback", verdict["agent_message"])

    def test_a_declaration_that_fails_admission_is_refused(self) -> None:
        self.fixture.declare({
            "declaration_version": "1.0",
            "declared_by": "TEST",
            "declared_at": "2026-08-23T04:00:00Z",
            "target": {"ref": "main", "paths": ["file.txt"], "operation": "COMMIT_AND_PUSH"},
            "reason": {"code": "PUBLISH_LANE_DELIVERABLE", "statement": "no reversal here"},
        })
        verdict = decide("git push origin main", self.fixture.repo)
        self.assertEqual("deny", verdict["permission"])
        self.assertIn("did not pass admission", verdict["user_message"])

    def test_an_unrunnable_admission_tool_refuses_rather_than_waving_through(self) -> None:
        """A guard that cannot check must not report that it checked."""
        broken = dict(BASE_CONFIG)
        broken["require_write_declaration"] = True
        broken["write_admission_tool"] = "/nonexistent/write_admission.py"
        broken["refuse_stale_ref_push"] = False
        fixture = FixtureRepo(broken)
        try:
            fixture.declare({
                "declaration_version": "1.0",
                "target": {"ref": "main", "paths": ["file.txt"], "operation": "COMMIT_AND_PUSH"},
            })
            verdict = decide("git push origin main", fixture.repo)
            self.assertEqual("deny", verdict["permission"])
        finally:
            fixture.cleanup()


class FailOpenTests(unittest.TestCase):
    """A guard that crashes must never become a guard that blocks everything."""

    def test_unparseable_input_allows(self) -> None:
        result = subprocess.run([sys.executable, str(HOOK)], input="not json",
                                capture_output=True, text=True, timeout=60)
        self.assertEqual("allow", json.loads(result.stdout)["permission"])

    def test_a_missing_config_allows_rather_than_inventing_a_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual("allow", decide("git push origin main", Path(empty))["permission"])


if __name__ == "__main__":
    unittest.main()
