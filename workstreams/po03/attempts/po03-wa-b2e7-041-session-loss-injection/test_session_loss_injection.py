"""Reproduction for session loss injected after every state transition.

Hypothesis under test: a worker session lost mid-flight leaves no false
completion and the unit is resumable from immutable input.

Every case here kills a real child worker with SIGKILL after it has reached and
committed the work belonging to one state, then interrogates the unmodified
mechanism.  The last class also checks the consolidated fault matrix that this
unit compiles for the whole cohort.
"""

from __future__ import annotations

import importlib.util
import json
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


kit = _load("po03_c6_041_kit", "fault_kit.py")
injector = _load("po03_c6_041_injector", "session_loss_injector.py")
matrix_tool = _load("po03_c6_041_matrix", "fault_matrix.py")


class SessionLossTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class KillPointTests(SessionLossTestCase):
    def test_the_child_session_really_dies_by_sigkill(self):
        result = injector.inject_session_loss(self.root, "RUNNING")
        self.assertEqual(-9, result["crash"]["returncode"])
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertEqual(
            ["CREATED", "LEASED", "RUNNING"], result["crash"]["child_report"]["reached"]
        )

    def test_loss_before_any_lease_is_classified_for_dispatch(self):
        result = injector.inject_session_loss(self.root, "CREATED")
        observed = result["observed"]
        self.assertEqual(["CREATED"], observed["event_states"])
        self.assertEqual("DISPATCH", observed["recovery_action"])
        self.assertEqual(0, observed["ingestion_records"])
        self.assertEqual("PASS", result["verdict"])

    def test_loss_mid_flight_is_classified_for_resumption_from_immutable_input(self):
        for state in ("LEASED", "RESULT_STAGING", "RESULT_VERIFIED"):
            with self.subTest(kill_after=state):
                result = injector.inject_session_loss(self.root, state)
                observed = result["observed"]
                self.assertEqual(
                    "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT", observed["recovery_action"]
                )
                self.assertTrue(observed["immutable_input_intact"])
                self.assertEqual("PARENT_INGESTED", observed["resumed_state"])
                self.assertEqual([], observed["resumed_errors"])
                self.assertTrue(all(observed["resumed_readback_match"]))

    def test_loss_after_a_durable_commit_still_resumes_to_ingestion(self):
        result = injector.inject_session_loss(self.root, "RESULT_COMMITTED")
        observed = result["observed"]
        self.assertIn("RESULT_COMMITTED", observed["event_states"])
        # The committed result is not replayed; the prescribed action is a rerun.
        # That unreplayed durable work is tracked as DEF-PO03-C6-042.
        self.assertEqual("RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT", observed["recovery_action"])
        self.assertEqual(0, observed["ingestion_records"])
        self.assertEqual("PARENT_INGESTED", observed["resumed_state"])
        self.assertNotEqual(
            result["crash"]["child_report"]["artifact_commit"], observed["resumed_commit"]
        )

    def test_loss_after_ingestion_leaves_the_result_in_custody(self):
        result = injector.inject_session_loss(self.root, "PARENT_INGESTED")
        observed = result["observed"]
        self.assertTrue(observed["ingested_result_survived_the_loss"])
        self.assertEqual(1, observed["ingestion_records"])
        self.assertEqual("AWAIT_COORDINATOR_COMPLETION", observed["recovery_action"])
        self.assertFalse(observed["completed_event_present"])


class NoFalseCompletionTests(SessionLossTestCase):
    def test_no_kill_point_produces_a_completion_event_or_file(self):
        for state in ("CHECKPOINTED", "RESULT_STAGED", "RESULT_COMMITTED", "PARENT_INGESTED"):
            with self.subTest(kill_after=state):
                result = injector.inject_session_loss(self.root, state)
                observed = result["observed"]
                self.assertFalse(observed["completed_event_present"])
                self.assertFalse(observed["completion_file_present"])
                self.assertEqual(0, observed["false_completion_count"])

    def test_completion_is_refused_while_a_lost_session_is_unrecovered(self):
        sandbox = self.root / "refusal"
        task_id = "po03-c6-041-refusal"
        crash = injector.run_child(sandbox, task_id, "RESULT_COMMITTED")
        self.assertTrue(crash["killed_by_sigkill"])
        module = kit.bind_sandbox(kit.load_factory("041_refusal"), sandbox)
        document = kit.build_result_document(
            module,
            task_id=task_id,
            commit=crash["child_report"]["artifact_commit"],
            paths=[crash["child_report"]["artifact_path"]],
            fence_token=crash["child_report"]["fence_token"],
            worker_id="worker-a",
        )
        with self.assertRaises(ValueError) as raised:
            module.complete_unit(task_id, document, reviewer_id="c6-coordinator")
        self.assertIn("cannot complete before PARENT_INGESTED", str(raised.exception))
        self.assertFalse(
            (module.CONTROL_ROOT / "tasks" / task_id / "transaction-completed.json").is_file()
        )
        self.assertEqual(
            0, module.scan_recovery("c6-sandbox", "0" * 40)["false_completion_count"]
        )


class ChainIntegrityTests(SessionLossTestCase):
    def test_the_event_chain_stays_verifiable_after_an_abrupt_loss(self):
        for state in ("RUNNING", "RESULT_STAGED", "RESULT_COMMITTED"):
            with self.subTest(kill_after=state):
                result = injector.inject_session_loss(self.root, state)
                self.assertEqual([], result["observed"]["event_chain_errors"])

    def test_the_immutable_capsule_hash_is_unchanged_by_the_loss(self):
        result = injector.inject_session_loss(self.root, "CHECKPOINTED")
        observed = result["observed"]
        self.assertTrue(observed["immutable_input_intact"])
        self.assertEqual(64, len(observed["immutable_input_sha256"]))


class AggregateTests(SessionLossTestCase):
    def test_every_state_transition_is_covered_with_no_false_completion(self):
        report = injector.inject_all(self.root)
        self.assertEqual(9, report["fault_classes"])
        self.assertEqual(9, len(report["state_transitions_covered"]))
        self.assertEqual(9, report["units_resumable"])
        self.assertEqual(0, report["false_completions_observed"])
        self.assertEqual("PASS", report["verdict"])


class FaultMatrixTests(unittest.TestCase):
    def setUp(self):
        self.matrix = matrix_tool.build_matrix()

    def test_the_matrix_covers_all_eight_cohort_units(self):
        self.assertEqual(8, len(self.matrix["units"]))
        covered = {row["source_unit"] for row in self.matrix["rows"]}
        self.assertEqual(set(self.matrix["units"]), covered)

    def test_every_row_names_a_fault_class_a_transition_and_a_verdict(self):
        for row in self.matrix["rows"]:
            with self.subTest(fault_class=row["fault_class"]):
                self.assertTrue(row["fault_class"])
                self.assertTrue(row["injected_at_state_transition"])
                self.assertTrue(row["observed_behaviour"])
                self.assertIn(row["verdict"], ("PASS", "FAIL", "OBSERVATION_ONLY"))

    def test_the_matrix_records_zero_false_completions(self):
        self.assertEqual(0, self.matrix["false_completions_observed"])

    def test_every_failing_unit_has_a_defect_record_with_a_repair_candidate(self):
        failing = {
            unit for unit, verdict in self.matrix["unit_verdicts"].items() if verdict == "FAIL"
        }
        recorded = {defect["source_unit"] for defect in self.matrix["defects"]}
        self.assertEqual(failing, recorded)
        for defect in self.matrix["defects"]:
            with self.subTest(defect=defect["defect_id"]):
                path = matrix_tool.REPO_ROOT / defect["repair_candidate"]
                self.assertTrue(path.is_file(), defect["repair_candidate"])
                self.assertFalse(defect["adopted_by_live_mechanism"])

    def test_each_source_hash_matches_the_bytes_on_disk(self):
        for source in self.matrix["sources"]:
            with self.subTest(path=source["path"]):
                body = (matrix_tool.REPO_ROOT / source["path"]).read_bytes()
                self.assertEqual(source["bytes"], len(body))
                self.assertEqual(source["sha256"], matrix_tool.hashlib.sha256(body).hexdigest())

    def test_the_written_matrix_still_matches_a_fresh_compilation(self):
        written = HERE / "recovery-fault-matrix.json"
        if not written.is_file():
            self.skipTest("matrix has not been written yet")
        stored = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(self.matrix["rows"], stored["rows"])
        self.assertEqual(self.matrix["defects"], stored["defects"])
        self.assertEqual(self.matrix["unit_verdicts"], stored["unit_verdicts"])

    def test_the_matrix_claims_only_readiness_to_commit(self):
        self.assertEqual("READY_TO_COMMIT", self.matrix["obzio_state_claim"])
        self.assertTrue(self.matrix["producer_may_not_accept_own_work"])


if __name__ == "__main__":
    unittest.main()
