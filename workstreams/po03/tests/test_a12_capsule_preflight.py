"""Dispatch preflight tests for CURRENT / DRIFTED / MISSING source states."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
CAPSULE_DIR = REPO_ROOT / "workstreams" / "po03" / "capsule"
PREFLIGHT_PATH = CAPSULE_DIR / "preflight.py"
V1_PATH = CAPSULE_DIR / "po03-wave-a-sources-v001.json"
V2_PATH = CAPSULE_DIR / "po03-wave-a-sources-v002.json"
DRIFT_EVIDENCE_PATH = (
    REPO_ROOT / "workstreams" / "po03" / "evidence" / "source-capsule-drift.json"
)
SPEC = importlib.util.spec_from_file_location("a12_capsule_preflight", PREFLIGHT_PATH)
PREFLIGHT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREFLIGHT)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_preflight(repo: Path, capsule: Path, current_ref: str):
    return subprocess.run(
        [
            "python3",
            "-I",
            str(PREFLIGHT_PATH),
            "--repo",
            str(repo),
            "--capsule",
            str(capsule),
            "--current-ref",
            current_ref,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class CapsulePreflightTests(unittest.TestCase):
    def test_four_real_drifts_are_rejected_at_immutable_evidence_snapshot(self):
        evidence = json.loads(DRIFT_EVIDENCE_PATH.read_text(encoding="utf-8"))
        evidence_commit = git(
            REPO_ROOT,
            "log",
            "--diff-filter=A",
            "--format=%H",
            "-1",
            "--",
            str(DRIFT_EVIDENCE_PATH.relative_to(REPO_ROOT)),
        )
        evidence_snapshot = git(REPO_ROOT, "rev-parse", f"{evidence_commit}^")
        capsule = PREFLIGHT.load_capsule(V1_PATH)
        report = PREFLIGHT.classify_capsule(
            REPO_ROOT, capsule, current_ref=evidence_snapshot
        )

        expected = {
            row["path"]: (row["frozen_sha256"], row["current_sha256"])
            for row in evidence["drifted_sources"]
        }
        observed = {
            row["path"]: (row["frozen_sha256"], row["current_sha256"])
            for row in report["sources"]
            if row["state"] == "DRIFTED"
        }
        self.assertEqual("DRIFTED", report["aggregate_state"])
        self.assertEqual(expected, observed)
        self.assertEqual(4, report["summary"]["DRIFTED"])
        self.assertEqual(3, PREFLIGHT.strict_exit_code(report))

        completed = run_preflight(REPO_ROOT, V1_PATH, evidence_snapshot)
        self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("DRIFTED", json.loads(completed.stdout)["aggregate_state"])

    def test_clean_successor_capsule_passes_at_its_immutable_commit(self):
        capsule = PREFLIGHT.load_capsule(V2_PATH)
        current_ref = capsule["entries"][0]["commit_sha"]
        report = PREFLIGHT.classify_capsule(
            REPO_ROOT, capsule, current_ref=current_ref
        )
        self.assertEqual("CURRENT", report["aggregate_state"])
        self.assertEqual(
            {"CURRENT": 12, "DRIFTED": 0, "MISSING": 0},
            report["summary"],
        )
        self.assertEqual(0, PREFLIGHT.strict_exit_code(report))

        completed = run_preflight(REPO_ROOT, V2_PATH, current_ref)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("CURRENT", json.loads(completed.stdout)["aggregate_state"])

    def test_missing_source_is_distinct_and_exits_four(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "preflight@example.invalid")
            git(repo, "config", "user.name", "Preflight Test")
            (repo / "source.txt").write_text("present\n", encoding="utf-8")
            git(repo, "add", "source.txt")
            git(repo, "commit", "-qm", "freeze source")
            frozen_commit = git(repo, "rev-parse", "HEAD")
            capsule = PREFLIGHT.create_capsule(
                repo,
                capsule_id="missing-fixture-v001",
                version=1,
                commit_sha=frozen_commit,
                paths=("source.txt",),
                reason="missing fixture",
            )
            capsule_path = Path(temporary) / "capsule.json"
            capsule_path.write_bytes(PREFLIGHT.canonical_bytes(capsule))
            git(repo, "rm", "-q", "source.txt")
            git(repo, "commit", "-qm", "remove source")
            missing_commit = git(repo, "rev-parse", "HEAD")

            report = PREFLIGHT.classify_capsule(
                repo, capsule, current_ref=missing_commit
            )
            self.assertEqual("MISSING", report["aggregate_state"])
            self.assertEqual("MISSING", report["sources"][0]["state"])
            self.assertIsNone(report["sources"][0]["current_blob_sha"])
            self.assertEqual(4, PREFLIGHT.strict_exit_code(report))

            completed = run_preflight(repo, capsule_path, missing_commit)
            self.assertEqual(
                4, completed.returncode, completed.stdout + completed.stderr
            )
            self.assertEqual("MISSING", json.loads(completed.stdout)["aggregate_state"])


if __name__ == "__main__":
    unittest.main()
