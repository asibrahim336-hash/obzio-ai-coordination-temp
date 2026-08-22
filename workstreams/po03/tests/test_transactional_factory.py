import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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
        (po03 / "COMMISSION.md").write_text("commission\n", encoding="utf-8")
        (po03 / "contracts" / "transactional-result.schema.json").write_text("{}\n", encoding="utf-8")
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

    def test_event_chain_is_monotonic_and_tamper_evident(self):
        self._create_task()
        MODULE.hash_chain_event(
            "po03-test-task",
            "LEASED",
            actor="integration-controller",
            details={"fence_token": 1},
            observed_at="2026-08-22T07:00:00Z",
        )
        self.assertEqual([], MODULE.verify_chain("po03-test-task"))
        event = MODULE.CONTROL_ROOT / "events" / "po03-test-task" / "000002-leased.json"
        document = json.loads(event.read_text())
        document["details"]["fence_token"] = 2
        event.write_text(json.dumps(document), encoding="utf-8")
        self.assertTrue(any("event hash mismatch" in error for error in MODULE.verify_chain("po03-test-task")))

    def test_controller_predispatch_transition_requires_explicit_marker(self):
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
            )
        MODULE.advance_task(
            "po03-test-task",
            state="RUNNING",
            actor="integration-controller",
            fence_token=1,
            details={"controller_pre_dispatch": True, "provider_run_id": "reserved-run-1"},
        )
        self.assertEqual("RUNNING", MODULE.task_events("po03-test-task")[-1]["state"])

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
