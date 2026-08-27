"""Proof that push_with_admission.py refuses on admission failure and works
from an arbitrary cwd.

Two different claims are tested separately, because conflating them is
exactly the mistake this lane exists to correct:

1. `ResolvesRepoRootIndependentOfCwdTests` — the pure resolution logic never
   consults `os.getcwd()`. This is checked by calling the function directly
   while the *test process's* cwd is changed to several unrelated
   directories, and confirming the resolved root never moves.
2. `EndToEndFromArbitraryCwdTests` — the wrapper, invoked as a real
   subprocess via its absolute path from several unrelated working
   directories, actually refuses an unadmitted push and actually runs an
   admitted one against a disposable fixture remote (never `origin`).

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pwa = _load("push_with_admission")
rr = _load("reversal_rehearsal")

WRAPPER = Path(__file__).resolve().parent / "push_with_admission.py"
THIS_REPO_ROOT = Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent,
                   capture_output=True, text=True, timeout=30).stdout.strip()
)


def _git(args, cwd, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


class FixtureRepo:
    """A real bare remote plus a real working clone, disposable, never `origin`."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="push-wrapper-test-"))
        self.remote = self.dir / "origin.git"
        self.repo = self.dir / "repo"
        _git(["init", "--quiet", "--bare", str(self.remote)], cwd=self.dir)
        _git(["init", "--quiet", "-b", "main", str(self.repo)], cwd=self.dir)
        for key, value in (("user.email", "t@obzio.invalid"), ("user.name", "T"),
                           ("commit.gpgsign", "false")):
            _git(["config", key, value], cwd=self.repo)
        _git(["remote", "add", "origin", str(self.remote)], cwd=self.repo)
        (self.repo / "file.txt").write_text("pre-write\n", encoding="utf-8")
        _git(["add", "-A"], cwd=self.repo)
        _git(["commit", "--quiet", "-m", "initial"], cwd=self.repo)
        _git(["push", "--quiet", "origin", "main"], cwd=self.repo)
        self.pre_sha = _git(["rev-parse", "main"], cwd=self.repo).stdout.strip()

    def advance(self) -> None:
        (self.repo / "file.txt").write_text("post-write\n", encoding="utf-8")
        _git(["add", "-A"], cwd=self.repo)
        _git(["commit", "--quiet", "-m", "the write under test"], cwd=self.repo)

    def remote_head(self) -> str | None:
        out = _git(["ls-remote", "--heads", "origin", "refs/heads/main"], cwd=self.repo).stdout
        return out.split()[0] if out.strip() else None

    def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)


def _declaration(ref: str = "main", *, missing_reversal: bool = False,
                 recorded_sha: str = "a" * 40, post_write_sha: str = "b" * 40) -> dict:
    decl = {
        "declaration_version": "1.0",
        "declared_by": "test_push_with_admission",
        "declared_at": "2026-08-27T05:00:00Z",
        "target": {"ref": ref, "paths": ["file.txt"], "operation": "COMMIT_AND_PUSH"},
        "reason": {
            "code": "PUBLISH_LANE_DELIVERABLE",
            "statement": f"Lane I publishes its own commissioned wrapper proof onto {ref}.",
            "lane_id": "SCP-SI-01-LANE-I",
            "commission_id": "SCP-SI-01",
        },
        "concurrency": {"observed_at": "2026-08-27T05:00:00Z", "agents": []},
    }
    if not missing_reversal:
        decl["reversal"] = {
            "method": "RESTORE_REF_TO_RECORDED_SHA",
            "recorded_sha": recorded_sha,
            "post_write_sha": post_write_sha,
            "custody_ref": "custody/test-push-wrapper",
            "command": rr.build_reversal(
                "RESTORE_REF_TO_RECORDED_SHA", ref,
                recorded_sha=recorded_sha, post_write_sha=post_write_sha,
            )["command"],
        }
    return decl


def _write_declaration(path: Path, decl: dict) -> None:
    path.write_text(json.dumps(decl, indent=2), encoding="utf-8")


def _run_wrapper(declaration_path: Path, repo: Path, cwd: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(WRAPPER), "--declaration", str(declaration_path),
            "--repo", str(repo), "--no-ref-movement"]
    if extra:
        argv += extra
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=180)


class ResolvesRepoRootIndependentOfCwdTests(unittest.TestCase):
    """The pure function never reads os.getcwd()."""

    def test_default_resolution_is_stable_across_unrelated_working_directories(self) -> None:
        candidates = [tempfile.gettempdir(), "/", str(Path.home())]
        resolved = set()
        original_cwd = os.getcwd()
        try:
            for candidate in candidates:
                target = Path(candidate)
                if not target.is_dir():
                    continue
                os.chdir(target)
                root = pwa.resolve_repo_root(None)
                self.assertIsNotNone(root, f"could not resolve from cwd={candidate}")
                resolved.add(str(root))
        finally:
            os.chdir(original_cwd)
        self.assertEqual(1, len(resolved), f"resolution varied by cwd: {resolved}")
        self.assertEqual(str(THIS_REPO_ROOT), next(iter(resolved)))

    def test_an_explicit_repo_override_is_independent_of_cwd_too(self) -> None:
        fixture = FixtureRepo()
        original_cwd = os.getcwd()
        try:
            resolved = set()
            for candidate in (tempfile.gettempdir(), "/"):
                if not Path(candidate).is_dir():
                    continue
                os.chdir(candidate)
                root = pwa.resolve_repo_root(str(fixture.repo))
                resolved.add(str(root))
            self.assertEqual({str(fixture.repo)}, resolved)
        finally:
            os.chdir(original_cwd)
            fixture.cleanup()

    def test_write_admission_module_loads_from_script_location_not_cwd(self) -> None:
        original_cwd = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            module = pwa._load_write_admission()
            self.assertIsNotNone(module)
            self.assertEqual(
                str(Path(pwa.SCRIPT_DIR) / "write_admission.py"),
                str(Path(module.__file__).resolve()),
            )
        finally:
            os.chdir(original_cwd)


class EndToEndFromArbitraryCwdTests(unittest.TestCase):
    """The wrapper as a subprocess, invoked from several unrelated cwds."""

    UNRELATED_CWDS = [tempfile.gettempdir(), "/"]

    def _cwds(self):
        return [Path(c) for c in self.UNRELATED_CWDS if Path(c).is_dir()]

    def test_a_refused_declaration_never_touches_the_remote_regardless_of_cwd(self) -> None:
        for cwd in self._cwds():
            fixture = FixtureRepo()
            try:
                fixture.advance()  # a real write exists locally, uncommitted to the remote
                decl_path = fixture.dir / "wd-missing-reversal.json"
                _write_declaration(decl_path, _declaration(missing_reversal=True))
                before = fixture.remote_head()

                result = _run_wrapper(decl_path, fixture.repo, cwd)

                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("REFUSED", result.stdout + result.stderr)
                self.assertEqual(before, fixture.remote_head(),
                                 f"remote moved despite refusal, invoked from cwd={cwd}")
            finally:
                fixture.cleanup()

    def test_an_admitted_declaration_actually_pushes_regardless_of_cwd(self) -> None:
        for cwd in self._cwds():
            fixture = FixtureRepo()
            try:
                fixture.advance()
                local_head = _git(["rev-parse", "HEAD"], cwd=fixture.repo).stdout.strip()
                decl = _declaration(recorded_sha=fixture.pre_sha, post_write_sha=local_head)
                decl_path = fixture.dir / "wd-admissible.json"
                _write_declaration(decl_path, decl)
                before = fixture.remote_head()
                self.assertEqual(fixture.pre_sha, before)

                result = _run_wrapper(decl_path, fixture.repo, cwd)

                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("ADMITTED", result.stdout)
                after = fixture.remote_head()
                self.assertEqual(local_head, after,
                                 f"remote did not advance to the admitted write, invoked from cwd={cwd}")
                self.assertNotEqual(before, after)
            finally:
                fixture.cleanup()

    def test_dry_run_admits_but_never_pushes(self) -> None:
        fixture = FixtureRepo()
        try:
            fixture.advance()
            local_head = _git(["rev-parse", "HEAD"], cwd=fixture.repo).stdout.strip()
            decl = _declaration(recorded_sha=fixture.pre_sha, post_write_sha=local_head)
            decl_path = fixture.dir / "wd-dry-run.json"
            _write_declaration(decl_path, decl)
            before = fixture.remote_head()

            result = _run_wrapper(decl_path, fixture.repo, Path(tempfile.gettempdir()), extra=["--dry-run"])

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("ADMITTED (dry run, not executed)", result.stdout)
            self.assertEqual(before, fixture.remote_head(), "dry run must never move the remote")
        finally:
            fixture.cleanup()

    def test_a_push_argv_naming_a_different_ref_than_the_declaration_is_rejected(self) -> None:
        """The wrapper cannot be tricked into pushing something other than what it admitted."""
        fixture = FixtureRepo()
        try:
            fixture.advance()
            local_head = _git(["rev-parse", "HEAD"], cwd=fixture.repo).stdout.strip()
            decl = _declaration(recorded_sha=fixture.pre_sha, post_write_sha=local_head)
            decl_path = fixture.dir / "wd-mismatch.json"
            _write_declaration(decl_path, decl)

            result = _run_wrapper(
                decl_path, fixture.repo, Path(tempfile.gettempdir()),
                extra=["--", "git", "push", "origin", "HEAD:refs/heads/a-different-branch"],
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("does not name declared ref", result.stdout + result.stderr)
        finally:
            fixture.cleanup()

    def test_a_missing_declaration_file_refuses_without_reaching_admission(self) -> None:
        fixture = FixtureRepo()
        try:
            result = _run_wrapper(fixture.dir / "does-not-exist.json", fixture.repo,
                                  Path(tempfile.gettempdir()))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("REFUSED", result.stdout + result.stderr)
        finally:
            fixture.cleanup()

    def test_a_missing_write_admission_module_is_a_setup_error_not_a_silent_allow(self) -> None:
        """If the wrapper cannot find the gate it exists to call, it must refuse to proceed."""
        with tempfile.TemporaryDirectory() as isolated:
            decoy = Path(isolated) / "push_with_admission.py"
            decoy.write_text(WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
            fixture = FixtureRepo()
            try:
                decl_path = fixture.dir / "wd.json"
                _write_declaration(decl_path, _declaration())
                result = subprocess.run(
                    [sys.executable, str(decoy), "--declaration", str(decl_path),
                     "--repo", str(fixture.repo)],
                    cwd=tempfile.gettempdir(), capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(pwa.SETUP_ERROR_EXIT, result.returncode)
                self.assertIn("write_admission.py not found beside this wrapper", result.stderr)
            finally:
                fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
