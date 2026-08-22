#!/usr/bin/env python3
"""Executable regression tests for the PO-03 path-scope adversarial review.

These tests are dependency-free and can be run from a clean clone with:

    python3 -I -m unittest discover \
      -s workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review/tests \
      -p 'test_*.py' -v

They deliberately do not repair the shared guard. Where the guard's observed
behaviour contradicts the PO-03 collision boundary, the test records that
behaviour as a characterisation so that any later repair flips a visible
assertion instead of passing silently.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SLOT.parents[4]
GUARD = REPO_ROOT / "workstreams" / "po03" / "tools" / "check_path_scope.py"
HIDDEN_CASES = SLOT / "hidden-cases.json"
OBSERVED_RESULTS = SLOT / "observed-results.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  (sibling module, loaded after sys.path setup)
import generate_cases  # noqa: E402


def load_guard():
    spec = importlib.util.spec_from_file_location("po03_guard_under_test", GUARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FrozenCaseSetTests(unittest.TestCase):
    def test_hidden_cases_match_their_generator(self):
        expected = generate_cases.render(generate_cases.build())
        self.assertEqual(
            expected,
            HIDDEN_CASES.read_text(encoding="utf-8"),
            "hidden-cases.json drifted from tests/generate_cases.py",
        )

    def test_case_set_covers_every_required_status_class(self):
        document = json.loads(HIDDEN_CASES.read_text(encoding="utf-8"))
        classes = {case["status_class"] for case in document["git_cases"]}
        for required in ("M", "A", "D", "R", "C", "T"):
            self.assertIn(required, classes, f"no git case exercises status class {required}")


class AllowlistFalsePositiveTests(unittest.TestCase):
    """In-allowlist work must never be blocked."""

    def setUp(self):
        self.guard = load_guard()
        self.document = json.loads(HIDDEN_CASES.read_text(encoding="utf-8"))

    def test_positive_controls_are_allowed(self):
        blocked = []
        for case in self.document["path_cases"]:
            if case["commission_requirement"] != "ALLOW":
                continue
            path = harness.decode(case["path_hex"])
            if self.guard.violations([path]):
                blocked.append((case["case_id"], case["path_display"]))
        self.assertEqual([], blocked, "guard rejected sanctioned in-allowlist paths")


class ReadOnlyEstateTests(unittest.TestCase):
    """Out-of-allowlist paths must be rejected as pure string inputs."""

    def setUp(self):
        self.guard = load_guard()
        self.document = json.loads(HIDDEN_CASES.read_text(encoding="utf-8"))

    def _divergences(self) -> set[str]:
        return {
            case["case_id"]
            for case in self.document["path_cases"]
            if case["commission_requirement"] == "REJECT"
            and case["predicted_guard_disposition"] == "ALLOW"
        }

    def test_rejects_every_out_of_allowlist_path_except_recorded_divergences(self):
        divergences = self._divergences()
        leaked = []
        for case in self.document["path_cases"]:
            if case["commission_requirement"] != "REJECT":
                continue
            if case["case_id"] in divergences:
                continue
            path = harness.decode(case["path_hex"])
            if not self.guard.violations([path]):
                leaked.append((case["case_id"], case["path_display"]))
        self.assertEqual([], leaked, "guard allowed protected paths")

    def test_recorded_divergences_still_diverge(self):
        """Characterisation: these paths violate the commission glob but the guard admits them.

        A repair of the workflow-name rule must invert this assertion.
        """
        for case_id in sorted(self._divergences()):
            case = next(c for c in self.document["path_cases"] if c["case_id"] == case_id)
            path = harness.decode(case["path_hex"])
            self.assertEqual(
                [],
                self.guard.violations([path]),
                f"{case_id} no longer diverges; update the divergence record",
            )


class RenameReportingTests(unittest.TestCase):
    """Characterise how the guard treats the source side of a detected rename."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="po03-043-unittest-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _repo(self, case_id: str) -> Path:
        document = json.loads(HIDDEN_CASES.read_text(encoding="utf-8"))
        case = next(c for c in document["git_cases"] if c["case_id"] == case_id)
        return harness.build_repository(self.root, case), case

    def _guard(self, repo: Path, base: str, head: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(GUARD), "--base", base, "--head", head],
            cwd=str(repo),
            capture_output=True,
            env={**os.environ, **harness.FIXED_ENV},
        )

    def test_rename_out_of_allowlist_into_allowlist_is_not_reported(self):
        """Characterisation of the headline defect.

        Renaming a protected file into the PO-03 subtree deletes the protected
        path, yet the guard exits zero because ``git diff --name-only`` prints
        only the rename destination. A repair must make this exit non-zero.
        """
        repo, case = self._repo("GIT-010")
        completed = self._guard(repo, case["base_ref"], case["head_ref"])
        self.assertEqual(
            0,
            completed.returncode,
            "GIT-010 now fails the guard; the rename-source defect appears repaired",
        )
        head_tree = subprocess.run(
            ("git", "ls-tree", "-r", "--name-only", "HEAD"),
            cwd=str(repo),
            capture_output=True,
            check=True,
            env={**os.environ, **harness.FIXED_ENV},
        ).stdout.decode()
        self.assertNotIn(
            "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            head_tree,
            "fixture did not actually remove the protected path",
        )

    def test_same_mutation_below_rename_threshold_is_reported(self):
        repo, case = self._repo("GIT-013")
        completed = self._guard(repo, case["base_ref"], case["head_ref"])
        self.assertEqual(1, completed.returncode)
        self.assertIn(
            "PO03_PATH_SCOPE_VIOLATION: state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            completed.stderr.decode(),
        )

    def test_rename_into_out_of_allowlist_destination_is_reported(self):
        repo, case = self._repo("GIT-009")
        completed = self._guard(repo, case["base_ref"], case["head_ref"])
        self.assertEqual(1, completed.returncode)


class ReproducibilityTests(unittest.TestCase):
    """A fresh harness run must reproduce the committed evidence."""

    @unittest.skipUnless(OBSERVED_RESULTS.exists(), "observed-results.json not yet committed")
    def test_harness_reproduces_committed_observed_results(self):
        committed = json.loads(OBSERVED_RESULTS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="po03-043-repro-") as tmp:
            out = Path(tmp) / "observed-results.json"
            self.assertEqual(0, harness.main(["--out", str(out)]))
            fresh = json.loads(out.read_text(encoding="utf-8"))
        for key in ("summary", "path_results", "git_results"):
            self.assertEqual(
                committed[key],
                fresh[key],
                f"{key} is not reproducible from the committed harness",
            )


if __name__ == "__main__":
    unittest.main()
