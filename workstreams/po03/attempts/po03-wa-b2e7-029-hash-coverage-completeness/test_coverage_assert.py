"""Tests for the PO-03 hash and byte-count coverage assertion.

The hypothesis under test is that hash and byte-count coverage over counted
artifacts is total, so a partially hashed result cannot be counted.  Each test
takes a manifest that would satisfy a trusting reader and asserts the auditor
refuses it, because the auditor measures the commit rather than believing the
manifest's own arithmetic.

One scratch repository is built per test class and each case mutates a copy of
its manifest in memory.  Committing a fresh repository per case cost about
twelve seconds here, which would have made the suite unusable in a gate.
"""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
MODULE_PATH = UNIT_ROOT / "coverage_assert.py"
SPEC = importlib.util.spec_from_file_location("po03_coverage_assert", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)

REPO_ROOT = UNIT_ROOT.parents[3]


def canonical(document) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class Scratch:
    """A throwaway repository holding one slot, its artifacts and its documents."""

    TASK = "synthetic-coverage-001"

    def __init__(self, root: Path, payload: dict[str, bytes] | None = None) -> None:
        self.root = root
        self.slot = f"{AUDITOR.ATTEMPTS_PREFIX}/{self.TASK}"
        (root / "workstreams/po03").mkdir(parents=True)
        self.git("init", "-q", "-b", "scratch", ".")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "po03-coverage-fixture")
        self.payload = payload or {"component.py": b"print('c')\n", "evidence/run.txt": b"ok\n"}
        for name, body in self.payload.items():
            self.write(f"{self.slot}/{name}", body)
        self.git("add", "-A")
        self.git("commit", "-qm", "artifacts")
        self.artifact_commit = self.git("rev-parse", "HEAD").strip()
        self.manifest = self.build_manifest()
        self.result = self.build_result(self.manifest)
        self.repository = AUDITOR.Repository(self.root)

    def git(self, *arguments):
        return subprocess.run(
            ("git", *arguments), cwd=self.root, check=True, capture_output=True, text=True
        ).stdout

    def write(self, relative: str, payload: bytes) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def build_manifest(self) -> dict:
        artifacts = []
        for index, (name, body) in enumerate(sorted(self.payload.items()), start=1):
            artifacts.append({
                "artifact_id": f"{self.TASK}-artifact-{index:03d}",
                "logical_name": name,
                "content_uri": f"git:{self.artifact_commit}:{self.slot}/{name}",
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "media_type": "text/plain",
            })
        return {
            "manifest_version": "PO03-ARTIFACT-MANIFEST-v1",
            "task_id": self.TASK,
            "result_slot": self.slot,
            "artifact_commit": self.artifact_commit,
            "artifact_count": len(artifacts),
            "total_bytes": sum(item["bytes"] for item in artifacts),
            "artifacts": artifacts,
        }

    @staticmethod
    def build_result(manifest: dict) -> dict:
        return {
            "task_id": manifest.get("task_id"),
            "result_transaction": {
                "artifact_count": manifest.get("artifact_count"),
                "total_bytes": manifest.get("total_bytes"),
                "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
            },
        }

    def audit(self, manifest: dict | None = None, result: dict | None = None) -> list[str]:
        """Audit a candidate manifest against the committed artifact tree."""
        manifest = self.manifest if manifest is None else manifest
        raw = canonical(manifest)
        if result is None:
            result = self.build_result(manifest)
        return AUDITOR.audit_documents(self.repository, self.slot, manifest, raw, result)[1]

    def commit_documents(self) -> str:
        self.write(f"{self.slot}/manifest.json", canonical(self.manifest))
        self.write(f"{self.slot}/result.json", canonical(self.build_result(self.manifest)))
        self.git("add", "-A")
        if self.git("status", "--porcelain").strip():
            self.git("commit", "-qm", "documents")
        return self.git("rev-parse", "HEAD").strip()


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.scratch = Scratch(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.manifest = copy.deepcopy(self.scratch.manifest)

    def assertFinding(self, prefix, findings):
        self.assertTrue(any(item.startswith(prefix) for item in findings), findings)

    def test_a_complete_manifest_passes(self):
        self.assertEqual([], self.scratch.audit(self.manifest))

    def test_an_omitted_entry_is_refused_even_with_consistent_totals(self):
        self.manifest["artifacts"] = self.manifest["artifacts"][:1]
        self.manifest["artifact_count"] = 1
        self.manifest["total_bytes"] = self.manifest["artifacts"][0]["bytes"]
        findings = self.scratch.audit(self.manifest)
        self.assertFinding("UNCOVERED_FILE", findings)
        self.assertFalse([item for item in findings if item.startswith(("COUNT_", "TOTAL_"))])

    def test_a_null_hash_is_refused(self):
        self.manifest["artifacts"][0]["sha256"] = None
        self.assertFinding("HASH_MISSING", self.scratch.audit(self.manifest))

    def test_an_empty_hash_is_refused(self):
        self.manifest["artifacts"][0]["sha256"] = ""
        self.assertFinding("HASH_MISSING", self.scratch.audit(self.manifest))

    def test_a_malformed_hash_is_refused(self):
        for value in ("not-a-hash", "ABCDEF" * 10 + "abcd", "0" * 63, 12345, ["a" * 64]):
            with self.subTest(value=value):
                manifest = copy.deepcopy(self.scratch.manifest)
                manifest["artifacts"][0]["sha256"] = value
                self.assertFinding("HASH_MALFORMED", self.scratch.audit(manifest))

    def test_an_absent_hash_field_is_refused(self):
        del self.manifest["artifacts"][0]["sha256"]
        self.assertFinding("MISSING_FIELD", self.scratch.audit(self.manifest))

    def test_an_absent_byte_count_field_is_refused(self):
        del self.manifest["artifacts"][0]["bytes"]
        self.assertFinding("MISSING_FIELD", self.scratch.audit(self.manifest))

    def test_a_null_zero_negative_or_non_integer_byte_count_is_refused(self):
        for value in (None, 0, -1, "12", True, 3.0):
            with self.subTest(value=value):
                manifest = copy.deepcopy(self.scratch.manifest)
                manifest["artifacts"][0]["bytes"] = value
                findings = self.scratch.audit(manifest)
                self.assertTrue(
                    any(item.startswith(("BYTES_MISSING", "BYTES_NOT_POSITIVE_INT")) for item in findings),
                    findings,
                )

    def test_a_wrong_hash_is_refused_by_measurement(self):
        self.manifest["artifacts"][0]["sha256"] = "a" * 64
        self.assertFinding("MEASURED_HASH_MISMATCH", self.scratch.audit(self.manifest))

    def test_a_wrong_byte_count_is_refused_by_measurement(self):
        self.manifest["artifacts"][0]["bytes"] = 99999
        findings = self.scratch.audit(self.manifest)
        self.assertFinding("MEASURED_BYTES_MISMATCH", findings)
        self.assertFinding("TOTAL_BYTES_DISAGREEMENT", findings)

    def test_a_count_disagreement_is_refused(self):
        self.manifest["artifact_count"] = 99
        self.assertFinding("COUNT_DISAGREEMENT", self.scratch.audit(self.manifest))

    def test_a_total_bytes_disagreement_is_refused(self):
        self.manifest["total_bytes"] = 1
        self.assertFinding("TOTAL_BYTES_DISAGREEMENT", self.scratch.audit(self.manifest))

    def test_a_duplicate_logical_name_is_refused(self):
        self.manifest["artifacts"].append(copy.deepcopy(self.manifest["artifacts"][0]))
        self.manifest["artifact_count"] = len(self.manifest["artifacts"])
        self.manifest["total_bytes"] = sum(item["bytes"] for item in self.manifest["artifacts"])
        self.assertFinding("DUPLICATE_LOGICAL_NAME", self.scratch.audit(self.manifest))

    def test_a_locator_pointing_at_another_commit_is_refused(self):
        self.manifest["artifacts"][0]["content_uri"] = f"git:{'b' * 40}:x"
        self.assertFinding("LOCATOR_FOREIGN_COMMIT", self.scratch.audit(self.manifest))

    def test_a_locator_outside_the_slot_is_refused(self):
        self.manifest["artifacts"][0]["content_uri"] = (
            f"git:{self.scratch.artifact_commit}:state/elsewhere.json"
        )
        self.assertFinding("LOCATOR_OUTSIDE_SLOT", self.scratch.audit(self.manifest))

    def test_an_entry_for_a_file_the_commit_does_not_hold_is_refused(self):
        self.manifest["artifacts"][0]["content_uri"] = (
            f"git:{self.scratch.artifact_commit}:{self.scratch.slot}/ghost.py"
        )
        findings = self.scratch.audit(self.manifest)
        self.assertFinding("ARTIFACT_MISSING_FROM_COMMIT", findings)
        self.assertFinding("UNCOVERED_FILE", findings)

    def test_an_empty_artifact_list_is_refused(self):
        self.manifest["artifacts"] = []
        self.assertFinding("NO_ARTIFACTS", self.scratch.audit(self.manifest))

    def test_a_missing_manifest_field_is_refused(self):
        del self.manifest["total_bytes"]
        self.assertFinding("MISSING_FIELD", self.scratch.audit(self.manifest))

    def test_a_non_object_artifact_entry_is_refused(self):
        self.manifest["artifacts"][0] = "component.py"
        self.assertFinding("ARTIFACT_NOT_AN_OBJECT", self.scratch.audit(self.manifest))

    def test_a_result_disagreeing_with_its_manifest_is_refused(self):
        result = Scratch.build_result(self.manifest)
        result["result_transaction"]["artifact_count"] = 99
        findings = self.scratch.audit(self.manifest, result)
        self.assertFinding("RESULT_DISAGREES_WITH_MANIFEST", findings)

    def test_a_stale_manifest_hash_in_the_result_is_refused(self):
        result = Scratch.build_result(self.manifest)
        result["result_transaction"]["manifest_sha256"] = "c" * 64
        self.assertFinding("MANIFEST_SHA256_MISMATCH", self.scratch.audit(self.manifest, result))

    def test_a_missing_result_document_is_refused(self):
        findings = AUDITOR.audit_documents(
            self.scratch.repository, self.scratch.slot, self.manifest,
            canonical(self.manifest), None,
        )[1]
        self.assertFinding("RESULT_MISSING", findings)

    def test_a_result_without_a_transaction_block_is_refused(self):
        findings = AUDITOR.audit_documents(
            self.scratch.repository, self.scratch.slot, self.manifest,
            canonical(self.manifest), {"task_id": "x"},
        )[1]
        self.assertFinding("RESULT_UNPARSEABLE", findings)


class EndToEndCommitTests(unittest.TestCase):
    """Read real committed documents, not just in-memory candidates."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.scratch = Scratch(Path(cls.temporary.name))
        cls.head = cls.scratch.commit_documents()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_committed_clean_slot_audits_complete(self):
        summaries, findings = AUDITOR.audit(self.scratch.repository, self.head, Scratch.TASK)
        self.assertEqual([], findings)
        self.assertEqual(2, summaries[0]["covered"])

    def test_a_slot_with_no_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            bare = Scratch(Path(scratch))
            summaries, findings = AUDITOR.audit(bare.repository, bare.artifact_commit, Scratch.TASK)
            self.assertTrue(any(item.startswith("MANIFEST_MISSING") for item in findings), findings)

    def test_unknown_task_is_reported(self):
        _, findings = AUDITOR.audit(self.scratch.repository, self.head, "no-such-task")
        self.assertTrue(any(item.startswith("NO_SUCH_SLOT") for item in findings), findings)

    def test_no_slots_is_reported_rather_than_counted_as_complete(self):
        with tempfile.TemporaryDirectory() as empty:
            root = Path(empty)
            (root / "workstreams/po03").mkdir(parents=True)
            for arguments in (("init", "-q", "-b", "s", "."), ("config", "user.email", "f@e.invalid"),
                              ("config", "user.name", "f")):
                subprocess.run(("git", *arguments), cwd=root, check=True, capture_output=True)
            (root / "workstreams/po03/placeholder.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(("git", "add", "-A"), cwd=root, check=True, capture_output=True)
            subprocess.run(("git", "commit", "-qm", "empty"), cwd=root, check=True, capture_output=True)
            head = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True,
                                  capture_output=True, text=True).stdout.strip()
            _, findings = AUDITOR.audit(AUDITOR.Repository(root), head)
            self.assertTrue(any(item.startswith("NO_SLOTS_FOUND") for item in findings), findings)


class BasenameShadowingTests(unittest.TestCase):
    """The emitter excludes manifest.json at any depth; this auditor does not."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.scratch = Scratch(
            Path(cls.temporary.name),
            {"component.py": b"print(1)\n", "nested/manifest.json": b'{"hidden": true}\n'},
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_a_nested_file_named_manifest_json_must_be_covered(self):
        counted = AUDITOR.counted_files(
            self.scratch.repository, self.scratch.artifact_commit, self.scratch.slot
        )
        self.assertIn(f"{self.scratch.slot}/nested/manifest.json", counted)
        self.assertEqual([], self.scratch.audit())

    def test_an_uncovered_nested_manifest_json_is_reported(self):
        manifest = copy.deepcopy(self.scratch.manifest)
        manifest["artifacts"] = [
            item for item in manifest["artifacts"] if item["logical_name"] != "nested/manifest.json"
        ]
        manifest["artifact_count"] = len(manifest["artifacts"])
        manifest["total_bytes"] = sum(item["bytes"] for item in manifest["artifacts"])
        findings = self.scratch.audit(manifest)
        self.assertTrue(
            any(item.startswith("UNCOVERED_FILE") and "nested/manifest.json" in item
                for item in findings),
            findings,
        )

    def test_only_slot_root_generated_documents_are_excluded(self):
        self.assertEqual(("manifest.json", "result.json"), AUDITOR.DECLARED_EXCLUSIONS)


class LiveRepositoryTests(unittest.TestCase):
    """Audit the manifests the live emitter actually produced in this repository."""

    def test_every_manifested_slot_at_head_has_total_coverage(self):
        """A slot whose producer is still mid-unit has no manifest yet and is not a result."""
        repository = AUDITOR.Repository(REPO_ROOT)
        head = repository.git("rev-parse", "HEAD").decode("utf-8").strip()
        audited = 0
        for slot in repository.slots(head):
            if repository.read_blob(head, f"{slot}/manifest.json") is None:
                continue
            summary, findings = AUDITOR.audit_slot(repository, head, slot)
            self.assertEqual([], findings, slot)
            self.assertGreater(summary["covered"], 0, slot)
            self.assertGreater(summary["measured_bytes"], 0, slot)
            audited += 1
        self.assertGreaterEqual(audited, 1, "no manifested slot found to audit")

    def test_command_line_audit_of_a_manifested_slot_exits_zero(self):
        repository = AUDITOR.Repository(REPO_ROOT)
        head = repository.git("rev-parse", "HEAD").decode("utf-8").strip()
        manifested = [
            slot for slot in repository.slots(head)
            if repository.read_blob(head, f"{slot}/manifest.json") is not None
        ]
        if not manifested:
            self.skipTest("no manifested slot committed yet")
        task = manifested[0].split("/")[-1]
        result = subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), "--repo-root", str(REPO_ROOT),
             "--commit", "HEAD", "--task-id", task),
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PO03_COVERAGE_PASS", result.stdout)

    def test_a_slot_with_artifacts_but_no_manifest_is_refused_rather_than_ignored(self):
        """An in-flight or abandoned slot must not be silently counted as covered."""
        repository = AUDITOR.Repository(REPO_ROOT)
        head = repository.git("rev-parse", "HEAD").decode("utf-8").strip()
        unmanifested = [
            slot for slot in repository.slots(head)
            if repository.read_blob(head, f"{slot}/manifest.json") is None
        ]
        if not unmanifested:
            self.skipTest("every committed slot at HEAD already carries a manifest")
        _, findings = AUDITOR.audit_slot(repository, head, unmanifested[0])
        self.assertTrue(any(item.startswith("MANIFEST_MISSING") for item in findings), findings)

    def test_unknown_task_exits_one(self):
        result = subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), "--repo-root", str(REPO_ROOT),
             "--task-id", "not-a-task"),
            capture_output=True, text=True,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("NO_SUCH_SLOT", result.stderr)

    def test_non_repository_exits_two(self):
        with tempfile.TemporaryDirectory() as scratch:
            result = subprocess.run(
                (sys.executable, "-I", str(MODULE_PATH), "--repo-root", scratch),
                capture_output=True, text=True,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("PO03_COVERAGE_ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main()
