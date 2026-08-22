from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

import compile_manifest
import verify_remote_readback


class ManifestCompilerTests(unittest.TestCase):
    def test_manifest_accounts_for_every_non_envelope_file(self):
        manifest = compile_manifest.build()
        expected = {
            path.relative_to(UNIT_ROOT).as_posix()
            for path in UNIT_ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and path.relative_to(UNIT_ROOT).as_posix()
            not in compile_manifest.EXCLUDED
        }
        observed = {
            artifact["logical_name"] for artifact in manifest["artifacts"]
        }
        self.assertEqual(expected, observed)
        self.assertEqual(len(expected), manifest["artifact_count"])
        self.assertEqual(
            sum(artifact["bytes"] for artifact in manifest["artifacts"]),
            manifest["total_bytes"],
        )

    def test_manifest_carries_exact_a02_identity_and_source_base(self):
        manifest = compile_manifest.build()
        self.assertEqual("PO03-WA-017-A02", manifest["attempt"]["attempt_id"])
        self.assertEqual(
            "po03:100bc2079ced:wa-017:a02",
            manifest["attempt"]["idempotency_key"],
        )
        self.assertEqual("lease-po03-wa-017-a02", manifest["attempt"]["lease_id"])
        self.assertEqual(2, manifest["attempt"]["fence_token"])
        self.assertEqual(
            "ef81e041befe9654ced9390ffd6cc046d8cdd033",
            manifest["source_base_commit"],
        )

    def test_manifest_order_and_bytes_are_deterministic(self):
        first = compile_manifest.json_bytes(compile_manifest.build())
        second = compile_manifest.json_bytes(compile_manifest.build())
        self.assertEqual(first, second)


class ImmutableReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name)
        self.git("init", "-q")
        artifact = self.repository / "unit" / "artifact.txt"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("immutable artifact\n", encoding="utf-8")
        data = artifact.read_bytes()
        manifest = {
            "artifact_count": 1,
            "artifacts": [
                {
                    "bytes": len(data),
                    "content_uri": "unit/artifact.txt",
                    "logical_name": "artifact.txt",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ],
            "total_bytes": len(data),
        }
        manifest_path = self.repository / "unit" / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "-c",
                "user.name=PO03 Test",
                "-c",
                "user.email=po03@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_git_show_readback_reconciles_manifest_and_artifact(self):
        result = verify_remote_readback.verify(
            self.repository,
            self.commit,
            "unit/manifest.json",
            self.manifest_sha,
        )
        self.assertTrue(result["all_match"])
        self.assertEqual(1, result["artifact_count"])
        self.assertEqual(self.manifest_sha, result["manifest_sha256"])

    def test_wrong_expected_manifest_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "manifest SHA-256 differs"):
            verify_remote_readback.verify(
                self.repository,
                self.commit,
                "unit/manifest.json",
                "0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
