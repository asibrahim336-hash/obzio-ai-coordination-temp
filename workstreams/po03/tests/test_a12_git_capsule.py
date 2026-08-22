"""Tests for immutable, git-resolvable source capsules."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "capsule" / "git_capsule.py"
REPO_ROOT = Path(__file__).parents[3]
WAVE_V1_PATH = MODULE_PATH.parent / "po03-wave-a-sources-v001.json"
WAVE_V2_PATH = MODULE_PATH.parent / "po03-wave-a-sources-v002.json"
SPEC = importlib.util.spec_from_file_location("a12_git_capsule", MODULE_PATH)
CAPSULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CAPSULE)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class GitCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix=".test-git-capsule-", dir=MODULE_PATH.parent
        )
        self.addCleanup(self.tempdir.cleanup)
        self.repo = Path(self.tempdir.name) / "source"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "capsule@example.invalid")
        git(self.repo, "config", "user.name", "Capsule Test")
        (self.repo / "sources").mkdir()
        (self.repo / "sources" / "alpha.txt").write_bytes(b"alpha-v1\n\x00")
        (self.repo / "sources" / "beta.txt").write_bytes(b"beta-v1\n")
        git(self.repo, "add", "sources")
        git(self.repo, "commit", "-qm", "freeze sources")
        self.first_commit = git(self.repo, "rev-parse", "HEAD")

    def make_v1(self):
        return CAPSULE.create_capsule(
            self.repo,
            capsule_id="fixture-sources-v001",
            version=1,
            commit_sha=self.first_commit,
            paths=("sources/alpha.txt", "sources/beta.txt"),
            reason="initial immutable freeze",
        )

    def test_capsule_is_only_path_blob_commit_triples(self):
        capsule = self.make_v1()
        self.assertEqual(
            {"path", "blob_sha", "commit_sha"},
            set(capsule["entries"][0]),
        )
        self.assertEqual(
            ["sources/alpha.txt", "sources/beta.txt"],
            [entry["path"] for entry in capsule["entries"]],
        )
        for entry in capsule["entries"]:
            self.assertEqual(self.first_commit, entry["commit_sha"])
            self.assertEqual(
                git(self.repo, "rev-parse", f"{self.first_commit}:{entry['path']}"),
                entry["blob_sha"],
            )
        self.assertEqual([], CAPSULE.validate_capsule(self.repo, capsule))

    def test_bare_fresh_clone_resolves_byte_identical_content(self):
        capsule = self.make_v1()
        expected = CAPSULE.resolve_capsule(self.repo, capsule)
        bare = Path(self.tempdir.name) / "fresh-clone.git"
        subprocess.run(
            ["git", "clone", "--bare", "--no-local", str(self.repo), str(bare)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("true", git(bare, "rev-parse", "--is-bare-repository"))
        self.assertFalse((bare / ".git").exists())
        self.assertEqual(expected, CAPSULE.resolve_capsule(bare, capsule))
        self.assertEqual(b"alpha-v1\n\x00", expected["sources/alpha.txt"])

    def test_change_issues_successor_with_lineage_without_mutating_frozen_capsule(self):
        predecessor = self.make_v1()
        frozen_bytes = CAPSULE.canonical_bytes(predecessor)
        frozen_hash = CAPSULE.manifest_sha256(predecessor)
        (self.repo / "sources" / "alpha.txt").write_bytes(b"alpha-v2\n\xff")
        git(self.repo, "add", "sources/alpha.txt")
        git(self.repo, "commit", "-qm", "legitimate source repair")
        second_commit = git(self.repo, "rev-parse", "HEAD")

        successor = CAPSULE.issue_successor(
            self.repo,
            predecessor=predecessor,
            capsule_id="fixture-sources-v002",
            commit_sha=second_commit,
            reason="legitimate source repair",
        )

        self.assertEqual(frozen_bytes, CAPSULE.canonical_bytes(predecessor))
        self.assertEqual(2, successor["version"])
        self.assertEqual(
            {
                "predecessor_capsule_id": "fixture-sources-v001",
                "predecessor_manifest_sha256": frozen_hash,
                "reason": "legitimate source repair",
            },
            successor["lineage"],
        )
        self.assertEqual(
            b"alpha-v1\n\x00",
            CAPSULE.resolve_capsule(self.repo, predecessor)["sources/alpha.txt"],
        )
        self.assertEqual(
            b"alpha-v2\n\xff",
            CAPSULE.resolve_capsule(self.repo, successor)["sources/alpha.txt"],
        )
        self.assertNotEqual(
            predecessor["entries"][0]["blob_sha"],
            successor["entries"][0]["blob_sha"],
        )
        self.assertEqual([], CAPSULE.validate_lineage(predecessor, successor))

    def test_manifest_round_trip_is_canonical(self):
        capsule = self.make_v1()
        encoded = CAPSULE.canonical_bytes(capsule)
        self.assertEqual(capsule, json.loads(encoded))
        self.assertEqual(encoded, CAPSULE.canonical_bytes(json.loads(encoded)))

    def test_wave_capsules_are_git_resolvable_and_lineage_closed(self):
        predecessor = CAPSULE.load_capsule(WAVE_V1_PATH)
        successor = CAPSULE.load_capsule(WAVE_V2_PATH)
        self.assertEqual([], CAPSULE.validate_capsule(REPO_ROOT, predecessor))
        self.assertEqual([], CAPSULE.validate_capsule(REPO_ROOT, successor))
        self.assertEqual([], CAPSULE.validate_lineage(predecessor, successor))
        self.assertEqual(
            CAPSULE.manifest_sha256(predecessor),
            successor["lineage"]["predecessor_manifest_sha256"],
        )
        self.assertEqual(
            set(entry["path"] for entry in predecessor["entries"]),
            set(CAPSULE.resolve_capsule(REPO_ROOT, predecessor)),
        )
        frozen_hashes = json.loads(
            (REPO_ROOT / "workstreams/po03/control/wave-a-spec.json").read_text(
                encoding="utf-8"
            )
        )["source_hashes"]
        self.assertEqual(
            frozen_hashes,
            {
                path: hashlib.sha256(content).hexdigest()
                for path, content in CAPSULE.resolve_capsule(
                    REPO_ROOT, predecessor
                ).items()
            },
        )


if __name__ == "__main__":
    unittest.main()
