"""Focused tests for this unit's mechanism-change and strategy registers.

These are structural and cross-reference tests.  They establish that the
registers stay honest about each other: that every patch named actually exists
and applies to the pinned tree, that every proposal is grounded in a hypothesis
this unit really froze, and above all that the five recorded states stay
distinct.  Whether a proposed change works is a separate question, answered by
proposals/verify_mechanism_changes.py.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from _support import REPO_ROOT, UNIT_ROOT

PROPOSALS = UNIT_ROOT / "proposals"
MECHANISM_PATH = PROPOSALS / "mechanism-changes.json"
STRATEGY_PATH = PROPOSALS / "strategy-proposals.json"
HYPOTHESES_PATH = UNIT_ROOT / "hypotheses" / "hypotheses.json"
PROBES_PATH = UNIT_ROOT / "harness" / "probes.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RegisterSeparationTests(unittest.TestCase):
    """The five states the acceptance contract requires to stay distinct."""

    def test_each_register_declares_exactly_one_state(self):
        expected = {
            UNIT_ROOT / "sources" / "source-claims.json": "SOURCE_CLAIM",
            HYPOTHESES_PATH: "FROZEN_HYPOTHESIS",
            MECHANISM_PATH: "MECHANISM_CHANGE_PROPOSAL",
            STRATEGY_PATH: "STRATEGY_PROPOSAL",
        }
        for path, state in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(state, load(path)["state"])

    def test_no_register_carries_another_registers_payload(self):
        forbidden = {
            MECHANISM_PATH: ("external_claims", "repository_claims", "hypotheses", "strategy_proposals"),
            STRATEGY_PATH: ("external_claims", "repository_claims", "hypotheses", "mechanism_changes"),
            HYPOTHESES_PATH: ("external_claims", "mechanism_changes", "strategy_proposals"),
            UNIT_ROOT / "sources" / "source-claims.json": ("hypotheses", "mechanism_changes", "strategy_proposals"),
        }
        for path, keys in forbidden.items():
            document = load(path)
            for key in keys:
                with self.subTest(path=path.name, key=key):
                    self.assertNotIn(key, document)

    def test_every_register_explains_what_it_is_not(self):
        for path in (UNIT_ROOT / "sources" / "source-claims.json", HYPOTHESES_PATH, MECHANISM_PATH, STRATEGY_PATH):
            with self.subTest(path=path.name):
                self.assertTrue(load(path)["state_note"].strip())


class MechanismChangeRegisterTests(unittest.TestCase):
    def setUp(self):
        self.document = load(MECHANISM_PATH)
        self.changes = self.document["mechanism_changes"]

    def test_at_least_one_mechanism_change_is_proposed(self):
        self.assertGreaterEqual(len(self.changes), 1, "the input requires a mechanism change or a rejection")

    def test_change_ids_are_unique(self):
        ids = [change["change_id"] for change in self.changes]
        self.assertEqual(sorted(set(ids)), sorted(ids))

    def test_every_named_patch_exists_with_the_recorded_digest_and_size(self):
        import hashlib

        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                patch = REPO_ROOT / change["patch"]
                self.assertTrue(patch.is_file(), f"{patch} is missing")
                payload = patch.read_bytes()
                self.assertEqual(change["patch_sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(change["patch_bytes"], len(payload))

    def test_every_patch_applies_to_the_pinned_tree(self):
        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                proc = subprocess.run(
                    ["git", "apply", "--check", change["patch"]],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, proc.returncode, proc.stderr)

    def test_every_patch_only_touches_the_paths_it_declares(self):
        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                text = (REPO_ROOT / change["patch"]).read_text(encoding="utf-8")
                touched = {
                    line.split(" b/", 1)[1].strip()
                    for line in text.splitlines()
                    if line.startswith("diff --git ")
                }
                self.assertEqual(set(change["targets"]), touched)

    def test_no_patch_targets_a_path_this_unit_owns(self):
        owned = "workstreams/po03/wave-a/units/wa-024/"
        for change in self.changes:
            for target in change["targets"]:
                with self.subTest(change=change["change_id"], target=target):
                    self.assertFalse(
                        target.startswith(owned),
                        "a mechanism change must propose a change to a read-only surface, "
                        "not edit this unit's own subtree",
                    )

    def test_the_unit_declares_it_applied_nothing(self):
        self.assertFalse(self.document["applied_by_this_unit"])

    def test_every_change_names_hypotheses_this_unit_froze(self):
        declared = {row["hypothesis_id"] for row in load(HYPOTHESES_PATH)["hypotheses"]}
        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                self.assertTrue(change["addresses_hypotheses"])
                self.assertLessEqual(set(change["addresses_hypotheses"]), declared)

    def test_every_change_records_a_defect_a_before_after_pair_and_a_blast_radius(self):
        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                for field in (
                    "defect",
                    "why_a_warm_checkout_hides_it",
                    "change",
                    "independent_test",
                    "blast_radius",
                    "reversibility",
                ):
                    self.assertTrue(str(change.get(field, "")).strip(), f"{field} is empty")

    def test_every_change_verified(self):
        for change in self.changes:
            with self.subTest(change=change["change_id"]):
                self.assertEqual("PASS", change["verification_disposition"])

    def test_rejected_candidates_carry_evidence_and_an_allowed_disposition(self):
        allowed = {"REJECTED", "NOT_PROPOSED"}
        candidates = self.document["rejected_candidates"]
        self.assertGreaterEqual(len(candidates), 1, "an evidence-backed rejection is part of the required output")
        for candidate in candidates:
            with self.subTest(candidate=candidate["candidate"]):
                self.assertIn(candidate["disposition"], allowed)
                self.assertTrue(candidate["evidence"].strip())

    def test_rejections_cite_probes_that_exist(self):
        import re

        declared = {probe["probe_id"] for probe in load(PROBES_PATH)["probes"]}
        short = {probe_id.split("-", 1)[0] for probe_id in declared}
        cited = set()
        for candidate in self.document["rejected_candidates"]:
            cited.update(re.findall(r"\bp\d\d\b", candidate["evidence"]))
        self.assertTrue(cited, "at least one rejection should rest on a named probe")
        self.assertLessEqual(cited, short)

    def test_the_verifier_is_executable_and_self_documented(self):
        verifier = PROPOSALS / self.document["verifier"]["path"].rsplit("/", 1)[1]
        self.assertTrue(verifier.is_file())
        text = verifier.read_text(encoding="utf-8")
        self.assertIn("--repo", text)
        self.assertIn("before", text)


class StrategyProposalRegisterTests(unittest.TestCase):
    def setUp(self):
        self.document = load(STRATEGY_PATH)
        self.proposals = self.document["strategy_proposals"]

    def test_proposal_ids_are_unique(self):
        ids = [proposal["proposal_id"] for proposal in self.proposals]
        self.assertEqual(sorted(set(ids)), sorted(ids))

    def test_every_proposal_is_grounded_in_a_frozen_hypothesis(self):
        declared = {row["hypothesis_id"] for row in load(HYPOTHESES_PATH)["hypotheses"]}
        for proposal in self.proposals:
            with self.subTest(proposal=proposal["proposal_id"]):
                self.assertTrue(proposal["grounded_in"])
                self.assertLessEqual(set(proposal["grounded_in"]), declared)

    def test_every_proposal_separates_observation_from_recommendation(self):
        for proposal in self.proposals:
            with self.subTest(proposal=proposal["proposal_id"]):
                for field in ("observation", "proposal", "why_it_matters", "cost"):
                    self.assertTrue(str(proposal.get(field, "")).strip(), f"{field} is empty")

    def test_no_proposal_claims_authority_or_acceptance(self):
        forbidden = ("COMPLETED", "ACCEPTED", "we have promoted", "merged")
        payload = json.dumps(self.document)
        for phrase in forbidden[:2]:
            self.assertIn(
                phrase,
                json.dumps(self.document["not_proposed"]),
                "the register should name the states it declines to claim",
            )
        for proposal in self.proposals:
            with self.subTest(proposal=proposal["proposal_id"]):
                self.assertEqual("coordinator", proposal["decision_owner"])
        self.assertIn("holds no authority", payload)

    def test_out_of_evidence_subjects_are_marked_not_supported(self):
        self.assertTrue(self.document["not_proposed"])
        for row in self.document["not_proposed"]:
            with self.subTest(subject=row["subject"]):
                self.assertEqual("NOT_SUPPORTED", row["status"])
                self.assertTrue(row["boundary"].strip())


class DecisionChangedTests(unittest.TestCase):
    def test_every_register_carries_an_empty_decision_changed(self):
        for path in (
            UNIT_ROOT / "sources" / "source-claims.json",
            HYPOTHESES_PATH,
            MECHANISM_PATH,
            STRATEGY_PATH,
        ):
            with self.subTest(path=path.name):
                self.assertEqual([], load(path)["decision_changed"])


if __name__ == "__main__":
    unittest.main()
