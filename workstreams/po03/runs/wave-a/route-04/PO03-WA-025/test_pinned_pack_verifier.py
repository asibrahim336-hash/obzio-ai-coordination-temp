import hashlib
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("pinned_pack_verifier.py")
SPEC = importlib.util.spec_from_file_location("wa025_pinned", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PinnedPackVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, shell=False)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"],
            check=True,
            shell=False,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Fixture"],
            check=True,
            shell=False,
        )
        payload = b"pinned\n"
        (self.repo / "claimed.txt").write_bytes(payload)
        subprocess.run(["git", "-C", str(self.repo), "add", "claimed.txt"], check=True, shell=False)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture"],
            check=True,
            shell=False,
        )
        self.commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
            shell=False,
        ).stdout.strip()
        self.claim = {
            "path": "claimed.txt",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_pinned_claim_passes(self):
        report = MODULE.verify_claims(
            self.repo, {"source_commit": self.commit, "artifacts": [self.claim]}
        )
        self.assertEqual("PASS", report["disposition"])

    def test_hidden_file_only_in_worktree_is_absent_at_commit(self):
        (self.repo / "late.txt").write_text("ambient only\n", encoding="utf-8")
        late = {
            "path": "late.txt",
            "bytes": 13,
            "sha256": hashlib.sha256(b"ambient only\n").hexdigest(),
        }
        report = MODULE.verify_claims(
            self.repo, {"source_commit": self.commit, "artifacts": [self.claim, late]}
        )
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(
            "CLAIMED_FILE_ABSENT_AT_PINNED_COMMIT", report["defects"][0]["code"]
        )

    def test_adversarial_same_size_wrong_hash_fails(self):
        corrupt = dict(self.claim, sha256="0" * 64)
        report = MODULE.verify_claims(
            self.repo, {"source_commit": self.commit, "artifacts": [corrupt]}
        )
        self.assertEqual("PINNED_BYTES_MISMATCH", report["defects"][0]["code"])


if __name__ == "__main__":
    unittest.main()
