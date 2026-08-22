#!/usr/bin/env python3
"""Tests for the blind review harness."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"po03_060_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


blind_review = load("blind_review")

HASH = "a" * 64


def synthetic_candidate():
    result = {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "synthetic-unit",
        "commission_id": "COM-PO03-SYNTHETIC",
        "immutable_input_manifest_sha256": HASH,
        "acceptance_contract_sha256": HASH,
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_COMMITTED",
        "attempt": {
            "attempt_id": "synthetic-unit-attempt-1",
            "idempotency_key": "COM-PO03-SYNTHETIC:synthetic-unit:attempt-1",
            "lease_id": "lease-synthetic-unit-1",
            "fence_token": 3,
            "provider_run_id": "run-1",
            "worker_id": "synthetic-producer",
            "heartbeat_at": "2026-08-22T07:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": "result-synthetic-unit-1",
            "state": "COMMITTED",
            "manifest_uri": "git:refs/heads/synthetic:manifest.json",
            "manifest_sha256": HASH,
            "artifact_count": 2,
            "total_bytes": 30,
            "committed_at": "2026-08-22T07:01:00Z",
            "verified_at": "2026-08-22T07:01:00Z",
            "parent_ingested_at": None,
            "result_commit_id": "b" * 40,
        },
        "artifacts": [
            {
                "artifact_id": "synthetic-unit-artifact-001",
                "logical_name": "component.py",
                "content_uri": f"git:{'b' * 40}:workstreams/po03/attempts/synthetic/component.py",
                "sha256": HASH,
                "bytes": 20,
                "media_type": "text/x-python",
                "readback_verified_at": "2026-08-22T07:01:00Z",
            },
            {
                "artifact_id": "synthetic-unit-artifact-002",
                "logical_name": "test_component.py",
                "content_uri": f"git:{'b' * 40}:workstreams/po03/attempts/synthetic/test_component.py",
                "sha256": HASH,
                "bytes": 10,
                "media_type": "text/x-python",
                "readback_verified_at": "2026-08-22T07:01:00Z",
            },
        ],
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
    manifest = {
        "manifest_version": "PO03-ARTIFACT-MANIFEST-v1",
        "task_id": "synthetic-unit",
        "artifact_count": 2,
        "total_bytes": 30,
        "falsifiable_hypothesis": "a synthetic hypothesis",
        "verdict": "PASS",
        "evidence": "the producer asserts that everything was verified",
        "limitations": ["a synthetic limitation"],
        "producer": {"obzio_state_claim": "READY_TO_COMMIT", "worker_id": "synthetic-producer"},
        "generated_at": "2026-08-22T07:02:00Z",
    }
    return {
        "candidate_id": "synthetic-unit",
        "slot": "workstreams/po03/attempts/synthetic-unit",
        "ref": "refs/heads/synthetic",
        "ref_commit": "b" * 40,
        "result": result,
        "manifest": manifest,
        "ground_truth": None,
        "injected_defect": None,
    }


def bundle():
    return {
        "task_id": "synthetic-unit",
        "criteria": ["executable component exists", "artifact manifest lists every artifact"],
        "forbidden": ["writes outside the owned subtree"],
        "acceptance_sha256": HASH,
        "criteria_freeze_sha256": HASH,
        "bundle_sha256": HASH,
    }


def all_holding():
    return {
        name: {"held": True, "detail": []}
        for name in (
            "result_contract_valid",
            "artifacts_read_back_byte_identical",
            "artifact_locators_name_immutable_objects",
            "tests_or_reproduction_evidence_present",
            "manifest_agrees_with_result",
            "no_producer_self_acceptance",
            "no_producer_set_completion",
        )
    }


class TestPacketConstruction(unittest.TestCase):
    def setUp(self):
        self.packets = blind_review.build_packets(synthetic_candidate(), bundle())

    def test_blind_packet_strips_every_producer_conclusion(self):
        serialised = json.dumps(self.packets["blind"])
        self.assertNotIn("the producer asserts that everything was verified", serialised)
        self.assertNotIn("a synthetic limitation", serialised)
        for field in ("producer_verdict", "producer_evidence", "producer_limitations", "producer_state_claim"):
            self.assertNotIn(field, self.packets["blind"])

    def test_blind_packet_retains_criteria_and_immutable_hypothesis(self):
        packet = self.packets["blind"]
        self.assertEqual(packet["criteria"], bundle()["criteria"])
        self.assertEqual(packet["falsifiable_hypothesis"], "a synthetic hypothesis")
        self.assertEqual(len(packet["artifact_inventory"]), 2)

    def test_narrative_packet_exposes_the_producer_conclusions(self):
        packet = self.packets["narrative"]
        self.assertEqual(packet["producer_verdict"], "PASS")
        self.assertIn("everything was verified", packet["producer_evidence"])
        self.assertEqual(packet["producer_state_claim"], "READY_TO_COMMIT")

    def test_two_packets_have_different_digests(self):
        blind = blind_review.sha256_bytes(blind_review.canonical(self.packets["blind"]))
        narrative = blind_review.sha256_bytes(blind_review.canonical(self.packets["narrative"]))
        self.assertNotEqual(blind, narrative)


class TestReviewers(unittest.TestCase):
    def test_both_arms_accept_when_every_criterion_holds(self):
        packets = blind_review.build_packets(synthetic_candidate(), bundle())
        observations = all_holding()
        self.assertEqual(blind_review.review_criteria_only(packets["blind"], observations)["verdict"], "ACCEPT")
        self.assertEqual(
            blind_review.review_narrative_anchored(packets["narrative"], observations)["verdict"], "ACCEPT"
        )

    def test_narrative_arm_misses_a_failure_it_trusts_the_producer_for(self):
        packets = blind_review.build_packets(synthetic_candidate(), bundle())
        observations = all_holding()
        observations["artifacts_read_back_byte_identical"] = {"held": False, "detail": ["digest mismatch"]}
        blind = blind_review.review_criteria_only(packets["blind"], observations)
        narrative = blind_review.review_narrative_anchored(packets["narrative"], observations)
        self.assertEqual(blind["verdict"], "REJECT")
        self.assertEqual(narrative["verdict"], "ACCEPT")
        self.assertIn("artifacts_read_back_byte_identical", narrative["criteria_trusted_from_narrative"])

    def test_narrative_arm_still_catches_a_contract_violation(self):
        packets = blind_review.build_packets(synthetic_candidate(), bundle())
        observations = all_holding()
        observations["result_contract_valid"] = {"held": False, "detail": ["$.artifacts: invalid"]}
        narrative = blind_review.review_narrative_anchored(packets["narrative"], observations)
        self.assertEqual(narrative["verdict"], "REJECT")

    def test_narrative_arm_verifies_everything_when_the_producer_claims_no_pass(self):
        candidate = synthetic_candidate()
        candidate["manifest"]["verdict"] = "FAIL"
        packets = blind_review.build_packets(candidate, bundle())
        observations = all_holding()
        observations["tests_or_reproduction_evidence_present"] = {"held": False, "detail": []}
        narrative = blind_review.review_narrative_anchored(packets["narrative"], observations)
        self.assertEqual(narrative["verdict"], "REJECT")
        self.assertEqual(narrative["criteria_trusted_from_narrative"], [])


class TestInjection(unittest.TestCase):
    def test_every_defect_produces_a_labelled_candidate(self):
        base = synthetic_candidate()
        for defect_id in blind_review.INJECTED_DEFECTS:
            mutated = blind_review.inject(base, defect_id)
            self.assertIsNotNone(mutated, defect_id)
            self.assertEqual(mutated["ground_truth"], "SHOULD_REJECT", defect_id)
            self.assertEqual(mutated["injected_defect"], defect_id, defect_id)
            self.assertTrue(mutated["candidate_id"].endswith(defect_id), defect_id)

    def test_injection_leaves_the_base_candidate_untouched(self):
        base = synthetic_candidate()
        snapshot = copy.deepcopy(base)
        for defect_id in blind_review.INJECTED_DEFECTS:
            blind_review.inject(base, defect_id)
        self.assertEqual(base, snapshot)

    def test_injected_candidates_still_assert_a_passing_narrative(self):
        base = synthetic_candidate()
        for defect_id in blind_review.INJECTED_DEFECTS:
            mutated = blind_review.inject(base, defect_id)
            self.assertEqual(mutated["manifest"]["verdict"], "PASS", defect_id)

    def test_unknown_defect_is_refused(self):
        with self.assertRaises(ValueError):
            blind_review.inject(synthetic_candidate(), "I99-not-a-defect")


class TestCriteriaPrecommit(unittest.TestCase):
    def test_precommit_records_digests_without_any_producer_conclusion(self):
        candidate = synthetic_candidate()
        candidate["result"]["task_id"] = "po03-wa-b2e7-057-metric-collection-harness"
        precommit = blind_review.precommit_criteria(REPO, [candidate])
        serialised = json.dumps(precommit)
        self.assertNotIn("the producer asserts", serialised)
        self.assertIn("po03-wa-b2e7-057-metric-collection-harness", precommit["units"])
        self.assertRegex(precommit["criteria_freeze_sha256"], r"^[0-9a-f]{64}$")

    def test_bundle_digest_is_reproducible(self):
        first = blind_review.criteria_bundle(REPO, "po03-wa-b2e7-060-blind-review-harness")
        second = blind_review.criteria_bundle(REPO, "po03-wa-b2e7-060-blind-review-harness")
        self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
        self.assertTrue(first["criteria"])


if __name__ == "__main__":
    unittest.main()
