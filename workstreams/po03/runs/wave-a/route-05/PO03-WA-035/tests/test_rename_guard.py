"""Falsification tests for the PO03-WA-035 rename guard.

Beyond synthetic records, one test builds a throwaway git repository in a
temporary directory, performs a real rename that escapes the owned subtree,
and feeds genuine ``git diff --name-status -z`` bytes to the guard.  The
temporary repository is fully isolated: its own ``--git-dir``, its own
identity, and no remotes.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "rename_guard.py"
SPEC = importlib.util.spec_from_file_location("rename_guard", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


OWNED = "workstreams/po03/runs/wave-a/route-05/PO03-WA-035"
SHARED = "workstreams/po03/control/outbox.jsonl"


def guard(prefixes=(OWNED,)):
    return G.RenameGuard(G.subtree_ownership(list(prefixes)))


class AdmissibilityMatrixTests(unittest.TestCase):
    def test_owned_to_owned_is_allowed(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/a.json", OWNED + "/b.json"))
        self.assertEqual(G.VERDICT_ALLOWED, decision.verdict)
        self.assertTrue(decision.source_owned and decision.destination_owned)

    def test_owned_to_foreign_is_rejected_on_the_destination(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/a.json", SHARED))
        self.assertEqual(G.VERDICT_REJECTED_DESTINATION_NOT_OWNED, decision.verdict)
        self.assertIn("evidence_leaves_subtree", decision.flags)

    def test_foreign_to_owned_is_rejected_on_the_source(self):
        decision = guard().evaluate(G.RenameRecord(SHARED, OWNED + "/captured.jsonl"))
        self.assertEqual(G.VERDICT_REJECTED_SOURCE_NOT_OWNED, decision.verdict)
        self.assertIn("unowned_source_removed", decision.flags)

    def test_foreign_to_foreign_is_rejected(self):
        decision = guard().evaluate(G.RenameRecord("docs/a.md", "docs/b.md"))
        self.assertEqual(G.VERDICT_REJECTED_BOTH_ENDPOINTS_NOT_OWNED, decision.verdict)

    def test_destination_only_check_would_have_admitted_the_capture(self):
        """Shows why a single-endpoint guard is insufficient."""
        owns = G.subtree_ownership([OWNED])
        record = G.RenameRecord(SHARED, OWNED + "/captured.jsonl")
        self.assertTrue(owns(record.destination))  # a destination-only guard says yes
        self.assertEqual(
            G.VERDICT_REJECTED_SOURCE_NOT_OWNED, guard().evaluate(record).verdict
        )

    def test_source_only_check_would_have_admitted_the_escape(self):
        owns = G.subtree_ownership([OWNED])
        record = G.RenameRecord(OWNED + "/a.json", SHARED)
        self.assertTrue(owns(record.source))  # a source-only guard says yes
        self.assertEqual(
            G.VERDICT_REJECTED_DESTINATION_NOT_OWNED, guard().evaluate(record).verdict
        )


class EdgeCaseTests(unittest.TestCase):
    def test_case_only_rename_is_flagged(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/README.md", OWNED + "/readme.md"))
        self.assertEqual(G.VERDICT_ALLOWED, decision.verdict)
        self.assertIn("case_only", decision.flags)

    def test_no_op_rename_is_flagged(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/a.json", OWNED + "/a.json"))
        self.assertIn("no_op", decision.flags)

    def test_traversal_in_destination_is_normalised_then_rejected(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/a.json", OWNED + "/../../route-04/a.json"))
        self.assertEqual(G.VERDICT_REJECTED_DESTINATION_NOT_OWNED, decision.verdict)
        self.assertEqual("workstreams/po03/runs/wave-a/route-04/a.json", decision.destination)

    def test_prefix_boundary_is_respected(self):
        decision = guard().evaluate(G.RenameRecord(OWNED + "/a", OWNED + "-sibling/a"))
        self.assertEqual(G.VERDICT_REJECTED_DESTINATION_NOT_OWNED, decision.verdict)

    def test_unusable_owned_prefix_is_refused(self):
        with self.assertRaises(ValueError):
            G.subtree_ownership(["../escape"])


class ParserTests(unittest.TestCase):
    def test_diff_name_status_z_parses_renames_and_skips_plain_entries(self):
        payload = "M\x00" + OWNED + "/kept.json\x00" "R100\x00" + OWNED + "/a.json\x00" + SHARED + "\x00"
        records = G.parse_diff_name_status_z(payload)
        self.assertEqual(1, len(records))
        self.assertEqual(OWNED + "/a.json", records[0].source)
        self.assertEqual(SHARED, records[0].destination)
        self.assertEqual(100, records[0].similarity)

    def test_diff_parser_handles_copies(self):
        payload = "C075\x00src/a\x00dst/b\x00"
        records = G.parse_diff_name_status_z(payload)
        self.assertEqual([("src/a", "dst/b", 75)], [(r.source, r.destination, r.similarity) for r in records])

    def test_diff_parser_rejects_truncated_rename(self):
        with self.assertRaises(G.RenameParseError):
            G.parse_diff_name_status_z("R100\x00only-one-path\x00")

    def test_status_porcelain_z_uses_new_then_old_order(self):
        payload = "R  " + OWNED + "/new.json\x00" + SHARED + "\x00 M other.txt\x00"
        records = G.parse_status_porcelain_z(payload)
        self.assertEqual(1, len(records))
        self.assertEqual(SHARED, records[0].source)
        self.assertEqual(OWNED + "/new.json", records[0].destination)

    def test_porcelain_parser_rejects_rename_without_source(self):
        with self.assertRaises(G.RenameParseError):
            G.parse_status_porcelain_z("R  only-new-path\x00")

    def test_paths_with_spaces_survive_nul_delimited_parsing(self):
        payload = "R100\x00" + OWNED + "/a file.json\x00" + OWNED + "/b file.json\x00"
        records = G.parse_diff_name_status_z(payload)
        self.assertEqual(OWNED + "/a file.json", records[0].source)


@unittest.skipIf(shutil.which("git") is None, "git binary unavailable")
class RealGitRenameTests(unittest.TestCase):
    """End-to-end: a genuine git rename out of the owned subtree is rejected."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-035-git-")
        self.repo = Path(self._tmp.name)
        self.git = [
            "git",
            "-c",
            "user.name=po03-wa-035-fixture",
            "-c",
            "user.email=po03-wa-035@fixture.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(self.repo),
        ]
        subprocess.run(self.git + ["init", "-q", "-b", "main"], check=True, capture_output=True)
        owned_dir = self.repo / OWNED
        owned_dir.mkdir(parents=True)
        (self.repo / "workstreams/po03/control").mkdir(parents=True)
        # A body large enough for git's rename detection to score it.
        (owned_dir / "a.json").write_text("\n".join(f"line-{i}" for i in range(200)), encoding="utf-8")
        subprocess.run(self.git + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(self.git + ["commit", "-q", "-m", "fixture base"], check=True, capture_output=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _rename_diff(self) -> str:
        proc = subprocess.run(
            self.git + ["diff", "--cached", "--find-renames", "--name-status", "-z", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    def test_real_escape_rename_is_detected_from_git_output(self):
        subprocess.run(
            self.git + ["mv", OWNED + "/a.json", "workstreams/po03/control/a.json"],
            check=True,
            capture_output=True,
        )
        records = G.parse_diff_name_status_z(self._rename_diff())
        report = G.build_report(guard(), records)
        self.assertFalse(report["admissible"], report)
        verdicts = {d["verdict"] for d in report["decisions"]}
        self.assertIn(G.VERDICT_REJECTED_DESTINATION_NOT_OWNED, verdicts)

    def test_real_internal_rename_is_admitted(self):
        subprocess.run(
            self.git + ["mv", OWNED + "/a.json", OWNED + "/b.json"], check=True, capture_output=True
        )
        records = G.parse_diff_name_status_z(self._rename_diff())
        report = G.build_report(guard(), records)
        self.assertTrue(report["admissible"], report)


class CommandLineTests(unittest.TestCase):
    def _run(self, payload: str, fmt: str = "diff-name-status-z"):
        with tempfile.TemporaryDirectory(prefix="po03-wa-035-cli-") as tmp:
            path = Path(tmp) / "payload.bin"
            path.write_text(payload, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--owned-prefix",
                    OWNED,
                    "--format",
                    fmt,
                    "--input",
                    str(path),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_internal_rename_exits_zero(self):
        proc = self._run("R100\x00" + OWNED + "/a.json\x00" + OWNED + "/b.json\x00")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["admissible"])

    def test_escaping_rename_exits_one(self):
        proc = self._run("R100\x00" + OWNED + "/a.json\x00" + SHARED + "\x00")
        self.assertEqual(1, proc.returncode)
        self.assertEqual(1, json.loads(proc.stdout)["rejected"])

    def test_malformed_payload_exits_two(self):
        proc = self._run("R100\x00lonely\x00")
        self.assertEqual(2, proc.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
