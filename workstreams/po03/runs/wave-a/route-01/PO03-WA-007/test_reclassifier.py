#!/usr/bin/env python3
"""Falsification suite for PO03-WA-007.

The hypothesis is falsified if any observation with provider ``COMPLETED`` and
no verifiable durable commit yields anything other than
``PROVIDER_COMPLETED_UNCOMMITTED``, or if the classifier ever derives
``COMPLETED`` at all.

The matrix is a full cross product of provider state and commit-durability
shape, and every derived verdict is additionally re-checked against the seeded
repository validator so this component cannot drift from the contract.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("reclassifier", Path(__file__).with_name("reclassifier.py"))
assert SPEC is not None and SPEC.loader is not None
RC = importlib.util.module_from_spec(SPEC)
sys.modules["reclassifier"] = RC
SPEC.loader.exec_module(RC)


class SeparationTests(unittest.TestCase):
    """Provider state and Obzio state are two axes and never merge."""

    def test_provider_completed_without_a_locator_is_reclassified(self):
        reclassifier = RC.Reclassifier(RC.CommitResolver())
        result = reclassifier.classify(RC.Observation("T1", "COMPLETED"))
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.obzio_state)
        self.assertFalse(result.durable_commit)
        self.assertEqual("NO_RESULT_COMMIT_LOCATOR", result.reason)
        self.assertEqual("COMPLETED", result.provider_state, "provider state is preserved, not rewritten")

    def test_classifier_can_never_derive_completed(self):
        self.assertNotIn("COMPLETED", RC.DERIVABLE)
        report = RC.sweep_matrix()
        self.assertEqual([], report["false_completions"], "no input may produce COMPLETED")

    def test_a_verified_commit_stops_at_result_committed(self):
        resolver = RC.CommitResolver()
        sha = resolver.add("c1", b"bytes")
        result = RC.Reclassifier(resolver).classify(
            RC.Observation("T1", "COMPLETED", "c1", sha, artifact_count=1)
        )
        self.assertEqual("RESULT_COMMITTED", result.obzio_state)
        self.assertTrue(result.durable_commit)

    def test_obzio_state_is_derived_not_accepted(self):
        """There is no input field by which a caller can assert Obzio state."""
        self.assertNotIn("obzio_state", RC.Observation.__dataclass_fields__)
        self.assertNotIn("durable_commit", RC.Observation.__dataclass_fields__)


class NonDurableCommitTests(unittest.TestCase):
    """Three distinct ways a claimed commit fails to be durable."""

    def setUp(self):
        self.resolver = RC.CommitResolver()
        self.good_sha = self.resolver.add("c1", b"bytes")
        self.reclassifier = RC.Reclassifier(self.resolver)

    def classify(self, **kwargs):
        return self.reclassifier.classify(RC.Observation("T1", "COMPLETED", **kwargs))

    def test_unresolvable_locator(self):
        result = self.classify(result_commit_id="c-missing", declared_manifest_sha256=self.good_sha, artifact_count=1)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.obzio_state)
        self.assertEqual("LOCATOR_UNRESOLVABLE", result.reason)

    def test_resolvable_but_unpinned_content(self):
        result = self.classify(result_commit_id="c1", declared_manifest_sha256=None, artifact_count=1)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.obzio_state)
        self.assertEqual("NO_DECLARED_MANIFEST_HASH", result.reason)

    def test_hash_mismatch_is_reported_with_both_hashes(self):
        result = self.classify(result_commit_id="c1", declared_manifest_sha256="a" * 64, artifact_count=1)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.obzio_state)
        self.assertEqual("MANIFEST_HASH_MISMATCH", result.reason)
        self.assertEqual("a" * 64, result.evidence["declared_sha256"])
        self.assertNotEqual(result.evidence["declared_sha256"], result.evidence["observed_sha256"])

    def test_a_commit_with_no_artifacts_is_not_durable(self):
        result = self.classify(result_commit_id="c1", declared_manifest_sha256=self.good_sha, artifact_count=0)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.obzio_state)
        self.assertEqual("NO_ARTIFACTS", result.reason)

    def test_blank_locator_is_treated_as_absent(self):
        for blank in ("", "   "):
            result = self.classify(result_commit_id=blank)
            self.assertEqual("NO_RESULT_COMMIT_LOCATOR", result.reason)


class MatrixTests(unittest.TestCase):
    def test_full_matrix_has_no_false_completion(self):
        report = RC.sweep_matrix()
        self.assertEqual(36, len(report["rows"]), "6 provider states x 6 commit shapes")
        self.assertEqual([], report["false_completions"])

    def test_every_completed_provider_without_commit_maps_to_one_state(self):
        report = RC.sweep_matrix()
        self.assertEqual(["PROVIDER_COMPLETED_UNCOMMITTED"], report["completed_provider_without_commit"])

    def test_every_derived_document_satisfies_the_seeded_contract(self):
        report = RC.sweep_matrix()
        self.assertEqual([], report["contract_violations"], "derived documents must satisfy the seeded validator")

    def test_non_completed_providers_are_classified_on_their_own_terms(self):
        resolver = RC.CommitResolver()
        reclassifier = RC.Reclassifier(resolver)
        expected = {
            "QUEUED": "RUNNING",
            "RUNNING": "RUNNING",
            "FAILED": "FAILED_TERMINAL",
            "CANCELLED": "CANCELLED",
            "UNKNOWN": "RECOVERY_REQUIRED",
        }
        for provider_state, obzio_state in expected.items():
            result = reclassifier.classify(RC.Observation("T1", provider_state))
            self.assertEqual(obzio_state, result.obzio_state, provider_state)

    def test_a_durable_commit_outranks_a_failed_provider_report(self):
        """A real committed result is not discarded because the provider errored."""
        resolver = RC.CommitResolver()
        sha = resolver.add("c1", b"bytes")
        for provider_state in ("FAILED", "CANCELLED", "UNKNOWN"):
            result = RC.Reclassifier(resolver).classify(
                RC.Observation("T1", provider_state, "c1", sha, artifact_count=1)
            )
            self.assertEqual("RESULT_COMMITTED", result.obzio_state, provider_state)

    def test_unknown_provider_state_is_refused(self):
        with self.assertRaises(ValueError):
            RC.Reclassifier(RC.CommitResolver()).classify(RC.Observation("T1", "DONE"))


class SeededValidatorCrossCheckTests(unittest.TestCase):
    """Bind this component to the repository's own contract validator."""

    def setUp(self):
        self.validator = RC.load_repository_validator()
        if self.validator is None:
            self.skipTest("seeded validator not reachable from this clone")

    def test_validator_is_reachable_in_this_clone(self):
        self.assertTrue(hasattr(self.validator, "validate_result"))

    def test_a_deliberately_false_completion_is_rejected_by_the_seeded_validator(self):
        """Confirm the cross-check can actually fail, not just pass."""
        resolver = RC.CommitResolver()
        reclassifier = RC.Reclassifier(resolver)
        observation = RC.Observation("T1", "COMPLETED")
        classification = reclassifier.classify(observation)
        document = reclassifier.to_result_document(observation, classification)
        self.assertEqual([], self.validator.validate_result(document))

        # Now forge the state the reclassifier refuses to produce.
        document["obzio_state"] = "RUNNING"
        errors = self.validator.validate_result(document)
        self.assertTrue(
            any("PROVIDER_COMPLETED_UNCOMMITTED" in error for error in errors),
            errors,
        )

    def test_forged_coordinator_completion_is_rejected(self):
        resolver = RC.CommitResolver()
        reclassifier = RC.Reclassifier(resolver)
        observation = RC.Observation("T1", "COMPLETED")
        document = reclassifier.to_result_document(observation, reclassifier.classify(observation))
        document["obzio_state"] = "COMPLETED"
        document["completion_actor"] = "worker-1"
        errors = self.validator.validate_result(document)
        self.assertTrue(errors, "a forged completion must not validate")


class Po02FixtureTests(unittest.TestCase):
    def test_recorded_po02_code2_fixture_reclassifies(self):
        report = RC.reproduce_po02_code2()
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", report["classification"]["obzio_state"])
        self.assertEqual("COMPLETED", report["classification"]["provider_state"])
        self.assertFalse(report["classification"]["durable_commit"])
        self.assertTrue(report["seeded_validator_available"])
        self.assertEqual([], report["seeded_validator_errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
