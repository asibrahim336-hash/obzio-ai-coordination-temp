#!/usr/bin/env python3
"""Tests for the seeded defects, the hidden case set and the sealed holdout."""

from __future__ import annotations

import importlib.util
import json
import shutil
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seeded_defects = load("seeded_defects.py", "po03_059_seeded")
apply_to_cohorts = load("apply_to_cohorts.py", "po03_059_apply")
seal_holdout = load("seal_holdout.py", "po03_059_seal")
hidden_cases = load("hidden/hidden_result_cases.py", "po03_059_hidden_cases")
holdout = load("hidden/holdout_custody_cases.py", "po03_059_holdout")

HIDDEN_PATH = HERE / "hidden/hidden_result_cases.py"


class StubInstance:
    """A generation instance with no custody capabilities at all."""

    def __init__(self):
        self.module = object()
        self.module_path = HERE / "hidden/holdout_custody_cases.py"
        self.root = HERE
        self.closed = False

    def close(self):
        self.closed = True


class StubGeneration:
    name = "STUB"

    def __init__(self):
        self.instances = []

    def instance(self):
        created = StubInstance()
        self.instances.append(created)
        return created


class TestSeededDefects(unittest.TestCase):
    def test_defect_ids_are_unique(self):
        ids = [defect["defect_id"] for defect in seeded_defects.SEEDED_DEFECTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 10)

    def test_every_defect_declares_a_hazard(self):
        for defect in seeded_defects.SEEDED_DEFECTS:
            self.assertTrue(defect["hazard"].strip(), defect["defect_id"])
            self.assertNotEqual(defect["old"], defect["new"], defect["defect_id"])

    def test_every_mutation_applies_byte_exactly_to_the_current_tool(self):
        source = (REPO / seeded_defects.TARGET).read_text(encoding="utf-8")
        for defect in seeded_defects.SEEDED_DEFECTS:
            self.assertIn(defect["old"], source, defect["defect_id"])

    def test_sandbox_reports_a_stale_mutation_rather_than_applying_it(self):
        stale = {"defect_id": "D99", "hazard": "stale", "old": "this text is not in the tool", "new": "x"}
        sandbox, applied = seeded_defects.build_sandbox(REPO, stale)
        try:
            self.assertFalse(applied)
            self.assertTrue((sandbox / seeded_defects.TARGET).is_file())
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)


class TestHiddenCasesOnUnmutatedTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox, _ = seeded_defects.build_sandbox(REPO, None)
        cls.module = seeded_defects.load_module(
            cls.sandbox / seeded_defects.TARGET, "po03_059_clean_target"
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.sandbox, ignore_errors=True)

    def test_no_hidden_case_fires_on_the_unmutated_validator(self):
        firing = [name for name, case in hidden_cases.HIDDEN_CASES.items() if case(self.module)]
        self.assertEqual(firing, [])

    def test_control_cases_confirm_valid_documents_are_accepted(self):
        firing = [name for name, case in hidden_cases.CONTROL_CASES.items() if case(self.module)]
        self.assertEqual(firing, [])

    def test_case_ids_are_unique_and_documented(self):
        self.assertEqual(len(hidden_cases.HIDDEN_CASES), len(set(hidden_cases.HIDDEN_CASES)))
        self.assertGreaterEqual(len(hidden_cases.HIDDEN_CASES), 12)


class TestHiddenCasesDetectSeededDefects(unittest.TestCase):
    def detect(self, defect_id: str) -> list[str]:
        defect = next(item for item in seeded_defects.SEEDED_DEFECTS if item["defect_id"] == defect_id)
        sandbox, applied = seeded_defects.build_sandbox(REPO, defect)
        try:
            self.assertTrue(applied, defect_id)
            record = seeded_defects.run_hidden_arm(sandbox, HIDDEN_PATH)
            self.assertEqual(record["control_failures"], [])
            return record["detections"]
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    def test_uppercase_hash_defect_is_detected(self):
        self.assertIn("H-R01-uppercase-sha256-rejected", self.detect("D02-uppercase-hash-accepted"))

    def test_zero_byte_artifact_defect_is_detected(self):
        self.assertIn("H-R02-zero-byte-artifact-rejected", self.detect("D04-zero-byte-artifact-accepted"))

    def test_worker_completion_defect_is_detected(self):
        self.assertIn("H-R06-worker-set-completed-rejected", self.detect("D01-worker-may-set-completed"))

    def test_wave_baseline_hash_defect_is_detected(self):
        self.assertIn(
            "H-R12-wave-bad-baseline-hash-rejected", self.detect("D10-wave-baseline-hash-unchecked")
        )


class TestHoldoutSuite(unittest.TestCase):
    def test_ten_cases_with_unique_ids(self):
        self.assertEqual(len(holdout.HOLDOUT_CASES), 10)
        self.assertEqual(len(set(holdout.HOLDOUT_CASES)), 10)

    def test_every_case_declares_a_hazard_and_public_coverage(self):
        for case_id, spec in holdout.HOLDOUT_CASES.items():
            self.assertTrue(spec["hazard"].strip(), case_id)
            self.assertIsInstance(spec["public_suite_covers"], bool, case_id)
            self.assertTrue(callable(spec["case"]), case_id)

    def test_holdout_is_not_only_a_list_of_expected_failures(self):
        covered = [
            case_id for case_id, spec in holdout.HOLDOUT_CASES.items() if spec["public_suite_covers"]
        ]
        self.assertGreaterEqual(len(covered), 3)

    def test_a_capability_free_generation_yields_unsupported_not_pass(self):
        generation = StubGeneration()
        for case_id, spec in holdout.HOLDOUT_CASES.items():
            record = spec["case"](generation)
            self.assertEqual(record["outcome"], "UNSUPPORTED", case_id)
            self.assertIsNone(record["invariant_held"], case_id)
            self.assertTrue(record["detail"].strip(), case_id)
        self.assertTrue(all(instance.closed for instance in generation.instances))
        self.assertEqual(len(generation.instances), 10)


class TestSeal(unittest.TestCase):
    def test_seal_matches_the_sealed_files(self):
        seal = seal_holdout.build_seal(HERE)
        for entry in seal["files"]:
            payload = (HERE / entry["path"]).read_bytes()
            self.assertEqual(entry["bytes"], len(payload))
        self.assertRegex(seal["combined_sha256"], r"^[0-9a-f]{64}$")

    def test_committed_seal_is_current(self):
        committed = HERE / "holdout-seal.json"
        if not committed.is_file():
            self.skipTest("seal has not been generated yet")
        recorded = json.loads(committed.read_text(encoding="utf-8"))
        recomputed = seal_holdout.build_seal(HERE)
        self.assertEqual(recorded["combined_sha256"], recomputed["combined_sha256"])
        self.assertEqual(
            [entry["sha256"] for entry in recorded["files"]],
            [entry["sha256"] for entry in recomputed["files"]],
        )


class TestCrossCohortApplication(unittest.TestCase):
    def test_own_units_are_excluded_from_the_examined_set(self):
        excluded = ("059-adversarial-hidden-cases",)
        found = apply_to_cohorts.discover_results(REPO, excluded)
        self.assertTrue(all(not record["slot"].endswith(excluded[0]) for record in found))

    def test_findings_are_reported_for_a_non_conforming_result(self):
        validator = apply_to_cohorts.load_validator(REPO)
        record = apply_to_cohorts.check(
            REPO,
            validator,
            {"slot": "workstreams/po03/attempts/does-not-exist", "ref": "refs/heads/none", "commit": "HEAD"},
        )
        self.assertFalse(record["readable"])
        self.assertTrue(record["findings"])


if __name__ == "__main__":
    unittest.main()
