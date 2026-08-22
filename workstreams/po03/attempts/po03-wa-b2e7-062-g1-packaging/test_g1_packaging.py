#!/usr/bin/env python3
"""Tests for the G1 package and the clean-clone runner.

The package's only claim is identity: these bytes are the live factory's bytes.
The runner's only claim is portability: those bytes execute in a checkout that
has none of the author's working state.  Both claims are checked against real
Git objects and real subprocesses rather than against the manifest's own text.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

UNIT = Path(__file__).resolve().parent
PO03 = UNIT.parents[1]
REPO = PO03.parents[1]
FACTORY_PATH = "workstreams/po03/tools/transactional_factory.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = load(UNIT / "package_g1.py", "po03_package_g1_under_test")
runner = load(UNIT / "clean_clone_runner.py", "po03_clean_clone_runner_under_test")
suite = load(
    PO03 / "attempts/po03-wa-b2e7-061-g0-reconstruction/generation_suite.py",
    "po03_generation_suite_for_g1",
)

PACKAGE = UNIT / "g1/transactional_factory.py"
MANIFEST = UNIT / "g1/package-manifest.json"


class ThePackageIsTheLiveFactory(unittest.TestCase):
    def test_the_package_is_byte_exact_with_the_committed_factory_blob(self) -> None:
        blob_id = subprocess.run(
            ("git", "rev-parse", f"HEAD:{FACTORY_PATH}"), cwd=REPO, check=True, capture_output=True, text=True
        ).stdout.strip()
        blob = subprocess.run(
            ("git", "cat-file", "blob", blob_id), cwd=REPO, check=True, capture_output=True
        ).stdout
        self.assertEqual(PACKAGE.read_bytes(), blob)

    def test_the_manifest_digest_matches_the_package_on_disk(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        payload = PACKAGE.read_bytes()
        self.assertEqual(manifest["package"]["sha256"], suite.sha256_bytes(payload))
        self.assertEqual(manifest["package"]["bytes"], len(payload))
        self.assertTrue(manifest["package"]["byte_exact_with_blob"])
        self.assertTrue(manifest["source"]["working_tree_matches_blob"])

    def test_the_manifest_names_the_runtime_dependencies_it_does_not_copy(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        named = {entry["path"] for entry in manifest["runtime_dependencies"]}
        self.assertIn("workstreams/po03/tools/validate_contracts.py", named)
        for entry in manifest["runtime_dependencies"]:
            observed = (REPO / entry["path"]).read_bytes()
            self.assertEqual(entry["sha256"], suite.sha256_bytes(observed), entry["path"])
            self.assertEqual(entry["bytes"], len(observed), entry["path"])

    def test_the_packager_refuses_a_copy_that_is_not_the_blob(self) -> None:
        forged = UNIT / "_forged_package_probe.py"
        try:
            forged.write_bytes(PACKAGE.read_bytes() + b"# tampered\n")
            record = packager.build(REPO, forged, write=False)
            self.assertFalse(record["package"]["byte_exact_with_blob"])
        finally:
            forged.unlink(missing_ok=True)

    def test_the_packager_reports_an_absent_package(self) -> None:
        record = packager.build(REPO, UNIT / "g1/_absent.py", write=False)
        self.assertFalse(record["package"]["present"])
        self.assertFalse(record["package"]["byte_exact_with_blob"])

    def test_the_package_stages_for_the_controller_rather_than_writing_it(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["staged_for_controller_path"], "successor/g1/")
        self.assertFalse((REPO / "successor/g1").exists(), "the controller owns successor/g1/, not this unit")


class ThePackageExecutes(unittest.TestCase):
    def test_the_packaged_cli_runs_under_isolated_python(self) -> None:
        completed = subprocess.run(
            ("python3", "-I", PACKAGE.as_posix(), "--help"), cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for subcommand in ("activate", "ingest", "complete", "recover", "collisions"):
            self.assertIn(subcommand, completed.stdout)

    def test_the_package_exposes_the_capabilities_the_suite_probes(self) -> None:
        generation = suite.Generation("G1PROBE", PACKAGE, REPO, description="probe")
        try:
            instance = generation.instance()
            try:
                for name in (
                    "allocate_fence",
                    "grant_lease",
                    "assert_fence_current",
                    "ingest_result",
                    "complete_unit",
                    "scan_recovery",
                    "detect_path_collisions",
                    "append_registry",
                    "read_object_bytes",
                    "load_result_validator",
                ):
                    self.assertTrue(hasattr(instance.module, name), name)
            finally:
                instance.close()
        finally:
            generation.close()


class TheCleanCloneRunnerIsHonest(unittest.TestCase):
    def test_the_recorded_report_shows_a_clone_of_the_pushed_commit(self) -> None:
        report_path = UNIT / "clean-clone-report.json"
        if not report_path.is_file():
            self.skipTest("clean-clone-report.json is produced by clean_clone_runner.py")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["executable_from_clean_clone"])
        self.assertTrue(report["integrity"]["package_matches_live_factory"])
        self.assertEqual(len(report["clone"]["head"]), 40)
        for step in report["steps"]:
            self.assertEqual(step["exit_code"], 0, step["command"])

    def test_the_report_records_a_failing_step_rather_than_hiding_it(self) -> None:
        record = runner.run(("python3", "-I", "-c", "raise SystemExit(3)"), REPO)
        self.assertEqual(record["exit_code"], 3)
        self.assertIn("command", record)

    def test_a_check_step_raises_on_a_non_zero_exit(self) -> None:
        with self.assertRaises(RuntimeError):
            runner.run(("python3", "-I", "-c", "raise SystemExit(4)"), REPO, check=True)

    def test_digest_in_clone_reports_absence_without_inventing_a_hash(self) -> None:
        record = runner.digest_in_clone(REPO, "workstreams/po03/attempts/_absent_probe.json")
        self.assertFalse(record["present"])
        self.assertNotIn("sha256", record)


class TheMeasurementUsedTheFrozenSuite(unittest.TestCase):
    def test_g1_was_measured_on_the_same_suite_bytes_as_g0(self) -> None:
        g1_path = UNIT / "g1-measurement.json"
        g0_path = PO03 / "attempts/po03-wa-b2e7-061-g0-reconstruction/g0-measurement.json"
        if not g1_path.is_file():
            self.skipTest("g1-measurement.json is produced by clean_clone_runner.py")
        g1 = json.loads(g1_path.read_text(encoding="utf-8"))
        g0 = json.loads(g0_path.read_text(encoding="utf-8"))
        self.assertEqual(
            g1["suite_freeze"]["public_suite_sha256"], g0["suite_freeze"]["public_suite_sha256"]
        )
        self.assertEqual(g1["suite_freeze"]["holdout_sha256"], g0["suite_freeze"]["holdout_sha256"])
        self.assertEqual(
            g1["suite_freeze"]["holdout_seal_combined_sha256"],
            g0["suite_freeze"]["holdout_seal_combined_sha256"],
        )
        self.assertEqual(g1["combined"]["case_count"], g0["combined"]["case_count"])
        self.assertEqual(g1["generation"]["source_sha256"], suite.sha256_bytes(PACKAGE.read_bytes()))

    def test_every_case_in_the_measurement_has_a_recorded_outcome(self) -> None:
        g1_path = UNIT / "g1-measurement.json"
        if not g1_path.is_file():
            self.skipTest("g1-measurement.json is produced by clean_clone_runner.py")
        g1 = json.loads(g1_path.read_text(encoding="utf-8"))
        self.assertEqual(len(g1["records"]), 26)
        for record in g1["records"]:
            self.assertIn(record["outcome"], {"PASS", "FAIL", "UNSUPPORTED"}, record["case_id"])
            self.assertTrue(record["detail"], record["case_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
