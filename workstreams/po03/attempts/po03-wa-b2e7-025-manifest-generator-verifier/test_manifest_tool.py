"""Tests for the PO-03 manifest generator and verifier.

The hypothesis under test is that every committed PO-03 artifact is covered by
a manifest entry with a matching hash and byte count, and that any gap fails
closed.  Each test names one way coverage can be broken and asserts the
verifier refuses rather than reports success.
"""

import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
MODULE_PATH = UNIT_ROOT / "manifest_tool.py"
SPEC = importlib.util.spec_from_file_location("po03_manifest_tool", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MANIFEST_TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANIFEST_TOOL)

REPO_ROOT = UNIT_ROOT.parents[3]


def write(root: Path, relative: str, payload: bytes) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_manifest_records_measured_hash_and_byte_count(self):
        write(self.root, "component.py", b"print(1)\n")
        write(self.root, "nested/data.json", b'{"a":1}\n')
        text = MANIFEST_TOOL.generate(MANIFEST_TOOL.DirectorySource(self.root))
        entries, trailer, findings = MANIFEST_TOOL.parse(text)
        self.assertEqual([], findings)
        self.assertEqual(
            {
                "component.py": (hashlib.sha256(b"print(1)\n").hexdigest(), 9),
                "nested/data.json": (hashlib.sha256(b'{"a":1}\n').hexdigest(), 8),
            },
            entries,
        )
        self.assertEqual((2, 17), trailer)

    def test_generated_manifest_verifies_against_its_own_source(self):
        write(self.root, "a.txt", b"alpha\n")
        write(self.root, "b/c.txt", b"charlie\n")
        source = MANIFEST_TOOL.DirectorySource(self.root)
        self.assertEqual([], MANIFEST_TOOL.verify(source, MANIFEST_TOOL.generate(source)))

    def test_generation_is_deterministic_and_path_sorted(self):
        write(self.root, "z.txt", b"z\n")
        write(self.root, "a.txt", b"a\n")
        source = MANIFEST_TOOL.DirectorySource(self.root)
        first = MANIFEST_TOOL.generate(source)
        self.assertEqual(first, MANIFEST_TOOL.generate(source))
        paths = [line.split("  ")[2] for line in first.splitlines() if line.startswith(("a", "z")) and "  " in line]
        self.assertEqual(sorted(paths), paths)

    def test_symlink_in_source_is_refused_rather_than_followed(self):
        write(self.root, "real.txt", b"real\n")
        (self.root / "link.txt").symlink_to("real.txt")
        with self.assertRaises(MANIFEST_TOOL.ManifestError):
            MANIFEST_TOOL.DirectorySource(self.root).paths()


class VerifyFailsClosedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        write(self.root, "one.txt", b"one\n")
        write(self.root, "two.txt", b"two\n")
        self.source = MANIFEST_TOOL.DirectorySource(self.root)
        self.manifest = MANIFEST_TOOL.generate(self.source)

    def findings(self, text):
        return MANIFEST_TOOL.verify(self.source, text)

    def test_uncovered_file_fails_closed(self):
        write(self.root, "three.txt", b"three\n")
        findings = self.findings(self.manifest)
        self.assertIn("UNCOVERED_FILE path=three.txt", findings)

    def test_uncovered_file_fails_even_when_trailer_is_forged_consistent(self):
        write(self.root, "hidden.txt", b"hidden\n")
        forged = MANIFEST_TOOL.generate(self.source)
        kept = [line for line in forged.splitlines() if "hidden.txt" not in line]
        kept = [line for line in kept if not line.startswith("TOTAL ")]
        entries = [line for line in kept if line.count("  ") == 2]
        total = sum(int(line.split("  ")[1]) for line in entries)
        forged = "\n".join(kept + [f"TOTAL {len(entries)} {total}"]) + "\n"
        findings = self.findings(forged)
        self.assertIn("UNCOVERED_FILE path=hidden.txt", findings)
        self.assertFalse([item for item in findings if item.startswith("TRAILER_")])

    def test_missing_file_fails_closed(self):
        (self.root / "two.txt").unlink()
        self.assertIn("MISSING_FILE path=two.txt", self.findings(self.manifest))

    def test_hash_mismatch_fails_closed(self):
        (self.root / "one.txt").write_bytes(b"ONE\n")
        findings = self.findings(self.manifest)
        self.assertTrue(any(item.startswith("HASH_MISMATCH path=one.txt") for item in findings), findings)

    def test_byte_count_mismatch_fails_closed(self):
        (self.root / "one.txt").write_bytes(b"one and more\n")
        findings = self.findings(self.manifest)
        self.assertTrue(any(item.startswith("BYTE_MISMATCH path=one.txt") for item in findings), findings)

    def test_duplicate_entry_is_reported(self):
        line = [item for item in self.manifest.splitlines() if item.endswith("one.txt")][0]
        doubled = self.manifest.replace(line, line + "\n" + line, 1)
        self.assertTrue(any(item.startswith("DUPLICATE_ENTRY") for item in self.findings(doubled)))

    def test_bad_header_is_refused_before_any_hashing(self):
        findings = self.findings(self.manifest.replace(MANIFEST_TOOL.HEADER, "PO03-MANIFEST-v0", 1))
        self.assertEqual(1, len(findings))
        self.assertTrue(findings[0].startswith("BAD_HEADER"))

    def test_malformed_hash_line_is_refused(self):
        broken = self.manifest.replace(hashlib.sha256(b"one\n").hexdigest(), "not-a-hash", 1)
        findings = self.findings(broken)
        self.assertTrue(any(item.startswith("MALFORMED_LINE") for item in findings), findings)
        self.assertIn("UNCOVERED_FILE path=one.txt", findings)

    def test_missing_trailer_is_refused(self):
        stripped = "\n".join(
            line for line in self.manifest.splitlines() if not line.startswith("TOTAL ")
        ) + "\n"
        self.assertIn("MISSING_TRAILER", self.findings(stripped))

    def test_trailer_count_disagreement_is_refused(self):
        tampered = self.manifest.replace("TOTAL 2 ", "TOTAL 5 ", 1)
        findings = self.findings(tampered)
        self.assertTrue(any(item.startswith("TRAILER_COUNT_MISMATCH") for item in findings), findings)

    def test_empty_source_and_empty_manifest_still_fails_closed(self):
        for path in ("one.txt", "two.txt"):
            (self.root / path).unlink()
        empty = MANIFEST_TOOL.generate(self.source)
        self.assertIn("EMPTY_MANIFEST no artifacts covered", self.findings(empty))

    def test_unsafe_manifest_path_is_refused(self):
        injected = self.manifest.replace("one.txt", "../escape.txt", 1)
        findings = self.findings(injected)
        self.assertTrue(any(item.startswith("UNSAFE_PATH") for item in findings), findings)


class GitSourceTests(unittest.TestCase):
    """Coverage measured against committed bytes at an immutable commit."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        write(self.repo, "slot/component.py", b"print(2)\n")
        write(self.repo, "slot/notes.txt", b"notes\n")
        self.git("add", "slot")
        self.git("commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        return subprocess.run(
            ("git", *arguments), cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout

    def test_git_source_manifest_verifies(self):
        source = MANIFEST_TOOL.GitSource(self.repo, self.commit, "slot")
        self.assertEqual([], MANIFEST_TOOL.verify(source, MANIFEST_TOOL.generate(source)))

    def test_committed_manifest_survives_working_tree_tampering(self):
        source = MANIFEST_TOOL.GitSource(self.repo, self.commit, "slot")
        manifest = MANIFEST_TOOL.generate(source)
        (self.repo / "slot/component.py").write_bytes(b"print(666)\n")
        self.assertEqual([], MANIFEST_TOOL.verify(source, manifest))
        working_tree_findings = MANIFEST_TOOL.verify(
            MANIFEST_TOOL.DirectorySource(self.repo / "slot"), manifest
        )
        self.assertTrue(
            any(item.startswith("HASH_MISMATCH") for item in working_tree_findings),
            working_tree_findings,
        )

    def test_unstaged_file_is_invisible_to_a_git_source_but_caught_by_a_directory_source(self):
        """The stated limitation of commit-scoped coverage, asserted rather than assumed."""
        write(self.repo, "slot/forgotten.py", b"never staged\n")
        git_source = MANIFEST_TOOL.GitSource(self.repo, self.commit, "slot")
        manifest = MANIFEST_TOOL.generate(git_source)
        self.assertEqual([], MANIFEST_TOOL.verify(git_source, manifest))
        directory_findings = MANIFEST_TOOL.verify(
            MANIFEST_TOOL.DirectorySource(self.repo / "slot"), manifest
        )
        self.assertIn("UNCOVERED_FILE path=forgotten.py", directory_findings)

    def test_later_commit_changing_a_byte_breaks_the_earlier_manifest(self):
        source = MANIFEST_TOOL.GitSource(self.repo, self.commit, "slot")
        manifest = MANIFEST_TOOL.generate(source)
        (self.repo / "slot/notes.txt").write_bytes(b"notes!\n")
        self.git("add", "slot/notes.txt")
        self.git("commit", "-qm", "mutate")
        later = self.git("rev-parse", "HEAD").strip()
        findings = MANIFEST_TOOL.verify(MANIFEST_TOOL.GitSource(self.repo, later, "slot"), manifest)
        self.assertTrue(any(item.startswith("HASH_MISMATCH path=notes.txt") for item in findings), findings)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        write(self.root, "tree/a.txt", b"a\n")

    def run_cli(self, *arguments):
        return subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), *arguments),
            capture_output=True,
            text=True,
        )

    def test_generate_then_verify_exits_zero(self):
        manifest = self.root / "MANIFEST"
        generated = self.run_cli("generate", "--dir", str(self.root / "tree"), "--out", str(manifest))
        self.assertEqual(0, generated.returncode, generated.stderr)
        verified = self.run_cli("verify", "--dir", str(self.root / "tree"), "--manifest", str(manifest))
        self.assertEqual(0, verified.returncode, verified.stderr)
        self.assertIn("PO03_MANIFEST_PASS", verified.stdout)

    def test_uncovered_file_exits_one_from_the_command_line(self):
        manifest = self.root / "MANIFEST"
        self.run_cli("generate", "--dir", str(self.root / "tree"), "--out", str(manifest))
        write(self.root, "tree/b.txt", b"b\n")
        verified = self.run_cli("verify", "--dir", str(self.root / "tree"), "--manifest", str(manifest))
        self.assertEqual(1, verified.returncode)
        self.assertIn("PO03_MANIFEST_VIOLATION: UNCOVERED_FILE path=b.txt", verified.stderr)

    def test_missing_source_exits_two(self):
        result = self.run_cli("verify", "--dir", str(self.root / "absent"), "--manifest", "/dev/null")
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_MANIFEST_ERROR", result.stderr)


class RealRepositoryTests(unittest.TestCase):
    """Exercise the tool against this unit's own bytes in the live repository."""

    def test_this_unit_subtree_is_fully_covered_by_a_generated_manifest(self):
        # Snapshot first: the live subtree holds the evidence file this very run
        # is still writing, and hashing a growing file would be a false alarm.
        with tempfile.TemporaryDirectory() as scratch:
            snapshot = Path(scratch) / "subtree"
            shutil.copytree(
                UNIT_ROOT,
                snapshot,
                ignore=shutil.ignore_patterns("__pycache__", "evidence"),
                symlinks=True,
            )
            source = MANIFEST_TOOL.DirectorySource(snapshot)
            self.assertEqual([], MANIFEST_TOOL.verify(source, MANIFEST_TOOL.generate(source)))
            self.assertIn("manifest_tool.py", source.paths())

    def test_head_commit_of_this_unit_subtree_is_enumerable(self):
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        prefix = UNIT_ROOT.relative_to(REPO_ROOT).as_posix()
        listing = subprocess.run(
            ("git", "ls-tree", "-r", "--name-only", head, "--", prefix),
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if not listing.strip():
            self.skipTest("unit subtree is not committed yet at HEAD")
        source = MANIFEST_TOOL.GitSource(REPO_ROOT, head, prefix)
        self.assertEqual([], MANIFEST_TOOL.verify(source, MANIFEST_TOOL.generate(source)))


if __name__ == "__main__":
    unittest.main()
