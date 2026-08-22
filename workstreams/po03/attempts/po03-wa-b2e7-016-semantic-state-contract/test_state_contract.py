#!/usr/bin/env python3
"""Tests for state_contract.py.

Run with: python3 -I test_state_contract.py
(standard-library `unittest` only; no third-party packages, no network.)
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state_contract as sc

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestDeriveKindSchema(unittest.TestCase):
    def test_empty_records_yields_empty_schema(self):
        schema = sc.derive_kind_schema([])
        self.assertEqual(schema["required_fields"], [])
        self.assertEqual(schema["allowed_status_values"], [])

    def test_required_fields_is_intersection_not_union(self):
        records = [
            {"a": 1, "b": 2, "status": "X"},
            {"a": 1, "b": 2, "c": 3, "status": "X"},
        ]
        schema = sc.derive_kind_schema(records)
        self.assertEqual(schema["required_fields"], ["a", "b", "status"])

    def test_allowed_status_values_is_observed_union(self):
        records = [{"status": "X"}, {"status": "Y"}, {"status": "X"}]
        schema = sc.derive_kind_schema(records)
        self.assertEqual(schema["allowed_status_values"], ["X", "Y"])

    def test_non_string_status_is_ignored(self):
        records = [{"status": "X"}, {"status": 42}]
        schema = sc.derive_kind_schema(records)
        self.assertEqual(schema["allowed_status_values"], ["X"])


class TestLoadRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "state" / "operator-system").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_kind_fails_closed(self):
        with self.assertRaises(sc.StateContractError):
            sc.load_records(self.root, "not_a_real_kind")

    def test_missing_source_file_fails_closed(self):
        with self.assertRaises(sc.StateContractError):
            sc.load_records(self.root, "function")

    def test_json_kind_loads_single_record(self):
        target = self.root / "state" / "operator-system" / "ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json"
        target.write_text(json.dumps({"status": "CURRENT"}), encoding="utf-8")
        records = sc.load_records(self.root, "operator_system_pointer")
        self.assertEqual(records, [{"status": "CURRENT"}])

    def test_jsonl_kind_loads_each_line(self):
        target = self.root / "state" / "operator-system" / "FUNCTION_REGISTER.jsonl"
        target.write_text(
            json.dumps({"status": "ACTIVE", "function_id": "a"}) + "\n" +
            json.dumps({"status": "ACTIVE", "function_id": "b"}) + "\n",
            encoding="utf-8",
        )
        records = sc.load_records(self.root, "function")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["function_id"], "a")
        self.assertEqual(records[1]["function_id"], "b")

    def test_blank_lines_in_jsonl_are_skipped(self):
        target = self.root / "state" / "operator-system" / "FUNCTION_REGISTER.jsonl"
        target.write_text(
            json.dumps({"status": "ACTIVE"}) + "\n\n\n" + json.dumps({"status": "ACTIVE"}) + "\n",
            encoding="utf-8",
        )
        records = sc.load_records(self.root, "function")
        self.assertEqual(len(records), 2)


class TestValidateRecord(unittest.TestCase):
    def setUp(self):
        self.contract = {
            "widget": {
                "required_fields": ["widget_id", "status"],
                "status_field": "status",
                "allowed_status_values": ["ACTIVE", "RETIRED"],
            }
        }

    def test_valid_record_has_no_errors(self):
        record = {"widget_id": "w1", "status": "ACTIVE"}
        self.assertEqual(sc.validate_record("widget", record, self.contract), [])

    def test_unknown_kind_raises(self):
        with self.assertRaises(sc.StateContractError):
            sc.validate_record("gizmo", {}, self.contract)

    def test_non_dict_record_raises(self):
        with self.assertRaises(sc.StateContractError):
            sc.validate_record("widget", ["not", "a", "dict"], self.contract)  # type: ignore[arg-type]

    def test_missing_required_field_is_rejected(self):
        record = {"status": "ACTIVE"}
        errors = sc.validate_record("widget", record, self.contract)
        self.assertEqual(errors, ["widget: missing required field 'widget_id'"])

    def test_undefined_status_value_is_rejected(self):
        record = {"widget_id": "w1", "status": "TOTALLY_UNDEFINED_STATE_XYZ"}
        errors = sc.validate_record("widget", record, self.contract)
        self.assertEqual(len(errors), 1)
        self.assertIn("undefined state", errors[0])
        self.assertIn("TOTALLY_UNDEFINED_STATE_XYZ", errors[0])

    def test_extra_unrecognised_fields_are_not_rejected(self):
        # Additive-only doctrine: an unrecognised extra field is not itself
        # a contract violation; only missing required fields and undefined
        # status values are.
        record = {"widget_id": "w1", "status": "ACTIVE", "brand_new_field": "ok"}
        self.assertEqual(sc.validate_record("widget", record, self.contract), [])

    def test_multiple_violations_are_all_reported(self):
        record = {"status": "GHOST_STATE"}
        errors = sc.validate_record("widget", record, self.contract)
        self.assertEqual(len(errors), 2)


class TestValidateRepoSynthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        opsys = self.root / "state" / "operator-system"
        opsys.mkdir(parents=True)

        def write(name, obj_or_lines, jsonl=False):
            path = opsys / name
            if jsonl:
                path.write_text("\n".join(json.dumps(o) for o in obj_or_lines) + "\n", encoding="utf-8")
            else:
                path.write_text(json.dumps(obj_or_lines), encoding="utf-8")

        pointer = {f: "x" for f in sc.CONTRACT["operator_system_pointer"]["required_fields"]}
        pointer["status"] = "CURRENT"
        write("ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", pointer)

        stack = {f: "x" for f in sc.CONTRACT["instruction_stack"]["required_fields"]}
        stack["status"] = "CURRENT"
        write("ACTIVE_INSTRUCTION_STACK.json", stack)

        envelope = {f: "x" for f in sc.CONTRACT["authority_envelope"]["required_fields"]}
        envelope["status"] = "ACTIVE"
        write("AUTHORITY_ENVELOPE_REGISTER.jsonl", [envelope], jsonl=True)

        commission = {f: "x" for f in sc.CONTRACT["commission"]["required_fields"]}
        commission["status"] = "ACTIVE_AND_CONTINUING"
        write("COMMISSION_REGISTER.jsonl", [commission], jsonl=True)

        func_valid = {f: "x" for f in sc.CONTRACT["function"]["required_fields"]}
        func_valid["status"] = "ACTIVE"
        func_bad = dict(func_valid)
        func_bad["status"] = "NEVER_SEEN_BEFORE_STATE"
        write("FUNCTION_REGISTER.jsonl", [func_valid, func_bad], jsonl=True)

        appt = {f: "x" for f in sc.CONTRACT["appointment"]["required_fields"]}
        appt["status"] = "SUPERSEDED_FOR_ACTIVE_ROUTING"
        write("OPERATOR_APPOINTMENT_REGISTER.jsonl", [appt], jsonl=True)

        runtime = {f: "x" for f in sc.CONTRACT["runtime_binding"]["required_fields"]}
        runtime["status"] = "ACTIVE_OBSERVED_AND_REPLACEABLE"
        write("RUNTIME_BINDING_REGISTER.jsonl", [runtime], jsonl=True)

        alias = {f: "x" for f in sc.CONTRACT["alias"]["required_fields"]}
        alias["status"] = "HISTORICAL_ACCEPTED_ALIAS"
        write("OPERATOR_ALIAS_REGISTER.jsonl", [alias], jsonl=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_bad_record_is_precisely_isolated(self):
        report = sc.validate_repo(self.root)
        self.assertFalse(report["all_valid"])
        self.assertEqual(report["status"], "CONTRACT_VIOLATIONS_PRESENT")
        self.assertEqual(report["total_records"], 9)  # 8 kinds, function has 2
        self.assertEqual(report["total_errors"], 1)
        func_report = report["kinds"]["function"]
        self.assertEqual(func_report["record_count"], 2)
        self.assertEqual(len(func_report["errors"]), 1)
        self.assertIn("NEVER_SEEN_BEFORE_STATE", func_report["errors"][0])
        # every other kind must remain unaffected by the one bad function record
        for kind, kind_report in report["kinds"].items():
            if kind == "function":
                continue
            self.assertTrue(kind_report["valid"], f"{kind} unexpectedly invalid: {kind_report['errors']}")

    def test_fixing_the_bad_status_makes_the_repo_all_valid(self):
        # Prove the negative case is real by flipping it positive.
        target = self.root / "state" / "operator-system" / "FUNCTION_REGISTER.jsonl"
        lines = [json.loads(l) for l in target.read_text(encoding="utf-8").splitlines() if l.strip()]
        lines[1]["status"] = "ACTIVE"
        target.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")
        report = sc.validate_repo(self.root)
        self.assertTrue(report["all_valid"])
        self.assertEqual(report["status"], "ALL_VALID")


class TestMainCLI(unittest.TestCase):
    def test_missing_repo_files_fails_closed_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = sc.main(["--repo-root", tmp])
            self.assertEqual(exit_code, 1)


class TestRealRepository(unittest.TestCase):
    """Grounding tests against the actual committed repository content."""

    def test_all_eight_source_files_are_readable(self):
        for kind in sc.SOURCE_FILES:
            records = sc.load_records(REPO_ROOT, kind)
            self.assertIsInstance(records, list)
            self.assertGreaterEqual(len(records), 1)

    def test_real_repo_validates_cleanly_against_pinned_contract(self):
        report = sc.validate_repo(REPO_ROOT)
        self.assertEqual(report["total_errors"], 0, report)
        self.assertTrue(report["all_valid"])
        self.assertEqual(report["status"], "ALL_VALID")
        self.assertEqual(report["total_records"], 20)


class TestContractMatchesRepoSnapshot(unittest.TestCase):
    """Proves the pinned CONTRACT above is not invented: independently
    re-deriving required_fields and allowed_status_values straight from the
    live committed files reproduces the pinned values exactly, for every
    one of the eight kinds."""

    def test_derived_contract_matches_pinned_contract_for_every_kind(self):
        derived = sc.derive_full_contract(REPO_ROOT)
        self.assertEqual(set(derived.keys()), set(sc.CONTRACT.keys()))
        for kind in sc.CONTRACT:
            with self.subTest(kind=kind):
                self.assertEqual(
                    derived[kind]["required_fields"],
                    sc.CONTRACT[kind]["required_fields"],
                    f"required_fields mismatch for kind={kind}",
                )
                self.assertEqual(
                    derived[kind]["allowed_status_values"],
                    sc.CONTRACT[kind]["allowed_status_values"],
                    f"allowed_status_values mismatch for kind={kind}",
                )


class TestUndefinedStateRejectedOnRealData(unittest.TestCase):
    """The core falsifiable claim: take a genuine, currently-valid real
    record and show that mutating only its status field to a value outside
    the pinned vocabulary is rejected, while the untouched original
    continues to validate. This is checked for every one of the eight
    kinds, using the actual committed record shapes (not synthetic
    stand-ins), and the real files are never written to."""

    def test_undefined_status_rejected_for_every_real_kind(self):
        for kind in sc.SOURCE_FILES:
            with self.subTest(kind=kind):
                records = sc.load_records(REPO_ROOT, kind)
                original = records[0]
                self.assertEqual(sc.validate_record(kind, original), [])

                mutated = copy.deepcopy(original)
                mutated["status"] = "UNDEFINED_STATE_NEVER_COMMITTED_ANYWHERE"
                errors = sc.validate_record(kind, mutated)
                self.assertEqual(len(errors), 1)
                self.assertIn("undefined state", errors[0])
                self.assertIn("UNDEFINED_STATE_NEVER_COMMITTED_ANYWHERE", errors[0])

    def test_real_files_are_never_mutated_by_validation(self):
        before = {
            kind: (REPO_ROOT / SOURCE_FILES_PATH).read_bytes()
            for kind, (SOURCE_FILES_PATH, _fmt) in sc.SOURCE_FILES.items()
        }
        for kind in sc.SOURCE_FILES:
            sc.validate_record(kind, sc.load_records(REPO_ROOT, kind)[0])
        after = {
            kind: (REPO_ROOT / SOURCE_FILES_PATH).read_bytes()
            for kind, (SOURCE_FILES_PATH, _fmt) in sc.SOURCE_FILES.items()
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
