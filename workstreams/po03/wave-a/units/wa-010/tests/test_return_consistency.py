"""Recurrence tests for the two return-document defects found on this branch.

DEF-PO03-WA-010-05 truncated the read-back record's manifest path label, and
DEF-PO03-WA-010-06 left three figures in the self-check prose pointing at a
superseded payload.  Both survived a proof-read, so both are pinned here.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNIT_DIR = HERE.parent
sys.path.insert(0, str(UNIT_DIR / "result"))

from check_return_consistency import check_document  # noqa: E402
from immutable_readback import repo_relative_manifest_path  # noqa: E402

UNIT_PREFIX = "workstreams/po03/wave-a/units/wa-010"
MANIFEST_PATH = f"{UNIT_PREFIX}/result/artifact-manifest.json"


def consistent_document():
    """A minimal return document that every check should accept."""
    return {
        "terminal_report": "READY_TO_COMMIT",
        "decision_changed": [],
        "manifest_path": MANIFEST_PATH,
        "manifest_sha256": "a" * 64,
        "artifact_count": 2,
        "total_bytes": 300,
        "changed_files": [f"{UNIT_PREFIX}/a.py", f"{UNIT_PREFIX}/b.py"],
        "payload_commit": {"base_to_payload_changed_path_count": 2},
        "tests": {"focused_tests": 7, "adversarial_cases": 3},
        "source_base": {"repository_sources_read": 5},
        "readback_verification": {
            "manifest_path": MANIFEST_PATH,
            "manifest_sha256": "a" * 64,
            "artifact_count": 2,
            "total_bytes": 300,
            "verified_paths": 3,
            "all_match": True,
            "mismatched_paths": [],
            "checks": [
                {"path": f"{UNIT_PREFIX}/a.py"},
                {"path": f"{UNIT_PREFIX}/b.py"},
                {"path": MANIFEST_PATH},
            ],
        },
        "transactional_result": {
            "result_transaction": {"manifest_sha256": "a" * 64},
            "artifacts": [{"content_uri": f"{UNIT_PREFIX}/a.py"}, {"content_uri": f"{UNIT_PREFIX}/b.py"}],
        },
        "acceptance_self_check": [
            {
                "assertion": "The producer wrote only its declared owned subtree in an isolated worktree.",
                "disposition": "PASS",
                "evidence": "2 changed paths from the immutable base, 0 out of scope.",
            },
            {
                "assertion": "The result carries complete SHA-256 and byte accounting.",
                "disposition": "PASS",
                "evidence": "2 artifacts totalling 300 bytes are hashed in the manifest.",
            },
            {
                "assertion": "Every artifact was read back from an immutable remote commit.",
                "disposition": "PASS",
                "evidence": "3 paths verified by SHA-256 and byte count.",
            },
            {
                "assertion": "The result leaves an executable component, reproduction, tests and adversarial cases behind.",
                "disposition": "PASS",
                "evidence": "7 focused tests, of which 3 are adversarial.",
            },
            {
                "assertion": "Exact repository SHAs read are recorded.",
                "disposition": "PASS",
                "evidence": "5 sources with observed SHA-256 and byte counts.",
            },
        ],
    }


def finding_ids(findings):
    return sorted(finding.check_id for finding in findings)


class ManifestPathLabelTest(unittest.TestCase):
    def test_the_units_own_manifest_gets_a_repository_relative_label(self):
        label = repo_relative_manifest_path(UNIT_DIR / "result" / "artifact-manifest.json")
        self.assertEqual(label, MANIFEST_PATH)

    def test_the_label_keeps_the_workstreams_prefix(self):
        """DEF-PO03-WA-010-05: splitting on 'workstreams/' dropped the prefix."""
        label = repo_relative_manifest_path(UNIT_DIR / "result" / "artifact-manifest.json")
        self.assertTrue(label.startswith("workstreams/"), label)
        self.assertNotEqual(label, MANIFEST_PATH.split("workstreams/")[-1])

    def test_a_foreign_manifest_is_reported_verbatim_rather_than_guessed(self):
        label = repo_relative_manifest_path(Path("/tmp/elsewhere/artifact-manifest.json"))
        self.assertEqual(label, "/tmp/elsewhere/artifact-manifest.json")


class ReturnConsistencyTest(unittest.TestCase):
    def test_a_consistent_document_produces_no_findings(self):
        self.assertEqual(check_document(consistent_document()), [])

    def test_a_stale_changed_path_figure_is_caught(self):
        """DEF-PO03-WA-010-06: the prose said 29 after the count moved to 30."""
        document = consistent_document()
        document["acceptance_self_check"][0]["evidence"] = (
            "1 changed path from the immutable base, 0 out of scope."
        )
        findings = check_document(document)
        self.assertIn("RC-N01", finding_ids(findings))
        self.assertEqual(findings[0].kind, "STALE_NARRATIVE_FIGURE")

    def test_a_stale_byte_total_is_caught(self):
        document = consistent_document()
        document["acceptance_self_check"][1]["evidence"] = (
            "2 artifacts totalling 299 bytes are hashed in the manifest."
        )
        self.assertIn("RC-N03", finding_ids(check_document(document)))

    def test_a_stale_readback_count_is_caught(self):
        document = consistent_document()
        document["acceptance_self_check"][2]["evidence"] = "2 paths verified by SHA-256."
        self.assertIn("RC-N04", finding_ids(check_document(document)))

    def test_a_truncated_manifest_label_is_caught(self):
        """DEF-PO03-WA-010-05 as it appeared in the return document."""
        document = consistent_document()
        document["readback_verification"]["manifest_path"] = MANIFEST_PATH.split("workstreams/")[-1]
        ids = finding_ids(check_document(document))
        self.assertIn("RC-X04", ids)

    def test_a_manifest_that_was_never_read_back_is_caught(self):
        document = consistent_document()
        document["readback_verification"]["checks"] = [{"path": f"{UNIT_PREFIX}/a.py"}]
        self.assertIn("RC-X12", finding_ids(check_document(document)))

    def test_a_readback_reaching_outside_the_owned_subtree_is_caught(self):
        document = consistent_document()
        document["readback_verification"]["checks"].append({"path": "state/operator-system/x.json"})
        self.assertIn("RC-X11", finding_ids(check_document(document)))

    def test_a_non_empty_decision_changed_is_caught(self):
        document = consistent_document()
        document["decision_changed"] = ["something"]
        self.assertIn("RC-X02", finding_ids(check_document(document)))

    def test_a_self_accepting_terminal_report_is_caught(self):
        document = consistent_document()
        document["terminal_report"] = "ACCEPTED"
        self.assertIn("RC-X01", finding_ids(check_document(document)))

    def test_a_missing_assertion_is_reported_rather_than_passed_over(self):
        document = consistent_document()
        document["acceptance_self_check"].pop(0)
        findings = check_document(document)
        self.assertIn("RC-N01", finding_ids(findings))
        self.assertEqual(
            [finding.kind for finding in findings if finding.check_id == "RC-N01"],
            ["MISSING_ASSERTION"],
        )

    def test_a_disagreeing_transactional_digest_is_caught(self):
        document = consistent_document()
        document["transactional_result"]["result_transaction"]["manifest_sha256"] = "b" * 64
        self.assertIn("RC-X09", finding_ids(check_document(document)))


class CommittedReturnTest(unittest.TestCase):
    """Run the checker against the real return document once it exists."""

    path = UNIT_DIR / "result" / "ready-to-commit.json"

    def test_the_committed_return_is_internally_consistent(self):
        if not self.path.exists():
            self.skipTest("ready-to-commit.json is written after the payload commit")
        document = json.loads(self.path.read_text(encoding="utf-8"))
        findings = check_document(document)
        self.assertEqual(
            [finding.as_dict() for finding in findings],
            [],
            "the committed return document contradicts itself",
        )


if __name__ == "__main__":
    unittest.main()
