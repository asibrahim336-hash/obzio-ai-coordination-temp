#!/usr/bin/env python3
"""Tests for the G0 reconstruction and the frozen public suite.

Two things need to be true before any generation number means anything.  The
baseline must be the real pre-amendment source, and the suite must score a
missing capability as not-passed rather than skipping it.  Both are tested here
against the actual committed bytes.
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
HOLDOUT = PO03 / "attempts/po03-wa-b2e7-059-adversarial-hidden-cases/hidden/holdout_custody_cases.py"
SEAL = PO03 / "attempts/po03-wa-b2e7-059-adversarial-hidden-cases/holdout-seal.json"
BASELINE_COMMIT = "2b48869"
FACTORY_PATH = "workstreams/po03/tools/transactional_factory.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suite = load(UNIT / "generation_suite.py", "po03_generation_suite_under_test")
reconstruct = load(UNIT / "reconstruct_g0.py", "po03_reconstruct_g0_under_test")

G0_SOURCE = UNIT / "g0/transactional_factory_g0.py"


class G0IsTheRealPreAmendmentSource(unittest.TestCase):
    def test_the_committed_copy_is_byte_exact_with_the_immutable_blob(self) -> None:
        completed = subprocess.run(
            ("git", "cat-file", "blob", f"{BASELINE_COMMIT}:{FACTORY_PATH}"),
            cwd=REPO,
            check=True,
            capture_output=True,
        )
        self.assertEqual(G0_SOURCE.read_bytes(), completed.stdout)

    def test_reconstruction_reports_byte_exact_and_names_the_blob(self) -> None:
        record = reconstruct.reconstruct(REPO, G0_SOURCE)
        self.assertTrue(record["committed_copy"]["byte_exact"])
        self.assertIsNone(record["committed_copy"]["first_difference_offset"])
        self.assertEqual(len(record["reconstructed"]["git_blob_id"]), 40)
        self.assertEqual(record["reconstructed"]["source_sha256"], record["committed_copy"]["sha256"])

    def test_reconstruction_refuses_a_copy_that_is_not_the_baseline(self) -> None:
        forged = UNIT / "_forged_g0_probe.py"
        try:
            forged.write_bytes(G0_SOURCE.read_bytes() + b"# tampered\n")
            record = reconstruct.reconstruct(REPO, forged)
            self.assertFalse(record["committed_copy"]["byte_exact"])
        finally:
            forged.unlink(missing_ok=True)

    def test_the_extension_surface_is_absent_from_g0_and_present_in_the_current_factory(self) -> None:
        record = reconstruct.reconstruct(REPO, G0_SOURCE)
        added = set(record["surface"]["added_after_g0"])
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
            self.assertIn(name, added, f"{name} should be an extension added after G0")
        self.assertEqual(record["surface"]["removed_after_g0"], [])

    def test_the_baseline_commit_predates_the_amendment_commit(self) -> None:
        record = reconstruct.reconstruct(REPO, G0_SOURCE)
        self.assertNotEqual(
            record["baseline_commit"]["blob_id"], record["amendment_commit"]["blob_id"]
        )
        self.assertEqual(
            record["current_factory"]["blob_id"], record["amendment_commit"]["blob_id"]
        )


class ThePublicSuiteIsWellFormed(unittest.TestCase):
    def test_sixteen_uniquely_named_callable_cases(self) -> None:
        self.assertEqual(len(suite.PUBLIC_SUITE), 16)
        self.assertEqual(len(set(suite.PUBLIC_SUITE)), 16)
        for case_id, spec in suite.PUBLIC_SUITE.items():
            self.assertTrue(callable(spec["case"]), case_id)

    def test_case_ids_are_ordered_and_prefixed(self) -> None:
        prefixes = [case_id.split("-", 1)[0] for case_id in suite.PUBLIC_SUITE]
        self.assertEqual(prefixes, [f"P{index:02d}" for index in range(1, 17)])

    def test_the_holdout_is_loaded_from_the_sealed_file_and_the_seal_matches(self) -> None:
        freeze = suite.suite_freeze(HOLDOUT, SEAL)
        self.assertTrue(freeze["holdout_seal_matches_file"])
        self.assertEqual(freeze["public_case_count"], 16)
        self.assertEqual(len(freeze["public_suite_sha256"]), 64)


class ScoringCountsUnsupportedAsNotPassed(unittest.TestCase):
    def test_pass_rate_denominator_includes_unsupported_cases(self) -> None:
        records = [
            {"outcome": "PASS", "reports_success": False, "invariant_held": True},
            {"outcome": "UNSUPPORTED", "reports_success": None, "invariant_held": None},
            {"outcome": "UNSUPPORTED", "reports_success": None, "invariant_held": None},
            {"outcome": "FAIL", "reports_success": True, "invariant_held": False},
        ]
        scored = suite.score(records)
        self.assertEqual(scored["case_count"], 4)
        self.assertEqual(scored["passed"], 1)
        self.assertEqual(scored["unsupported"], 2)
        self.assertEqual(scored["pass_rate"], 0.25)

    def test_false_green_counts_only_cases_that_reported_success_while_broken(self) -> None:
        records = [
            {"outcome": "FAIL", "reports_success": True, "invariant_held": False},
            {"outcome": "FAIL", "reports_success": False, "invariant_held": False},
            {"outcome": "PASS", "reports_success": False, "invariant_held": True},
        ]
        scored = suite.score(records)
        self.assertEqual(scored["reported_success_count"], 1)
        self.assertEqual(scored["false_green_count"], 1)
        self.assertEqual(scored["false_green_rate"], 1.0)

    def test_no_reported_success_yields_a_zero_false_green_rate(self) -> None:
        scored = suite.score([{"outcome": "UNSUPPORTED", "reports_success": None, "invariant_held": None}])
        self.assertEqual(scored["false_green_rate"], 0.0)
        self.assertIsNotNone(scored["pass_rate"])


class TheSandboxIsARealRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generation = suite.Generation("G0PROBE", G0_SOURCE, REPO, description="probe")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.generation.close()

    def test_committed_bytes_are_readable_back_by_object_id(self) -> None:
        instance = self.generation.instance()
        try:
            commit = instance.commit_bytes("workstreams/po03/attempts/probe/artifact.txt", b"probe\n")
            self.assertEqual(len(commit), 40)
            shown = subprocess.run(
                ("git", "cat-file", "blob", f"{commit}:workstreams/po03/attempts/probe/artifact.txt"),
                cwd=instance.root,
                check=True,
                capture_output=True,
            )
            self.assertEqual(shown.stdout, b"probe\n")
        finally:
            instance.close()

    def test_each_instance_gets_an_independent_module_and_root(self) -> None:
        first = self.generation.instance()
        second = self.generation.instance()
        try:
            self.assertNotEqual(first.root, second.root)
            self.assertIsNot(first.module, second.module)
            first.module.write_once(first.root / "workstreams/po03/control/probe.json", b"{}\n")
            self.assertFalse((second.root / "workstreams/po03/control/probe.json").exists())
        finally:
            first.close()
            second.close()

    def test_the_skeleton_the_suite_depends_on_is_present(self) -> None:
        instance = self.generation.instance()
        try:
            for relative in suite.SKELETON_SOURCES:
                self.assertTrue((instance.root / relative).is_file(), relative)
        finally:
            instance.close()


class TheSuiteScoresG0AsMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generation = suite.Generation("G0CASES", G0_SOURCE, REPO, description="probe")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.generation.close()

    def test_a_primitive_g0_has_scores_pass(self) -> None:
        record = suite.PUBLIC_SUITE["P02-write-once-rejects-divergent-rewrite"]["case"](self.generation)
        self.assertEqual(record["outcome"], "PASS")
        self.assertTrue(record["invariant_held"])

    def test_a_capability_g0_lacks_scores_unsupported_and_names_it(self) -> None:
        record = suite.PUBLIC_SUITE["P07-fence-allocation-is-monotonic"]["case"](self.generation)
        self.assertEqual(record["outcome"], "UNSUPPORTED")
        self.assertIn("allocate_fence", record["detail"])
        self.assertIsNone(record["invariant_held"])

    def test_every_case_returns_the_recorded_outcome_shape(self) -> None:
        for case_id in ("P01-capsule-creation-is-immutable", "P09-contract-rejects-worker-set-completion"):
            record = suite.PUBLIC_SUITE[case_id]["case"](self.generation)
            self.assertIn(record["outcome"], {"PASS", "FAIL", "UNSUPPORTED"}, case_id)
            self.assertIsInstance(record["detail"], str)
            self.assertTrue(record["detail"], case_id)


class TheRecordedMeasurementMatchesTheCommittedSuite(unittest.TestCase):
    def test_the_measurement_document_names_the_suite_bytes_on_disk(self) -> None:
        measurement = UNIT / "g0-measurement.json"
        if not measurement.is_file():
            self.skipTest("g0-measurement.json is produced by run_generation.py")
        payload = json.loads(measurement.read_text(encoding="utf-8"))
        freeze = payload["suite_freeze"]
        self.assertEqual(
            freeze["public_suite_sha256"],
            suite.sha256_bytes((UNIT / "generation_suite.py").read_bytes()),
            "the recorded measurement was produced by different suite bytes than are committed",
        )
        self.assertEqual(freeze["holdout_sha256"], suite.sha256_bytes(HOLDOUT.read_bytes()))
        self.assertTrue(freeze["holdout_seal_matches_file"])
        self.assertEqual(payload["generation"]["source_sha256"], suite.sha256_bytes(G0_SOURCE.read_bytes()))
        self.assertEqual(payload["combined"]["case_count"], 26)
        self.assertEqual(payload["combined"]["passed"] + payload["combined"]["failed"]
                         + payload["combined"]["unsupported"], 26)


if __name__ == "__main__":
    unittest.main(verbosity=2)
