import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = UNIT_ROOT / "result" / "verify_remote_readback.py"
SPEC = importlib.util.spec_from_file_location("wa007_readback", VERIFIER_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class ReadbackFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wa007-readback-test-")
        self.root = Path(self.temporary.name)
        self.producer = self.root / "producer"
        self.remote = self.root / "remote.git"
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.root)
        self.git("init", "-q", str(self.producer), cwd=self.root)
        self.git("config", "user.name", "WA007 Test")
        self.git("config", "user.email", "wa007@example.invalid")
        self.git("checkout", "-q", "-b", "fixture-branch")
        self.artifact_path = "payload/artifact.txt"
        self.manifest_path = "payload/artifact-manifest.json"
        artifact = self.producer / self.artifact_path
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"portable payload\n")
        manifest = {
            "artifacts": [
                {
                    "content_uri": self.artifact_path,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "bytes": len(artifact.read_bytes()),
                }
            ]
        }
        self.manifest_data = json_bytes(manifest)
        (self.producer / self.manifest_path).write_bytes(self.manifest_data)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture payload")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "-u", "origin", "fixture-branch")

    def git(self, *arguments, cwd=None):
        return subprocess.run(
            ["git", "-C", str(cwd or self.producer), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def verify(self, **overrides):
        arguments = {
            "remote": str(self.remote),
            "branch": "fixture-branch",
            "commit": self.commit,
            "manifest_path": self.manifest_path,
            "manifest_sha256": hashlib.sha256(self.manifest_data).hexdigest(),
            "manifest_bytes": len(self.manifest_data),
        }
        arguments.update(overrides)
        return VERIFIER.verify(**arguments)

    def cleanup(self):
        self.temporary.cleanup()


class ImmutableRemoteReadbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReadbackFixture()

    def tearDown(self):
        self.fixture.cleanup()

    def test_fresh_repository_readback_matches_payload_and_manifest(self):
        result = self.fixture.verify()
        self.assertTrue(result["all_match"])
        self.assertEqual(self.fixture.commit, result["remote_tip"])
        self.assertEqual(2, result["artifact_count"])
        self.assertTrue(all(check["matches"] for check in result["checks"]))

    def test_wrong_manifest_digest_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            self.fixture.verify(manifest_sha256="0" * 64)

    def test_branch_movement_is_detected(self):
        (self.fixture.producer / "later.txt").write_text("later\n", encoding="utf-8")
        self.fixture.git("add", "later.txt")
        self.fixture.git("commit", "-q", "-m", "move branch")
        self.fixture.git("push", "-q", "origin", "fixture-branch")
        with self.assertRaisesRegex(ValueError, "remote branch tip mismatch"):
            self.fixture.verify()

    def test_parent_traversal_extra_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsafe repository path"):
            self.fixture.verify(extra_specs=["../escape|%s|1" % ("0" * 64)])


if __name__ == "__main__":
    unittest.main()
