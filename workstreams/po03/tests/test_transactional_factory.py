import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "tools" / "transactional_factory.py"
SPEC = importlib.util.spec_from_file_location("transactional_factory", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TransactionalFactoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.originals = {
            name: getattr(MODULE, name)
            for name in ("REPO_ROOT", "PO03_ROOT", "CONTROL_ROOT", "RECEIPT_ROOT")
        }
        self.addCleanup(self._restore_roots)
        repository = Path(self.temporary.name) / "repository"
        po03 = repository / "workstreams" / "po03"
        (po03 / "contracts").mkdir(parents=True)
        (po03 / "tools").mkdir()
        (po03 / "COMMISSION.md").write_text("commission\n", encoding="utf-8")
        (po03 / "contracts" / "transactional-result.schema.json").write_text("{}\n", encoding="utf-8")
        validator = MODULE_PATH.with_name("validate_contracts.py").read_text(encoding="utf-8")
        (po03 / "tools" / "validate_contracts.py").write_text(validator, encoding="utf-8")
        MODULE.REPO_ROOT = repository
        MODULE.PO03_ROOT = po03
        MODULE.CONTROL_ROOT = po03 / "control"
        MODULE.RECEIPT_ROOT = repository / "receipts" / "po03" / "2026-08-22"

    def _restore_roots(self):
        for name, value in self.originals.items():
            setattr(MODULE, name, value)

    def _create_task(self):
        return MODULE.task_capsule(
            task_id="po03-test-task",
            head_sha="a" * 40,
            run_id="bc-test",
            model="gpt-5.6-sol-xhigh-fast",
            reasoning="xhigh",
            hypothesis="A committed canary remains byte-identical after read-back.",
            prompt="Write and verify a canary.",
            owned_paths=["workstreams/po03/attempts/test/**"],
            result_slot="workstreams/po03/attempts/test",
            acceptance={"criteria": ["read back exact bytes"], "decision_changed": []},
            lease_seconds=300,
            fence_token=1,
            nonce="b" * 64,
        )

    def _git(self, *arguments):
        return subprocess.run(
            ("git", *arguments),
            cwd=MODULE.REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _committed_ready_result(
        self,
        *,
        include_scope_escape=False,
        source_manifest=False,
        review_manifest=False,
    ):
        if source_manifest and review_manifest:
            raise ValueError("test manifest dialects are mutually exclusive")
        self._create_task()
        MODULE.advance_task(
            "po03-test-task",
            state="LEASED",
            actor="integration-controller",
            fence_token=1,
            details={"worker_id": "worker-1", "provider_run_id": "reservation-1"},
        )
        MODULE.advance_task(
            "po03-test-task",
            state="RUNNING",
            actor="worker-1",
            fence_token=1,
            details={"provider_task_id": "provider-task-1", "worker_agent_id": "agent-1"},
        )
        self._git("init")
        self._git("config", "user.name", "PO-03 Test")
        self._git("config", "user.email", "po03-test@example.invalid")
        self._git("add", "-A")
        self._git("commit", "-m", "freeze task custody")
        base_commit = self._git("rev-parse", "HEAD")

        result_root = MODULE.REPO_ROOT / "workstreams" / "po03" / "attempts" / "test"
        result_root.mkdir(parents=True)
        artifact_path = "empty.txt" if source_manifest else "result.json"
        artifact_bytes = b"" if source_manifest else b'{"outcome":"ready"}\n'
        (result_root / artifact_path).write_bytes(artifact_bytes)
        artifact = {
            "path": artifact_path,
            "sha256": MODULE.sha256_bytes(artifact_bytes),
            "bytes": len(artifact_bytes),
        }
        if source_manifest:
            artifact["git_blob_sha"] = hashlib.sha1(
                b"blob " + str(len(artifact_bytes)).encode("ascii") + b"\0" + artifact_bytes
            ).hexdigest()
            manifest = {
                "manifest_version": "PO03-ATTEMPT-MANIFEST-v1",
                "task_id": "po03-test-task",
                "unit_root": "workstreams/po03/attempts/test",
                "self_excluded": "manifest.json",
                "sources": [artifact],
                "decision_changed": [],
            }
        elif review_manifest:
            manifest = {
                "manifest_version": "PO03-WAVE-A-TEST-MANIFEST-v1",
                "task_id": "po03-test-task",
                "result_slot": "workstreams/po03/attempts/test",
                "artifact_count": 1,
                "total_bytes": len(artifact_bytes),
                "artifacts": [
                    {
                        "logical_name": artifact_path,
                        "repository_path": (
                            f"workstreams/po03/attempts/test/{artifact_path}"
                        ),
                        "sha256": artifact["sha256"],
                        "bytes": artifact["bytes"],
                    }
                ],
                "decision_changed": [],
            }
        else:
            manifest = {
                "task_id": "po03-test-task",
                "result_slot": "workstreams/po03/attempts/test",
                "artifact_count": 1,
                "total_artifact_bytes_excluding_manifest": len(artifact_bytes),
                "artifacts": [artifact],
            }
        (result_root / "manifest.json").write_bytes(MODULE.canonical_json(manifest))
        if include_scope_escape:
            escaped = MODULE.REPO_ROOT / "state" / "scope-escape.json"
            escaped.parent.mkdir()
            escaped.write_text("{}\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "produce immutable result")
        return base_commit, self._git("rev-parse", "HEAD")

    def _parent_ingested_result_with_review(
        self,
        *,
        reviewer_family="claude-opus-5",
        reviewer_model_exact=None,
        reviewer_execution_id="review-execution-1",
    ):
        result_base_commit, result_commit_id = self._committed_ready_result()
        MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        acceptance_sha256 = MODULE.sha256_file(
            MODULE.CONTROL_ROOT / "tasks" / "po03-test-task" / "acceptance.json"
        )
        receipt_path = "workstreams/po03/reviews/po03-test-task-review.json"
        exact_model = reviewer_model_exact or {
            "claude-opus-5": "claude-opus-5-thinking-high",
            "gpt-5.6-sol": "gpt-5.6-sol-xhigh",
        }.get(reviewer_family, reviewer_family)
        receipt = {
            "review_version": "PO03-INDEPENDENT-REVIEW-v1",
            "task_id": "po03-test-task",
            "result_commit_id": result_commit_id,
            "reviewer_id": "reviewer-2",
            "reviewer_model_family": reviewer_family,
            "reviewer_model_exact": exact_model,
            "reviewer_runtime_id": "review-runtime-2",
            "reviewer_execution_id": reviewer_execution_id,
            "disposition": "ACCEPTED",
            "criteria_sha256": acceptance_sha256,
            "reviewed_at": "2026-08-22T08:00:00Z",
            "findings": [{"id": "finding-1", "result": "criteria reviewed"}],
            "conclusion": "The immutable result meets the frozen acceptance contract.",
            "decision_changed": [],
        }
        receipt_file = MODULE.REPO_ROOT / receipt_path
        receipt_file.parent.mkdir(parents=True)
        receipt_file.write_bytes(MODULE.canonical_json(receipt))
        self._git("add", "-A")
        self._git("commit", "-m", "record independent review")
        return result_commit_id, self._git("rev-parse", "HEAD"), receipt_path

    def test_canonical_json_and_hash_are_stable(self):
        first = MODULE.canonical_json({"b": 2, "a": 1})
        second = MODULE.canonical_json({"a": 1, "b": 2})
        self.assertEqual(first, second)
        self.assertEqual(MODULE.sha256_bytes(first), MODULE.sha256_bytes(second))

    def test_git_sha1_and_sha256_object_ids_are_supported(self):
        MODULE.require_git_object_id("a" * 40, "head")
        MODULE.require_git_object_id("b" * 64, "head")
        with self.assertRaises(ValueError):
            MODULE.require_git_object_id("c" * 39, "head")

    def test_recovery_projection_separates_provider_and_obzio_state(self):
        self.assertEqual("NOT_DISPATCHED", MODULE._provider_projection("CREATED"))
        self.assertEqual("RUNNING", MODULE._provider_projection("CHECKPOINTED"))
        self.assertEqual("COMPLETED", MODULE._provider_projection("RESULT_STAGED"))
        self.assertEqual("COMPLETED", MODULE._provider_projection("PARENT_INGESTED"))
        self.assertEqual(
            "AWAIT_COORDINATOR_COMPLETION_AND_INDEPENDENT_REVIEW",
            MODULE._recovery_action("PARENT_INGESTED"),
        )
        self.assertEqual("NONE", MODULE._recovery_action("COMPLETED"))
        self.assertEqual(
            "COMPLETED",
            MODULE.provider_state_from_events(
                [{"state": "CREATED"}, {"state": "RESULT_STAGED"}, {"state": "RECOVERY_REQUIRED"}]
            ),
        )
        self.assertEqual(
            "NOT_DISPATCHED",
            MODULE.provider_state_from_events(
                [
                    {"state": "CREATED"},
                    {
                        "state": "RECOVERY_REQUIRED",
                        "details": {"provider_dispatched": False},
                    },
                ]
            ),
        )

    def test_route_collision_is_recorded_once_and_suspends_dispatch(self):
        MODULE.CONTROL_ROOT.mkdir(parents=True)
        MODULE.replace_atomic(
            MODULE.CONTROL_ROOT / "recovery-state.json",
            MODULE.canonical_json(
                {
                    "recovery_version": "PO03-RECOVERY-STATE-v1",
                    "scan_state": "ACTIVE",
                    "units": {},
                    "false_completion_count": 0,
                    "orphan_count": 0,
                    "duplicate_callback_count": 0,
                    "collision_count": 0,
                    "decision_changed": [],
                }
            ),
        )
        receipt_relative = "receipts/po03/2026-08-22/collision.json"
        MODULE.write_once(
            MODULE.REPO_ROOT / receipt_relative,
            MODULE.canonical_json(
                {
                    "receipt_id": "collision-1",
                    "collision_policy": "FAIL_CLOSED",
                    "route_state": "DISPATCH_SUSPENDED",
                    "decision_changed": [],
                }
            ),
        )
        first = MODULE.record_route_collision(receipt_relative)
        replay = MODULE.record_route_collision(receipt_relative)
        projection = json.loads((MODULE.CONTROL_ROOT / "recovery-state.json").read_text())
        self.assertEqual("RECORDED", first["status"])
        self.assertEqual("ALREADY_RECORDED", replay["status"])
        self.assertEqual(1, projection["collision_count"])
        self.assertEqual("DISPATCH_SUSPENDED", projection["dispatch_route_state"])
        self.assertEqual(1, len(projection["collision_receipts"]))

    def test_route_reactivation_requires_exact_two_canary_proof(self):
        MODULE.CONTROL_ROOT.mkdir(parents=True)
        MODULE.replace_atomic(
            MODULE.CONTROL_ROOT / "route-health.json",
            MODULE.canonical_json(
                {
                    "route_id": "cursor-subagent-cloud-shared-checkout",
                    "state": "DISPATCH_SUSPENDED",
                    "collision_count": 1,
                }
            ),
        )
        MODULE.replace_atomic(
            MODULE.CONTROL_ROOT / "recovery-state.json",
            MODULE.canonical_json(
                {
                    "recovery_version": "PO03-RECOVERY-STATE-v1",
                    "scan_state": "ACTIVE",
                    "units": {},
                    "collision_count": 1,
                    "decision_changed": [],
                }
            ),
        )
        evidence = {
            "canary_results": [
                {
                    "task_id": "po03-route-isolation-canary-a",
                    "result_commit_id": "a" * 40,
                    "canary_sha256": "b" * 64,
                    "result_slot": "workstreams/po03/attempts/canary/a",
                },
                {
                    "task_id": "po03-route-isolation-canary-b",
                    "result_commit_id": "c" * 40,
                    "canary_sha256": "d" * 64,
                    "result_slot": "workstreams/po03/attempts/canary/b",
                },
            ],
            "shared_base_commit_id": "e" * 40,
            "overlap_seconds": 124,
            "resolved_metadata_fields_disjoint": True,
            "result_ranges_no_foreign_paths": True,
            "parent_readback_verified": True,
            "no_completion_or_self_acceptance": True,
        }

        def receipt(ceiling):
            return {
                "receipt_version": "PO03-ROUTE-REACTIVATION-v1",
                "receipt_id": "reactivation-1",
                "commission_id": MODULE.COMMISSION_ID,
                "route_id": "cursor-subagent-cloud-shared-checkout",
                "prior_route_state": "DISPATCH_SUSPENDED",
                "route_state": MODULE.ROUTE_REACTIVATED_STATE,
                "safe_new_dispatch_ceiling": ceiling,
                "recorded_at": "2026-08-22T08:00:00Z",
                "canary_results": evidence["canary_results"],
                "controller_comparison": {
                    key: evidence[key]
                    for key in (
                        "shared_base_commit_id",
                        "overlap_seconds",
                        "resolved_metadata_fields_disjoint",
                        "result_ranges_no_foreign_paths",
                        "parent_readback_verified",
                        "no_completion_or_self_acceptance",
                    )
                },
                "decision_changed": [],
            }

        invalid_receipt_relative = "receipts/po03/2026-08-22/reactivation-invalid.json"
        valid_receipt_relative = "receipts/po03/2026-08-22/reactivation-valid.json"
        MODULE.write_once(
            MODULE.REPO_ROOT / invalid_receipt_relative,
            MODULE.canonical_json(receipt(3)),
        )
        with patch.object(MODULE, "_route_canary_pair_evidence", return_value=evidence):
            with self.assertRaises(MODULE.FactoryError):
                MODULE.reactivate_route(invalid_receipt_relative)

        MODULE.write_once(
            MODULE.REPO_ROOT / valid_receipt_relative,
            MODULE.canonical_json(receipt(2)),
        )
        with patch.object(MODULE, "_route_canary_pair_evidence", return_value=evidence):
            first = MODULE.reactivate_route(valid_receipt_relative)
            replay = MODULE.reactivate_route(valid_receipt_relative)
        health = json.loads((MODULE.CONTROL_ROOT / "route-health.json").read_text())
        projection = json.loads((MODULE.CONTROL_ROOT / "recovery-state.json").read_text())
        self.assertEqual("REACTIVATED", first["status"])
        self.assertEqual("ALREADY_REACTIVATED", replay["status"])
        self.assertEqual(MODULE.ROUTE_REACTIVATED_STATE, health["state"])
        self.assertEqual(2, health["safe_new_dispatch_ceiling"])
        self.assertEqual(MODULE.ROUTE_REACTIVATED_STATE, projection["dispatch_route_state"])

    def test_write_once_is_idempotent_but_immutable(self):
        destination = MODULE.PO03_ROOT / "control" / "immutable.json"
        MODULE.write_once(destination, b"{}\n")
        MODULE.write_once(destination, b"{}\n")
        with self.assertRaises(FileExistsError):
            MODULE.write_once(destination, b'{"changed":true}\n')

    def test_write_outside_allowlist_is_rejected(self):
        destination = MODULE.REPO_ROOT / "state" / "forbidden.json"
        with self.assertRaises(ValueError):
            MODULE.write_once(destination, b"{}\n")

    def test_task_capsule_freezes_input_acceptance_and_initial_state(self):
        capsule = self._create_task()
        task_directory = MODULE.CONTROL_ROOT / "tasks" / "po03-test-task"
        transaction = json.loads((task_directory / "transaction-created.json").read_text())
        self.assertEqual(capsule["input_sha256"], MODULE.sha256_file(task_directory / "input.json"))
        self.assertEqual(
            transaction["acceptance_contract_sha256"],
            MODULE.sha256_file(task_directory / "acceptance.json"),
        )
        self.assertEqual("CREATED", transaction["obzio_state"])
        self.assertEqual("QUEUED", transaction["provider_state"])
        self.assertIsNone(transaction["result_transaction"]["result_commit_id"])

    def test_task_capsule_same_input_replays_idempotently(self):
        first = self._create_task()
        second = self._create_task()
        self.assertEqual(first, second)
        self.assertEqual(1, len(list((MODULE.CONTROL_ROOT / "events" / "po03-test-task").glob("*.json"))))

    def test_event_chain_is_monotonic_and_tamper_evident(self):
        self._create_task()
        MODULE.hash_chain_event(
            "po03-test-task",
            "LEASED",
            actor="integration-controller",
            details={
                "fence_token": 1,
                "prior_state": "CREATED",
                "worker_id": "worker-1",
                "provider_run_id": "reservation-1",
            },
            observed_at="2026-08-22T07:00:00Z",
        )
        self.assertEqual([], MODULE.verify_chain("po03-test-task"))
        event = MODULE.CONTROL_ROOT / "events" / "po03-test-task" / "000002-leased.json"
        document = json.loads(event.read_text())
        document["details"]["fence_token"] = 2
        event.write_text(json.dumps(document), encoding="utf-8")
        self.assertTrue(any("event hash mismatch" in error for error in MODULE.verify_chain("po03-test-task")))

    def test_event_chain_rejects_semantically_stale_lease(self):
        self._create_task()
        event = MODULE.hash_chain_event(
            "po03-test-task",
            "LEASED",
            actor="integration-controller",
            details={
                "fence_token": 1,
                "prior_state": "CREATED",
                "worker_id": "worker-1",
                "provider_run_id": "reservation-1",
            },
            observed_at="2026-08-22T07:00:00Z",
        )
        document = json.loads(event.read_text(encoding="utf-8"))
        document["details"]["fence_token"] = 2
        unhashed = dict(document)
        unhashed.pop("event_sha256")
        document["event_sha256"] = MODULE.sha256_bytes(MODULE.canonical_json(unhashed))
        event.write_bytes(MODULE.canonical_json(document))
        self.assertTrue(any("invalid lease fence" in error for error in MODULE.verify_chain("po03-test-task")))

    def test_running_requires_worker_execution_evidence(self):
        self._create_task()
        MODULE.advance_task(
            "po03-test-task",
            state="LEASED",
            actor="integration-controller",
            fence_token=1,
            details={"worker_id": "worker-1", "provider_run_id": "reserved-run-1"},
        )
        with self.assertRaises(MODULE.FactoryError):
            MODULE.advance_task(
                "po03-test-task",
                state="RUNNING",
                actor="integration-controller",
                fence_token=1,
                details={"controller_pre_dispatch": True, "provider_run_id": "reserved-run-1"},
            )
        with self.assertRaises(MODULE.FactoryError):
            MODULE.advance_task(
                "po03-test-task",
                state="RUNNING",
                actor="worker-1",
                fence_token=1,
            )
        MODULE.advance_task(
            "po03-test-task",
            state="RUNNING",
            actor="worker-1",
            fence_token=1,
            details={"provider_task_id": "provider-task-1", "worker_agent_id": "agent-1"},
        )
        self.assertEqual("RUNNING", MODULE.task_events("po03-test-task")[-1]["state"])

    def test_undispatched_reservation_is_recovered_without_claiming_provider_execution(self):
        original_utc_now = MODULE.utc_now
        self.addCleanup(setattr, MODULE, "utc_now", original_utc_now)
        MODULE.utc_now = lambda: "2000-01-01T00:00:00Z"
        self._create_task()
        MODULE.advance_task(
            "po03-test-task",
            state="LEASED",
            actor="integration-controller",
            fence_token=1,
            details={"worker_id": "worker-1", "provider_run_id": "reservation:task:attempt-1"},
        )
        MODULE.hash_chain_event(
            "po03-test-task",
            "RUNNING",
            actor="integration-controller",
            details={
                "controller_pre_dispatch": True,
                "fence_token": 1,
                "prior_state": "LEASED",
                "provider_run_id": "reservation:task:attempt-1",
            },
        )
        events = MODULE.task_events("po03-test-task")
        self.assertEqual("NOT_DISPATCHED", MODULE.provider_state_from_events(events))
        self.assertEqual(
            "AWAIT_PROVIDER_ADMISSION_OR_LEASE_EXPIRY",
            MODULE._recovery_action("RUNNING", provider_dispatched=False),
        )
        recovered = MODULE.recover_undispatched_task(
            "po03-test-task",
            reason="reservation did not produce provider execution evidence",
        )
        self.assertEqual("RETRY_SCHEDULED", recovered["status"])
        self.assertEqual(
            ["RECOVERY_REQUIRED", "RETRY_SCHEDULED"],
            [event["state"] for event in MODULE.task_events("po03-test-task")][-2:],
        )

    def _advance_to_result_committed(self):
        self._create_task()
        MODULE.advance_task(
            "po03-test-task",
            state="LEASED",
            actor="integration-controller",
            fence_token=1,
            details={"worker_id": "worker-1", "provider_run_id": "reservation-1"},
        )
        MODULE.advance_task(
            "po03-test-task",
            state="RUNNING",
            actor="worker-1",
            fence_token=1,
            details={"provider_task_id": "provider-task-1", "worker_agent_id": "agent-1"},
        )
        MODULE.advance_task(
            "po03-test-task",
            state="RESULT_STAGING",
            actor="worker-1",
            fence_token=1,
        )
        MODULE.advance_task(
            "po03-test-task",
            state="RESULT_STAGED",
            actor="worker-1",
            fence_token=1,
            details={"manifest_sha256": "a" * 64, "total_bytes": 1},
        )
        MODULE.advance_task(
            "po03-test-task",
            state="RESULT_VERIFIED",
            actor="worker-1",
            fence_token=1,
            details={"verified_artifacts": 1, "parent_remote_readback": "PASS"},
        )
        result_commit_id = "c" * 40
        MODULE.advance_task(
            "po03-test-task",
            state="RESULT_COMMITTED",
            actor="integration-controller",
            fence_token=1,
            details={"result_commit_id": result_commit_id},
        )
        return result_commit_id

    def _write_parent_ingestion(self, result_commit_id):
        task_directory = MODULE.CONTROL_ROOT / "tasks" / "po03-test-task"
        created = json.loads((task_directory / "transaction-created.json").read_text(encoding="utf-8"))
        record = {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "po03-test-task",
            "commission_id": created["commission_id"],
            "immutable_input_manifest_sha256": created["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": created["acceptance_contract_sha256"],
            "provider_state": "COMPLETED",
            "obzio_state": "PARENT_INGESTED",
            "attempt": {
                "attempt_id": "po03-test-task-attempt-1",
                "idempotency_key": created["attempt"]["idempotency_key"],
                "lease_id": created["attempt"]["lease_id"],
                "fence_token": 1,
                "provider_run_id": "provider-1",
                "worker_id": "worker-1",
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 4,
            },
            "result_transaction": {
                "result_txn_id": "result-po03-test-task-1",
                "state": "INGESTED",
                "manifest_uri": "git:po03/test@commit:manifest.json",
                "manifest_sha256": "a" * 64,
                "artifact_count": 2,
                "total_bytes": 2,
                "committed_at": "2026-08-22T07:00:00Z",
                "verified_at": "2026-08-22T07:00:01Z",
                "parent_ingested_at": "2026-08-22T07:00:02Z",
                "result_commit_id": result_commit_id,
            },
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "logical_name": "result.json",
                    "content_uri": "git:po03/test@commit:result.json",
                    "sha256": "a" * 64,
                    "bytes": 1,
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T07:00:01Z",
                },
                {
                    "artifact_id": "artifact-manifest",
                    "logical_name": "manifest.json",
                    "content_uri": "git:po03/test@commit:manifest.json",
                    "sha256": "a" * 64,
                    "bytes": 1,
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T07:00:01Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "PENDING", "reviewer_id": None, "receipt_uri": None},
        }
        (task_directory / "transaction-ingested.json").write_bytes(MODULE.canonical_json(record))

    def test_parent_ingestion_requires_immutable_result_record(self):
        result_commit_id = self._advance_to_result_committed()
        with self.assertRaises(MODULE.FactoryError):
            MODULE.advance_task(
                "po03-test-task",
                state="PARENT_INGESTED",
                actor="integration-controller",
                fence_token=1,
                details={"parent_readback": "PASS", "result_commit_id": result_commit_id},
            )

    def test_recovery_rebuild_preserves_parent_ingestion_without_completion(self):
        result_commit_id = self._advance_to_result_committed()
        self._write_parent_ingestion(result_commit_id)
        MODULE.advance_task(
            "po03-test-task",
            state="PARENT_INGESTED",
            actor="integration-controller",
            fence_token=1,
            details={"parent_readback": "PASS", "result_commit_id": result_commit_id},
        )
        projection = MODULE.rebuild_recovery_state(run_id="bc-rebuild")
        unit = projection["units"]["po03-test-task"]
        self.assertEqual("PARENT_INGESTED", unit["obzio_state"])
        self.assertEqual("COMPLETED", unit["provider_state"])
        self.assertEqual(result_commit_id, unit["result_commit_id"])
        self.assertEqual([], MODULE.verify_recovery_state())

    def test_committed_result_is_ingested_from_immutable_git_bytes(self):
        result_base_commit, result_commit_id = self._committed_ready_result()
        result = MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        self.assertEqual("PARENT_INGESTED", result["status"])
        self.assertEqual(2, result["artifact_count"])
        self.assertEqual(
            [
                "RESULT_STAGING",
                "RESULT_STAGED",
                "RESULT_VERIFIED",
                "RESULT_COMMITTED",
                "PARENT_INGESTED",
            ],
            [event["state"] for event in MODULE.task_events("po03-test-task")][-5:],
        )
        self.assertEqual([], MODULE.validate_ingested_result("po03-test-task"))
        transaction = json.loads(
            (MODULE.CONTROL_ROOT / "tasks" / "po03-test-task" / "transaction-ingested.json").read_text()
        )
        self.assertEqual(result_commit_id, transaction["result_transaction"]["result_commit_id"])
        self.assertEqual(2, transaction["result_transaction"]["artifact_count"])
        replay = MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        self.assertEqual("ALREADY_INGESTED", replay["status"])

    def test_source_manifest_with_zero_byte_artifact_is_ingested(self):
        result_base_commit, result_commit_id = self._committed_ready_result(source_manifest=True)
        result = MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        transaction = json.loads(
            (MODULE.CONTROL_ROOT / "tasks" / "po03-test-task" / "transaction-ingested.json").read_text()
        )
        self.assertEqual("PARENT_INGESTED", result["status"])
        self.assertEqual(2, result["artifact_count"])
        self.assertEqual(0, transaction["artifacts"][0]["bytes"])
        self.assertEqual(
            transaction["artifacts"][1]["bytes"],
            transaction["result_transaction"]["total_bytes"],
        )

    def test_wave_review_manifest_with_repository_paths_is_ingested(self):
        result_base_commit, result_commit_id = self._committed_ready_result(review_manifest=True)
        result = MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        transaction = json.loads(
            (MODULE.CONTROL_ROOT / "tasks" / "po03-test-task" / "transaction-ingested.json").read_text()
        )
        self.assertEqual("PARENT_INGESTED", result["status"])
        self.assertEqual(
            "result.json",
            transaction["artifacts"][0]["logical_name"],
        )

    def test_ingestion_rejects_commit_that_escapes_owned_result_slot(self):
        result_base_commit, result_commit_id = self._committed_ready_result(include_scope_escape=True)
        with self.assertRaises(MODULE.FactoryError):
            MODULE.ingest_committed_result(
                "po03-test-task",
                result_commit_id=result_commit_id,
                result_base_commit_id=result_base_commit,
                result_ref="HEAD",
                provider_run_id="provider-execution-1",
            )
        self.assertEqual("RUNNING", MODULE.task_events("po03-test-task")[-1]["state"])

    def test_completion_requires_immutable_independent_review(self):
        result_base_commit, result_commit_id = self._committed_ready_result()
        MODULE.ingest_committed_result(
            "po03-test-task",
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit,
            result_ref="HEAD",
            provider_run_id="provider-execution-1",
        )
        with self.assertRaises(MODULE.FactoryError):
            MODULE.advance_task(
                "po03-test-task",
                state="COMPLETED",
                actor="integration-controller",
                fence_token=1,
                details={"result_commit_id": result_commit_id},
            )

    def test_independent_review_completes_parent_ingested_result(self):
        result_commit_id, review_commit_id, receipt_path = self._parent_ingested_result_with_review()
        result = MODULE.complete_task_after_independent_review(
            "po03-test-task",
            review_commit_id=review_commit_id,
            review_ref="HEAD",
            receipt_path=receipt_path,
        )
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual("ACCEPTED", result["independent_disposition"])
        self.assertEqual("COMPLETED", MODULE.task_events("po03-test-task")[-1]["state"])
        self.assertEqual([], MODULE.validate_independent_acceptance("po03-test-task"))
        self.assertEqual("ACCEPTED", MODULE.independent_acceptance_state("po03-test-task"))
        replay = MODULE.complete_task_after_independent_review(
            "po03-test-task",
            review_commit_id=review_commit_id,
            review_ref="HEAD",
            receipt_path=receipt_path,
        )
        self.assertEqual("ALREADY_COMPLETED", replay["status"])

    def test_same_model_family_cannot_independently_complete_result(self):
        _, review_commit_id, receipt_path = self._parent_ingested_result_with_review(
            reviewer_family="gpt-5.6-sol"
        )
        with self.assertRaises(MODULE.FactoryError):
            MODULE.complete_task_after_independent_review(
                "po03-test-task",
                review_commit_id=review_commit_id,
                review_ref="HEAD",
                receipt_path=receipt_path,
            )
        self.assertEqual("PARENT_INGESTED", MODULE.task_events("po03-test-task")[-1]["state"])

    def test_unobserved_reviewer_model_cannot_independently_complete_result(self):
        _, review_commit_id, receipt_path = self._parent_ingested_result_with_review(
            reviewer_family="gpt-5.6-terra",
            reviewer_model_exact="gpt-5.6-terra-max-fast",
        )
        with self.assertRaises(MODULE.FactoryError):
            MODULE.complete_task_after_independent_review(
                "po03-test-task",
                review_commit_id=review_commit_id,
                review_ref="HEAD",
                receipt_path=receipt_path,
            )
        self.assertEqual("PARENT_INGESTED", MODULE.task_events("po03-test-task")[-1]["state"])

    def test_source_lock_hashes_pinned_git_bytes_not_worktree_bytes(self):
        original_git = MODULE.git
        original_git_bytes = MODULE.git_bytes
        self.addCleanup(setattr, MODULE, "git", original_git)
        self.addCleanup(setattr, MODULE, "git_bytes", original_git_bytes)
        MODULE.git = lambda *arguments: "f" * 40
        MODULE.git_bytes = lambda *arguments: b"pinned-source-bytes"
        lock = MODULE.source_lock("a" * 40)
        self.assertTrue(all(source["bytes"] == 19 for source in lock["sources"]))
        self.assertTrue(
            all(source["sha256"] == MODULE.sha256_bytes(b"pinned-source-bytes") for source in lock["sources"])
        )

    def test_duplicate_task_with_changed_acceptance_fails_closed(self):
        self._create_task()
        with self.assertRaises(FileExistsError):
            MODULE.task_capsule(
                task_id="po03-test-task",
                head_sha="a" * 40,
                run_id="bc-test",
                model="gpt-5.6-sol-xhigh-fast",
                reasoning="xhigh",
                hypothesis="changed",
                prompt="changed",
                owned_paths=["workstreams/po03/attempts/test/**"],
                result_slot="workstreams/po03/attempts/test",
                acceptance={"criteria": ["different"], "decision_changed": []},
                lease_seconds=300,
                fence_token=1,
            )


if __name__ == "__main__":
    unittest.main()
