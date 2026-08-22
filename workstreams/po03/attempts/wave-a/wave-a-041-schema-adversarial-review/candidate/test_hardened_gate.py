#!/usr/bin/env python3
"""Regression tests for the unapplied candidate repair.

Every confirmed exploit must be refused *for its own stated reason*, not
incidentally, and every truthful custody state must remain expressible.  The
shared control is imported read-only for comparison and is never modified.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTEMPT_ROOT = HERE.parent
sys.path.insert(0, str(ATTEMPT_ROOT / "tests"))

import harness  # noqa: E402

CANDIDATE_PATH = HERE / "validate_contracts_hardened.py"
FIXTURES_PATH = HERE / "hardened-fixtures.json"


def _load_candidate():
    spec = importlib.util.spec_from_file_location("po03_candidate_hardened", CANDIDATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARDENED = _load_candidate()
FIXTURES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
CASES = {case["case_id"]: case for case in harness.load_cases()["cases"]}


def build_honest_ledger() -> list[dict]:
    spec = FIXTURES["honest_ledger"]
    documents = []
    for step in spec["steps"]:
        doc = copy.deepcopy(spec["base"])
        doc["obzio_state"] = step["obzio_state"]
        doc["provider_state"] = step["provider_state"]
        doc["attempt"]["checkpoint_seq"] = step["checkpoint_seq"]
        doc["result_transaction"]["state"] = step["transaction_state"]
        if step.get("artifacts") == "staged":
            doc["artifacts"] = copy.deepcopy(spec["staged_artifacts"])
            doc["result_transaction"].update(spec["staged_manifest"])
        elif step.get("artifacts") == "committed":
            doc["artifacts"] = copy.deepcopy(spec["committed_artifacts"])
        doc["result_transaction"]["artifact_count"] = len(doc["artifacts"])
        doc["result_transaction"]["total_bytes"] = sum(a["bytes"] for a in doc["artifacts"])
        if step.get("committed"):
            evidence = dict(spec["commit_evidence"])
            if not step.get("ingested"):
                evidence.pop("parent_ingested_at")
            doc["result_transaction"].update(evidence)
        if step.get("completion_actor"):
            doc["completion_actor"] = step["completion_actor"]
        documents.append(doc)
    return documents


class CandidateClosesConfirmedExploits(unittest.TestCase):
    """Each fix must fire for the defect it was written for."""

    def test_every_confirmed_exploit_is_refused_for_its_own_reason(self):
        expectations = FIXTURES["expected_hardened_rejection"]
        self.assertEqual(
            sorted(expectations),
            sorted(cid for cid in CASES if cid.startswith("C") and cid != "C00-honest-control"),
            "every attack case must have a declared hardened expectation",
        )
        for case_id, expectation in sorted(expectations.items()):
            with self.subTest(case=case_id, closed_by=expectation["closed_by"]):
                context = expectation.get("context")
                errors = []
                for document in CASES[case_id]["documents"]:
                    errors.extend(HARDENED.validate_result(copy.deepcopy(document), context))
                if expectation["level"] == "ledger":
                    # Ledger relations are only meaningful once each entry is
                    # individually valid, so the probe fixtures carry the defect
                    # in isolation.
                    self.assertTrue(errors, f"{case_id}: expected incidental document defects in the raw fixture")
                    continue
                self.assertTrue(errors, f"{case_id}: candidate accepted a confirmed exploit")
                self.assertTrue(
                    any(expectation["error_substring"] in error for error in errors),
                    f"{case_id}: refused, but not for its own reason {expectation['error_substring']!r}: {errors}",
                )

    def test_ledger_defects_are_caught_only_by_the_ledger_gate(self):
        probes = {key: value for key, value in FIXTURES["ledger_probes"].items() if isinstance(value, dict)}
        self.assertEqual(2, len(probes))
        for case_id, probe in sorted(probes.items()):
            with self.subTest(case=case_id):
                documents = copy.deepcopy(probe["documents"])
                for index, document in enumerate(documents):
                    self.assertEqual(
                        [],
                        HARDENED.validate_result(copy.deepcopy(document)),
                        f"{case_id}[{index}]: probe must be valid as a single document, "
                        "otherwise it cannot show that only the ledger gate catches the defect",
                    )
                errors = HARDENED.validate_result_sequence(documents)
                self.assertTrue(
                    any(probe["error_substring"] in error for error in errors),
                    f"{case_id}: ledger gate did not report {probe['error_substring']!r}: {errors}",
                )

    def test_shared_gate_still_accepts_what_candidate_refuses(self):
        """Confirms the exploits are live against the shipped control, not strawmen."""
        gate = harness.load_shared_gate()
        for case_id in FIXTURES["expected_hardened_rejection"]:
            with self.subTest(case=case_id):
                for document in CASES[case_id]["documents"]:
                    self.assertEqual(
                        [],
                        gate.validate_result(copy.deepcopy(document)),
                        f"{case_id}: shared gate unexpectedly rejects this document",
                    )


class CandidatePreservesTruthfulStates(unittest.TestCase):
    def test_honest_completion_is_accepted(self):
        self.assertEqual([], HARDENED.validate_result(copy.deepcopy(FIXTURES["honest_control_v2"])))

    def test_provider_loss_after_staging_becomes_representable(self):
        document = copy.deepcopy(FIXTURES["truthful_staged_provider_loss"])
        self.assertEqual([], HARDENED.validate_result(document))
        gate = harness.load_shared_gate()
        self.assertNotEqual([], gate.validate_result(copy.deepcopy(document)), "shared gate should still refuse it")

    def test_zero_byte_artifact_becomes_manifestable(self):
        document = copy.deepcopy(FIXTURES["truthful_zero_byte_artifact"])
        self.assertEqual([], HARDENED.validate_result(document))

    def test_full_custody_chain_ledger_is_accepted(self):
        ledger = build_honest_ledger()
        self.assertEqual(11, len(ledger))
        self.assertEqual([], HARDENED.validate_result_sequence(ledger))

    def test_duplicate_callback_replay_is_harmless(self):
        ledger = build_honest_ledger()
        replayed = ledger + [copy.deepcopy(ledger[-1]), copy.deepcopy(ledger[-1])]
        self.assertEqual([], HARDENED.validate_result_sequence(replayed))

    def test_divergent_commit_under_one_idempotency_key_is_refused(self):
        ledger = build_honest_ledger()
        forked = copy.deepcopy(ledger[-1])
        forked["result_transaction"]["result_commit_id"] = "0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e"
        errors = HARDENED.validate_result_sequence(ledger + [forked])
        self.assertTrue(any("cannot also produce" in error for error in errors), errors)


class CandidateKeepsExistingProtections(unittest.TestCase):
    def test_blocked_controls_remain_blocked(self):
        for case_id in ("B01-completed-without-commit-id", "B02-exact-string-self-accept", "B03-running-with-committed-artifacts"):
            with self.subTest(case=case_id):
                document = copy.deepcopy(CASES[case_id]["documents"][0])
                self.assertNotEqual([], HARDENED.validate_result(document))

    def test_identity_normalisation_is_conservative(self):
        normalise = HARDENED.normalise_identity
        self.assertEqual(normalise("producer-1"), normalise("producer-1 "))
        self.assertEqual(normalise("producer-1"), normalise("Producer-1"))
        self.assertEqual(normalise("producer-1"), normalise("producer-1\u200b"))
        self.assertEqual(normalise("produc\u00e9r-1"), normalise("produce\u0301r-1"))
        self.assertNotEqual(normalise("producer-1"), normalise("producer-2"))
        self.assertNotEqual(normalise("producer-1"), normalise("reviewer-1"))
        self.assertIsNone(normalise(None))
        self.assertIsNone(normalise("   "))

    def test_candidate_needs_no_third_party_packages(self):
        source = CANDIDATE_PATH.read_text(encoding="utf-8")
        for banned in ("import jsonschema", "import pydantic", "import requests", "import yaml"):
            self.assertNotIn(banned, source)

    def test_candidate_does_not_touch_the_shared_control(self):
        self.assertEqual(harness.EXPECTED_GATE_SHA256, harness.sha256_file(harness.SHARED_GATE_PATH))
        self.assertEqual(harness.EXPECTED_SCHEMA_SHA256, harness.sha256_file(harness.SCHEMA_PATH))


if __name__ == "__main__":
    unittest.main()
