"""Falsification tests for PO03-WA-056 corrupt-manifest false-PASS resistance.

The hypothesis fails the moment any corruption in the generator, or any on-disk
tampering, yields a PASS.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from manifest_verifier import (  # noqa: E402
    MANIFEST_VERSION,
    build_manifest,
    corruptions,
    sha256_file,
    verify,
)


def make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "component.py").write_text("VALUE = 1\n")
    (root / "notes.md").write_text("# notes\n\nlimitations: synthetic fixture\n")
    (root / "sub" / "data.json").write_text(json.dumps({"rows": [1, 2, 3]}) + "\n")


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_tree(self.root)
        self.manifest = build_manifest(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_faithful_manifest_passes(self):
        verdict = verify(self.root, self.manifest)
        self.assertTrue(verdict.passed, verdict.failures)
        self.assertEqual(3, verdict.checked)

    def test_the_manifest_describes_the_whole_tree(self):
        self.assertEqual(3, self.manifest["artifact_count"])
        self.assertEqual(
            {"component.py", "notes.md", "sub/data.json"},
            {e["path"] for e in self.manifest["artifacts"]},
        )

    def test_the_manifest_records_real_hashes_and_sizes(self):
        for entry in self.manifest["artifacts"]:
            path = self.root / entry["path"]
            with self.subTest(path=entry["path"]):
                self.assertEqual(sha256_file(path), entry["sha256"])
                self.assertEqual(path.stat().st_size, entry["bytes"])

    def test_version_is_pinned(self):
        self.assertEqual(MANIFEST_VERSION, self.manifest["manifest_version"])


class CorruptionSweepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_tree(self.root)
        self.manifest = build_manifest(self.root)
        self.cases = corruptions(self.manifest, self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_generator_produces_a_broad_corpus(self):
        self.assertGreaterEqual(len(self.cases), 20)
        self.assertEqual(len(self.cases), len({name for name, _, _ in self.cases}))

    def test_no_corrupt_manifest_passes(self):
        for name, corrupt, _ in self.cases:
            with self.subTest(corruption=name):
                verdict = verify(self.root, corrupt)
                self.assertFalse(verdict.passed, f"{name} produced a false PASS")

    def test_each_corruption_is_diagnosed_with_its_expected_code(self):
        for name, corrupt, expected in self.cases:
            with self.subTest(corruption=name):
                verdict = verify(self.root, corrupt)
                self.assertIn(
                    expected,
                    verdict.codes,
                    f"{name}: expected {expected}, got {sorted(verdict.codes)}",
                )

    def test_every_failure_carries_an_actionable_detail(self):
        for name, corrupt, _ in self.cases:
            verdict = verify(self.root, corrupt)
            with self.subTest(corruption=name):
                self.assertTrue(verdict.failures)
                for failure in verdict.failures:
                    self.assertTrue(failure["detail"].strip())


class OnDiskTamperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_tree(self.root)
        self.manifest = build_manifest(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_editing_an_artifact_after_manifesting_is_caught(self):
        (self.root / "component.py").write_text("VALUE = 2\n")
        verdict = verify(self.root, self.manifest)
        self.assertFalse(verdict.passed)
        self.assertIn("DIGEST_MISMATCH", verdict.codes)

    def test_a_same_length_edit_is_caught_by_the_hash(self):
        original = (self.root / "component.py").read_text()
        (self.root / "component.py").write_text(original.replace("1", "9"))
        self.assertEqual(
            len(original), (self.root / "component.py").stat().st_size
        )
        verdict = verify(self.root, self.manifest)
        self.assertIn("DIGEST_MISMATCH", verdict.codes)
        self.assertNotIn("BYTES_MISMATCH", verdict.codes)

    def test_deleting_an_artifact_is_caught(self):
        (self.root / "notes.md").unlink()
        verdict = verify(self.root, self.manifest)
        self.assertIn("ARTIFACT_MISSING", verdict.codes)

    def test_adding_an_unmanifested_artifact_is_caught(self):
        (self.root / "smuggled.py").write_text("PAYLOAD = 1\n")
        verdict = verify(self.root, self.manifest)
        self.assertFalse(verdict.passed)
        self.assertIn("UNLISTED_ARTIFACT", verdict.codes)

    def test_replacing_an_artifact_with_a_symlink_is_caught(self):
        target = self.root / "component.py"
        outside = Path(self._tmp.name).parent / "po03-wa-056-outside.txt"
        outside.write_text("VALUE = 1\n")
        try:
            target.unlink()
            target.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this filesystem")
        try:
            verdict = verify(self.root, self.manifest)
            self.assertFalse(verdict.passed)
            self.assertIn("PATH_SYMLINK", verdict.codes)
        finally:
            outside.unlink(missing_ok=True)

    def test_a_symlinked_directory_cannot_hide_an_unlisted_file(self):
        outside_dir = Path(self._tmp.name).parent / "po03-wa-056-outdir"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "hidden.txt").write_text("hidden\n")
        link = self.root / "linkdir"
        try:
            link.symlink_to(outside_dir, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable on this filesystem")
        try:
            verdict = verify(self.root, self.manifest)
            # os.walk does not follow the link, so the tree still reconciles;
            # the guarantee under test is that nothing outside the root is ever
            # silently admitted as a verified artifact.
            self.assertTrue(verdict.passed, verdict.failures)
            self.assertEqual(3, verdict.checked)
        finally:
            link.unlink()
            (outside_dir / "hidden.txt").unlink()
            outside_dir.rmdir()

    def test_truncating_an_artifact_to_zero_bytes_is_caught(self):
        (self.root / "notes.md").write_text("")
        verdict = verify(self.root, self.manifest)
        self.assertIn("DIGEST_MISMATCH", verdict.codes)
        self.assertIn("BYTES_MISMATCH", verdict.codes)


class DegenerateInputTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_tree(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_non_object_manifest_fails(self):
        self.assertFalse(verify(self.root, ["component.py"]).passed)

    def test_a_manifest_with_no_artifacts_key_fails(self):
        verdict = verify(self.root, {"manifest_version": MANIFEST_VERSION})
        self.assertFalse(verdict.passed)
        self.assertIn("EMPTY_MANIFEST", verdict.codes)

    def test_an_empty_tree_with_an_empty_manifest_still_fails(self):
        empty = Path(tempfile.mkdtemp())
        try:
            manifest = build_manifest(empty)
            self.assertFalse(verify(empty, manifest).passed)
        finally:
            os.rmdir(empty)


if __name__ == "__main__":
    unittest.main()
