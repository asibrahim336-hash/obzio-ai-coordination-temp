"""Unit a3-u07: no claim may rest on bytes that were never committed.

This is the failure mode that lost the PO-02 Code-2 packaging return: work
existed in a working tree, the provider reported completion, and nothing durable
was ever committed, so four reported recovery routes found nothing.

The decisive test is ``test_manifest_matching_the_working_file_but_not_the_blob``.
A gate that hashes the file on disk would pass that case, because the producer
hashed exactly those bytes -- and it is precisely the case where the bytes
another process can read differ from the bytes the claim describes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "workstreams" / "po03" / "runtime" / "committed_only.py"
UNITS_DIR = REPO_ROOT / "workstreams" / "po03" / "control" / "units" / "a3"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_module(GATE_PATH, "po03_committed_only")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def result_document(artifacts: list[dict], state: str = "RESULT_COMMITTED") -> dict:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "fixture-u00",
        "obzio_state": state,
        "artifacts": [
            {
                "logical_name": Path(artifact["path"]).name,
                "content_uri": f"git:main@0000000:{artifact['path']}",
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
            }
            for artifact in artifacts
        ],
    }


@unittest.skipUnless(shutil.which("git"), "git is required")
class GateOnSyntheticRepositories(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="po03-a3-u07-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        git(self.root, "init", "--quiet", "--initial-branch", "main", ".")
        git(self.root, "config", "user.email", "po03-worker-a3@example.invalid")
        git(self.root, "config", "user.name", "po03-worker-a3")
        self.committed = self.root / "artifact.txt"
        self.committed.write_text("committed content\n", encoding="utf-8")
        git(self.root, "add", "--all")
        git(self.root, "commit", "--quiet", "--message", "fixture")

    def write_manifest(self, artifacts: list[dict], state: str = "RESULT_COMMITTED") -> Path:
        path = self.root / "manifest.json"
        path.write_text(json.dumps(result_document(artifacts, state)), encoding="utf-8")
        return path

    def sha_and_size(self, data: bytes) -> tuple[str, int]:
        return hashlib.sha256(data).hexdigest(), len(data)

    # -- tree check ------------------------------------------------------

    def test_clean_tree_passes(self) -> None:
        check = gate.check_tree(self.root)
        self.assertEqual(check["verdict"], "PASS", check)
        self.assertEqual(check["dirty_count"], 0)

    def test_modified_tracked_file_fails(self) -> None:
        self.committed.write_text("modified in the working tree\n", encoding="utf-8")
        check = gate.check_tree(self.root)
        self.assertEqual(check["verdict"], "FAIL")
        self.assertEqual([entry["path"] for entry in check["dirty_entries"]], ["artifact.txt"])

    def test_untracked_content_file_fails(self) -> None:
        (self.root / "never-pushed.json").write_text("{}", encoding="utf-8")
        check = gate.check_tree(self.root)
        self.assertEqual(check["verdict"], "FAIL")
        self.assertIn("never-pushed.json", [entry["path"] for entry in check["dirty_entries"]])

    def test_bytecode_only_dirt_passes_but_is_counted(self) -> None:
        cache = self.root / "pkg" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "mod.cpython-312.pyc").write_bytes(b"\x00\x01")
        check = gate.check_tree(self.root)
        self.assertEqual(check["verdict"], "PASS", check)
        self.assertEqual(check["dirty_count"], 0)
        self.assertEqual(check["bytecode_count"], 1)

    def test_rename_reports_the_destination_path(self) -> None:
        entries = gate.parse_porcelain("R  old/name.txt -> new/name.txt\n")
        self.assertEqual(entries, [{"status": "R", "path": "new/name.txt"}])

    # -- manifest check --------------------------------------------------

    def test_manifest_of_committed_bytes_passes(self) -> None:
        blob = self.committed.read_bytes()
        sha, size = self.sha_and_size(blob)
        manifest = self.write_manifest([{"path": "artifact.txt", "sha256": sha, "bytes": size}])
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "PASS", check)
        self.assertEqual(check["verified_count"], 1)

    def test_manifest_referencing_an_untracked_path_fails(self) -> None:
        never_pushed = self.root / "never-pushed.json"
        never_pushed.write_text('{"claim": "exists only here"}', encoding="utf-8")
        sha, size = self.sha_and_size(never_pushed.read_bytes())
        manifest = self.write_manifest([{"path": "never-pushed.json", "sha256": sha, "bytes": size}])
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "FAIL")
        self.assertEqual(check["findings"][0]["path"], "never-pushed.json")
        self.assertIn("not tracked by git", check["findings"][0]["reason"])

    def test_manifest_matching_the_working_file_but_not_the_blob(self) -> None:
        """The case a working-tree hash check would wrongly pass.

        The producer hashed the bytes on disk, and those bytes are not what any
        other process can read at the recorded revision.
        """
        self.committed.write_text("uncommitted revision of the artifact\n", encoding="utf-8")
        working_sha, working_size = self.sha_and_size(self.committed.read_bytes())
        manifest = self.write_manifest(
            [{"path": "artifact.txt", "sha256": working_sha, "bytes": working_size}]
        )
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "FAIL", check)
        self.assertIn("does not match manifest", check["findings"][0]["reason"])

    def test_manifest_with_a_wrong_byte_count_fails(self) -> None:
        blob = self.committed.read_bytes()
        sha, size = self.sha_and_size(blob)
        manifest = self.write_manifest([{"path": "artifact.txt", "sha256": sha, "bytes": size + 1}])
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "FAIL")
        self.assertIn("bytes", check["findings"][0]["reason"])

    def test_manifest_referencing_a_path_absent_from_the_revision_fails(self) -> None:
        later = self.root / "added-later.txt"
        later.write_text("added after the fixture commit\n", encoding="utf-8")
        git(self.root, "add", "--all")
        sha, size = self.sha_and_size(later.read_bytes())
        manifest = self.write_manifest([{"path": "added-later.txt", "sha256": sha, "bytes": size}])
        # Staged but not committed: tracked, yet absent from HEAD.
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "FAIL")
        self.assertIn("not present in HEAD", check["findings"][0]["reason"])

    def test_committed_manifest_with_no_artifacts_fails(self) -> None:
        manifest = self.write_manifest([])
        check = gate.check_manifest(self.root, manifest, "HEAD")
        self.assertEqual(check["verdict"], "FAIL")
        self.assertIn("references no artifacts", check["findings"][0]["reason"])

    def test_non_result_document_is_skipped_not_silently_passed(self) -> None:
        path = self.root / "canary.json"
        path.write_text(json.dumps({"worker_id": "x", "nonce": "y"}), encoding="utf-8")
        check = gate.check_manifest(self.root, path, "HEAD")
        self.assertEqual(check["verdict"], "SKIP")
        self.assertIn("not a OBZIO-TRANSACTIONAL-RESULT-v1", check["skip_reason"])


class GateOnTheRealRepository(unittest.TestCase):
    def test_every_committed_a3_result_verifies_against_head(self) -> None:
        manifests = sorted(UNITS_DIR.glob("a3-u*.json"))
        self.assertTrue(manifests, "no a3 result documents to verify")
        for manifest in manifests:
            check = gate.check_manifest(REPO_ROOT, manifest, "HEAD")
            self.assertEqual(check["verdict"], "PASS", f"{manifest.name}: {check['findings']}")
            self.assertEqual(check["verified_count"], check["referenced_count"])

    def test_no_a3_result_references_an_untracked_path(self) -> None:
        tracked = gate.tracked_paths(REPO_ROOT)
        for manifest in sorted(UNITS_DIR.glob("a3-u*.json")):
            document = json.loads(manifest.read_text(encoding="utf-8"))
            for reference in gate.manifest_paths(document):
                self.assertIn(reference["path"], tracked, f"{manifest.name} -> {reference['path']}")


class CommandLineBehaviour(unittest.TestCase):
    def run_gate(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(GATE_PATH), *args],
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
        )

    def test_real_manifests_pass_with_the_tree_check_skipped(self) -> None:
        result = self.run_gate(
            "--skip-tree", "--manifest-dir", str(UNITS_DIR), "--root", str(REPO_ROOT)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS committed-only gate", result.stdout)

    def test_json_report_shape(self) -> None:
        result = self.run_gate(
            "--skip-tree", "--manifest-dir", str(UNITS_DIR), "--root", str(REPO_ROOT), "--json"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-committed-only-report-v1")
        self.assertGreater(report["manifests_checked"], 0)
        self.assertEqual(report["verdict"], "PASS")

    def test_only_skippable_manifests_is_an_error_not_a_pass(self) -> None:
        """A run that verified nothing must not be reported as verified."""
        with tempfile.TemporaryDirectory() as scratch:
            decoy = Path(scratch) / "decoy.json"
            decoy.write_text(json.dumps({"not": "a result"}), encoding="utf-8")
            result = self.run_gate(
                "--skip-tree", "--manifest", str(decoy), "--root", str(REPO_ROOT)
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("COMMITTED_ONLY_ERROR", result.stderr)

    def test_no_checks_requested_is_an_error(self) -> None:
        result = self.run_gate("--skip-tree", "--root", str(REPO_ROOT))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("nothing to check", result.stderr)

    def test_unreadable_manifest_fails_closed(self) -> None:
        result = self.run_gate(
            "--skip-tree", "--manifest", str(REPO_ROOT / "does-not-exist.json"), "--root", str(REPO_ROOT)
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
