"""Custody invariants for the PO-03 transactional factory.

These tests hold the line the lost PO-02 Code-2 return crossed: a provider
callback must never become an Obzio completion, a superseded worker must never
commit, and a replayed callback must never double-count.
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "transactional_factory.py"
SPEC = importlib.util.spec_from_file_location("transactional_factory_custody", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

VALIDATOR_SOURCE = Path(__file__).parents[1] / "tools" / "validate_contracts.py"
H = "a" * 64


class CustodyTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.originals = {
            name: getattr(MODULE, name)
            for name in ("REPO_ROOT", "PO03_ROOT", "CONTROL_ROOT", "RECEIPT_ROOT")
        }
        self.addCleanup(self._restore_roots)

        self.repository = Path(self.temporary.name) / "repository"
        po03 = self.repository / "workstreams" / "po03"
        (po03 / "contracts").mkdir(parents=True)
        (po03 / "tools").mkdir(parents=True)
        (po03 / "COMMISSION.md").write_text("commission\n", encoding="utf-8")
        (po03 / "contracts" / "transactional-result.schema.json").write_text("{}\n", encoding="utf-8")
        (po03 / "tools" / "validate_contracts.py").write_bytes(VALIDATOR_SOURCE.read_bytes())

        MODULE.REPO_ROOT = self.repository
        MODULE.PO03_ROOT = po03
        MODULE.CONTROL_ROOT = po03 / "control"
        MODULE.RECEIPT_ROOT = self.repository / "receipts" / "po03" / "2026-08-22"
        MODULE.CONTROL_ROOT.mkdir(parents=True, exist_ok=True)

    def _restore_roots(self):
        for name, value in self.originals.items():
            setattr(MODULE, name, value)

    def _git(self, *arguments):
        return subprocess.run(
            ("git", *arguments),
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _init_repository_with_artifact(self, body: bytes):
        self._git("init", "--quiet")
        self._git("config", "user.email", "po03@obzio.invalid")
        self._git("config", "user.name", "PO-03 Test")
        artifact = self.repository / "workstreams" / "po03" / "attempts" / "unit" / "result.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(body)
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "po03: test artifact")
        return self._git("rev-parse", "HEAD")

    def _result_document(self, *, commit, sha256, size, fence_token=1, worker_id="producer-1"):
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "po03-unit-001",
            "commission_id": MODULE.COMMISSION_ID,
            "immutable_input_manifest_sha256": H,
            "acceptance_contract_sha256": H,
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": "po03-unit-001-attempt-1",
                "idempotency_key": "po03-unit-001:1",
                "lease_id": "lease-po03-unit-001-1",
                "fence_token": fence_token,
                "provider_run_id": "provider-run-1",
                "worker_id": worker_id,
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 2,
            },
            "result_transaction": {
                "result_txn_id": "result-po03-unit-001-1",
                "state": "COMMITTED",
                "manifest_uri": f"git:{commit}:workstreams/po03/attempts/unit/result.json",
                "manifest_sha256": sha256,
                "artifact_count": 1,
                "total_bytes": size,
                "committed_at": "2026-08-22T07:01:00Z",
                "verified_at": "2026-08-22T07:02:00Z",
                "parent_ingested_at": None,
                "result_commit_id": commit,
            },
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "logical_name": "result.json",
                    "content_uri": f"git:{commit}:workstreams/po03/attempts/unit/result.json",
                    "sha256": sha256,
                    "bytes": size,
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T07:02:00Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }


class FenceAndLeaseTests(CustodyTestCase):
    def test_fence_tokens_are_strictly_monotonic(self):
        tokens = [MODULE.allocate_fence() for _ in range(5)]
        self.assertEqual([1, 2, 3, 4, 5], tokens)

    def test_lease_transfer_advances_the_fence(self):
        first = MODULE.grant_lease("po03-unit-001", holder="worker-a", lease_seconds=60, attempt=1)
        second = MODULE.grant_lease("po03-unit-001", holder="worker-b", lease_seconds=60, attempt=2)
        self.assertLess(first["fence_token"], second["fence_token"])
        self.assertEqual(second["fence_token"], MODULE.current_fence("po03-unit-001"))

    def test_superseded_worker_cannot_commit(self):
        MODULE.grant_lease("po03-unit-001", holder="worker-a", lease_seconds=60, attempt=1)
        MODULE.grant_lease("po03-unit-001", holder="worker-b", lease_seconds=60, attempt=2)
        with self.assertRaises(MODULE.StaleFenceError):
            MODULE.assert_fence_current("po03-unit-001", 1)
        MODULE.assert_fence_current("po03-unit-001", 2)

    def test_unleased_task_accepts_any_fence(self):
        MODULE.assert_fence_current("po03-unknown", 1)


class IngestionTests(CustodyTestCase):
    def test_matching_artifact_is_ingested(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        MODULE.grant_lease("po03-unit-001", holder="producer-1", lease_seconds=60, attempt=1)
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertEqual([], ingestion["errors"])
        self.assertEqual("PARENT_INGESTED", ingestion["obzio_state"])
        self.assertTrue(ingestion["artifact_readback"][0]["match"])

    def test_corrupt_artifact_hash_is_refused(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(commit=commit, sha256="b" * 64, size=len(body))
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertEqual("RECOVERY_REQUIRED", ingestion["obzio_state"])
        self.assertTrue(any("read-back mismatch" in error for error in ingestion["errors"]))

    def test_missing_artifact_object_is_refused(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        document["artifacts"][0]["content_uri"] = f"git:{commit}:workstreams/po03/attempts/unit/absent.json"
        document["result_transaction"]["manifest_uri"] = document["artifacts"][0]["content_uri"]
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertEqual("RECOVERY_REQUIRED", ingestion["obzio_state"])
        self.assertTrue(any("read-back failed" in error for error in ingestion["errors"]))

    def test_non_git_locator_is_not_durable(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        document["artifacts"][0]["content_uri"] = "file:///tmp/result.json"
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertTrue(any("non-durable" in error for error in ingestion["errors"]))

    def test_stale_worker_result_is_refused(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        MODULE.grant_lease("po03-unit-001", holder="worker-a", lease_seconds=60, attempt=1)
        MODULE.grant_lease("po03-unit-001", holder="worker-b", lease_seconds=60, attempt=2)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body), fence_token=1
        )
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertEqual("RECOVERY_REQUIRED", ingestion["obzio_state"])
        self.assertTrue(any("stale" in error for error in ingestion["errors"]))

    def test_duplicate_callback_is_harmless(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        MODULE.grant_lease("po03-unit-001", holder="producer-1", lease_seconds=60, attempt=1)
        MODULE.ingest_result("po03-unit-001", document)
        registry = MODULE.CONTROL_ROOT / "work-unit-registry.jsonl"
        first_lines = registry.read_text(encoding="utf-8").count("\n")
        second = MODULE.ingest_result("po03-unit-001", document)
        self.assertTrue(second.get("duplicate_callback_suppressed"))
        self.assertEqual(first_lines, registry.read_text(encoding="utf-8").count("\n"))

    def test_result_without_artifacts_cannot_be_ingested(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        document["artifacts"] = []
        document["result_transaction"]["artifact_count"] = 0
        document["result_transaction"]["total_bytes"] = 0
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        self.assertEqual("RECOVERY_REQUIRED", ingestion["obzio_state"])


class CompletionTests(CustodyTestCase):
    def _ingested_document(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        MODULE.grant_lease("po03-unit-001", holder="producer-1", lease_seconds=60, attempt=1)
        return document

    def test_completion_before_ingestion_is_impossible(self):
        document = self._ingested_document()
        with self.assertRaises(ValueError):
            MODULE.complete_unit("po03-unit-001", document)

    def test_coordinator_stamps_parent_ingestion_itself(self):
        document = self._ingested_document()
        ingestion = MODULE.ingest_result("po03-unit-001", document)
        completed = MODULE.complete_unit("po03-unit-001", document)
        self.assertEqual(
            ingestion["ingested_at"], completed["result_transaction"]["parent_ingested_at"]
        )

    def test_producer_supplied_parent_ingestion_is_refused(self):
        document = self._ingested_document()
        MODULE.ingest_result("po03-unit-001", document)
        forged = json.loads(json.dumps(document))
        forged["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:03:00Z"
        with self.assertRaises(ValueError):
            MODULE.complete_unit("po03-unit-001", forged)

    def test_completion_requires_a_matching_ingestion_record(self):
        document = self._ingested_document()
        MODULE.ingest_result("po03-unit-001", document)
        divergent = json.loads(json.dumps(document))
        divergent["attempt"]["checkpoint_seq"] = 99
        with self.assertRaises(ValueError):
            MODULE.complete_unit("po03-unit-001", divergent)

    def test_completion_of_a_failed_ingestion_is_refused(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(commit=commit, sha256="b" * 64, size=len(body))
        MODULE.grant_lease("po03-unit-001", holder="producer-1", lease_seconds=60, attempt=1)
        MODULE.ingest_result("po03-unit-001", document)
        MODULE.hash_chain_event("po03-unit-001", "PARENT_INGESTED", actor="test", details={})
        with self.assertRaises(ValueError):
            MODULE.complete_unit("po03-unit-001", document)

    def test_coordinator_completion_passes_the_seeded_contract(self):
        document = self._ingested_document()
        MODULE.ingest_result("po03-unit-001", document)
        completed = MODULE.complete_unit("po03-unit-001", document, reviewer_id="reviewer-2")
        self.assertEqual("COMPLETED", completed["obzio_state"])
        self.assertEqual("coordinator", completed["completion_actor"])
        self.assertEqual("PENDING", completed["independent_acceptance"]["state"])
        validator = MODULE.load_result_validator()
        self.assertEqual([], validator.validate_result(completed))

    def test_completion_never_self_accepts(self):
        document = self._ingested_document()
        MODULE.ingest_result("po03-unit-001", document)
        completed = MODULE.complete_unit("po03-unit-001", document, reviewer_id="producer-1")
        self.assertNotEqual("ACCEPTED", completed["independent_acceptance"]["state"])


class DispositionTests(CustodyTestCase):
    def _completed_unit(self):
        body = b'{"unit":"po03-unit-001"}\n'
        commit = self._init_repository_with_artifact(body)
        document = self._result_document(
            commit=commit, sha256=MODULE.sha256_bytes(body), size=len(body)
        )
        MODULE.grant_lease("po03-unit-001", holder="producer-1", lease_seconds=60, attempt=1)
        MODULE.ingest_result("po03-unit-001", document)
        MODULE.complete_unit("po03-unit-001", document, reviewer_id="reviewer-2")

    def test_disposition_before_completion_is_impossible(self):
        with self.assertRaises(ValueError):
            MODULE.dispose_unit(
                "po03-unit-001",
                reviewer_id="reviewer-2",
                decision="ACCEPTED",
                receipt_uri="git:receipt.json",
                criteria_sha256=H,
                reviewer_model="gpt-5.6-sol-xhigh",
                notes="",
            )

    def test_producer_cannot_render_its_own_disposition(self):
        self._completed_unit()
        with self.assertRaises(ValueError):
            MODULE.dispose_unit(
                "po03-unit-001",
                reviewer_id="producer-1",
                decision="ACCEPTED",
                receipt_uri="git:receipt.json",
                criteria_sha256=H,
                reviewer_model="gpt-5.6-sol-xhigh",
                notes="",
            )

    def test_independent_reviewer_disposition_is_recorded(self):
        self._completed_unit()
        disposed = MODULE.dispose_unit(
            "po03-unit-001",
            reviewer_id="reviewer-2",
            decision="ACCEPTED",
            receipt_uri="git:receipt.json",
            criteria_sha256=H,
            reviewer_model="gpt-5.6-sol-xhigh",
            notes="criteria frozen before producer conclusions",
        )
        self.assertEqual("ACCEPTED", disposed["independent_acceptance"]["state"])
        self.assertEqual("reviewer-2", disposed["independent_acceptance"]["reviewer_id"])
        self.assertEqual([], MODULE.verify_chain("po03-unit-001"))

    def test_rejection_is_a_valid_disposition(self):
        self._completed_unit()
        disposed = MODULE.dispose_unit(
            "po03-unit-001",
            reviewer_id="reviewer-3",
            decision="REJECTED",
            receipt_uri="git:receipt.json",
            criteria_sha256=H,
            reviewer_model="claude-sonnet-5-thinking-xhigh",
            notes="hidden case failed",
        )
        self.assertEqual("REJECTED", disposed["independent_acceptance"]["state"])

    def test_unfrozen_criteria_hash_is_refused(self):
        self._completed_unit()
        with self.assertRaises(ValueError):
            MODULE.dispose_unit(
                "po03-unit-001",
                reviewer_id="reviewer-2",
                decision="ACCEPTED",
                receipt_uri="git:receipt.json",
                criteria_sha256="not-a-hash",
                reviewer_model="gpt-5.6-sol-xhigh",
                notes="",
            )


class RecoveryAndCollisionTests(CustodyTestCase):
    def test_recovery_scan_marks_created_units_for_dispatch(self):
        MODULE.task_capsule(
            task_id="po03-unit-002",
            head_sha="a" * 40,
            run_id="bc-test",
            model="gpt-5.6-sol-xhigh",
            reasoning="xhigh",
            hypothesis="a unit with no result requires redispatch",
            prompt="do the work",
            owned_paths=["workstreams/po03/attempts/unit-002/**"],
            result_slot="workstreams/po03/attempts/unit-002",
            acceptance={"criteria": ["x"], "decision_changed": []},
            lease_seconds=60,
            fence_token=1,
            function="wave-a-work-unit",
        )
        state = MODULE.scan_recovery("bc-test", "a" * 40)
        self.assertEqual("DISPATCH", state["units"]["po03-unit-002"]["recovery_action"])
        self.assertEqual(0, state["false_completion_count"])

    def test_recovery_scan_detects_completion_without_ingestion(self):
        MODULE.task_capsule(
            task_id="po03-unit-003",
            head_sha="a" * 40,
            run_id="bc-test",
            model="gpt-5.6-sol-xhigh",
            reasoning="xhigh",
            hypothesis="a forged completion must be visible",
            prompt="do the work",
            owned_paths=["workstreams/po03/attempts/unit-003/**"],
            result_slot="workstreams/po03/attempts/unit-003",
            acceptance={"criteria": ["x"], "decision_changed": []},
            lease_seconds=60,
            fence_token=1,
            function="wave-a-work-unit",
        )
        forged = MODULE.CONTROL_ROOT / "tasks" / "po03-unit-003" / "transaction-completed.json"
        MODULE.write_once(forged, MODULE.canonical_json({"obzio_state": "COMPLETED"}))
        state = MODULE.scan_recovery("bc-test", "a" * 40)
        self.assertEqual(1, state["false_completion_count"])

    def test_overlapping_owned_subtrees_fail_closed(self):
        MODULE.replace_atomic(
            MODULE.CONTROL_ROOT / "path-ownership.json",
            MODULE.canonical_json(
                {
                    "ownership_version": "PO03-PATH-OWNERSHIP-v1",
                    "controller": {"run_id": "bc-test", "owned_paths": []},
                    "subordinates": [
                        {"task_id": "unit-a", "owned_paths": ["workstreams/po03/attempts/shared/**"]},
                        {"task_id": "unit-b", "owned_paths": ["workstreams/po03/attempts/shared/inner/**"]},
                    ],
                    "collision_policy": "FAIL_CLOSED",
                }
            ),
        )
        self.assertTrue(MODULE.detect_path_collisions())

    def test_disjoint_owned_subtrees_pass(self):
        MODULE.replace_atomic(
            MODULE.CONTROL_ROOT / "path-ownership.json",
            MODULE.canonical_json(
                {
                    "ownership_version": "PO03-PATH-OWNERSHIP-v1",
                    "controller": {"run_id": "bc-test", "owned_paths": []},
                    "subordinates": [
                        {"task_id": "unit-a", "owned_paths": ["workstreams/po03/attempts/a/**"]},
                        {"task_id": "unit-b", "owned_paths": ["workstreams/po03/attempts/b/**"]},
                    ],
                    "collision_policy": "FAIL_CLOSED",
                }
            ),
        )
        self.assertEqual([], MODULE.detect_path_collisions())


class CrossControllerLeaseTests(CustodyTestCase):
    """Two controllers inheriting one capsule must not both own the result slot.

    Regression cover for the observed collision on po03-canary-001, where a local
    fence token could not arbitrate because both controllers read the same frozen
    token from identical immutable bytes.
    """

    def setUp(self):
        super().setUp()
        root = Path(self.temporary.name)
        self.remote = root / "remote.git"
        subprocess.run(("git", "init", "--bare", "--quiet", str(self.remote)), check=True)
        self.controllers = {}
        for name in ("alpha", "beta"):
            path = root / name
            path.mkdir()
            subprocess.run(("git", "init", "--quiet"), cwd=path, check=True)
            for key, value in (("user.email", "po03@obzio.invalid"), ("user.name", "PO-03 Test")):
                subprocess.run(("git", "config", key, value), cwd=path, check=True)
            subprocess.run(("git", "remote", "add", "origin", str(self.remote)), cwd=path, check=True)
            self.controllers[name] = path

    def _as(self, name):
        MODULE.REPO_ROOT = self.controllers[name]

    def test_first_controller_acquires_and_second_is_refused(self):
        self._as("alpha")
        first = MODULE.acquire_remote_lease("po03-canary-001", "bc-alpha")
        self.assertEqual("ACQUIRED", first["state"])

        self._as("beta")
        second = MODULE.acquire_remote_lease("po03-canary-001", "bc-beta")
        self.assertEqual("REFUSED", second["state"])
        self.assertEqual("bc-alpha", second["owner"])

    def test_reacquisition_by_the_owner_is_idempotent(self):
        self._as("alpha")
        MODULE.acquire_remote_lease("po03-canary-001", "bc-alpha")
        again = MODULE.acquire_remote_lease("po03-canary-001", "bc-alpha")
        self.assertEqual("OWNED", again["state"])
        self.assertEqual("bc-alpha", again["owner"])

    def test_publishing_without_ownership_is_refused(self):
        self._as("alpha")
        MODULE.acquire_remote_lease("po03-unit-900", "bc-alpha")
        MODULE.assert_remote_ownership("po03-unit-900", "bc-alpha")

        self._as("beta")
        with self.assertRaises(MODULE.StaleFenceError):
            MODULE.assert_remote_ownership("po03-unit-900", "bc-beta")

    def test_unclaimed_slot_is_refused_until_claimed(self):
        self._as("alpha")
        with self.assertRaises(MODULE.StaleFenceError):
            MODULE.assert_remote_ownership("po03-unit-901", "bc-alpha")
        MODULE.acquire_remote_lease("po03-unit-901", "bc-alpha")
        MODULE.assert_remote_ownership("po03-unit-901", "bc-alpha")

    def test_distinct_tasks_do_not_contend(self):
        self._as("alpha")
        self.assertEqual("ACQUIRED", MODULE.acquire_remote_lease("po03-unit-902", "bc-alpha")["state"])
        self._as("beta")
        self.assertEqual("ACQUIRED", MODULE.acquire_remote_lease("po03-unit-903", "bc-beta")["state"])


class RegistryTests(CustodyTestCase):
    def test_registry_is_append_only(self):
        MODULE.append_registry({"registry_event": "CREATED", "task_id": "po03-unit-004"})
        MODULE.append_registry({"registry_event": "INGESTION", "task_id": "po03-unit-004"})
        lines = [
            json.loads(line)
            for line in (MODULE.CONTROL_ROOT / "work-unit-registry.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(["CREATED", "INGESTION"], [row["registry_event"] for row in lines])

    def test_registry_write_outside_allowlist_is_rejected(self):
        MODULE.CONTROL_ROOT = self.repository / "state" / "control"
        with self.assertRaises(ValueError):
            MODULE.append_registry({"registry_event": "CREATED", "task_id": "escape"})


if __name__ == "__main__":
    unittest.main()
