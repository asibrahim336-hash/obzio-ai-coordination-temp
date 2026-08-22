import hashlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "manifest.py"
SPEC = importlib.util.spec_from_file_location("manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT = shutil.which("git")


class ExclusionTests(unittest.TestCase):
    def test_manifest_excludes_itself(self):
        self.assertTrue(MODULE.is_excluded("workstreams/po03/MANIFEST.sha256"))

    def test_manifest_excludes_bytecode_caches(self):
        for path in (
            "workstreams/po03/tools/__pycache__/manifest.cpython-312.pyc",
            "workstreams/po03/__pycache__/x.pyc",
        ):
            self.assertTrue(MODULE.is_excluded(path), path)

    def test_regular_files_are_included(self):
        for path in (
            "workstreams/po03/COMMISSION.md",
            "workstreams/po03/.gitignore",
            "workstreams/po03/tools/manifest.py",
        ):
            self.assertFalse(MODULE.is_excluded(path), path)


class ManifestTextTests(unittest.TestCase):
    def test_lines_are_tab_separated_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("c.txt", "a.txt", "b.txt"):
                target = root / MODULE.SUBTREE / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(name, encoding="utf-8")
            relative = [f"{MODULE.SUBTREE}/{name}" for name in ("c.txt", "a.txt", "b.txt")]
            text = MODULE.manifest_text(root, relative)
            lines = text.splitlines()
            self.assertEqual(3, len(lines))
            self.assertEqual(sorted(lines), lines)
            for line in lines:
                path, _, digest = line.partition("\t")
                self.assertTrue(path.startswith(f"{MODULE.SUBTREE}/"))
                self.assertEqual(64, len(digest))
                self.assertEqual(digest, digest.lower())

    def test_digest_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / MODULE.SUBTREE / "a.txt"
            target.parent.mkdir(parents=True)
            payload = b"obzio-po03\n"
            target.write_bytes(payload)
            text = MODULE.manifest_text(root, [f"{MODULE.SUBTREE}/a.txt"])
            self.assertEqual(
                f"{MODULE.SUBTREE}/a.txt\t{hashlib.sha256(payload).hexdigest()}\n", text
            )

    def test_missing_worktree_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MODULE.ManifestError):
                MODULE.manifest_text(Path(tmp), [f"{MODULE.SUBTREE}/absent.txt"])

    def test_text_ends_with_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / MODULE.SUBTREE / "a.txt"
            target.parent.mkdir(parents=True)
            target.write_text("x", encoding="utf-8")
            self.assertTrue(MODULE.manifest_text(root, [f"{MODULE.SUBTREE}/a.txt"]).endswith("\n"))


@unittest.skipUnless(GIT, "git is required to enumerate tracked files")
class WriteAndVerifyTests(unittest.TestCase):
    def git(self, cwd, *args):
        return subprocess.run(
            [
                GIT,
                "-c",
                "user.email=po03@obzio.invalid",
                "-c",
                "user.name=PO-03 fixture",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def build_repo(self, root):
        self.git(root, "init", "-q", "-b", "main")
        for name in ("COMMISSION.md", "tools/thing.py", "evidence/e.json"):
            target = root / MODULE.SUBTREE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"seed {name}\n", encoding="utf-8")
        outside = root / "state" / "unrelated.json"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("{}\n", encoding="utf-8")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "seed")

    def test_write_then_verify_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            text, count = MODULE.write(root)
            self.assertEqual(3, count)
            ok, detail = MODULE.verify(root)
            self.assertTrue(ok, detail)

    def test_manifest_covers_only_the_po03_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            text, _ = MODULE.write(root)
            self.assertNotIn("state/unrelated.json", text)
            for line in text.splitlines():
                self.assertTrue(line.startswith(f"{MODULE.SUBTREE}/"), line)

    def test_verify_detects_modified_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            MODULE.write(root)
            (root / MODULE.SUBTREE / "tools" / "thing.py").write_text("tampered\n", encoding="utf-8")
            ok, detail = MODULE.verify(root)
            self.assertFalse(ok)
            self.assertIn("tools/thing.py", detail)

    def test_verify_detects_untracked_addition_only_after_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            MODULE.write(root)
            new_file = root / MODULE.SUBTREE / "evidence" / "added.json"
            new_file.write_text("{}\n", encoding="utf-8")
            ok, _ = MODULE.verify(root)
            self.assertTrue(ok, "untracked files are outside manifest scope")
            self.git(root, "add", "-A")
            ok, detail = MODULE.verify(root)
            self.assertFalse(ok)
            self.assertIn("evidence/added.json", detail)

    def test_verify_reports_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            ok, detail = MODULE.verify(root)
            self.assertFalse(ok)
            self.assertIn("missing manifest", detail)

    def test_verify_exit_code_is_nonzero_on_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            MODULE.write(root)
            (root / MODULE.SUBTREE / "COMMISSION.md").write_text("drift\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", str(MODULE_PATH), "--verify", "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("MANIFEST VERIFY: FAIL", result.stdout)

    def test_tracked_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            outside = root / "state" / "secret.txt"
            outside.write_text("outside content\n", encoding="utf-8")
            link = root / MODULE.SUBTREE / "link.txt"
            link.symlink_to(Path("..") / ".." / "state" / "secret.txt")
            self.git(root, "add", "-A")
            with self.assertRaises(MODULE.ManifestError) as caught:
                MODULE.build(root)
            self.assertIn("link.txt", str(caught.exception))
            self.assertIn("120000", str(caught.exception))

    def test_symlink_content_is_never_hashed_into_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            outside = root / "state" / "secret.txt"
            payload = b"outside content\n"
            outside.write_bytes(payload)
            link = root / MODULE.SUBTREE / "link.txt"
            link.symlink_to(Path("..") / ".." / "state" / "secret.txt")
            self.git(root, "add", "-A")
            result = subprocess.run(
                [sys.executable, "-I", str(MODULE_PATH), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, result.returncode, result.stdout)
            self.assertIn("MANIFEST ERROR", result.stdout)
            manifest = root / MODULE.MANIFEST_RELATIVE_PATH
            if manifest.exists():
                self.assertNotIn(
                    hashlib.sha256(payload).hexdigest(),
                    manifest.read_text(encoding="utf-8"),
                )

    def test_manifest_text_refuses_a_symlink_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subtree = root / MODULE.SUBTREE
            subtree.mkdir(parents=True)
            (root / "target.txt").write_text("x\n", encoding="utf-8")
            (subtree / "link.txt").symlink_to(Path("..") / ".." / "target.txt")
            with self.assertRaises(MODULE.ManifestError):
                MODULE.manifest_text(root, [f"{MODULE.SUBTREE}/link.txt"])

    def test_tracked_entries_report_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            entries = dict(
                (relative, mode) for mode, relative in MODULE.tracked_entries(root)
            )
            self.assertEqual("100644", entries[f"{MODULE.SUBTREE}/COMMISSION.md"])
            self.assertNotIn("state/unrelated.json", entries)

    def test_write_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_repo(root)
            first, _ = MODULE.write(root)
            second, _ = MODULE.write(root)
            self.assertEqual(first, second)


@unittest.skipUnless(GIT, "git is required to enumerate tracked files")
class CommittedManifestTests(unittest.TestCase):
    def test_committed_manifest_matches_this_repository(self):
        manifest = REPO_ROOT / MODULE.MANIFEST_RELATIVE_PATH
        if not manifest.exists():
            self.skipTest("manifest has not been written yet in this tree")
        ok, detail = MODULE.verify(REPO_ROOT)
        self.assertTrue(ok, f"committed manifest is stale:\n{detail}")


if __name__ == "__main__":
    unittest.main()
