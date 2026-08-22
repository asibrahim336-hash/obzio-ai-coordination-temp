"""Falsification tests for the PO03-WA-036 manifest reconciler.

Fixtures are built in a temporary directory and then deliberately corrupted
one property at a time, so each finding is attributable to exactly one
injected defect.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "manifest_reconciler.py"
SPEC = importlib.util.spec_from_file_location("manifest_reconciler", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReconcilerFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-036-")
        self.root = Path(self._tmp.name) / "slot"
        (self.root / "src").mkdir(parents=True)
        self.files = {
            "src/component.py": b"print('component')\n",
            "notes.md": b"# notes\n\nbody text\n",
            "data.bin": bytes(range(256)) * 8,
        }
        for relative, payload in self.files.items():
            (self.root / relative).write_bytes(payload)
        self.manifest_path = self.root / "manifest.json"
        self.write_manifest(self.build_manifest())

    def tearDown(self):
        self._tmp.cleanup()

    def build_manifest(self) -> dict:
        artifacts = [
            {
                "artifact_id": f"artifact-{index}",
                "content_uri": relative,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
            }
            for index, (relative, payload) in enumerate(sorted(self.files.items()), start=1)
        ]
        return {
            "artifacts": artifacts,
            "artifact_count": len(artifacts),
            "total_bytes": sum(a["bytes"] for a in artifacts),
        }

    def write_manifest(self, document: dict) -> None:
        self.manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def run_reconcile(self) -> dict:
        return G.reconcile(self.manifest_path, self.root, excludes=["manifest.json"])

    def findings_for(self, report: dict, content_uri: str) -> str:
        for finding in report["artifact_findings"]:
            if finding["content_uri"] == content_uri:
                return finding["finding"]
        self.fail(f"no finding for {content_uri}")


class HonestManifestTests(ReconcilerFixture):
    def test_untampered_manifest_reconciles(self):
        report = self.run_reconcile()
        self.assertTrue(report["reconciled"], report)
        self.assertEqual(3, report["artifacts_matched"])
        self.assertEqual(sum(len(v) for v in self.files.values()), report["observed_total_bytes"])

    def test_hash_and_count_come_from_the_same_stream(self):
        digest, total = G.hash_and_count(self.root / "data.bin", chunk_bytes=7)
        payload = self.files["data.bin"]
        self.assertEqual(sha256_bytes(payload), digest)
        self.assertEqual(len(payload), total)

    def test_chunk_size_does_not_change_the_result(self):
        big = self.root / "big.bin"
        big.write_bytes(os.urandom(300_000))
        self.assertEqual(G.hash_and_count(big, 1024), G.hash_and_count(big, 1024 * 1024))


class CorruptionDetectionTests(ReconcilerFixture):
    def test_single_flipped_byte_is_caught_with_matching_length(self):
        payload = bytearray(self.files["data.bin"])
        payload[100] ^= 0x01
        (self.root / "data.bin").write_bytes(bytes(payload))
        report = self.run_reconcile()
        self.assertFalse(report["reconciled"])
        self.assertEqual(G.SHA_MISMATCH, self.findings_for(report, "data.bin"))

    def test_truncation_is_reported_as_a_byte_mismatch(self):
        (self.root / "notes.md").write_bytes(self.files["notes.md"][:-3])
        report = self.run_reconcile()
        self.assertEqual(G.BYTES_MISMATCH, self.findings_for(report, "notes.md"))

    def test_missing_artifact_is_caught(self):
        (self.root / "src" / "component.py").unlink()
        report = self.run_reconcile()
        self.assertEqual(G.MISSING, self.findings_for(report, "src/component.py"))

    def test_directory_in_place_of_a_file_is_caught(self):
        (self.root / "notes.md").unlink()
        (self.root / "notes.md").mkdir()
        report = self.run_reconcile()
        self.assertEqual(G.NOT_A_REGULAR_FILE, self.findings_for(report, "notes.md"))

    def test_symlink_in_place_of_a_file_is_caught(self):
        target = Path(self._tmp.name) / "elsewhere.md"
        target.write_bytes(self.files["notes.md"])
        (self.root / "notes.md").unlink()
        os.symlink(target, self.root / "notes.md")
        report = self.run_reconcile()
        self.assertEqual(G.NOT_A_REGULAR_FILE, self.findings_for(report, "notes.md"))

    def test_uppercase_hash_is_non_canonical(self):
        document = self.build_manifest()
        document["artifacts"][0]["sha256"] = document["artifacts"][0]["sha256"].upper()
        self.write_manifest(document)
        report = self.run_reconcile()
        self.assertIn(G.NON_CANONICAL_SHA, [f["finding"] for f in report["artifact_findings"]])

    def test_duplicate_artifact_id_is_caught(self):
        document = self.build_manifest()
        document["artifacts"][1]["artifact_id"] = document["artifacts"][0]["artifact_id"]
        self.write_manifest(document)
        report = self.run_reconcile()
        self.assertIn(G.DUPLICATE_ARTIFACT_ID, [f["finding"] for f in report["artifact_findings"]])

    def test_duplicate_content_uri_is_caught(self):
        document = self.build_manifest()
        duplicate = dict(document["artifacts"][0])
        duplicate["artifact_id"] = "artifact-dup"
        document["artifacts"].append(duplicate)
        self.write_manifest(document)
        report = self.run_reconcile()
        self.assertIn(G.DUPLICATE_CONTENT_URI, [f["finding"] for f in report["artifact_findings"]])

    def test_manifested_path_escaping_root_is_caught(self):
        document = self.build_manifest()
        document["artifacts"][0]["content_uri"] = "../elsewhere.md"
        self.write_manifest(document)
        report = self.run_reconcile()
        self.assertIn(G.PATH_ESCAPES_ROOT, [f["finding"] for f in report["artifact_findings"]])


class CompletenessTests(ReconcilerFixture):
    def test_omitted_artifact_is_caught_by_the_reverse_check(self):
        """A manifest cannot pass by simply not mentioning a file."""
        document = self.build_manifest()
        dropped = document["artifacts"].pop()
        document["artifact_count"] = len(document["artifacts"])
        document["total_bytes"] = sum(a["bytes"] for a in document["artifacts"])
        self.write_manifest(document)
        report = self.run_reconcile()
        self.assertFalse(report["reconciled"])
        extras = [f["content_uri"] for f in report["tree_findings"] if f["finding"] == G.UNMANIFESTED_FILE]
        self.assertIn(dropped["content_uri"], extras)

    def test_stray_file_is_reported(self):
        (self.root / "src" / "stray.tmp").write_bytes(b"x")
        report = self.run_reconcile()
        extras = [f["content_uri"] for f in report["tree_findings"] if f["finding"] == G.UNMANIFESTED_FILE]
        self.assertIn("src/stray.tmp", extras)

    def test_declared_counts_are_reconciled(self):
        document = self.build_manifest()
        document["artifact_count"] = 99
        document["total_bytes"] = 1
        self.write_manifest(document)
        report = self.run_reconcile()
        findings = {f["finding"] for f in report["tree_findings"]}
        self.assertIn("ARTIFACT_COUNT_MISMATCH", findings)
        self.assertIn("TOTAL_BYTES_MISMATCH", findings)

    def test_excluded_paths_are_not_reported_as_extras(self):
        (self.root / "scratch").mkdir()
        (self.root / "scratch" / "tmp.txt").write_bytes(b"y")
        report = G.reconcile(self.manifest_path, self.root, excludes=["manifest.json", "scratch"])
        self.assertTrue(report["reconciled"], report)


class MalformedManifestTests(ReconcilerFixture):
    def test_non_object_root_is_refused(self):
        self.manifest_path.write_text("[]", encoding="utf-8")
        with self.assertRaises(G.ManifestError):
            self.run_reconcile()

    def test_missing_artifacts_array_is_refused(self):
        self.manifest_path.write_text("{}", encoding="utf-8")
        with self.assertRaises(G.ManifestError):
            self.run_reconcile()

    def test_invalid_json_is_refused(self):
        self.manifest_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(G.ManifestError):
            self.run_reconcile()

    def test_artifact_without_content_uri_is_refused(self):
        self.write_manifest({"artifacts": [{"artifact_id": "a", "sha256": "0" * 64, "bytes": 1}]})
        with self.assertRaises(G.ManifestError):
            self.run_reconcile()


class CommandLineTests(ReconcilerFixture):
    def _run(self):
        return subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--manifest",
                str(self.manifest_path),
                "--root",
                str(self.root),
                "--exclude",
                "manifest.json",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_clean_tree_exits_zero(self):
        proc = self._run()
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["reconciled"])

    def test_corrupted_tree_exits_one(self):
        (self.root / "notes.md").write_bytes(b"tampered")
        proc = self._run()
        self.assertEqual(1, proc.returncode)
        self.assertFalse(json.loads(proc.stdout)["reconciled"])

    def test_bad_root_exits_two(self):
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--manifest", str(self.manifest_path), "--root", "/nonexistent-po03"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, proc.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
