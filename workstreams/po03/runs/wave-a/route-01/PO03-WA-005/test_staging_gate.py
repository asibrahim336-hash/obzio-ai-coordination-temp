#!/usr/bin/env python3
"""Falsification suite for PO03-WA-005.

The hypothesis is falsified if any partially written slot reaches
``RESULT_STAGED`` or leaves a published slot on disk.  The crash matrix is
exhaustive over (artifact index x truncation point) rather than a single
hand-placed failure, and includes the two adversarial cases that defeat naive
gates: an artifact truncated to zero bytes, and a same-length corruption that
only a hash comparison can catch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("staging_gate", Path(__file__).with_name("staging_gate.py"))
assert SPEC is not None and SPEC.loader is not None
SG = importlib.util.module_from_spec(SPEC)
sys.modules["staging_gate"] = SG
SPEC.loader.exec_module(SG)


def artifacts():
    return [
        SG.DeclaredArtifact("a.py", b"A" * 100),
        SG.DeclaredArtifact("nested/b.txt", b"B" * 200),
        SG.DeclaredArtifact("c.md", b"C" * 300),
    ]


class TempCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.directory = Path(self._directory.name)


class CleanStageTests(TempCase):
    def test_a_complete_write_reaches_staged(self):
        gate = SG.StagingGate(self.directory / "slot")
        self.assertEqual("RESULT_STAGING", gate.state)
        self.assertEqual("RESULT_STAGED", gate.stage(artifacts()))
        self.assertTrue(gate.slot.exists())
        self.assertTrue(all(item["verified"] for item in gate.verification_report))

    def test_all_declared_artifacts_are_present_after_promotion(self):
        gate = SG.StagingGate(self.directory / "slot")
        gate.stage(artifacts())
        published = sorted(p.relative_to(gate.slot).as_posix() for p in gate.slot.rglob("*") if p.is_file())
        self.assertEqual(["a.py", "c.md", "nested/b.txt"], published)

    def test_no_scratch_directory_survives_a_successful_stage(self):
        gate = SG.StagingGate(self.directory / "slot")
        gate.stage(artifacts())
        self.assertFalse(gate.scratch.exists())

    def test_empty_declaration_is_refused(self):
        gate = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused) as caught:
            gate.stage([])
        self.assertEqual("EMPTY_DECLARATION", caught.exception.reason)
        self.assertEqual("RESULT_STAGING", gate.state)


class CrashMatrixTests(TempCase):
    def test_every_silent_short_write_fails_closed(self):
        """Exhaustive matrix over (artifact index x truncation point).

        Nothing raises during the write loop here: the loop completes and the
        gate is told the slot is ready.  Only readback verification stands
        between a truncated artifact and RESULT_STAGED.
        """
        declared = artifacts()
        reached_staged = []
        published = []
        undetected = []
        for index, artifact in enumerate(declared):
            for fraction in (0, 2, 4, 8):
                truncate_to = 0 if fraction == 0 else artifact.bytes // fraction
                slot = self.directory / f"slot-{index}-{fraction}"
                gate = SG.StagingGate(slot)
                injector = SG.CrashInjector(truncate_at_index=index, truncate_to=truncate_to)
                with self.assertRaises(SG.StagingRefused) as caught:
                    gate.stage(declared, injector)
                if caught.exception.reason != "ARTIFACT_VERIFICATION_FAILED":
                    undetected.append((index, fraction, caught.exception.reason))
                if gate.state == "RESULT_STAGED":
                    reached_staged.append((index, fraction))
                if slot.exists():
                    published.append((index, fraction))
        self.assertEqual([], undetected, "every short write must be caught by verification")
        self.assertEqual([], reached_staged, "no partial write may reach RESULT_STAGED")
        self.assertEqual([], published, "no partial write may publish a slot")

    def test_every_process_loss_point_fails_closed(self):
        """Loud crashes before and after each artifact never publish a slot."""
        declared = artifacts()
        published = []
        for index in range(len(declared)):
            for kind in ("before", "after"):
                slot = self.directory / f"crash-{index}-{kind}"
                gate = SG.StagingGate(slot)
                injector = (
                    SG.CrashInjector(crash_at_index=index)
                    if kind == "before"
                    else SG.CrashInjector(crash_after_index=index)
                )
                with self.assertRaises(SG.StagingRefused) as caught:
                    gate.stage(declared, injector)
                self.assertEqual("PROCESS_LOST_MID_WRITE", caught.exception.reason)
                self.assertEqual("RESULT_STAGING", gate.state)
                if slot.exists():
                    published.append((index, kind))
        self.assertEqual([], published)

    def test_truncation_is_reported_with_declared_and_observed_counts(self):
        declared = artifacts()
        gate = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused) as caught:
            gate.stage(declared, SG.CrashInjector(truncate_at_index=1, truncate_to=50))
        self.assertEqual("ARTIFACT_VERIFICATION_FAILED", caught.exception.reason)
        failure = caught.exception.failures[0]
        self.assertEqual("nested/b.txt", failure["logical_name"])
        self.assertEqual("BYTES_TRUNCATED", failure["reason"])
        self.assertEqual(200, failure["declared_bytes"])
        self.assertEqual(50, failure["observed_bytes"])
        self.assertNotEqual(failure["declared_sha256"], failure["observed_sha256"])

    def test_zero_byte_artifact_is_caught(self):
        declared = artifacts()
        gate = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused) as caught:
            gate.stage(declared, SG.CrashInjector(truncate_at_index=2, truncate_to=0))
        self.assertEqual(0, caught.exception.failures[0]["observed_bytes"])
        self.assertFalse(gate.slot.exists())


class AdversarialTests(TempCase):
    def test_same_length_corruption_is_caught_by_the_hash_not_the_byte_count(self):
        """A byte-count-only gate would pass this; the hash must catch it."""
        declared = [SG.DeclaredArtifact("a.py", b"A" * 100)]
        corrupt = SG.DeclaredArtifact("a.py", b"B" * 100)
        self.assertEqual(declared[0].bytes, corrupt.bytes, "the corruption preserves length")
        self.assertNotEqual(declared[0].sha256, corrupt.sha256)

        gate = SG.StagingGate(self.directory / "slot")
        gate.scratch.mkdir(parents=True)
        gate._write_artifact(gate.scratch, "a.py", corrupt.payload)
        failures = gate._verify(gate.scratch, declared)
        self.assertEqual(1, len(failures))
        self.assertEqual("HASH_MISMATCH", failures[0]["reason"])
        self.assertEqual(100, failures[0]["observed_bytes"])

    def test_missing_artifact_is_distinguished_from_truncation(self):
        declared = artifacts()
        gate = SG.StagingGate(self.directory / "slot")
        gate.scratch.mkdir(parents=True)
        gate._write_artifact(gate.scratch, "a.py", declared[0].payload)
        failures = gate._verify(gate.scratch, declared)
        reasons = {item["logical_name"]: item["reason"] for item in failures}
        self.assertEqual({"nested/b.txt": "MISSING_ARTIFACT", "c.md": "MISSING_ARTIFACT"}, reasons)

    def test_verification_reads_the_file_not_the_declaration(self):
        """Overwrite after writing: the gate must notice the disk, not the intent."""
        declared = [SG.DeclaredArtifact("a.py", b"A" * 100)]
        gate = SG.StagingGate(self.directory / "slot")
        gate.scratch.mkdir(parents=True)
        gate._write_artifact(gate.scratch, "a.py", declared[0].payload)
        (gate.scratch / "a.py").write_bytes(b"A" * 99)
        failures = gate._verify(gate.scratch, declared)
        self.assertEqual("BYTES_TRUNCATED", failures[0]["reason"])

    def test_publishing_over_an_existing_slot_is_refused(self):
        gate = SG.StagingGate(self.directory / "slot")
        gate.stage(artifacts())
        second = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused) as caught:
            second.stage(artifacts())
        self.assertEqual("SLOT_ALREADY_PUBLISHED", caught.exception.reason)


class RecoveryTests(TempCase):
    def test_crash_debris_is_discarded_and_named_on_recovery(self):
        """A dead process cannot clean up after itself; recovery must."""
        declared = artifacts()
        gate = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused):
            gate.stage(declared, SG.CrashInjector(crash_after_index=0))
        self.assertTrue(gate.scratch.exists(), "the crash leaves scratch behind")
        report = gate.recover(declared)
        self.assertEqual("SCRATCH_DISCARDED", report["action"])
        self.assertIn("a.py", report["debris_found"])
        self.assertFalse(report["slot_published"])
        self.assertFalse(gate.scratch.exists(), "debris must not survive recovery")

    def test_recovery_after_a_clean_stage_verifies_the_published_slot(self):
        gate = SG.StagingGate(self.directory / "slot")
        gate.stage(artifacts())
        report = gate.recover(artifacts())
        self.assertEqual("PUBLISHED_SLOT_VERIFIED", report["action"])
        self.assertEqual([], report["failures"])

    def test_retry_after_a_failed_stage_succeeds(self):
        declared = artifacts()
        gate = SG.StagingGate(self.directory / "slot")
        with self.assertRaises(SG.StagingRefused):
            gate.stage(declared, SG.CrashInjector(truncate_at_index=0, truncate_to=5))
        gate.recover(declared)
        self.assertEqual("RESULT_STAGED", gate.stage(declared))


class ReproductionTests(TempCase):
    def test_reproduction_never_stages_or_publishes_a_partial_slot(self):
        report = SG.reproduce_partial_write(self.directory)
        self.assertFalse(report["any_reached_staged"])
        self.assertFalse(report["any_slot_published"])
        self.assertEqual("RESULT_STAGED", report["clean_stage_state"])
        self.assertEqual(3, len(report["clean_slot_files"]))
        for attempt in report["truncation_attempts"]:
            self.assertEqual("RESULT_STAGING", attempt["state"])
            self.assertEqual("ARTIFACT_VERIFICATION_FAILED", attempt["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
