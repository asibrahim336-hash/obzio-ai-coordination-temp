"""Reproduction for the push-boundary failure classes.

Hypothesis under test: a failure before or after push is distinguishable and
recoverable, and a pushed-but-unreported result is not lost.

Assertions describe the observed behaviour of the unmodified mechanism across a
real bare remote, a producer clone and a separate controller clone.  Nothing is
relaxed to obtain a pass; where the mechanism misses the bar the test says so.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_044_kit", "fault_kit.py")
injector = _load("po03_c6_044_injector", "push_boundary_injector.py")
repair = _load("po03_c6_044_repair", "repair_candidate_remote_recovery.py")


class PushBoundaryTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class ObservedBehaviourTests(PushBoundaryTestCase):
    def test_pre_push_failure_is_refused_and_leaves_no_false_completion(self):
        result = injector.inject_pre_push_failure(self.root)
        self.assertFalse(result["observed"]["commit_present_on_remote"])
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["ingestion_state"])
        self.assertEqual(0, result["observed"]["false_completion_count"])
        self.assertEqual(53, result["observed"]["producer_local_bytes"])
        self.assertTrue(result["observed"]["producer_local_bytes_match_committed"])

    def test_pushed_result_is_recovered_when_the_controller_has_fetched(self):
        result = injector.inject_post_push_controller_fetched(self.root)
        self.assertEqual(0, result["observed"]["push_returncode"])
        self.assertEqual("PARENT_INGESTED", result["observed"]["ingestion_state"])
        self.assertEqual([], result["observed"]["ingestion_errors"])
        self.assertTrue(all(result["observed"]["artifact_readback_match"]))
        self.assertTrue(result["observed"]["scanner_sees_ingested_result"])
        self.assertEqual("PASS", result["verdict"])

    def test_pushed_result_is_not_recovered_when_the_controller_has_not_fetched(self):
        result = injector.inject_post_push_controller_not_fetched(self.root)
        self.assertTrue(result["observed"]["commit_present_on_remote"])
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["ingestion_state"])
        self.assertFalse(result["observed"]["mechanism_attempted_a_fetch"])
        self.assertEqual("FAIL", result["verdict"])
        self.assertEqual(0, result["observed"]["false_completion_count"])

    def test_pre_and_post_push_failures_are_indistinguishable_to_the_mechanism(self):
        report = injector.inject_all(self.root)
        self.assertEqual(
            report["pre_push_error_signature"], report["post_push_unfetched_error_signature"]
        )
        self.assertFalse(report["pre_and_post_push_failures_distinguishable_by_the_mechanism"])
        self.assertEqual("FAIL", report["verdict"])

    def test_rejected_non_fast_forward_push_preserves_the_competing_commit(self):
        result = injector.inject_rejected_non_fast_forward_push(self.root)
        self.assertNotEqual(0, result["observed"]["push_returncode"])
        self.assertTrue(result["observed"]["push_rejected"])
        self.assertTrue(result["observed"]["remote_tip_is_competitor_commit"])
        self.assertTrue(result["observed"]["producer_bytes_intact_locally"])
        self.assertEqual(0, result["observed"]["false_completion_count"])

    def test_no_push_fault_class_produces_a_false_completion(self):
        report = injector.inject_all(self.root)
        self.assertEqual(0, report["false_completions_observed"])


class RepairCandidateTests(PushBoundaryTestCase):
    def _unfetched_context(self, task_id: str):
        context = injector.stage(self.root / task_id, task_id)
        committed = injector.producer_commits(context)
        kit.git(context["producer"], "push", "--quiet", "origin", injector.BRANCH)
        document = kit.build_result_document_from_bytes(
            context["module"],
            task_id=task_id,
            commit=committed["commit"],
            bodies={committed["path"]: committed["body"]},
            fence_token=context["fence_token"],
            worker_id="worker-a",
        )
        return context, committed, document

    def test_candidate_classifies_a_pushed_but_unfetched_result(self):
        context, committed, _ = self._unfetched_context("po03-c6-044-classify-pushed")
        classification = repair.classify_missing_result(
            context["module"], str(context["remote"]), committed["commit"]
        )
        self.assertEqual(repair.PRESENT_ON_REMOTE_NOT_FETCHED, classification)

    def test_candidate_classifies_a_result_that_was_never_pushed(self):
        task_id = "po03-c6-044-classify-unpushed"
        context = injector.stage(self.root / task_id, task_id)
        committed = injector.producer_commits(context)
        classification = repair.classify_missing_result(
            context["module"], str(context["remote"]), committed["commit"]
        )
        self.assertEqual(repair.ABSENT_EVERYWHERE, classification)

    def test_candidate_recovers_the_pushed_result_from_the_remote(self):
        context, _, document = self._unfetched_context("po03-c6-044-recover-pushed")
        recovery = repair.recover_from_remote(
            context["module"], "po03-c6-044-recover-pushed", document, str(context["remote"])
        )
        self.assertEqual(repair.PRESENT_ON_REMOTE_NOT_FETCHED, recovery["classification"])
        self.assertEqual("PARENT_INGESTED", recovery["obzio_state"])
        self.assertEqual([], recovery["errors"])

    def test_candidate_refuses_to_ingest_a_result_that_is_absent_everywhere(self):
        task_id = "po03-c6-044-absent"
        context = injector.stage(self.root / task_id, task_id)
        committed = injector.producer_commits(context)
        document = kit.build_result_document_from_bytes(
            context["module"],
            task_id=task_id,
            commit=committed["commit"],
            bodies={committed["path"]: committed["body"]},
            fence_token=context["fence_token"],
            worker_id="worker-a",
        )
        recovery = repair.recover_from_remote(
            context["module"], task_id, document, str(context["remote"])
        )
        self.assertEqual(repair.ABSENT_EVERYWHERE, recovery["classification"])
        self.assertIsNone(recovery["ingestion"])

    def test_candidate_never_completes_a_unit(self):
        context, _, document = self._unfetched_context("po03-c6-044-no-completion")
        repair.recover_from_remote(
            context["module"], "po03-c6-044-no-completion", document, str(context["remote"])
        )
        task_directory = context["module"].CONTROL_ROOT / "tasks" / "po03-c6-044-no-completion"
        self.assertFalse((task_directory / "transaction-completed.json").is_file())


if __name__ == "__main__":
    unittest.main()
