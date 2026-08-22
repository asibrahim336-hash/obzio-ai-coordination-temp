"""Falsification tests for the PO03-WA-037 transport debris disposition.

The load-bearing assertion in this slot is negative: after a full scan and
disposition pass, a byte-level census of the fixture tree must be identical
to the census taken before the run.  A component that classified correctly
but removed a single file would fail these tests.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "transport_debris_disposition.py"
SPEC = importlib.util.spec_from_file_location("transport_debris_disposition", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


CONFLICTED = b"head\n<<<<<<< ours\na\n=======\nb\n>>>>>>> theirs\ntail\n"


class DebrisFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-037-")
        self.root = Path(self._tmp.name) / "tree"
        (self.root / "src" / "__pycache__").mkdir(parents=True)
        (self.root / "docs").mkdir(parents=True)
        self.layout = {
            "src/component.py": b"print('authored content')\n",
            "src/__pycache__/component.cpython-312.pyc": b"\x00\x00fake bytecode\n",
            "docs/notes.md": b"# authored notes\n",
            "docs/.DS_Store": b"macos metadata\x00",
            "docs/notes.md.orig": b"# pre-merge original\n",
            "docs/patch.rej": b"@@ rejected hunk @@\n",
            "docs/draft.md~": b"editor backup\n",
            "docs/._resource": b"AppleDouble\n",
            "docs/conflicted.md": CONFLICTED,
            "docs/empty.log": b"",
        }
        for relative, payload in self.layout.items():
            (self.root / relative).write_bytes(payload)

    def tearDown(self):
        self._tmp.cleanup()

    def dispositions(self):
        return {f.path: f.disposition for f in G.scan(self.root)}

    def rules(self):
        return {f.path: f.rule_id for f in G.scan(self.root)}


class ClassificationTests(DebrisFixture):
    def test_authored_content_is_not_flagged(self):
        found = self.dispositions()
        self.assertNotIn("src/component.py", found)
        self.assertNotIn("docs/notes.md", found)

    def test_bytecode_cache_is_an_ignore_rule(self):
        self.assertEqual(
            G.IGNORE_RULE, self.dispositions()["src/__pycache__/component.cpython-312.pyc"]
        )

    def test_platform_metadata_is_an_ignore_rule(self):
        self.assertEqual(G.IGNORE_RULE, self.dispositions()["docs/.DS_Store"])

    def test_merge_leftovers_are_retained_as_evidence(self):
        found = self.dispositions()
        self.assertEqual(G.RETAIN_AS_EVIDENCE, found["docs/notes.md.orig"])
        self.assertEqual(G.RETAIN_AS_EVIDENCE, found["docs/patch.rej"])

    def test_editor_backup_is_quarantine_recorded(self):
        self.assertEqual(G.QUARANTINE_RECORD, self.dispositions()["docs/draft.md~"])

    def test_apple_double_residue_is_quarantine_recorded(self):
        self.assertEqual(G.QUARANTINE_RECORD, self.dispositions()["docs/._resource"])

    def test_conflict_markers_are_detected_by_content_not_name(self):
        self.assertEqual(G.RETAIN_AS_EVIDENCE, self.dispositions()["docs/conflicted.md"])
        self.assertEqual("conflict-markers", self.rules()["docs/conflicted.md"])

    def test_partial_conflict_marker_set_is_not_a_false_positive(self):
        (self.root / "docs" / "prose.md").write_bytes(b"a line with ======= in it\n")
        self.assertNotIn("docs/prose.md", self.dispositions())

    def test_zero_byte_file_requires_review(self):
        self.assertEqual(G.REVIEW_REQUIRED, self.dispositions()["docs/empty.log"])

    def test_every_finding_carries_a_digest_and_byte_count(self):
        for finding in G.scan(self.root):
            payload = (self.root / finding.path).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), finding.sha256)
            self.assertEqual(len(payload), finding.bytes)

    def test_symlinks_are_not_classified_or_followed(self):
        os.symlink(self.root / "docs" / "notes.md", self.root / "docs" / "link.orig")
        self.assertNotIn("docs/link.orig", self.dispositions())


class NonDestructivenessTests(DebrisFixture):
    def test_census_is_identical_before_and_after_a_scan(self):
        before = G.census(self.root)
        G.scan(self.root)
        after = G.census(self.root)
        self.assertEqual([], G.verify_census_unchanged(before, after))
        self.assertEqual(len(self.layout), len(after))

    def test_census_detects_a_deletion_when_one_actually_happens(self):
        """Control case: the census would have caught a destructive run."""
        before = G.census(self.root)
        (self.root / "docs" / "patch.rej").unlink()
        violations = G.verify_census_unchanged(before, G.census(self.root))
        self.assertEqual(["DELETED: docs/patch.rej"], violations)

    def test_census_detects_modification(self):
        before = G.census(self.root)
        (self.root / "docs" / "notes.md").write_bytes(b"changed\n")
        self.assertEqual(["MODIFIED: docs/notes.md"], G.verify_census_unchanged(before, G.census(self.root)))

    def test_census_detects_creation(self):
        before = G.census(self.root)
        (self.root / "docs" / "new.md").write_bytes(b"new\n")
        self.assertEqual(["CREATED: docs/new.md"], G.verify_census_unchanged(before, G.census(self.root)))

    def test_module_source_contains_no_deletion_path(self):
        self.assertEqual([], G.self_audit(MODULE_PATH))

    def test_self_audit_catches_a_deletion_path_when_present(self):
        """Control case: the static audit is not vacuous."""
        planted = Path(self._tmp.name) / "planted.py"
        planted.write_text(
            "import os, shutil\n"
            "def cleanup(p):\n"
            "    os.unlink(p)\n"
            "    shutil.rmtree(p)\n"
            "    open(p, 'w').write('x')\n",
            encoding="utf-8",
        )
        offences = G.self_audit(planted)
        self.assertTrue(any("unlink" in o for o in offences), offences)
        self.assertTrue(any("rmtree" in o for o in offences), offences)
        self.assertTrue(any("writable open mode" in o for o in offences), offences)


class CommandLineTests(DebrisFixture):
    def _run(self, *extra: str):
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), "--root", str(self.root), "--json", *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_delete_policy_is_refused_with_exit_three(self):
        before = G.census(self.root)
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--root", str(self.root), "--policy", "delete"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(3, proc.returncode)
        self.assertIn("DELETION_PROHIBITED", proc.stderr)
        self.assertEqual([], G.verify_census_unchanged(before, G.census(self.root)))

    def test_debris_present_exits_one_and_reports_zero_deletions(self):
        before = G.census(self.root)
        proc = self._run("--self-audit")
        self.assertEqual(1, proc.returncode)
        report = json.loads(proc.stdout)
        self.assertEqual(0, report["deleted"])
        self.assertTrue(report["non_destructive"])
        self.assertEqual([], report["self_audit_offences"])
        self.assertEqual([], G.verify_census_unchanged(before, G.census(self.root)))

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory(prefix="po03-wa-037-clean-") as tmp:
            clean = Path(tmp) / "clean"
            clean.mkdir()
            (clean / "authored.md").write_text("# only authored content\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--root", str(clean), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            self.assertEqual(0, json.loads(proc.stdout)["debris_found"])

    def test_missing_root_exits_two(self):
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--root", str(self.root / "nope")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, proc.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
