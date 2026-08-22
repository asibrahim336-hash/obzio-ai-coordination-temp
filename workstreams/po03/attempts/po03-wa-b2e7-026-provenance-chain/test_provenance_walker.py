"""Tests for the PO-03 provenance walker.

The hypothesis under test is that every counted result traces back to its
immutable task input and acceptance contract by hash.  Each test either roots a
real committed result or breaks one link and asserts the walker reports the
artifact as unrooted instead of passing it.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
MODULE_PATH = UNIT_ROOT / "provenance_walker.py"
SPEC = importlib.util.spec_from_file_location("po03_provenance_walker", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
WALKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WALKER)

REPO_ROOT = UNIT_ROOT.parents[3]
ROOTED_TASK = "po03-wa-b2e7-025-manifest-generator-verifier"


def canonical(document: dict) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class SyntheticRepository:
    """A minimal PO-03 layout whose provenance links can be broken one at a time."""

    def __init__(self, root: Path, task_id: str = "synthetic-unit-001") -> None:
        self.root = root
        self.task_id = task_id
        self.slot = f"{WALKER.ATTEMPTS_PREFIX}/{task_id}"
        self.acceptance = {"acceptance_version": "PO03-WAVE-A-UNIT-ACCEPTANCE-v1", "task_id": task_id}
        acceptance_bytes = canonical(self.acceptance)
        self.capsule = {
            "task_id": task_id,
            "commission_id": "COM-SYNTHETIC",
            "falsifiable_hypothesis": "synthetic",
            "ownership": {"result_slot": self.slot},
            "source_hashes": {"acceptance_contract_sha256": hashlib.sha256(acceptance_bytes).hexdigest()},
            "transaction": {"idempotency_key": "key-1", "lease_id": "lease-1", "fence_token": 7},
        }
        self.write(f"{WALKER.TASKS_PREFIX}/{task_id}/acceptance.json", acceptance_bytes)
        capsule_bytes = canonical(self.capsule)
        self.write(f"{WALKER.TASKS_PREFIX}/{task_id}/input.json", capsule_bytes)
        self.write(f"{WALKER.EVENTS_PREFIX}/{task_id}/000001-created.json", canonical({"sequence": 1}))
        self.write(f"{self.slot}/component.py", b"print('component')\n")
        self.result = {
            "task_id": task_id,
            "commission_id": "COM-SYNTHETIC",
            "immutable_input_manifest_sha256": hashlib.sha256(capsule_bytes).hexdigest(),
            "acceptance_contract_sha256": hashlib.sha256(acceptance_bytes).hexdigest(),
            "obzio_state": "RESULT_COMMITTED",
            "completion_actor": None,
            "attempt": {"idempotency_key": "key-1", "lease_id": "lease-1", "fence_token": 7,
                        "worker_id": "synthetic-producer"},
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }
        self.manifest = {
            "task_id": task_id,
            "artifact_commit": "0" * 40,
            "artifacts": [{"logical_name": "component.py",
                           "content_uri": f"git:{'0' * 40}:{self.slot}/component.py",
                           "sha256": hashlib.sha256(b"print('component')\n").hexdigest(),
                           "bytes": 19}],
        }
        self.flush()

    def write(self, relative: str, payload: bytes) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def flush(self) -> None:
        self.write(f"{self.slot}/result.json", canonical(self.result))
        self.write(f"{self.slot}/manifest.json", canonical(self.manifest))

    def findings(self) -> list[str]:
        reader = WALKER.Reader(self.root)
        return WALKER.walk(reader, self.task_id)[1]


class SyntheticProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "workstreams/po03").mkdir(parents=True)
        self.repository = SyntheticRepository(self.root)

    def assertFinding(self, prefix, findings):
        self.assertTrue(any(item.startswith(prefix) for item in findings), findings)

    def test_intact_chain_is_rooted(self):
        self.assertEqual([], self.repository.findings())

    def test_claimed_input_hash_that_does_not_reproduce_is_unrooted(self):
        self.repository.result["immutable_input_manifest_sha256"] = "f" * 64
        self.repository.flush()
        self.assertFinding("INPUT_HASH_MISMATCH", self.repository.findings())

    def test_capsule_mutated_after_the_result_is_detected(self):
        capsule = dict(self.repository.capsule)
        capsule["falsifiable_hypothesis"] = "quietly rewritten"
        self.repository.write(
            f"{WALKER.TASKS_PREFIX}/{self.repository.task_id}/input.json", canonical(capsule)
        )
        self.assertFinding("INPUT_HASH_MISMATCH", self.repository.findings())

    def test_claimed_acceptance_hash_that_does_not_reproduce_is_unrooted(self):
        self.repository.result["acceptance_contract_sha256"] = "e" * 64
        self.repository.flush()
        self.assertFinding("ACCEPTANCE_HASH_MISMATCH", self.repository.findings())

    def test_capsule_declaring_an_acceptance_hash_it_does_not_have_is_detected(self):
        """The emitter copies this hash instead of measuring it, so the walker measures it."""
        capsule = dict(self.repository.capsule)
        capsule["source_hashes"] = {"acceptance_contract_sha256": "d" * 64}
        capsule_bytes = canonical(capsule)
        self.repository.write(
            f"{WALKER.TASKS_PREFIX}/{self.repository.task_id}/input.json", capsule_bytes
        )
        self.repository.result["immutable_input_manifest_sha256"] = hashlib.sha256(capsule_bytes).hexdigest()
        self.repository.result["acceptance_contract_sha256"] = "d" * 64
        self.repository.flush()
        findings = self.repository.findings()
        self.assertFinding("CAPSULE_SELF_INCONSISTENT", findings)
        self.assertFinding("ACCEPTANCE_HASH_MISMATCH", findings)

    def test_missing_capsule_is_unrooted(self):
        (self.root / WALKER.TASKS_PREFIX / self.repository.task_id / "input.json").unlink()
        self.assertFinding("CAPSULE_MISSING", self.repository.findings())

    def test_missing_acceptance_contract_is_unrooted(self):
        (self.root / WALKER.TASKS_PREFIX / self.repository.task_id / "acceptance.json").unlink()
        self.assertFinding("ACCEPTANCE_MISSING", self.repository.findings())

    def test_attempt_binding_that_does_not_match_the_capsule_is_unrooted(self):
        self.repository.result["attempt"]["fence_token"] = 999
        self.repository.flush()
        self.assertFinding("ATTEMPT_BINDING_MISMATCH", self.repository.findings())

    def test_result_for_a_different_commission_is_unrooted(self):
        self.repository.result["commission_id"] = "COM-SOMETHING-ELSE"
        self.repository.flush()
        self.assertFinding("COMMISSION_MISMATCH", self.repository.findings())

    def test_missing_event_chain_is_unrooted(self):
        for event in (self.root / WALKER.EVENTS_PREFIX / self.repository.task_id).iterdir():
            event.unlink()
        self.assertFinding("EVENT_CHAIN_MISSING", self.repository.findings())

    def test_artifact_pointing_at_another_commit_is_unrooted(self):
        self.repository.manifest["artifacts"][0]["content_uri"] = f"git:{'a' * 40}:x"
        self.repository.flush()
        findings = self.repository.findings()
        self.assertFinding("ARTIFACT_UNROOTED", findings)

    def test_artifact_absent_from_the_manifest_is_reported_uncovered(self):
        self.repository.write(f"{self.repository.slot}/extra.py", b"extra\n")
        self.assertFinding("ARTIFACT_UNCOVERED", self.repository.findings())

    def test_slot_with_artifacts_and_no_result_is_an_orphan(self):
        (self.root / self.repository.slot / "result.json").unlink()
        self.assertFinding("ORPHAN_SLOT", self.repository.findings())

    def test_missing_manifest_is_reported(self):
        (self.root / self.repository.slot / "manifest.json").unlink()
        self.assertFinding("MANIFEST_MISSING", self.repository.findings())

    def test_producer_claiming_completion_is_reported(self):
        self.repository.result["obzio_state"] = "COMPLETED"
        self.repository.result["completion_actor"] = "synthetic-producer"
        self.repository.flush()
        self.assertFinding("PRODUCER_CLAIMED_COMPLETION", self.repository.findings())

    def test_producer_self_acceptance_is_reported(self):
        self.repository.result["independent_acceptance"] = {
            "state": "ACCEPTED", "reviewer_id": "synthetic-producer", "receipt_uri": "receipt"
        }
        self.repository.flush()
        self.assertFinding("SELF_ACCEPTANCE", self.repository.findings())

    def test_unknown_task_is_reported_rather_than_silently_passing(self):
        reader = WALKER.Reader(self.root)
        self.assertFinding("NO_SUCH_SLOT", WALKER.walk(reader, "no-such-task")[1])


class LiveRepositoryTests(unittest.TestCase):
    """Root a real committed PO-03 result against its real frozen capsule."""

    def test_committed_unit_025_result_is_rooted_in_the_working_tree(self):
        if not (REPO_ROOT / WALKER.ATTEMPTS_PREFIX / ROOTED_TASK / "result.json").is_file():
            self.skipTest(f"{ROOTED_TASK} has no committed result yet")
        reader = WALKER.Reader(REPO_ROOT)
        records, findings = WALKER.walk(reader, ROOTED_TASK)
        self.assertEqual([], findings)
        self.assertEqual(1, len(records))
        self.assertTrue(records[0]["rooted"])
        self.assertEqual(64, len(records[0]["measured_input_sha256"]))

    def test_committed_unit_025_result_is_rooted_at_an_immutable_commit(self):
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        reader = WALKER.Reader(REPO_ROOT, head)
        if not WALKER.discover_slots(reader):
            self.skipTest("no committed slots at HEAD")
        records, findings = WALKER.walk(reader, ROOTED_TASK)
        if not records:
            self.skipTest(f"{ROOTED_TASK} not committed at HEAD")
        self.assertEqual([], findings)
        self.assertTrue(records[0]["rooted"])

    def test_live_capsules_declare_the_acceptance_hash_their_bytes_actually_have(self):
        """Measured across every frozen capsule in the repository, not just this cohort's."""
        tasks = sorted((REPO_ROOT / WALKER.TASKS_PREFIX).iterdir())
        self.assertGreater(len(tasks), 0)
        inconsistent = []
        for task in tasks:
            acceptance = task / "acceptance.json"
            capsule = task / "input.json"
            if not acceptance.is_file() or not capsule.is_file():
                continue
            measured = hashlib.sha256(acceptance.read_bytes()).hexdigest()
            declared = json.loads(capsule.read_text(encoding="utf-8"))["source_hashes"][
                "acceptance_contract_sha256"
            ]
            if measured != declared:
                inconsistent.append(task.name)
        self.assertEqual([], inconsistent)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), *arguments), capture_output=True, text=True
        )

    def test_rooted_task_exits_zero(self):
        if not (REPO_ROOT / WALKER.ATTEMPTS_PREFIX / ROOTED_TASK / "result.json").is_file():
            self.skipTest(f"{ROOTED_TASK} has no committed result yet")
        result = self.run_cli("--repo-root", str(REPO_ROOT), "--task-id", ROOTED_TASK)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PO03_PROVENANCE_PASS", result.stdout)

    def test_unknown_task_exits_one(self):
        result = self.run_cli("--repo-root", str(REPO_ROOT), "--task-id", "not-a-task")
        self.assertEqual(1, result.returncode)
        self.assertIn("NO_SUCH_SLOT", result.stderr)

    def test_non_repository_root_exits_two(self):
        with tempfile.TemporaryDirectory() as scratch:
            result = self.run_cli("--repo-root", scratch)
            self.assertEqual(2, result.returncode)
            self.assertIn("PO03_PROVENANCE_ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main()
