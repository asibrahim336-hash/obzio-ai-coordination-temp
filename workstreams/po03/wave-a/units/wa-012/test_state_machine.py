import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_DIR = Path(__file__).resolve().parent
MODULE_PATH = UNIT_DIR / "state_machine.py"
SPEC = importlib.util.spec_from_file_location("wa012_state_machine", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SOURCE_SPEC = importlib.util.spec_from_file_location(
    "wa012_compile_source_capsule",
    UNIT_DIR / "compile_source_capsule.py",
)
SOURCE_MODULE = importlib.util.module_from_spec(SOURCE_SPEC)
assert SOURCE_SPEC.loader is not None
sys.modules[SOURCE_SPEC.name] = SOURCE_MODULE
SOURCE_SPEC.loader.exec_module(SOURCE_MODULE)

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "wa012_verify_artifacts",
    UNIT_DIR / "verify_artifacts.py",
)
VERIFY_MODULE = importlib.util.module_from_spec(VERIFY_SPEC)
assert VERIFY_SPEC.loader is not None
sys.modules[VERIFY_SPEC.name] = VERIFY_MODULE
VERIFY_SPEC.loader.exec_module(VERIFY_MODULE)

H = "a" * 64
C = "b" * 40


def snapshot(state="LEASED", fence=2, checkpoint=0, evidence=None):
    value = {
        "state": state,
        "current_fence": fence,
        "checkpoint_seq": checkpoint,
        "producer_id": "producer-1",
    }
    if evidence is not None:
        value["evidence"] = evidence
    return MODULE.MachineSnapshot.from_document(value)


def event(source, target, actor="worker:producer-1", fence=2, **extra):
    return {
        "from_state": source,
        "to_state": target,
        "actor": actor,
        "fence_token": fence,
        **extra,
    }


class TransitionRejectionTests(unittest.TestCase):
    def assert_rejected(self, current, attempted, code):
        before = current.as_dict()
        with self.assertRaises(MODULE.TransitionRejected) as raised:
            MODULE.apply_transition(current, attempted)
        self.assertEqual(code, raised.exception.code)
        self.assertEqual(before, current.as_dict(), "rejection mutated the input snapshot")

    def test_skipped_transition_is_rejected(self):
        self.assert_rejected(
            snapshot("RUNNING"),
            event("RUNNING", "RESULT_STAGED"),
            "ILLEGAL_TRANSITION",
        )

    def test_regressive_transition_is_rejected(self):
        self.assert_rejected(
            snapshot("RESULT_VERIFIED"),
            event("RESULT_VERIFIED", "RESULT_STAGED"),
            "ILLEGAL_TRANSITION",
        )

    def test_worker_cannot_set_completed(self):
        self.assert_rejected(
            snapshot("PARENT_INGESTED"),
            event("PARENT_INGESTED", "COMPLETED"),
            "ACTOR_NOT_AUTHORIZED",
        )

    def test_provider_observation_cannot_advance_state(self):
        self.assert_rejected(
            snapshot("PARENT_INGESTED"),
            event(
                "PARENT_INGESTED",
                "COMPLETED",
                actor="provider:runtime-sanitized",
            ),
            "ACTOR_NOT_AUTHORIZED",
        )

    def test_stale_fence_after_transfer_is_rejected(self):
        self.assert_rejected(
            snapshot("LEASED", fence=3),
            event("LEASED", "RUNNING", fence=2),
            "STALE_FENCE",
        )

    def test_ungranted_future_fence_is_rejected(self):
        self.assert_rejected(
            snapshot("LEASED", fence=3),
            event("LEASED", "RUNNING", fence=4),
            "FUTURE_FENCE",
        )

    def test_checkpoint_must_increase(self):
        self.assert_rejected(
            snapshot("CHECKPOINTED", checkpoint=4),
            event(
                "CHECKPOINTED",
                "CHECKPOINTED",
                checkpoint_seq=4,
            ),
            "CHECKPOINT_REGRESSION",
        )

    def test_wrong_worker_cannot_use_current_lease(self):
        self.assert_rejected(
            snapshot("LEASED"),
            event("LEASED", "RUNNING", actor="worker:producer-2"),
            "WORKER_IDENTITY_MISMATCH",
        )

    def test_commit_requires_verified_manifest_evidence(self):
        self.assert_rejected(
            snapshot("RESULT_VERIFIED"),
            event(
                "RESULT_VERIFIED",
                "RESULT_COMMITTED",
                result_commit_id=C,
                remote_branch="cursor/sanitized",
            ),
            "VERIFICATION_EVIDENCE_REQUIRED",
        )

    def test_producer_cannot_self_review(self):
        complete_evidence = {
            "manifest_verified": True,
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 1,
            "result_commit_id": C,
            "remote_branch": "cursor/sanitized",
            "immutable_readback_verified": True,
            "ingestion_receipt": "receipt:sanitized",
        }
        self.assert_rejected(
            snapshot("COMPLETED", evidence=complete_evidence),
            event(
                "COMPLETED",
                "ACCEPTED",
                actor="reviewer:producer-1",
            ),
            "PRODUCER_SELF_REVIEW",
        )


class LifecycleTests(unittest.TestCase):
    def test_valid_full_lifecycle_requires_distinct_roles_and_evidence(self):
        current = snapshot("CREATED", fence=1)
        events = [
            event("CREATED", "LEASED", "controller:control-1", 1),
            event("LEASED", "RUNNING", fence=1),
            event("RUNNING", "CHECKPOINTED", fence=1, checkpoint_seq=1),
            event("CHECKPOINTED", "RESULT_STAGING", fence=1),
            event("RESULT_STAGING", "RESULT_STAGED", fence=1),
            event(
                "RESULT_STAGED",
                "RESULT_VERIFIED",
                "verifier:verification-1",
                1,
                manifest_sha256=H,
                artifact_count=2,
                total_bytes=10,
            ),
            event(
                "RESULT_VERIFIED",
                "RESULT_COMMITTED",
                fence=1,
                result_commit_id=C,
                remote_branch="cursor/sanitized",
            ),
            event(
                "RESULT_COMMITTED",
                "PARENT_INGESTED",
                "coordinator:control-1",
                1,
                immutable_readback_verified=True,
                ingestion_receipt="receipt:sanitized",
            ),
            event(
                "PARENT_INGESTED",
                "COMPLETED",
                "coordinator:control-1",
                1,
            ),
            event(
                "COMPLETED",
                "ACCEPTED",
                "reviewer:independent-1",
                1,
            ),
        ]
        for item in events:
            current = MODULE.apply_transition(current, item)
        self.assertEqual("ACCEPTED", current.state)
        self.assertTrue(current.evidence["immutable_readback_verified"])

    def test_checkpoint_sequence_advances_monotonically(self):
        current = MODULE.apply_transition(
            snapshot("RUNNING", checkpoint=2),
            event(
                "RUNNING",
                "CHECKPOINTED",
                checkpoint_seq=3,
            ),
        )
        self.assertEqual(3, current.checkpoint_seq)

    def test_completed_requires_custody_evidence_even_for_coordinator(self):
        current = snapshot("PARENT_INGESTED")
        with self.assertRaises(MODULE.TransitionRejected) as raised:
            MODULE.apply_transition(
                current,
                event(
                    "PARENT_INGESTED",
                    "COMPLETED",
                    actor="coordinator:control-1",
                ),
            )
        self.assertEqual("COMPLETION_EVIDENCE_REQUIRED", raised.exception.code)


class ArtifactAndReproductionTests(unittest.TestCase):
    def test_frozen_matrix_matches_executable_matrix(self):
        frozen = json.loads(
            (UNIT_DIR / "transition-matrix.json").read_text(encoding="utf-8")
        )
        self.assertEqual(MODULE.matrix_document(), frozen)

    def test_sanitized_reproduction_matches_all_expectations(self):
        fixture = json.loads(
            (UNIT_DIR / "fixtures" / "sanitized-obzio-reproduction.json").read_text(
                encoding="utf-8"
            )
        )
        result = MODULE.run_reproduction(fixture)
        self.assertEqual(5, result["summary"]["case_count"])
        self.assertEqual(5, result["summary"]["matched_count"])
        self.assertTrue(result["summary"]["all_expectations_matched"])
        self.assertEqual("SUPPORTED", result["hypothesis_outcome"])

    def test_reproduction_detects_an_incorrect_expectation(self):
        fixture = json.loads(
            (UNIT_DIR / "fixtures" / "sanitized-obzio-reproduction.json").read_text(
                encoding="utf-8"
            )
        )
        mutated = copy.deepcopy(fixture)
        mutated["cases"][1]["expected"]["error_code"] = "STALE_FENCE"
        result = MODULE.run_reproduction(mutated)
        self.assertFalse(result["summary"]["all_expectations_matched"])
        self.assertEqual("REFUTED", result["hypothesis_outcome"])

    def test_cli_reproduction_writes_independently_checkable_output(self):
        fixture = UNIT_DIR / "fixtures" / "sanitized-obzio-reproduction.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "observed.json"
            exit_code = MODULE.main(
                ["reproduce", str(fixture), "--output", str(output)]
            )
            observed = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0, exit_code)
        self.assertTrue(observed["summary"]["all_expectations_matched"])

    def test_source_capsule_recompiles_from_pinned_commit(self):
        repo = UNIT_DIR.parents[4]
        expected = json.loads(
            (UNIT_DIR / "source-capsule.json").read_text(encoding="utf-8")
        )
        observed = SOURCE_MODULE.compile_capsule(repo)
        self.assertEqual(expected, observed)
        self.assertTrue(observed["all_declared_pins_match"])
        self.assertEqual(25, observed["source_count"])

    def test_complete_artifact_manifest_verifies(self):
        manifest = json.loads(
            (UNIT_DIR / "artifact-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], VERIFY_MODULE.verify(UNIT_DIR, manifest))

    def test_artifact_manifest_detects_one_tamper(self):
        manifest = json.loads(
            (UNIT_DIR / "artifact-manifest.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "wa-012"
            shutil.copytree(
                UNIT_DIR,
                copy,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            target = copy / "transition-matrix.json"
            target.write_bytes(target.read_bytes() + b"\n")
            errors = VERIFY_MODULE.verify(copy, manifest)
        self.assertTrue(any("transition-matrix.json" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
