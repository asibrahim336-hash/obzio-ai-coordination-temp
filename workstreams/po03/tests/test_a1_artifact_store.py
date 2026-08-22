"""a1-u07 — bit flips and truncation are caught on read-back, and named.

Hypothesis (frozen in ``control/dispatch/a1-u07.json``): a content-addressed
artifact store detects single-bit corruption and truncation on read-back.

Acceptance, satisfied literally: bit-flip and truncation fixtures are rejected
at read-back with 100% detection and a precise diagnostic naming the artifact.
Falsified if a corrupted artifact is accepted or the diagnostic omits the
artifact identity.

Detection is measured over randomised fixtures rather than one example, because
one example proves only that one byte matters.  Every fixture damages real bytes
on disk through a real write; nothing simulates corruption by faking a hash.
The diagnostic is asserted field by field, since a message that says only
"checksum mismatch" is useless when sixty-four units are running at once.
"""

from __future__ import annotations

import random
import unittest

from test_a1_support import ScratchCase

from engine.artifact_store import (
    BYTE_COUNT_MISMATCH,
    CONTENT_MISMATCH,
    OBJECT_ABSENT,
    ArtifactCorruption,
    ArtifactStore,
    ArtifactStoreError,
    corrupt_in_place,
    truncate_in_place,
)
from engine.canonical import sha256_bytes
from engine.ledger import HashChainedLedger

UNIT = "a1-u07-subject"
FIXTURES_PER_CLASS = 200


class StoreCase(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.ledger = HashChainedLedger(self.scratch / "ledger.jsonl")
        self.store = ArtifactStore(self.scratch / "store", self.ledger)

    def put(self, name: str, data: bytes, artifact_id: str | None = None):
        return self.store.put(
            artifact_id or f"{UNIT}-art-{name}", name, data, unit_id=UNIT, media_type="text/plain"
        )


class RoundTripTests(StoreCase):
    def test_intact_artifact_round_trips(self):
        data = b"transactional custody engine\n"
        ref = self.put("result.json", data)
        self.assertEqual(sha256_bytes(data), ref.sha256)
        self.assertEqual(len(data), ref.bytes)
        self.assertEqual(data, self.store.get(ref, unit_id=UNIT))
        self.assertTrue(self.store.audit()["ok"])

    def test_address_is_the_digest(self):
        data = b"content addressed\n"
        ref = self.put("a.txt", data)
        expected = self.store.objects_root / ref.sha256[:2] / ref.sha256[2:]
        self.assertTrue(expected.is_file())
        self.assertEqual(data, expected.read_bytes())

    def test_identical_bytes_are_stored_once(self):
        data = b"deduplicated\n"
        first = self.put("a.txt", data, artifact_id="art-a")
        second = self.put("b.txt", data, artifact_id="art-b")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(1, sum(1 for _ in self.store.objects_root.rglob("*") if _.is_file()))
        self.assertEqual(data, self.store.get(second))

    def test_empty_artifact_is_refused(self):
        with self.assertRaises(ArtifactStoreError):
            self.put("empty.txt", b"")

    def test_storing_is_recorded_in_the_ledger(self):
        ref = self.put("a.txt", b"recorded\n")
        stored = [row for row in self.ledger.events_for(UNIT) if row["event"] == "ARTIFACT_STORED"]
        self.assertEqual(1, len(stored))
        self.assertEqual(ref.sha256, stored[0]["payload"]["sha256"])


class BitFlipDetectionTests(StoreCase):
    def test_every_randomised_bit_flip_is_detected(self):
        rng = random.Random(20260822)
        detected = 0
        classifications: set[str] = set()
        for index in range(FIXTURES_PER_CLASS):
            store = ArtifactStore(self.scratch / f"flip-{index:04d}")
            size = rng.randrange(2, 4096)
            data = bytes(rng.randrange(256) for _ in range(size))
            ref = store.put(f"art-{index:04d}", f"artifact-{index:04d}.bin", data)
            self.assertEqual(data, store.get(ref))

            corrupt_in_place(
                store.object_path(ref.sha256), offset=rng.randrange(size), bit=rng.randrange(8)
            )
            try:
                store.get(ref)
            except ArtifactCorruption as failure:
                detected += 1
                classifications.add(failure.classification)
            else:
                self.fail(f"fixture {index} returned corrupted bytes without complaint")
        self.assertEqual(FIXTURES_PER_CLASS, detected)
        self.assertEqual({CONTENT_MISMATCH}, classifications)

    def test_bit_flip_diagnostic_names_the_artifact(self):
        data = b"y" * 512
        ref = self.put("evidence.bin", data, artifact_id="a1-u07-art-01")
        corrupt_in_place(self.store.object_path(ref.sha256), offset=17, bit=3)
        with self.assertRaises(ArtifactCorruption) as caught:
            self.store.get(ref, unit_id=UNIT)
        failure = caught.exception
        self.assertEqual("a1-u07-art-01", failure.artifact_id)
        self.assertEqual("evidence.bin", failure.logical_name)
        self.assertEqual(CONTENT_MISMATCH, failure.classification)
        self.assertEqual(ref.sha256, failure.expected_sha256)
        self.assertNotEqual(ref.sha256, failure.observed_sha256)
        self.assertEqual(len(data), failure.expected_bytes)
        self.assertEqual(len(data), failure.observed_bytes)
        self.assertEqual("NOT_SUPPORTED", failure.corrupt_byte_offset)
        message = str(failure)
        self.assertIn("a1-u07-art-01", message)
        self.assertIn("evidence.bin", message)
        self.assertIn(ref.sha256, message)
        self.assertIn("NOT_SUPPORTED", message)


class TruncationDetectionTests(StoreCase):
    def test_every_randomised_truncation_is_detected(self):
        rng = random.Random(101)
        detected = 0
        for index in range(FIXTURES_PER_CLASS):
            store = ArtifactStore(self.scratch / f"trunc-{index:04d}")
            size = rng.randrange(2, 4096)
            data = bytes(rng.randrange(256) for _ in range(size))
            ref = store.put(f"art-{index:04d}", f"artifact-{index:04d}.bin", data)
            truncate_in_place(store.object_path(ref.sha256), keep_bytes=rng.randrange(0, size))
            try:
                store.get(ref)
            except ArtifactCorruption as failure:
                self.assertEqual(BYTE_COUNT_MISMATCH, failure.classification)
                self.assertLess(failure.observed_bytes, failure.expected_bytes)
                detected += 1
            else:
                self.fail(f"fixture {index} returned truncated bytes without complaint")
        self.assertEqual(FIXTURES_PER_CLASS, detected)

    def test_truncation_to_zero_bytes_is_detected(self):
        ref = self.put("evidence.bin", b"z" * 64, artifact_id="a1-u07-art-02")
        truncate_in_place(self.store.object_path(ref.sha256), keep_bytes=0)
        with self.assertRaises(ArtifactCorruption) as caught:
            self.store.get(ref)
        self.assertEqual(BYTE_COUNT_MISMATCH, caught.exception.classification)
        self.assertEqual(0, caught.exception.observed_bytes)
        self.assertIn("truncated by 64 bytes", str(caught.exception))

    def test_extension_is_distinguished_from_truncation(self):
        ref = self.put("evidence.bin", b"w" * 32, artifact_id="a1-u07-art-03")
        path = self.store.object_path(ref.sha256)
        with path.open("ab") as handle:
            handle.write(b"appended")
        with self.assertRaises(ArtifactCorruption) as caught:
            self.store.get(ref)
        self.assertEqual(BYTE_COUNT_MISMATCH, caught.exception.classification)
        self.assertIn("extended by 8 bytes", str(caught.exception))

    def test_a_deleted_object_is_distinguished_from_a_damaged_one(self):
        ref = self.put("evidence.bin", b"v" * 32, artifact_id="a1-u07-art-04")
        self.store.object_path(ref.sha256).unlink()
        with self.assertRaises(ArtifactCorruption) as caught:
            self.store.get(ref)
        self.assertEqual(OBJECT_ABSENT, caught.exception.classification)
        self.assertIn("a1-u07-art-04", str(caught.exception))


class AuditTests(StoreCase):
    def test_audit_reports_one_diagnostic_per_damaged_artifact(self):
        refs = [self.put(f"file-{n}.bin", bytes([n]) * (64 + n), artifact_id=f"art-{n}") for n in range(1, 6)]
        self.assertTrue(self.store.audit()["ok"])

        corrupt_in_place(self.store.object_path(refs[1].sha256), offset=3, bit=1)
        truncate_in_place(self.store.object_path(refs[3].sha256), keep_bytes=10)
        report = self.store.audit()
        self.assertFalse(report["ok"])
        self.assertEqual(5, report["artifacts_checked"])
        self.assertEqual(2, report["corrupt"])
        self.assertEqual(3, report["intact"])
        named = {item["artifact_id"] for item in report["diagnostics"]}
        self.assertEqual({"art-2", "art-4"}, named)
        classes = {item["artifact_id"]: item["classification"] for item in report["diagnostics"]}
        self.assertEqual(CONTENT_MISMATCH, classes["art-2"])
        self.assertEqual(BYTE_COUNT_MISMATCH, classes["art-4"])

    def test_corruption_is_recorded_in_the_ledger(self):
        ref = self.put("a.bin", b"q" * 40, artifact_id="art-q")
        corrupt_in_place(self.store.object_path(ref.sha256), offset=1, bit=0)
        with self.assertRaises(ArtifactCorruption):
            self.store.get(ref, unit_id=UNIT)
        rows = [row for row in self.ledger.events_for(UNIT) if row["event"] == "ARTIFACT_CORRUPT"]
        self.assertEqual(1, len(rows))
        self.assertEqual("art-q", rows[0]["payload"]["artifact_id"])
        self.assertEqual(CONTENT_MISMATCH, rows[0]["payload"]["classification"])
        self.assertTrue(self.ledger.verify().ok)

    def test_an_object_that_does_not_match_its_own_address_is_refused_on_put(self):
        data = b"p" * 48
        ref = self.put("a.bin", data, artifact_id="art-p")
        corrupt_in_place(self.store.object_path(ref.sha256), offset=2, bit=4)
        with self.assertRaises(ArtifactCorruption) as caught:
            self.put("a.bin", data, artifact_id="art-p-again")
        self.assertIn("does not match its own address", str(caught.exception))


class NegativeControlTests(StoreCase):
    """Prove the verification is what catches the damage."""

    def test_an_unchecked_read_returns_the_corrupted_bytes(self):
        data = b"m" * 128
        ref = self.put("a.bin", data, artifact_id="art-m")
        path = self.store.object_path(ref.sha256)
        corrupt_in_place(path, offset=9, bit=6)

        # The read the store deliberately does not offer: bytes straight off
        # disk with no digest recomputation.  It succeeds and returns damage.
        unchecked = path.read_bytes()
        self.assertEqual(len(data), len(unchecked))
        self.assertNotEqual(data, unchecked)
        self.assertNotEqual(sha256_bytes(data), sha256_bytes(unchecked))

        with self.assertRaises(ArtifactCorruption):
            self.store.get(ref)

    def test_a_size_only_check_would_miss_every_bit_flip(self):
        rng = random.Random(7)
        missed_by_size_check = 0
        for index in range(50):
            store = ArtifactStore(self.scratch / f"size-only-{index:03d}")
            data = bytes(rng.randrange(256) for _ in range(64))
            ref = store.put(f"art-{index}", "a.bin", data)
            path = store.object_path(ref.sha256)
            corrupt_in_place(path, offset=rng.randrange(64), bit=rng.randrange(8))
            if path.stat().st_size == ref.bytes:
                missed_by_size_check += 1
            with self.assertRaises(ArtifactCorruption):
                store.get(ref)
        self.assertEqual(50, missed_by_size_check, "a size-only check must be shown to be insufficient")


if __name__ == "__main__":
    unittest.main()
