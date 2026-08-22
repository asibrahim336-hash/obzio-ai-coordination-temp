import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from immutable_readback import (  # noqa: E402
    VerificationError,
    load_manifest,
    verify_readback,
)
from reproduce_branch_movement import run_reproduction  # noqa: E402


class GitFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.producer = root / "producer"
        self.consumer = root / "consumer"
        self.branch = "results/unit-test"
        self.path = "result/artifact.bin"
        self.content = b"\x00focused-test\r\n\xff\n"

        self._run(None, "init", "--bare", str(self.origin))
        self._run(None, "init", str(self.producer))
        self._run(None, "init", str(self.consumer))
        self._run(self.producer, "config", "user.name", "PO03 Test")
        self._run(
            self.producer, "config", "user.email", "po03-test@invalid.example"
        )
        artifact = self.producer / self.path
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(self.content)
        self._run(self.producer, "add", self.path)
        self._run(self.producer, "commit", "-m", "fixture")
        self.commit = self._run(self.producer, "rev-parse", "HEAD").strip()
        self._run(self.producer, "remote", "add", "origin", str(self.origin))
        self._run(
            self.producer,
            "push",
            "origin",
            f"HEAD:refs/heads/{self.branch}",
        )

    @staticmethod
    def _run(repo: Path | None, *args: str) -> str:
        command = ["git"]
        if repo is not None:
            command.extend(("-C", str(repo)))
        command.extend(args)
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_DATE": "2026-08-22T07:20:00+00:00",
                "GIT_COMMITTER_DATE": "2026-08-22T07:20:00+00:00",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            }
        )
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        return completed.stdout

    def manifest(self, *, digest: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "path": self.path,
                "sha256": digest or hashlib.sha256(self.content).hexdigest(),
                "bytes": len(self.content),
            }
        ]


class ImmutableReadbackTests(unittest.TestCase):
    def test_exact_hypothesis_on_unrelated_forced_branch_move(self):
        with tempfile.TemporaryDirectory(prefix="wa025-reproduction-test-") as temp:
            result = run_reproduction(Path(temp))
        self.assertTrue(result["success"])
        self.assertEqual("SUPPORTED", result["hypothesis_outcome"])
        self.assertEqual(
            "FORCED_NON_FAST_FORWARD_UNRELATED_HISTORY",
            result["branch_move"]["kind"],
        )
        self.assertTrue(result["branch_move"]["detected"])
        self.assertTrue(result["branch_move"]["tracking_ref_changed"])
        self.assertTrue(result["readback"]["all_pinned_bytes_match"])
        self.assertTrue(result["readback"]["moved_tip_content_differs"])

    def test_pre_movement_control_refuses_required_move(self):
        with tempfile.TemporaryDirectory(prefix="wa025-control-test-") as temp:
            fixture = GitFixture(Path(temp))
            result = verify_readback(
                repo=fixture.consumer,
                remote=str(fixture.origin),
                branch=fixture.branch,
                expected_commit=fixture.commit,
                artifacts=fixture.manifest(),
                require_branch_moved=True,
            )
        self.assertFalse(result["branch_tip_moved_from_expected_commit"])
        self.assertFalse(result["movement_requirement_met"])
        self.assertFalse(result["success"])

    def test_digest_substitution_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="wa025-digest-test-") as temp:
            fixture = GitFixture(Path(temp))
            result = verify_readback(
                repo=fixture.consumer,
                remote=str(fixture.origin),
                branch=fixture.branch,
                expected_commit=fixture.commit,
                artifacts=fixture.manifest(digest="0" * 64),
            )
        self.assertFalse(result["artifacts"][0]["digest_matches"])
        self.assertFalse(result["all_artifacts_match"])
        self.assertFalse(result["success"])

    def test_unavailable_expected_commit_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="wa025-missing-test-") as temp:
            fixture = GitFixture(Path(temp))
            with self.assertRaisesRegex(
                VerificationError, "expected immutable commit is unavailable"
            ):
                verify_readback(
                    repo=fixture.consumer,
                    remote=str(fixture.origin),
                    branch=fixture.branch,
                    expected_commit="0" * 40,
                    artifacts=fixture.manifest(),
                )

    def test_manifest_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory(prefix="wa025-manifest-test-") as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "path": "../outside",
                                "sha256": "0" * 64,
                                "bytes": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                VerificationError, "not repository-relative"
            ):
                load_manifest(manifest)

    def test_black_box_reproduction_writes_machine_readable_result(self):
        with tempfile.TemporaryDirectory(prefix="wa025-cli-test-") as temp:
            output = Path(temp) / "result.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(HERE / "reproduce_branch_movement.py"),
                    "--output",
                    str(output),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout_document = json.loads(completed.stdout)
            file_document = json.loads(output.read_bytes())
        self.assertEqual(0, completed.returncode, completed.stderr.decode())
        self.assertTrue(stdout_document["success"])
        self.assertEqual(stdout_document, file_document)


if __name__ == "__main__":
    unittest.main()
