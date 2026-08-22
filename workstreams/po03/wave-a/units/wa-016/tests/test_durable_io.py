"""Crash consistency of the durable write primitives."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness.durable_io import DurableIO, canonical_json
from harness.fault_injector import ProcessLoss, quiet, single


class TempRoot(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="po03-wa016-io-")
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)


class AppendOnlyLogTests(TempRoot):
    def test_records_round_trip(self):
        io = DurableIO(self.root, quiet())
        for index in range(3):
            io.append_record("log.jsonl", {"seq": index}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        read = io.read_records("log.jsonl")
        self.assertEqual([0, 1, 2], [r["seq"] for r in read.records])
        self.assertFalse(read.torn)

    def test_crash_before_append_leaves_nothing(self):
        io = DurableIO(self.root, single("PRE_WRITE_LOSS", "pre_journal_append"))
        with self.assertRaises(ProcessLoss):
            io.append_record("log.jsonl", {"seq": 1}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        self.assertEqual([], io.read_records("log.jsonl").records)

    def test_crash_after_append_keeps_the_record(self):
        io = DurableIO(self.root, single("POST_WRITE_LOSS", "post_journal_append"))
        with self.assertRaises(ProcessLoss):
            io.append_record("log.jsonl", {"seq": 1}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        self.assertEqual([1], [r["seq"] for r in io.read_records("log.jsonl").records])

    def test_torn_record_is_not_replayed(self):
        io = DurableIO(self.root, quiet())
        io.append_record("log.jsonl", {"seq": 1}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        torn = DurableIO(self.root, single("PARTIAL_WRITE", "journal_append_partial"))
        with self.assertRaises(ProcessLoss):
            torn.append_record("log.jsonl", {"seq": 2}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        read = torn.read_records("log.jsonl")
        self.assertEqual([1], [r["seq"] for r in read.records])
        self.assertTrue(read.torn)

    def test_healing_truncates_only_the_torn_tail(self):
        io = DurableIO(self.root, quiet())
        io.append_record("log.jsonl", {"seq": 1}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        torn = DurableIO(self.root, single("PARTIAL_WRITE", "journal_append_partial"))
        with self.assertRaises(ProcessLoss):
            torn.append_record("log.jsonl", {"seq": 2}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        discarded = torn.heal_records("log.jsonl")
        self.assertGreater(discarded, 0)
        healed = torn.read_records("log.jsonl")
        self.assertFalse(healed.torn)
        self.assertEqual([1], [r["seq"] for r in healed.records])
        # The healed log accepts further appends and still parses.
        torn.append_record("log.jsonl", {"seq": 3}, pre="pre_journal_append", partial="journal_append_partial", post="post_journal_append")
        self.assertEqual([1, 3], [r["seq"] for r in torn.read_records("log.jsonl").records])


class AtomicSnapshotTests(TempRoot):
    def _write(self, io: DurableIO, payload: dict) -> None:
        io.atomic_write("state.json", canonical_json(payload), pre="pre_snapshot_write", mid="post_snapshot_tmp_write", post="post_snapshot_rename")

    def test_crash_before_rename_preserves_the_previous_snapshot(self):
        self._write(DurableIO(self.root, quiet()), {"generation": 1})
        io = DurableIO(self.root, single("SNAPSHOT_ROLLBACK", "post_snapshot_tmp_write"))
        with self.assertRaises(ProcessLoss):
            self._write(io, {"generation": 2})
        self.assertEqual({"generation": 1}, io.read_json("state.json"))
        self.assertEqual(["state.json.tmp"], io.orphan_temp_files())

    def test_crash_after_rename_keeps_the_new_snapshot(self):
        self._write(DurableIO(self.root, quiet()), {"generation": 1})
        io = DurableIO(self.root, single("PROCESS_LOSS", "post_snapshot_rename"))
        with self.assertRaises(ProcessLoss):
            self._write(io, {"generation": 2})
        self.assertEqual({"generation": 2}, io.read_json("state.json"))
        self.assertEqual([], io.orphan_temp_files())


class ArtifactWriteTests(TempRoot):
    def test_partial_artifact_write_is_detectable(self):
        payload = b"x" * 100
        io = DurableIO(self.root, single("PARTIAL_WRITE", "artifact_write_partial"))
        with self.assertRaises(ProcessLoss):
            io.write_artifact("staging/a.bin", payload)
        written = io.read_artifact("staging/a.bin")
        self.assertIsNotNone(written)
        self.assertLess(len(written), len(payload))


if __name__ == "__main__":
    unittest.main()
