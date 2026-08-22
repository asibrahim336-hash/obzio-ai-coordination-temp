"""Falsification tests for the PO03-WA-038 lineage recorder.

The fixture is a small two-stage generation pipeline built in a temporary
directory: a tool reads ``input.txt`` and writes ``stage1.txt``; a second
record derives ``stage2.txt`` from ``stage1.txt``.  Each test then breaks
exactly one link in that chain and asserts the specific finding.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "lineage_recorder.py"
SPEC = importlib.util.spec_from_file_location("lineage_recorder", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


class LineageFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-038-")
        self.root = Path(self._tmp.name)
        (self.root / "tools").mkdir()
        (self.root / "out").mkdir()
        (self.root / "input.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        (self.root / "tools" / "shout.py").write_text(
            "import sys\nsys.stdout.write(open(sys.argv[1]).read().upper())\n", encoding="utf-8"
        )
        self.config1 = {"mode": "upper", "encoding": "utf-8", "retries": 0}
        self.config2 = {"mode": "reverse", "encoding": "utf-8"}

        stage1 = (self.root / "input.txt").read_text(encoding="utf-8").upper()
        (self.root / "out" / "stage1.txt").write_text(stage1, encoding="utf-8")
        (self.root / "out" / "stage2.txt").write_text(stage1[::-1], encoding="utf-8")

        self.r1 = G.record_generation(
            self.root, "rec-stage1", "out/stage1.txt", ["input.txt"],
            "shout", "1.0.0", "tools/shout.py", self.config1, parents=[],
            recorded_at="2026-08-22T07:00:00Z",
        )
        self.r2 = G.record_generation(
            self.root, "rec-stage2", "out/stage2.txt", ["out/stage1.txt"],
            "shout", "1.0.0", "tools/shout.py", self.config2, parents=["rec-stage1"],
            recorded_at="2026-08-22T07:00:01Z",
        )
        self.ledger_path = self.root / "lineage.json"
        self.save(G.LineageLedger([self.r1, self.r2]))

    def tearDown(self):
        self._tmp.cleanup()

    def save(self, ledger):
        self.ledger_path.write_text(
            json.dumps(ledger.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def reload(self):
        return G.LineageLedger.from_dict(json.loads(self.ledger_path.read_text(encoding="utf-8")))

    def findings(self, ledger=None):
        return {f.finding for f in G.verify(ledger or self.reload(), self.root)}

    def mutate_document(self, mutate):
        document = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        mutate(document)
        self.ledger_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class RecordingTests(LineageFixture):
    def test_intact_lineage_verifies(self):
        self.assertEqual(set(), self.findings())

    def test_record_pins_all_four_provenance_facts(self):
        record = self.reload().get("rec-stage2")
        self.assertEqual("out/stage2.txt", record.output.path)
        self.assertEqual(["out/stage1.txt"], [s.path for s in record.sources])
        self.assertEqual("tools/shout.py", record.tool.source_path)
        self.assertEqual(64, len(record.tool.source_sha256))
        self.assertEqual({"mode": "reverse", "encoding": "utf-8"}, record.configuration)
        self.assertEqual(["rec-stage1"], record.parents)

    def test_attestation_is_stable_across_a_round_trip(self):
        self.assertEqual(self.r2.attestation_sha256, self.reload().get("rec-stage2").attestation_sha256)

    def test_configuration_key_order_does_not_change_the_digest(self):
        a = G.sha256_bytes(G.canonical_json({"b": 2, "a": 1}))
        b = G.sha256_bytes(G.canonical_json({"a": 1, "b": 2}))
        self.assertEqual(a, b)

    def test_configuration_value_change_does_change_the_digest(self):
        a = G.sha256_bytes(G.canonical_json({"a": 1}))
        b = G.sha256_bytes(G.canonical_json({"a": 2}))
        self.assertNotEqual(a, b)

    def test_ancestry_walks_to_the_root(self):
        self.assertEqual(["rec-stage1"], self.reload().ancestry("rec-stage2"))

    def test_duplicate_record_id_is_refused(self):
        with self.assertRaises(G.LineageError):
            G.LineageLedger([self.r1, self.r1])


class DriftDetectionTests(LineageFixture):
    def test_source_mutation_after_recording_is_caught(self):
        (self.root / "input.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        self.assertIn(G.SOURCE_DRIFT, self.findings())

    def test_output_mutation_after_recording_is_caught(self):
        (self.root / "out" / "stage2.txt").write_text("hand edited\n", encoding="utf-8")
        self.assertIn(G.OUTPUT_DRIFT, self.findings())

    def test_tool_source_change_is_caught_even_at_the_same_version(self):
        (self.root / "tools" / "shout.py").write_text("# silently different behaviour\n", encoding="utf-8")
        findings = self.findings()
        self.assertIn(G.TOOL_DRIFT, findings)

    def test_missing_source_file_is_caught(self):
        (self.root / "input.txt").unlink()
        self.assertIn(G.MISSING_FILE, self.findings())

    def test_configuration_tampering_is_caught(self):
        self.mutate_document(
            lambda d: d["records"][0]["configuration"].update(retries=99)
        )
        findings = self.findings()
        self.assertIn(G.CONFIG_TAMPERED, findings)

    def test_field_edit_without_reseal_is_caught(self):
        self.mutate_document(lambda d: d["records"][0].update(record_id="rec-stage1"))
        self.mutate_document(lambda d: d["records"][0]["output"].update(bytes=1))
        self.assertIn(G.ATTESTATION_MISMATCH, self.findings())

    def test_resealing_a_tampered_record_still_fails_on_the_bytes(self):
        """An attacker who reseals must still make the filesystem agree."""
        (self.root / "out" / "stage1.txt").write_text("forged\n", encoding="utf-8")
        ledger = self.reload()
        record = ledger.get("rec-stage1")
        record.seal()
        self.assertIn(G.OUTPUT_DRIFT, {f.finding for f in G.verify(ledger, self.root)})


class LineageStructureTests(LineageFixture):
    def test_missing_parent_is_broken_lineage(self):
        self.mutate_document(
            lambda d: [r for r in d["records"] if r["record_id"] == "rec-stage2"][0].update(
                parents=["rec-does-not-exist"]
            )
        )
        self.assertIn(G.BROKEN_LINEAGE, self.findings())

    def test_cycle_is_detected(self):
        def make_cycle(document):
            for record in document["records"]:
                if record["record_id"] == "rec-stage1":
                    record["parents"] = ["rec-stage2"]

        self.mutate_document(make_cycle)
        self.assertIn(G.CYCLE_DETECTED, self.findings())

    def test_self_parent_is_a_cycle(self):
        self.mutate_document(
            lambda d: [r for r in d["records"] if r["record_id"] == "rec-stage1"][0].update(
                parents=["rec-stage1"]
            )
        )
        self.assertIn(G.CYCLE_DETECTED, self.findings())

    def test_unrecorded_source_is_caught_when_declared(self):
        findings = G.verify(self.reload(), self.root, declared_sources={"rec-stage1": ["tools/shout.py"]})
        self.assertIn(G.UNRECORDED_SOURCE, {f.finding for f in findings})

    def test_malformed_ledger_is_refused(self):
        with self.assertRaises(G.LineageError):
            G.LineageLedger.from_dict({"records": "not a list"})

    def test_record_missing_a_field_is_refused(self):
        with self.assertRaises(G.LineageError):
            G.LineageRecord.from_dict({"record_id": "x"})


class CommandLineTests(LineageFixture):
    def _run(self):
        return subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--ledger",
                str(self.ledger_path),
                "--root",
                str(self.root),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_intact_lineage_exits_zero(self):
        proc = self._run()
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["lineage_intact"])

    def test_broken_lineage_exits_one(self):
        (self.root / "input.txt").write_text("changed\n", encoding="utf-8")
        proc = self._run()
        self.assertEqual(1, proc.returncode)
        self.assertFalse(json.loads(proc.stdout)["lineage_intact"])

    def test_unreadable_ledger_exits_two(self):
        self.ledger_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(2, self._run().returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
