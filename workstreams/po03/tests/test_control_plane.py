"""Custody invariant tests for the coordinator control plane.

Each test corresponds to a way the PO-02 Code-2 return was lost or could have
been silently faked.  The tests run the real module against an isolated ledger
so they exercise the same code path that governs live dispatch.
"""

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "control_plane.py"
SPEC = importlib.util.spec_from_file_location("control_plane", MODULE_PATH)
CP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CP)

COMMISSION = "COM-PO03-TEST"
OWNED = "workstreams/po03/engine/thing.py"


class IsolatedControlPlane(unittest.TestCase):
    """Redirect every control-plane path into a scratch tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self._saved = {
            name: getattr(CP, name)
            for name in ("LEDGER_PATH", "REGISTRY_PATH", "RECOVERY_PATH", "DISPATCH_DIR", "PATH_OWNERSHIP_PATH")
        }
        CP.LEDGER_PATH = self.root / "control/events/ledger.jsonl"
        CP.REGISTRY_PATH = self.root / "control/work-unit-registry.jsonl"
        CP.RECOVERY_PATH = self.root / "control/recovery-state.json"
        CP.DISPATCH_DIR = self.root / "control/dispatch"
        CP.PATH_OWNERSHIP_PATH = self.root / "control/path-ownership.json"
        for name, value in self._saved.items():
            self.addCleanup(setattr, CP, name, value)

        CP.write_json(
            CP.PATH_OWNERSHIP_PATH,
            {
                "owners": {
                    "po03-worker-a1": {"owned_prefixes": ["workstreams/po03/engine/"]},
                    # A disposition requires a registered independent reviewer,
                    # so the roster the guard consults must contain one.
                    "po03-worker-a6": {"owned_prefixes": ["workstreams/po03/review/luna/"]},
                }
            },
        )

    def seed_unit(self, unit_id="a1-u01", owner="po03-worker-a1"):
        manifest = {"unit_id": unit_id, "owner": owner}
        manifest_sha = CP.sha256_text(CP.canonical(manifest))
        acceptance_sha = CP.sha256_text(CP.canonical({"assertion": "x"}))
        CP.write_json(
            CP.DISPATCH_DIR / f"{unit_id}.json",
            {
                "unit_id": unit_id,
                "commission_id": COMMISSION,
                "owner": owner,
                "immutable_input_manifest_sha256": manifest_sha,
                "acceptance_contract_sha256": acceptance_sha,
                "idempotency_key": f"{unit_id}:key",
                "result_slot": {"unit_record": f"units/{unit_id}.json"},
            },
        )
        CP.append_event(
            unit_id, "CREATED", actor="coordinator", provider_state="QUEUED", payload={"owner": owner}
        )
        return manifest_sha, acceptance_sha

    def lease_unit(self, unit_id="a1-u01", owner="po03-worker-a1", fence=1,
                   expires_at="2099-01-01T00:00:00Z"):
        CP.append_event(
            unit_id,
            "LEASED",
            actor="coordinator",
            provider_state="RUNNING",
            fence_token=fence,
            payload={"lease_id": f"lease-{unit_id}-{fence}", "worker_id": owner, "expires_at": expires_at},
        )

    def forge_row(self, unit_id, event, actor, payload=None, provider_state="COMPLETED", fence_token=1):
        """Append a chained row without the append guard.

        Several invariants must hold for rows that already exist -- rows written
        by an earlier version of this module, or by any process that bypasses
        ``append_event``.  Those cases can no longer be produced through the
        guarded path, so they are constructed directly.
        """
        rows = CP.ledger_rows()
        body = {
            "seq": len(rows) + 1,
            "ts": "2026-08-22T07:30:00Z",
            "unit_id": unit_id,
            "event": event,
            "obzio_state": event,
            "provider_state": provider_state,
            "actor": actor,
            "fence_token": fence_token,
            "payload": payload or {},
            "prev_sha256": rows[-1]["row_sha256"] if rows else CP.GENESIS_HASH,
        }
        body["row_sha256"] = CP.sha256_text(CP.canonical(body))
        CP.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CP.LEDGER_PATH.open("a", encoding="utf-8") as handle:
            handle.write(CP.canonical(body) + "\n")
        return body

    def write_artifact(self, relative=OWNED, body=b"payload\n"):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return hashlib.sha256(body).hexdigest(), len(body)

    def result_doc(self, unit_id="a1-u01", owner="po03-worker-a1", relative=OWNED, fence=1):
        manifest_sha, acceptance_sha = self._shas
        sha, size = self.write_artifact(relative)
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": unit_id,
            "commission_id": COMMISSION,
            "immutable_input_manifest_sha256": manifest_sha,
            "acceptance_contract_sha256": acceptance_sha,
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": f"{unit_id}-attempt-{fence}",
                "idempotency_key": f"{unit_id}:key",
                "lease_id": f"lease-{unit_id}-{fence}",
                "fence_token": fence,
                "provider_run_id": "provider-run",
                "worker_id": owner,
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": f"{unit_id}-txn",
                "state": "COMMITTED",
                "manifest_uri": f"git:branch@sha:{unit_id}",
                "manifest_sha256": CP.sha256_text("manifest"),
                "artifact_count": 1,
                "total_bytes": size,
                "committed_at": "2026-08-22T07:00:01Z",
                "verified_at": "2026-08-22T07:00:02Z",
                "parent_ingested_at": None,
                "result_commit_id": "deadbeef",
            },
            "artifacts": [
                {
                    "artifact_id": f"{unit_id}-art-01",
                    "logical_name": relative.rsplit("/", 1)[-1],
                    "content_uri": f"git:branch@sha:{relative}",
                    "sha256": sha,
                    "bytes": size,
                    "media_type": "text/x-python",
                    "readback_verified_at": "2026-08-22T07:00:02Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }

    def ingest(self, doc):
        return CP.ingest_result(doc, artifact_root=self.root)


class PathScopeTests(unittest.TestCase):
    def test_allowlisted_prefixes_pass(self):
        for path in (
            "workstreams/po03/engine/a.py",
            "receipts/po03/2026-08-22/x.json",
            ".github/workflows/po03-path-scope.yml",
        ):
            self.assertTrue(CP.path_in_allowlist(path), path)

    def test_out_of_allowlist_paths_fail(self):
        for path in (
            "packs/operator.json",
            "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            ".cursor/environment.json",
            ".github/workflows/other.yml",
            ".github/workflows/po03-nested/x.yml",
            "workstreams/po01/thing.py",
            "scripts/check_operator_taxonomy.py",
        ):
            self.assertFalse(CP.path_in_allowlist(path), path)

    def test_traversal_is_refused(self):
        for path in (
            "workstreams/po03/../../etc/passwd",
            "./../workstreams/po03/engine/a.py",
            "../packs/operator.json",
            "/workstreams/po03/engine/a.py",
            "workstreams/po03//engine/a.py",
            "workstreams/po03/./engine/a.py",
            "",
            "   ",
        ):
            self.assertFalse(CP.path_in_allowlist(path), path)

    def test_leading_dot_slash_is_tolerated_without_eating_dotfiles(self):
        self.assertTrue(CP.path_in_allowlist("./workstreams/po03/engine/a.py"))
        self.assertTrue(CP.path_in_allowlist("./.github/workflows/po03-x.yml"))
        self.assertIsNone(CP.normalise_path("./../workstreams/po03/a.py"))

    def test_deliberate_out_of_allowlist_fixture_is_rejected(self):
        fixture = ["workstreams/po03/engine/ok.py", "modules/operators/forbidden.json"]
        self.assertEqual(["modules/operators/forbidden.json"], CP.check_allowlist(fixture))


class LedgerIntegrityTests(IsolatedControlPlane):
    def setUp(self):
        super().setUp()
        self._shas = self.seed_unit()
        # Progress events require a coordinator-issued lease, so the fixture
        # leases the unit rather than reporting work that was never granted.
        self.lease_unit()

    def test_clean_chain_verifies(self):
        CP.append_event("a1-u01", "RUNNING", actor="po03-worker-a1", fence_token=1)
        self.assertEqual([], CP.verify_chain(CP.ledger_rows()))

    def test_row_mutation_is_detected(self):
        CP.append_event("a1-u01", "RUNNING", actor="po03-worker-a1", fence_token=1)
        rows = [json.loads(line) for line in CP.LEDGER_PATH.read_text().splitlines()]
        rows[0]["event"] = "COMPLETED"
        CP.LEDGER_PATH.write_text("\n".join(CP.canonical(r) for r in rows) + "\n")
        self.assertTrue(CP.verify_chain(CP.ledger_rows()))

    def test_row_reorder_is_detected(self):
        CP.append_event("a1-u01", "RUNNING", actor="po03-worker-a1", fence_token=1)
        rows = [json.loads(line) for line in CP.LEDGER_PATH.read_text().splitlines()]
        rows.reverse()
        CP.LEDGER_PATH.write_text("\n".join(CP.canonical(r) for r in rows) + "\n")
        self.assertTrue(CP.verify_chain(CP.ledger_rows()))

    def test_truncation_is_detected_by_projection_gap(self):
        CP.append_event("a1-u01", "RUNNING", actor="po03-worker-a1", fence_token=1)
        CP.append_event(
            "a1-u01", "CHECKPOINTED", actor="po03-worker-a1", fence_token=1, payload={"checkpoint_seq": 3}
        )
        rows = CP.LEDGER_PATH.read_text().splitlines()
        CP.LEDGER_PATH.write_text("\n".join(rows[:-1]) + "\n")
        surviving = CP.ledger_rows()
        self.assertEqual([], CP.verify_chain(surviving))
        self.assertEqual(0, CP.project_units()["a1-u01"]["checkpoint_seq"])

    def test_append_refuses_to_extend_a_tampered_chain(self):
        rows = [json.loads(line) for line in CP.LEDGER_PATH.read_text().splitlines()]
        rows[0]["actor"] = "worker"
        CP.LEDGER_PATH.write_text("\n".join(CP.canonical(r) for r in rows) + "\n")
        with self.assertRaises(CP.ControlPlaneError):
            CP.append_event("a1-u01", "RUNNING", actor="coordinator")

    def test_unknown_event_kind_is_refused(self):
        with self.assertRaises(CP.ControlPlaneError):
            CP.append_event("a1-u01", "DEFINITELY_DONE", actor="coordinator")

    def test_registry_is_a_pure_projection(self):
        CP.append_event("a1-u01", "RUNNING", actor="po03-worker-a1", fence_token=1)
        first = CP.materialize()
        CP.REGISTRY_PATH.unlink()
        self.assertEqual(first, CP.materialize())


class IngestionTests(IsolatedControlPlane):
    def setUp(self):
        super().setUp()
        self._shas = self.seed_unit()
        CP.append_event(
            "a1-u01",
            "LEASED",
            actor="coordinator",
            fence_token=1,
            payload={"lease_id": "lease-a1-u01-1", "worker_id": "po03-worker-a1", "expires_at": "2099-01-01T00:00:00Z"},
        )

    def test_verified_result_is_ingested(self):
        outcome = self.ingest(self.result_doc())
        self.assertFalse(outcome["duplicate"])
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])
        self.assertEqual("PARENT_INGESTED", CP.project_units()["a1-u01"]["obzio_state"])

    def failed_doc(self, state="FAILED_TERMINAL"):
        doc = self.result_doc()
        doc["obzio_state"] = state
        doc["provider_state"] = "UNKNOWN"
        doc["result_transaction"].update(
            state="RESERVED", manifest_uri=None, manifest_sha256=None, committed_at=None,
            verified_at=None, result_commit_id=None,
        )
        doc["artifacts"][0]["readback_verified_at"] = None
        return doc

    def test_honest_failure_is_not_promoted_to_a_committed_state(self):
        outcome = self.ingest(self.failed_doc())
        self.assertEqual("FAILED_TERMINAL", outcome["ingest_event"])
        unit = CP.project_units()["a1-u01"]
        self.assertEqual("FAILED_TERMINAL", unit["obzio_state"])
        self.assertIsNone(unit["result_commit_id"])
        self.assertEqual([], CP.scan_recovery()["false_completions"])

    def test_uncommitted_provider_completion_is_ingested_as_such(self):
        outcome = self.ingest(self.failed_doc("PROVIDER_COMPLETED_UNCOMMITTED"))
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", outcome["ingest_event"])
        state = CP.scan_recovery()
        self.assertEqual([], state["false_completions"])
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", CP.project_units()["a1-u01"]["obzio_state"])

    def test_replayed_failure_is_as_harmless_as_a_replayed_success(self):
        doc = self.failed_doc()
        self.ingest(doc)
        again = self.ingest(copy.deepcopy(doc))
        self.assertTrue(again["duplicate"])
        events = [r["event"] for r in CP.ledger_rows() if r["event"] in CP.INGESTION_EVENTS]
        self.assertEqual(["FAILED_TERMINAL"], events)

    def test_duplicate_callback_is_harmless(self):
        doc = self.result_doc()
        self.ingest(doc)
        again = self.ingest(copy.deepcopy(doc))
        self.assertTrue(again["duplicate"])
        ingested = [r for r in CP.ledger_rows() if r["event"] == "PARENT_INGESTED"]
        self.assertEqual(1, len(ingested))

    def test_stale_fence_cannot_commit_after_ownership_transfer(self):
        CP.append_event(
            "a1-u01",
            "LEASED",
            actor="coordinator",
            fence_token=2,
            payload={"lease_id": "lease-a1-u01-2", "worker_id": "po03-worker-a1", "expires_at": "2099-01-01T00:00:00Z"},
        )
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(self.result_doc(fence=1))
        self.assertIn("stale fence", str(ctx.exception))
        self.assertTrue(any(r["event"] == "FENCE_REJECTED" for r in CP.ledger_rows()))

    def test_missing_artifact_is_refused(self):
        doc = self.result_doc()
        (self.root / OWNED).unlink()
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("missing on read-back", str(ctx.exception))

    def test_corrupted_artifact_is_refused(self):
        doc = self.result_doc()
        (self.root / OWNED).write_bytes(b"payload!")
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("hash mismatch", str(ctx.exception))

    def test_truncated_artifact_is_refused(self):
        doc = self.result_doc()
        doc["artifacts"][0]["bytes"] += 1
        doc["result_transaction"]["total_bytes"] += 1
        with self.assertRaises(CP.ControlPlaneError):
            self.ingest(doc)

    def test_out_of_allowlist_artifact_is_refused(self):
        doc = self.result_doc(relative="modules/operators/forbidden.json")
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("outside the commission allowlist", str(ctx.exception))

    def test_unowned_artifact_is_refused(self):
        doc = self.result_doc(relative="workstreams/po03/metrics/not-mine.json")
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("does not own", str(ctx.exception))

    def test_result_must_reference_its_own_dispatch_manifest(self):
        doc = self.result_doc()
        doc["immutable_input_manifest_sha256"] = "b" * 64
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("immutable input manifest", str(ctx.exception))

    def test_result_must_reference_the_frozen_acceptance_contract(self):
        doc = self.result_doc()
        doc["acceptance_contract_sha256"] = "c" * 64
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("frozen acceptance contract", str(ctx.exception))

    def test_contract_invalid_result_is_refused(self):
        doc = self.result_doc()
        doc["result_transaction"]["result_commit_id"] = None
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("result contract invalid", str(ctx.exception))

    def test_unknown_unit_is_refused(self):
        doc = self.result_doc()
        doc["task_id"] = "a1-u99"
        with self.assertRaises(CP.ControlPlaneError):
            self.ingest(doc)


class CompletionAuthorityTests(IsolatedControlPlane):
    def setUp(self):
        super().setUp()
        self._shas = self.seed_unit()
        CP.append_event(
            "a1-u01",
            "LEASED",
            actor="coordinator",
            fence_token=1,
            payload={"lease_id": "lease-a1-u01-1", "worker_id": "po03-worker-a1", "expires_at": "2099-01-01T00:00:00Z"},
        )

    def _complete(self):
        args = type("A", (), {"unit_id": "a1-u01"})()
        return CP.cmd_complete(args)

    def test_completion_requires_parent_ingestion(self):
        CP.append_event("a1-u01", "RESULT_COMMITTED", actor="po03-worker-a1", fence_token=1)
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self._complete()
        self.assertIn("requires PARENT_INGESTED", str(ctx.exception))

    def test_completion_after_ingestion_succeeds_and_is_coordinator_authored(self):
        self.ingest(self.result_doc())
        self.assertEqual(0, self._complete())
        row = [r for r in CP.ledger_rows() if r["event"] == "COMPLETED"][-1]
        self.assertEqual("coordinator", row["actor"])

    def test_provider_completion_without_commit_is_not_completion(self):
        doc = self.result_doc()
        doc["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
        doc["result_transaction"].update(
            state="RESERVED",
            manifest_uri=None,
            manifest_sha256=None,
            artifact_count=0,
            total_bytes=0,
            committed_at=None,
            verified_at=None,
            result_commit_id=None,
        )
        doc["artifacts"] = []
        self.ingest(doc)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", CP.project_units()["a1-u01"]["obzio_state"])
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            self._complete()
        self.assertIn("completion requires PARENT_INGESTED", str(ctx.exception))

    def test_producer_cannot_accept_its_own_work(self):
        self.ingest(self.result_doc())
        self._complete()
        args = type(
            "A",
            (),
            {
                "unit_id": "a1-u01",
                "decision": "ACCEPTED",
                "reviewer": "po03-worker-a1",
                "receipt": "git:receipt",
                "rationale": "",
            },
        )()
        with self.assertRaises(CP.ControlPlaneError) as ctx:
            CP.cmd_review(args)
        self.assertIn("cannot accept or reject its own work", str(ctx.exception))

    def test_independent_reviewer_may_accept(self):
        self.ingest(self.result_doc())
        self._complete()
        args = type(
            "A",
            (),
            {
                "unit_id": "a1-u01",
                "decision": "ACCEPTED",
                "reviewer": "po03-worker-a6",
                "receipt": "git:receipt",
                "rationale": "criteria met",
            },
        )()
        self.assertEqual(0, CP.cmd_review(args))
        self.assertEqual("ACCEPTED", CP.project_units()["a1-u01"]["acceptance"])

    def test_review_requires_completion(self):
        args = type(
            "A",
            (),
            {
                "unit_id": "a1-u01",
                "decision": "ACCEPTED",
                "reviewer": "po03-worker-a6",
                "receipt": "git:receipt",
                "rationale": "",
            },
        )()
        with self.assertRaises(CP.ControlPlaneError):
            CP.cmd_review(args)


class RecoveryScannerTests(IsolatedControlPlane):
    def setUp(self):
        super().setUp()
        self._shas = self.seed_unit()

    def test_expired_lease_is_reported(self):
        CP.append_event(
            "a1-u01",
            "LEASED",
            actor="coordinator",
            fence_token=1,
            payload={"lease_id": "l", "worker_id": "po03-worker-a1", "expires_at": "2000-01-01T00:00:00Z"},
        )
        state = CP.scan_recovery()
        self.assertIn("a1-u01", state["expired_leases"])
        self.assertTrue(state["recovery_required"])

    def test_provider_completed_without_commit_is_reported(self):
        CP.append_event(
            "a1-u01", "PROVIDER_COMPLETED_UNCOMMITTED", actor="coordinator", provider_state="COMPLETED"
        )
        state = CP.scan_recovery()
        self.assertIn("a1-u01", state["provider_completed_uncommitted"])
        self.assertEqual([], state["false_completions"])

    def test_completed_without_commit_is_a_false_completion(self):
        # The guarded append path now refuses this row outright; the scanner
        # must still catch one that already exists in the ledger.
        with self.assertRaises(CP.ControlPlaneError):
            CP.append_event("a1-u01", "COMPLETED", actor="coordinator", provider_state="COMPLETED")
        self.forge_row("a1-u01", "COMPLETED", "coordinator", {})
        state = CP.scan_recovery()
        self.assertIn("a1-u01", state["false_completions"])
        self.assertTrue(state["recovery_required"])

    def test_orphan_without_lease_is_reported(self):
        self.assertIn("a1-u01", CP.scan_recovery()["orphaned_units"])

    def test_parent_restart_rebuilds_identical_state(self):
        self.lease_unit()
        CP.append_event(
            "a1-u01", "CHECKPOINTED", actor="po03-worker-a1", fence_token=1, payload={"checkpoint_seq": 2}
        )
        before = CP.project_units()
        CP.REGISTRY_PATH.unlink(missing_ok=True)
        CP.RECOVERY_PATH.unlink(missing_ok=True)
        self.assertEqual(before, CP.project_units())

    def test_checkpoints_are_monotonic(self):
        self.lease_unit()
        CP.append_event(
            "a1-u01", "CHECKPOINTED", actor="po03-worker-a1", fence_token=1, payload={"checkpoint_seq": 5}
        )
        CP.append_event(
            "a1-u01", "CHECKPOINTED", actor="po03-worker-a1", fence_token=1, payload={"checkpoint_seq": 2}
        )
        self.assertEqual(5, CP.project_units()["a1-u01"]["checkpoint_seq"])


class OwnershipTests(IsolatedControlPlane):
    def test_unknown_owner_owns_nothing(self):
        self.assertEqual(
            ["workstreams/po03/engine/x.py"],
            CP.check_ownership("stranger", ["workstreams/po03/engine/x.py"]),
        )

    def test_owner_confined_to_its_subtree(self):
        violations = CP.check_ownership(
            "po03-worker-a1",
            ["workstreams/po03/engine/ok.py", "workstreams/po03/metrics/no.json"],
        )
        self.assertEqual(["workstreams/po03/metrics/no.json"], violations)

    def test_traversal_cannot_be_normalised_into_an_owned_subtree(self):
        self.assertEqual(
            ["workstreams/po03/engine/../../../packs/x.json"],
            CP.check_ownership("po03-worker-a1", ["workstreams/po03/engine/../../../packs/x.json"]),
        )


if __name__ == "__main__":
    unittest.main()
