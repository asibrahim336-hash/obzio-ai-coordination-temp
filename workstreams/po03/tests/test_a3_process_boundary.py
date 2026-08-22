"""Unit a3-u08: every entry point runs as a separate process, cleanly.

The acceptance turns on the harness being able to tell in-process success from
subprocess success.  Both directions are proved here with real cases:

* a planted fixture that reads a variable at module scope succeeds when imported
  into a parent that has it set and fails as a command with a constructed
  environment -- an in-process-only assumption;
* ``make_result`` is the reverse, working as a command but not drivable
  in-process because its ``main()`` takes no argv.

A harness that only ever ran one of the two would report whichever it happened
to use and prove nothing about portability.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
HARNESS_PATH = RUNTIME_DIR / "process_boundary.py"
MANIFEST_PATH = RUNTIME_DIR / "entry-points.json"
PLANTED_ENTRY = "workstreams/po03/runtime/fixtures/process_boundary/env_dependent_entry.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load_module(HARNESS_PATH, "po03_process_boundary")
MANIFEST = harness.load_manifest(MANIFEST_PATH)


class EveryEntryPointRunsAsACommand(unittest.TestCase):
    def setUp(self) -> None:
        self.report = harness.run_harness(MANIFEST)

    def test_every_declared_invocation_passes_as_a_subprocess(self) -> None:
        failing = [record for record in self.report["results"] if record["verdict"] == "FAIL"]
        detail = json.dumps(failing, indent=2)
        self.assertEqual(self.report["verdict"], "PASS", detail)
        self.assertEqual(self.report["failing_invocations"], [], detail)

    def test_the_child_inherits_nothing(self) -> None:
        self.assertEqual(self.report["inherited_variables"], 0)
        self.assertEqual(
            self.report["child_environment_keys"], ["HOME", "LC_ALL", "PATH", "TMPDIR"]
        )

    def test_every_committed_entry_point_is_declared(self) -> None:
        """A harness that misses an entry point silently proves less than it claims."""
        declared = {entry["path"] for entry in MANIFEST["entry_points"]}
        tracked = subprocess.run(
            ["git", "ls-files", "workstreams/po03/tools", "workstreams/po03/runtime"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        executable_modules = set()
        for path in tracked:
            parts = Path(path).parts
            if not path.endswith(".py") or "fixtures" in parts or "__pycache__" in parts:
                continue
            if '__name__ == "__main__"' in (REPO_ROOT / path).read_text(encoding="utf-8"):
                executable_modules.add(path)
        self.assertEqual(executable_modules - declared, set())

    def test_declared_entry_points_all_exist(self) -> None:
        for entry in MANIFEST["entry_points"]:
            self.assertTrue((REPO_ROOT / entry["path"]).is_file(), entry["path"])


class HarnessDistinguishesTheTwoModes(unittest.TestCase):
    def build_manifest(self, scratch: Path) -> Path:
        manifest = {
            "schema": "po03-entry-points-v1",
            "entry_points": [
                {
                    "id": "planted_env_dependent",
                    "path": PLANTED_ENTRY,
                    "owner": "po03-worker-a3",
                    "invocations": [
                        {"name": "run", "args": [], "expected_exit_code": 0}
                    ],
                }
            ],
        }
        path = scratch / "planted-entry-points.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_planted_in_process_only_assumption_is_detected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="po03-a3-u08-") as scratch:
            manifest = harness.load_manifest(self.build_manifest(Path(scratch)))
            token = {"PO03_BOUNDARY_TOKEN": "present-in-this-process-only"}
            with mock.patch.dict(os.environ, token):
                with contextlib.redirect_stdout(io.StringIO()):
                    report = harness.run_harness(manifest, compare=True)

        record = report["results"][0]
        self.assertNotEqual(record["subprocess_exit_code"], 0, record)
        self.assertEqual(record["in_process_exit_code"], 0, record)
        self.assertTrue(record["in_process_only_success"], record)
        self.assertEqual(report["in_process_only_successes"], ["planted_env_dependent:run"])
        self.assertEqual(report["verdict"], "FAIL")

    def test_the_planted_fixture_is_not_a_declared_entry_point(self) -> None:
        declared = {entry["path"] for entry in MANIFEST["entry_points"]}
        self.assertNotIn(PLANTED_ENTRY, declared)

    def test_subprocess_only_success_is_reported_for_make_result(self) -> None:
        """The reverse direction, observed on a real coordinator-owned tool."""
        with contextlib.redirect_stdout(io.StringIO()):
            report = harness.run_harness(MANIFEST, compare=True)
        self.assertIn("make_result:help", report["subprocess_only_successes"])
        self.assertEqual(report["in_process_only_successes"], [])
        self.assertEqual(report["verdict"], "PASS")


class RecordedBoundaries(unittest.TestCase):
    def test_boundaries_are_recorded_with_evidence(self) -> None:
        boundaries = MANIFEST["recorded_boundaries"]
        self.assertGreaterEqual(len(boundaries), 4)
        for boundary in boundaries:
            self.assertTrue(boundary["statement"].strip())
            self.assertTrue(boundary["observed_in"].strip())
            self.assertIn(boundary["disposition"], {"RECORDED_AS_BOUNDARY", "RECORDED_AND_FIXED"})

    def prepare_probe(self, scratch: Path) -> dict[str, str]:
        """A module and a loader that reaches it by path, plus a constructed environment."""
        (scratch / "probe_module.py").write_text("value = 1\n", encoding="utf-8")
        (scratch / "loader.py").write_text(
            "import importlib.util, pathlib\n"
            'target = pathlib.Path(__file__).with_name("probe_module.py")\n'
            'spec = importlib.util.spec_from_file_location("probe_module", target)\n'
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n",
            encoding="utf-8",
        )
        (scratch / "sibling_importer.py").write_text("import probe_module\n", encoding="utf-8")
        environment = dict(harness.clean_environment(scratch))
        (scratch / "home").mkdir(exist_ok=True)
        (scratch / "tmp").mkdir(exist_ok=True)
        return environment

    def test_isolated_mode_ignores_python_environment_variables(self) -> None:
        """Reproduces PO03-BOUNDARY-001 rather than only asserting it was written down."""
        with tempfile.TemporaryDirectory(prefix="po03-a3-u08-pyc-") as raw:
            scratch = Path(raw)
            environment = self.prepare_probe(scratch)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            subprocess.run(
                [sys.executable, "-I", "loader.py"],
                cwd=scratch,
                env=environment,
                capture_output=True,
                check=True,
            )
            self.assertTrue(
                list(scratch.glob("__pycache__/*.pyc")),
                "PYTHONDONTWRITEBYTECODE appeared to work under -I, contradicting the record",
            )

    def test_isolated_mode_drops_the_script_directory(self) -> None:
        """Reproduces PO03-BOUNDARY-004, which -B alone does not cure."""
        with tempfile.TemporaryDirectory(prefix="po03-a3-u08-path-") as raw:
            scratch = Path(raw)
            environment = self.prepare_probe(scratch)
            sibling = subprocess.run(
                [sys.executable, "-I", "-B", "sibling_importer.py"],
                cwd=scratch,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(sibling.returncode, 0, sibling.stdout + sibling.stderr)
            self.assertIn("No module named 'probe_module'", sibling.stderr)

            by_path = subprocess.run(
                [sys.executable, "-I", "-B", "loader.py"],
                cwd=scratch,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(by_path.returncode, 0, by_path.stdout + by_path.stderr)

    def test_po03_is_not_an_importable_package(self) -> None:
        """Reproduces PO03-BOUNDARY-002."""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-m", "unittest", "workstreams.po03.tests.test_a3_process_boundary"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named", result.stdout + result.stderr)


class CommandLineBehaviour(unittest.TestCase):
    def run_harness_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(HARNESS_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_harness_exits_zero_on_the_real_tree(self) -> None:
        result = self.run_harness_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("in separate processes with 0 inherited variables", result.stdout)

    def test_json_report_shape(self) -> None:
        result = self.run_harness_cli("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-process-boundary-report-v1")
        self.assertGreaterEqual(report["invocations_run"], report["entry_points_declared"])
        self.assertEqual(report["verdict"], "PASS")

    def test_bad_manifest_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "manifest.json"
            bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
            result = self.run_harness_cli("--manifest", str(bad))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("PROCESS_BOUNDARY_ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main()
