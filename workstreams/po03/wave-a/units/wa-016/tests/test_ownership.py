"""The producer writes only its declared subtree and causes no external effect.

The frozen input names one allowed write glob, a prohibited list and a read-only
list.  This module checks that the harness as shipped can only write inside the
allowed glob: it runs the whole evidence-writing entry point and compares the
repository before and after.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness.run_harness import EVIDENCE_DIR, UNIT_ROOT, collect, write_evidence
from harness.seeded import repository_root, task_input

OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-016/"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout


def _dirty_paths(repo: Path) -> set[str]:
    """Every path git reports as changed or untracked, excluding caches."""
    lines = _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    paths = set()
    for line in lines:
        path = line[3:].strip()
        if "__pycache__" in path or path.endswith(".pyc"):
            continue
        paths.add(path)
    return paths


class DeclaredOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ownership = task_input()["ownership"]

    def test_exactly_one_write_glob_is_allowed_and_it_is_this_unit(self):
        self.assertEqual([f"{OWNED_PREFIX}**"], self.ownership["allowed_write_globs"])

    def test_the_result_slot_is_inside_the_allowed_glob(self):
        self.assertTrue(self.ownership["result_slot"].startswith(OWNED_PREFIX))

    def test_the_runner_branch_carries_the_declared_prefix(self):
        branch = _git(repository_root(), "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.assertTrue(
            branch.startswith(self.ownership["remote_branch_prefix"]),
            f"{branch} does not start with {self.ownership['remote_branch_prefix']}",
        )

    def test_no_prohibited_or_read_only_path_overlaps_the_owned_subtree(self):
        for glob in self.ownership["prohibited_globs"] + self.ownership["read_only_globs"]:
            self.assertFalse(glob.startswith(OWNED_PREFIX), glob)


class SourceDisciplineTests(unittest.TestCase):
    """Static check: nothing in the harness names a path outside the subtree.

    A dynamic check alone would only prove that this particular run behaved; the
    combination proves the code has no such path to take.
    """

    def setUp(self) -> None:
        self.modules = {p.name: p.read_text(encoding="utf-8") for p in (UNIT_ROOT / "harness").glob("*.py")}

    def _absent(self, needle: str, haystack: str, where: str) -> None:
        """assertNotIn on a whole module would print the module on failure."""
        self.assertTrue(needle not in haystack, f"{where}: unexpected {needle!r}")

    def test_no_module_names_a_prohibited_path_as_a_string_literal(self):
        for name, source in sorted(self.modules.items()):
            for literal in ('"state/', '"dispatch/', '"receipts/po01', '"workstreams/po01', "environment.json"):
                self._absent(literal, source, name)

    def test_the_seeded_controls_are_only_ever_read(self):
        read_only = ("workstreams/po03/tools", "workstreams/po03/contracts", "workstreams/po03/tests")
        for name, source in sorted(self.modules.items()):
            for number, line in enumerate(source.splitlines(), 1):
                if not any(prefix in line for prefix in read_only):
                    continue
                for verb in ("write_text", "write_bytes", "unlink", "mkdir", "os.replace"):
                    self._absent(verb, line, f"{name}:{number}")

    def test_the_harness_imports_no_network_client(self):
        clients = {"urllib", "requests", "http", "https", "socket", "ssl", "ftplib", "smtplib", "asyncio"}
        for name, source in sorted(self.modules.items()):
            for line in source.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                tokens = set(stripped.replace(",", " ").replace(".", " ").split())
                self.assertEqual(set(), tokens & clients, f"{name}: {stripped}")

    def test_the_only_git_remote_the_probe_uses_is_a_local_file_url(self):
        probe = self.modules["git_custody_probe.py"]
        self.assertIn("as_uri()", probe)
        for scheme in ("https://", "http://", "git@", "ssh://"):
            self._absent(scheme, probe, "git_custody_probe.py")

    def test_the_recorded_source_urls_are_data_and_are_never_fetched(self):
        """research.py holds URLs already retrieved; it must not retrieve them."""
        from harness import research

        self.assertIn("https://", self.modules["research.py"])
        # A purely declarative module: nothing it imports can reach the network
        # or the filesystem, so the recorded URLs cannot be re-fetched here.
        for line in self.modules["research.py"].splitlines():
            if line.startswith(("import ", "from ")):
                self.assertIn(line.strip(), {"from __future__ import annotations", "from typing import Any"})
        self.assertEqual(
            {"evaluate", "resolve_mechanisms"},
            {
                name
                for name, value in vars(research).items()
                if not name.startswith("_") and getattr(value, "__module__", None) == research.__name__
            },
        )


class WriteContainmentTests(unittest.TestCase):
    """Run the real entry point and prove nothing outside the subtree moved."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repository_root()
        try:
            _git(cls.repo, "rev-parse", "--git-dir")
        except (subprocess.CalledProcessError, OSError) as exc:
            raise unittest.SkipTest(f"git unavailable: {exc}") from exc

    def test_writing_the_evidence_touches_only_the_owned_subtree(self):
        # Written to a scratch directory so this test cannot overwrite the
        # evidence of the full campaign that result.json reports.
        scratch = Path(tempfile.mkdtemp(prefix=".scratch-evidence-", dir=UNIT_ROOT))
        self.addCleanup(shutil.rmtree, scratch, True)

        before = _dirty_paths(self.repo)
        # A small campaign: this test is about where bytes land, not how many.
        evidence = collect(fuzz_cases=12, fuzz_max_faults=3)
        written = write_evidence(evidence, target=scratch)
        after = _dirty_paths(self.repo)

        for path in after - before:
            self.assertTrue(path.startswith(OWNED_PREFIX), f"wrote outside the owned subtree: {path}")
        self.assertTrue(written)
        for entry in written:
            self.assertTrue((UNIT_ROOT / entry["path"]).exists(), entry["path"])
            self.assertGreater(entry["bytes"], 0)
            self.assertEqual(64, len(entry["sha256"]))

    def test_the_evidence_directory_is_inside_the_owned_subtree(self):
        self.assertEqual(
            OWNED_PREFIX.rstrip("/") + "/evidence",
            EVIDENCE_DIR.relative_to(self.repo).as_posix(),
        )

    def test_no_temporary_working_directory_is_left_inside_the_repository(self):
        stray = [p for p in UNIT_ROOT.rglob(".scratch-*") if p.is_dir()]
        self.assertEqual([], stray)


if __name__ == "__main__":
    unittest.main()
