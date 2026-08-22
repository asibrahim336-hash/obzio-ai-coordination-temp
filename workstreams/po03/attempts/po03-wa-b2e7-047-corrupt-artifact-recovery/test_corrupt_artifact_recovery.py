"""Reproduction for corrupt and absent artifacts at ingestion.

Hypothesis under test: a corrupt or missing artifact is refused at ingestion and
routed to recovery rather than accepted.

Each class asserts refusal, the RECOVERY_REQUIRED classification, an intact
immutable capsule, and a successful rerun from that capsule.  One class asserts
the opposite direction on purpose: tampering with the worktree after the commit
must not change what ingestion reads, because read-back is governed by the
immutable object.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_047_kit", "fault_kit.py")
injector = _load("po03_c6_047_injector", "corruption_injector.py")

REFUSING_CLASSES = tuple(
    (name, mutate) for name, mutate in injector.CORRUPTIONS if name != "WORKTREE_TAMPERED_AFTER_THE_COMMIT"
)


class CorruptionTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class RefusalTests(CorruptionTestCase):
    def test_every_corruption_class_is_refused_and_routed_to_recovery(self):
        for name, mutate in REFUSING_CLASSES:
            with self.subTest(fault_class=name):
                result = injector.inject_corruption(self.root, name, mutate)
                observed = result["observed"]
                self.assertEqual("RECOVERY_REQUIRED", observed["ingestion_state"])
                self.assertTrue(observed["error_fragment_present"], observed["ingestion_errors"])
                self.assertFalse(observed["scanner_sees_ingested_result"])
                self.assertEqual(0, observed["false_completion_count"])
                self.assertEqual("PASS", result["verdict"])

    def test_a_wrong_hash_names_the_read_back_mismatch(self):
        result = injector.inject_corruption(
            self.root, "CLAIMED_HASH_DOES_NOT_MATCH_COMMITTED_BYTES", injector.corrupt_wrong_hash
        )
        self.assertTrue(
            any("read-back mismatch" in error for error in result["observed"]["ingestion_errors"])
        )

    def test_a_wrong_byte_count_alone_is_enough_to_refuse(self):
        result = injector.inject_corruption(
            self.root,
            "CLAIMED_BYTE_COUNT_DOES_NOT_MATCH_COMMITTED_BYTES",
            injector.corrupt_wrong_byte_count,
        )
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["ingestion_state"])

    def test_a_non_durable_locator_is_named_as_such(self):
        result = injector.inject_corruption(
            self.root, "LOCATOR_IS_NOT_A_DURABLE_GIT_OBJECT", injector.corrupt_non_durable_locator
        )
        self.assertTrue(
            any("non-durable" in error for error in result["observed"]["ingestion_errors"])
        )

    def test_an_empty_or_missing_artifact_set_is_refused(self):
        result = injector.inject_empty_artifact(self.root)
        observed = result["observed"]
        self.assertEqual("RECOVERY_REQUIRED", observed["zero_byte_artifact_state"])
        self.assertEqual("RECOVERY_REQUIRED", observed["no_artifact_state"])
        self.assertEqual(
            ["$.artifacts[0].bytes: must be an integer >= 1"], observed["zero_byte_artifact_errors"]
        )
        # The seeded contract rejects an artifact-free committed result before
        # ingestion reaches its own "nothing durable to ingest" guard.
        self.assertEqual(
            ["$.artifacts: committed result requires at least one artifact"],
            observed["no_artifact_errors"],
        )


class RecoveryTests(CorruptionTestCase):
    def test_the_immutable_capsule_survives_every_refusal(self):
        for name, mutate in REFUSING_CLASSES:
            with self.subTest(fault_class=name):
                result = injector.inject_corruption(self.root, name, mutate)
                self.assertTrue(result["observed"]["immutable_input_intact"])

    def test_a_rerun_from_the_immutable_capsule_is_ingested(self):
        for name, mutate in REFUSING_CLASSES:
            with self.subTest(fault_class=name):
                result = injector.inject_corruption(self.root, name, mutate)
                self.assertEqual("PARENT_INGESTED", result["observed"]["rerun_state"])
                self.assertEqual([], result["observed"]["rerun_errors"])

    def test_the_event_chain_stays_verifiable_through_refusal_and_rerun(self):
        result = injector.inject_corruption(
            self.root, "ARTIFACT_PATH_ABSENT_FROM_THE_COMMIT", injector.corrupt_absent_path
        )
        self.assertEqual([], result["observed"]["event_chain_errors"])


class ImmutableReadBackTests(CorruptionTestCase):
    def test_tampering_with_the_worktree_after_the_commit_changes_nothing(self):
        result = injector.inject_corruption(
            self.root,
            "WORKTREE_TAMPERED_AFTER_THE_COMMIT",
            injector.corrupt_worktree_after_commit,
        )
        observed = result["observed"]
        self.assertEqual("PARENT_INGESTED", observed["ingestion_state"])
        self.assertEqual([], observed["ingestion_errors"])
        self.assertTrue(observed["committed_object_still_governs"])

    def test_read_back_refuses_any_locator_that_is_not_a_git_object(self):
        module = kit.bind_sandbox(kit.load_factory("047_locator"), self.root / "locator")
        for locator in ("file:///tmp/result.json", "http://example.invalid/result.json", "result.json"):
            with self.subTest(locator=locator):
                with self.assertRaises(ValueError):
                    module.read_object_bytes(locator)


class AggregateTests(CorruptionTestCase):
    def test_unit_passes_with_no_false_completion_across_all_classes(self):
        report = injector.inject_all(self.root)
        self.assertEqual(9, report["fault_classes"])
        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(0, report["false_completions_observed"])


if __name__ == "__main__":
    unittest.main()
