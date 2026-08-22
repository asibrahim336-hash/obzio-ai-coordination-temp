#!/usr/bin/env python3
"""Focused tests for the WA-015 fault-injecting replay harness."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from _support import UNIT_ROOT, silenced

import outbox_processor as mechanism
import replay_harness as harness
import verify_replay


WORKLOAD_PATH = UNIT_ROOT / "fixtures" / "sanitized-workload.json"
DUPLICATE_PATH = UNIT_ROOT / "fixtures" / "duplicate-callbacks.json"
LOST_PATH = UNIT_ROOT / "fixtures" / "lost-callbacks.json"
ORACLE_PATH = UNIT_ROOT / "reproduction" / "expected-report.json"

_FORBIDDEN_KEYS = ("secret", "token", "password", "credential", "url", "endpoint", "host")


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key, child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield f"{path}[{index}]", None, child
            yield from _walk(child, f"{path}[{index}]")


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workload = mechanism.load_workload(WORKLOAD_PATH)
        cls.index = harness._callback_index(cls.workload)
        cls.report = harness.compile_report()


class TestShippedFixtures(FixtureCase):
    def test_every_scenario_passes(self) -> None:
        failing = {
            scenario["scenario_id"]: scenario["mismatches"]
            for fixture in self.report["fixtures"]
            for scenario in fixture["scenarios"]
            if scenario["outcome"] != "PASS"
        }
        self.assertEqual(failing, {})
        self.assertEqual(self.report["outcome"], "PASS")
        self.assertEqual(self.report["failures"], [])

    def test_both_callback_classes_are_covered(self) -> None:
        self.assertGreaterEqual(self.report["duplicate_scenarios"], 5)
        self.assertGreaterEqual(self.report["lost_scenarios"], 5)
        self.assertEqual(
            self.report["scenario_count"],
            self.report["duplicate_scenarios"] + self.report["lost_scenarios"],
        )

    def test_faults_are_actually_injected(self) -> None:
        self.assertGreaterEqual(self.report["injected_crashes"], 8)
        fired = [
            fault["point"]
            for fixture in self.report["fixtures"]
            for scenario in fixture["scenarios"]
            for phase in scenario["phases"]
            for fault in phase["faults_fired"]
        ]
        self.assertGreaterEqual(len(set(fired)), 5)
        self.assertTrue(set(fired) <= harness.FAULT_POINTS)

    def test_duplicates_are_suppressed_not_applied(self) -> None:
        self.assertGreaterEqual(self.report["duplicates_suppressed"], 10)

    def test_every_invariant_holds_in_every_scenario(self) -> None:
        for fixture in self.report["fixtures"]:
            for scenario in fixture["scenarios"]:
                self.assertEqual(
                    scenario["invariant_violations"], {}, scenario["scenario_id"]
                )
        self.assertEqual(
            set(self.report["invariants_checked"]), set(harness.INVARIANTS)
        )

    def test_no_scenario_leaves_a_pending_effect(self) -> None:
        for fixture in self.report["fixtures"]:
            for scenario in fixture["scenarios"]:
                self.assertEqual(
                    scenario["final"]["pending_effects"], [], scenario["scenario_id"]
                )

    def test_effect_receipts_are_dense_per_scenario(self) -> None:
        for fixture in self.report["fixtures"]:
            for scenario in fixture["scenarios"]:
                receipts = sorted(scenario["final"]["effect_receipts"].values())
                self.assertEqual(
                    receipts, list(range(1, len(receipts) + 1)), scenario["scenario_id"]
                )
                self.assertEqual(len(receipts), scenario["final"]["sink_effects"])

    def test_scenario_ids_are_unique_across_fixtures(self) -> None:
        identifiers = [
            scenario["scenario_id"]
            for fixture in self.report["fixtures"]
            for scenario in fixture["scenarios"]
        ]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_report_carries_no_environment_value(self) -> None:
        rendered = mechanism.canonical_bytes(self.report).decode("utf-8")
        for needle in ("/tmp", "/workspace", "wa015-", str(UNIT_ROOT)):
            self.assertNotIn(needle, rendered)


class TestFixtureValidation(FixtureCase):
    def valid(self) -> dict[str, Any]:
        return {
            "protocol_version": harness.FIXTURE_PROTOCOL,
            "scenarios": [
                {
                    "scenario_id": "SC-TEST-001",
                    "class": "duplicate",
                    "title": "A title.",
                    "phases": [{"phase": "one", "deliveries": ["alpha-lease"]}],
                    "expect": {"crashes": 0},
                }
            ],
        }

    def test_valid_fixture_is_accepted(self) -> None:
        self.assertEqual(
            harness.validate_fixture(self.valid(), self.index)["scenarios"][0][
                "scenario_id"
            ],
            "SC-TEST-001",
        )

    def _invalid(self, document: Any) -> None:
        with self.assertRaises(ValueError):
            harness.validate_fixture(document, self.index)

    def test_structural_defects_are_refused(self) -> None:
        self._invalid(["not", "an", "object"])
        self._invalid(dict(self.valid(), protocol_version="OTHER"))
        self._invalid(dict(self.valid(), scenarios=[]))
        self._invalid(dict(self.valid(), scenarios=["not an object"]))

    def test_scenario_identity_is_required_and_unique(self) -> None:
        document = self.valid()
        document["scenarios"] = [document["scenarios"][0], dict(document["scenarios"][0])]
        self._invalid(document)
        broken = self.valid()
        broken["scenarios"][0]["scenario_id"] = "  "
        self._invalid(broken)

    def test_class_and_title_are_constrained(self) -> None:
        for field, value in (("class", "unclassified"), ("title", "")):
            broken = self.valid()
            broken["scenarios"][0][field] = value
            self._invalid(broken)

    def test_unknown_callback_ref_is_refused(self) -> None:
        broken = self.valid()
        broken["scenarios"][0]["phases"][0]["deliveries"] = ["never-declared"]
        self._invalid(broken)

    def test_unknown_fault_point_or_mode_is_refused(self) -> None:
        for spec in (
            {"point": "invented_boundary"},
            {"point": "after_journal_append", "mode": "explode"},
            {"point": "after_journal_append", "occurrence": 0},
            "not an object",
        ):
            broken = self.valid()
            broken["scenarios"][0]["phases"][0]["faults"] = [spec]
            self._invalid(broken)

    def test_unknown_expectation_key_is_refused(self) -> None:
        broken = self.valid()
        broken["scenarios"][0]["expect"] = {"invented_metric": 1}
        self._invalid(broken)

    def test_empty_expectation_block_is_refused(self) -> None:
        broken = self.valid()
        broken["scenarios"][0]["expect"] = {}
        self._invalid(broken)

    def test_missing_phases_are_refused(self) -> None:
        broken = self.valid()
        broken["scenarios"][0]["phases"] = []
        self._invalid(broken)

    def test_shipped_fixtures_are_valid(self) -> None:
        for path in (DUPLICATE_PATH, LOST_PATH):
            document = harness.validate_fixture(
                json.loads(path.read_text(encoding="utf-8")), self.index
            )
            self.assertGreaterEqual(len(document["scenarios"]), 5)

    def test_workload_declares_no_external_surface(self) -> None:
        for path_label, key, value in _walk(self.workload):
            if key is not None:
                self.assertNotIn(
                    key.lower(),
                    _FORBIDDEN_KEYS,
                    f"{path_label} names an external surface",
                )
            if isinstance(value, str):
                self.assertNotIn("://", value, path_label)
                self.assertNotIn("@", value, path_label)

    def test_workload_declares_no_po01_path(self) -> None:
        rendered = WORKLOAD_PATH.read_text(encoding="utf-8")
        self.assertNotIn("workstreams/po01", rendered)
        self.assertNotIn("receipts/po01", rendered)


class TestFaultInjector(unittest.TestCase):
    def test_crash_fires_on_the_requested_occurrence(self) -> None:
        fault = harness._Fault([{"point": "after_journal_append", "occurrence": 2}])
        fault.trip("after_journal_append")
        with self.assertRaises(mechanism.InjectedCrash):
            fault.trip("after_journal_append")
        self.assertEqual(len(fault.fired), 1)

    def test_arrivals_are_counted_per_point(self) -> None:
        fault = harness._Fault([{"point": "before_sink_apply", "occurrence": 1}])
        fault.trip("after_journal_append")
        with self.assertRaises(mechanism.InjectedCrash):
            fault.trip("before_sink_apply")

    def test_tear_returns_the_requested_prefix_length(self) -> None:
        fault = harness._Fault(
            [
                {
                    "point": "journal_torn_write",
                    "mode": "tear",
                    "occurrence": 1,
                    "keep_bytes": 4,
                }
            ]
        )
        self.assertEqual(fault.tear("journal_torn_write"), 4)
        self.assertIsNone(fault.tear("journal_torn_write"))

    def test_an_unarmed_boundary_never_fires(self) -> None:
        fault = harness._Fault([])
        self.assertIsNone(fault.trip("after_sink_apply"))
        self.assertIsNone(fault.tear("journal_torn_write"))
        self.assertEqual(fault.fired, [])


class TestAudit(FixtureCase):
    def build_store(self) -> tuple[Any, Any]:
        tmp = tempfile.TemporaryDirectory(prefix="wa015-audit-")
        self.addCleanup(tmp.cleanup)
        store = Path(tmp.name) / "store"
        processor = mechanism.OutboxProcessor(store)
        processor.register_workload(self.workload)
        return processor, store

    def drive_to_commit(self, processor: Any) -> None:
        for ref in (
            "alpha-lease",
            "alpha-run",
            "alpha-checkpoint-1",
            "alpha-checkpoint-2",
            "alpha-staging",
            "alpha-staged",
            "alpha-verified",
            "alpha-committed",
        ):
            processor.handle(self.index[ref])
        processor.drain()

    def test_a_clean_run_has_no_violation(self) -> None:
        processor, _ = self.build_store()
        self.drive_to_commit(processor)
        self.assertEqual(harness.audit(processor), {})

    def test_a_duplicated_transition_record_is_caught(self) -> None:
        processor, store = self.build_store()
        self.drive_to_commit(processor)
        forged = dict(processor.records[4])
        forged["seq"] = processor.seq + 1
        processor.journal.append(mechanism.canonical_bytes(forged))
        violations = harness.audit(mechanism.OutboxProcessor(store))
        self.assertIn("single_transition_per_delivery", violations)

    def test_a_duplicated_sink_receipt_is_caught(self) -> None:
        processor, store = self.build_store()
        self.drive_to_commit(processor)
        forged = dict(processor.sink.receipts()[0])
        processor.sink.journal.append(mechanism.canonical_bytes(forged))
        violations = harness.audit(mechanism.OutboxProcessor(store))
        self.assertIn("single_effect_per_key", violations)

    def test_an_effect_without_an_enqueue_is_caught(self) -> None:
        processor, store = self.build_store()
        self.drive_to_commit(processor)
        processor.sink.journal.append(
            mechanism.canonical_bytes(
                {
                    "effect_key": "ef-smuggled",
                    "kind": "smuggled",
                    "payload_digest": "0" * 64,
                    "receipt_seq": 2,
                    "task_id": "FIX-PO03-CUSTODY-ALPHA",
                }
            )
        )
        violations = harness.audit(mechanism.OutboxProcessor(store))
        self.assertIn("no_effect_without_transition", violations)

    def test_a_forged_illegal_edge_is_caught(self) -> None:
        processor, store = self.build_store()
        self.drive_to_commit(processor)
        forged = dict(
            processor.records[-2],
            seq=processor.seq + 1,
            delivery_id="dlv-forged",
            idempotency_key="dlv-forged\x00" + "0" * 64,
            from_state="RESULT_COMMITTED",
            to_state="LEASED",
        )
        processor.journal.append(mechanism.canonical_bytes(forged))
        violations = harness.audit(mechanism.OutboxProcessor(store))
        self.assertIn("legal_state_path", violations)

    def test_a_non_dense_journal_sequence_is_caught(self) -> None:
        processor, store = self.build_store()
        self.drive_to_commit(processor)
        forged = dict(processor.records[-1], seq=processor.seq + 5)
        processor.journal.append(mechanism.canonical_bytes(forged))
        violations = harness.audit(mechanism.OutboxProcessor(store))
        self.assertIn("dense_journal_sequence", violations)


class TestReportDeterminism(unittest.TestCase):
    def test_two_compilations_are_byte_identical(self) -> None:
        self.assertEqual(verify_replay.compile_bytes(), verify_replay.compile_bytes())

    def test_report_matches_the_committed_oracle(self) -> None:
        self.assertEqual(verify_replay.compile_bytes(), ORACLE_PATH.read_bytes())

    def test_verify_reports_pass_with_a_dense_digest_set(self) -> None:
        report = verify_replay.verify(3)
        self.assertEqual(report["outcome"], "PASS")
        self.assertEqual(report["distinct_digests"], 1)
        self.assertTrue(report["self_consistent"])
        self.assertTrue(report["matches_oracle"])
        self.assertEqual(
            report["report_sha256"],
            hashlib.sha256(ORACLE_PATH.read_bytes()).hexdigest(),
        )

    def test_verify_refuses_a_single_compilation(self) -> None:
        with self.assertRaises(ValueError):
            verify_replay.verify(1)

    def test_verify_fails_against_a_wrong_oracle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wa015-oracle-") as tmp:
            wrong = Path(tmp) / "wrong.json"
            wrong.write_bytes(b'{"outcome":"PASS"}\n')
            report = verify_replay.verify(2, wrong)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertFalse(report["matches_oracle"])
        self.assertTrue(report["self_consistent"])

    def test_oracle_is_canonical_with_one_trailing_newline(self) -> None:
        raw = ORACLE_PATH.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw[:-1].endswith(b"\n"))
        self.assertEqual(
            mechanism.canonical_bytes(json.loads(raw.decode("utf-8"))) + b"\n", raw
        )


class TestCommandLine(unittest.TestCase):
    def test_harness_cli_reports_success(self) -> None:
        with silenced():
            self.assertEqual(harness.main([]), 0)

    def test_verify_cli_reports_success(self) -> None:
        with silenced():
            self.assertEqual(verify_replay.main(["--repeats", "2"]), 0)

    def test_verify_cli_fails_on_a_missing_oracle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wa015-cli-") as tmp:
            with silenced():
                code = verify_replay.main(
                    ["--repeats", "2", "--oracle", str(Path(tmp) / "absent.json")]
                )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
