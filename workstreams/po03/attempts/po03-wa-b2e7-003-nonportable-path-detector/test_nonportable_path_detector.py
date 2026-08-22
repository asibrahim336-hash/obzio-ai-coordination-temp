import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCANNER = HERE / "nonportable_path_detector.py"
SCRATCH = HERE / "_test_scratch"


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class NonportablePathDetectorTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)
        self.repo = SCRATCH / "repo"
        execute("git", "init", "-q", str(self.repo), cwd=SCRATCH)
        execute("git", "config", "user.email", "fixture@example.invalid", cwd=self.repo)
        execute("git", "config", "user.name", "Fixture", cwd=self.repo)

    def commit(self, files: dict[str, bytes]) -> str:
        for relative, body in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        execute("git", "add", ".", cwd=self.repo)
        result = execute("git", "commit", "-qm", "fixture", cwd=self.repo)
        self.assertEqual(0, result.returncode, result.stderr)
        return execute("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def invoke(self, commit: str, allowlist: Path | None = None) -> subprocess.CompletedProcess[str]:
        argv = [
            sys.executable,
            "-I",
            "-B",
            str(SCANNER),
            "--repo",
            str(self.repo),
            "--commit",
            commit,
        ]
        if allowlist:
            argv.extend(("--allowlist", str(allowlist)))
        return execute(*argv, cwd=HERE)

    def test_flags_machine_paths_in_committed_po03_text(self):
        commit = self.commit(
            {
                "workstreams/po03/artifact.md": (
                    b"home=/home/alice/project\ncache=~/cache\nscratch=/tmp/run\n"
                    b"checkout=/workspace/repository\n"
                ),
                "workstreams/po03/binary.bin": b"\x00/tmp/not-text",
                "outside.txt": b"/home/outside/not-scanned\n",
            }
        )
        result = self.invoke(commit)
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(4, report["finding_count"])
        self.assertEqual(
            {"home-relative", "machine-root", "temporary-root", "user-home-root"},
            {item["pattern"] for item in report["findings"]},
        )
        self.assertEqual(1, report["skipped_binary_artifacts"])

    def test_allowlist_is_path_pattern_and_line_specific(self):
        commit = self.commit(
            {"workstreams/po03/docs.md": b"deliberate example: /tmp/documented\n"}
        )
        allowlist = SCRATCH / "allowlist.json"
        allowlist.write_text(
            json.dumps(
                [
                    {
                        "path": "workstreams/po03/docs.md",
                        "pattern": "temporary-root",
                        "line": 1,
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = self.invoke(commit, allowlist)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, json.loads(result.stdout)["finding_count"])

    def test_clean_relative_paths_pass(self):
        commit = self.commit(
            {"workstreams/po03/artifact.md": b"read workstreams/po03/tests/test_example.py\n"}
        )
        result = self.invoke(commit)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], json.loads(result.stdout)["findings"])


if __name__ == "__main__":
    unittest.main()
