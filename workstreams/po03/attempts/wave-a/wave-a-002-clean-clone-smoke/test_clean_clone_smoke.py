#!/usr/bin/env python3
"""Tests for the dependency-free clean-clone smoke harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "po03_clean_clone_smoke",
    ROOT / "clean_clone_smoke.py",
)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class CleanCloneSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._git("config", "user.name", "PO-03 Fixture")
        self._git("config", "user.email", "po03-fixture@example.invalid")

    def _git(self, *arguments: str) -> str:
        return subprocess.run(
            ("git", *arguments),
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _commit(self, message: str = "freeze fixture") -> str:
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", message)
        return self._git("rev-parse", "HEAD")

    def test_clean_synthetic_suite_runs_in_fresh_clone(self) -> None:
        tests = self.repository / "tests"
        tests.mkdir()
        (tests / "test_fixture.py").write_text(
            "import unittest\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_standard_library_execution(self):\n"
            "        self.assertEqual(4, 2 + 2)\n",
            encoding="utf-8",
        )
        commit = self._commit()

        result = smoke.run_clean_clone_smoke(
            self.repository,
            commit,
            test_start_dir="tests",
            timeout_seconds=30,
        )

        self.assertEqual("PASS", result["outcome"])
        self.assertEqual(commit, result["revision_commit"])
        self.assertEqual([], result["post_run_checkout_state"])
        self.assertEqual(0, result["returncode"])
        self.assertIn("Ran 1 test", result["stderr"])
        self.assertEqual(["-I", "-S", "-B"], result["runtime_isolation"]["python_flags"])

    def test_frozen_hidden_state_fixtures_are_rejected(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "hidden-checkout-state.json").read_text(
                encoding="utf-8"
            )
        )
        for case in fixture["cases"]:
            with self.subTest(case=case["case_id"]):
                case_repository = Path(self.temporary.name) / case["case_id"]
                subprocess.run(
                    ("git", "init", "--quiet", str(case_repository)),
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ("git", "config", "user.name", "PO-03 Fixture"),
                    cwd=case_repository,
                    check=True,
                )
                subprocess.run(
                    (
                        "git",
                        "config",
                        "user.email",
                        "po03-fixture@example.invalid",
                    ),
                    cwd=case_repository,
                    check=True,
                )
                tracked = case_repository / "tracked.txt"
                tracked.write_text("immutable\n", encoding="utf-8")
                gitignore = case.get("gitignore")
                if gitignore is not None:
                    (case_repository / ".gitignore").write_text(
                        gitignore,
                        encoding="utf-8",
                    )
                subprocess.run(
                    ("git", "add", "-A"),
                    cwd=case_repository,
                    check=True,
                )
                subprocess.run(
                    ("git", "commit", "--quiet", "-m", "freeze fixture"),
                    cwd=case_repository,
                    check=True,
                )
                hidden = case_repository / case["hidden_path"]
                hidden.parent.mkdir(parents=True, exist_ok=True)
                hidden.write_text("provider-local-state\n", encoding="utf-8")

                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.assert_clean_checkout(case_repository, case["phase"])

                self.assertEqual(case["expected_code"], caught.exception.code)
                self.assertEqual(case["phase"], caught.exception.details["phase"])
                self.assertTrue(
                    any(
                        case["expected_entry_fragment"] in entry
                        for entry in caught.exception.details["entries"]
                    )
                )

    def test_nonportable_test_selector_is_rejected(self) -> None:
        (self.repository / "tracked.txt").write_text("immutable\n", encoding="utf-8")
        commit = self._commit()
        with self.assertRaises(smoke.SmokeFailure) as caught:
            smoke.run_clean_clone_smoke(
                self.repository,
                commit,
                test_start_dir="../outside",
            )
        self.assertEqual("NON_PORTABLE_TEST_SELECTOR", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
