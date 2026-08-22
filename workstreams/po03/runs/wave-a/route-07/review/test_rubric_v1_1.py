"""Guard tests for the v1.1 review-rubric erratum.

Two obligations:

1. Every hidden case pre-registered against rubric_v1 must reach the same
   recommendation under v1.1. The erratum may not weaken any v1 guarantee.
2. New abuse cases must prove each erratum cannot be exploited: an unlisted file
   that does not bind the manifest still fails, a receipt that claims the wrong
   manifest hash still fails, a differently named manifest with a corrupt hash
   still fails, a src/tests layout whose tests genuinely fail still fails, and a
   foreign task_id on a binding document still fails.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hidden_cases_v1 as hc  # noqa: E402
import rubric_v1_1 as rb11  # noqa: E402


def _cohort_for(root: Path, case: str) -> dict:
    if case != "duplicate_unit":
        return {}
    golden = root / hc.OWNED_PREFIX / "golden"
    return {"GOLDEN": {p.name: p.read_text(encoding="utf-8") for p in golden.glob("*.py")}}


def _review(root: Path, slot_rel: str, cohort=None):
    return rb11.review_slot_v1_1(
        repo_root=root,
        slot_rel=slot_rel,
        task_id=hc.TASK_ID,
        hypothesis=hc.HYPOTHESIS,
        acceptance_sha=hc.ACCEPTANCE_SHA,
        manifest_sha=hc.MANIFEST_SHA,
        owned_prefix=hc.OWNED_PREFIX,
        cohort=cohort or {},
    )


class ErratumPreservesV1Guarantees(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.expectations = hc.build_all(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_v1_hidden_case_keeps_its_recommendation(self):
        for exp in self.expectations:
            review = _review(self.root, exp["slot"], _cohort_for(self.root, exp["case"]))
            with self.subTest(case=exp["case"]):
                self.assertEqual(
                    exp["expected_recommendation"],
                    review.recommendation,
                    f"{exp['case']}: erratum changed the frozen verdict; defects={review.defects}",
                )


class ErratumAbuseCases(unittest.TestCase):
    """Each case tries to exploit one erratum and must still be rejected."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _slot(self, name: str) -> Path:
        return hc._base_slot(self.root, name)

    def test_e1_unlisted_non_binding_file_still_rejected(self):
        slot = self._slot("abuse_unlisted")
        hc._write_manifest(slot)
        (slot / "smuggled.py").write_text("PAYLOAD = 1\n")
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_unlisted")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)
        self.assertTrue(any("smuggled.py" in d for dim in review.dimensions for d in dim.evidence))

    def test_e1_receipt_claiming_wrong_manifest_hash_still_rejected(self):
        slot = self._slot("abuse_wrong_manifest_claim")
        hc._write_manifest(slot)
        doc = json.loads((slot / "result.json").read_text())
        doc["manifest_sha256"] = "d" * 64
        (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_wrong_manifest_claim")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)

    def test_e1_exemption_applies_only_to_correct_binding(self):
        slot = self._slot("legit_binding")
        hc._write_manifest(slot)
        manifest_sha = rb11.rb.sha256_file(slot / "manifest.json")
        doc = json.loads((slot / "result.json").read_text())
        doc["manifest_sha256"] = manifest_sha
        (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        hc._write_manifest(slot)  # rewrite so the manifest no longer lists result.json's old hash
        manifest_sha = rb11.rb.sha256_file(slot / "manifest.json")
        doc["manifest_sha256"] = manifest_sha
        (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        entries = json.loads((slot / "manifest.json").read_text())
        entries["artifacts"] = [e for e in entries["artifacts"] if e["path"] != "result.json"]
        entries["artifact_count"] = len(entries["artifacts"])
        (slot / "manifest.json").write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
        doc["manifest_sha256"] = rb11.rb.sha256_file(slot / "manifest.json")
        (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        review = _review(self.root, f"{hc.OWNED_PREFIX}/legit_binding")
        failed = [d.dimension for d in review.dimensions if d.verdict == "FAIL"]
        self.assertNotIn("R4_MANIFEST_COMPLETE", failed, review.defects)

    def test_e2_renamed_manifest_with_corrupt_hash_still_rejected(self):
        slot = self._slot("abuse_renamed_manifest")
        hc._write_manifest(slot, corrupt_hash="component.py")
        (slot / "manifest.json").rename(slot / "artifact-manifest.json")
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_renamed_manifest")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)

    def test_e2_renamed_manifest_is_accepted_when_sound(self):
        slot = self._slot("renamed_manifest_ok")
        hc._write_manifest(slot)
        (slot / "manifest.json").rename(slot / "artifact-manifest.json")
        review = _review(self.root, f"{hc.OWNED_PREFIX}/renamed_manifest_ok")
        failed = [d.dimension for d in review.dimensions if d.verdict == "FAIL"]
        self.assertNotIn("R4_MANIFEST_COMPLETE", failed, review.defects)

    def test_e3_src_tests_layout_with_failing_tests_still_rejected(self):
        slot = self.root / hc.OWNED_PREFIX / "abuse_src_tests_fail"
        (slot / "src").mkdir(parents=True)
        (slot / "tests").mkdir()
        (slot / "src" / "component.py").write_text(
            hc.COMPONENT.replace("if fence < self.fence:", "if False:")
        )
        (slot / "tests" / "test_component.py").write_text(
            "import sys, unittest\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
            + hc.TESTS.split("import unittest\n", 1)[1]
        )
        (slot / "evidence").mkdir()
        (slot / "evidence" / "observed-output.txt").write_text(hc.OBSERVED)
        (slot / "result.json").write_text(
            json.dumps(
                {
                    "task_id": hc.TASK_ID,
                    "acceptance_contract_sha256": hc.ACCEPTANCE_SHA,
                    "disposition": "PASS",
                    "limitations": ["synthetic"],
                },
                indent=2,
            )
            + "\n"
        )
        hc._write_manifest(slot)
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_src_tests_fail")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)
        r2 = [d for d in review.dimensions if d.dimension == "R2_TESTS_RERUN"][0]
        self.assertEqual("FAIL", r2.verdict)

    def test_e3_src_tests_layout_with_passing_tests_is_rerun(self):
        slot = self.root / hc.OWNED_PREFIX / "src_tests_ok"
        (slot / "src").mkdir(parents=True)
        (slot / "tests").mkdir()
        (slot / "src" / "component.py").write_text(hc.COMPONENT)
        (slot / "tests" / "test_component.py").write_text(
            "import sys, unittest\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
            + hc.TESTS.split("import unittest\n", 1)[1]
        )
        (slot / "evidence").mkdir()
        (slot / "evidence" / "observed-output.txt").write_text(hc.OBSERVED)
        (slot / "result.json").write_text(
            json.dumps(
                {
                    "task_id": hc.TASK_ID,
                    "acceptance_contract_sha256": hc.ACCEPTANCE_SHA,
                    "disposition": "PASS",
                    "limitations": ["synthetic"],
                },
                indent=2,
            )
            + "\n"
        )
        hc._write_manifest(slot)
        review = _review(self.root, f"{hc.OWNED_PREFIX}/src_tests_ok")
        r2 = [d for d in review.dimensions if d.dimension == "R2_TESTS_RERUN"][0]
        self.assertEqual("PASS", r2.verdict, r2.detail)
        self.assertGreaterEqual(sum(e["ran"] for e in r2.evidence), 4)

    def test_e4_foreign_task_id_on_binding_document_still_rejected(self):
        slot = self._slot("abuse_foreign_task_id")
        doc = json.loads((slot / "result.json").read_text())
        doc["task_id"] = "SOME-OTHER-TASK"
        (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        hc._write_manifest(slot)
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_foreign_task_id")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)

    def test_e4_fixture_with_own_identifier_is_tolerated(self):
        slot = self._slot("fixture_identifier")
        (slot / "fixture.json").write_text(
            json.dumps({"task_id": "OBZIO-SANITIZED-001", "rows": [1, 2, 3]}, indent=2) + "\n"
        )
        hc._write_manifest(slot)
        review = _review(self.root, f"{hc.OWNED_PREFIX}/fixture_identifier")
        r9 = [d for d in review.dimensions if d.dimension == "R9_CONTRACT_ECHO"][0]
        self.assertEqual("PASS", r9.verdict, r9.detail)

    def test_e4_fixture_claiming_wrong_acceptance_hash_still_rejected(self):
        slot = self._slot("abuse_fixture_hash")
        (slot / "fixture.json").write_text(
            json.dumps(
                {"task_id": "OBZIO-SANITIZED-001", "acceptance_contract_sha256": "e" * 64}, indent=2
            )
            + "\n"
        )
        hc._write_manifest(slot)
        review = _review(self.root, f"{hc.OWNED_PREFIX}/abuse_fixture_hash")
        self.assertEqual("RECOMMEND_REJECT", review.recommendation)


if __name__ == "__main__":
    unittest.main()
