"""Unit a3-u05: generated artifacts are byte-deterministic across runs.

Two runs of the real generators usually complete inside the same UTC second, so
the declared timestamp fields do not actually differ and the masking path is
never exercised.  The comparison logic is therefore also driven directly with
documents that differ only in a declared field, and only in an undeclared one,
so both directions are proved rather than assumed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
CHECKER_PATH = RUNTIME_DIR / "determinism.py"
CONTRACT_PATH = RUNTIME_DIR / "determinism-contract.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


determinism = load_module(CHECKER_PATH, "po03_determinism")
CONTRACT = determinism.load_contract(CONTRACT_PATH)


def spec_for(artifact_class: str) -> dict:
    for key in ("generators", "fixture_generators"):
        for spec in CONTRACT[key]:
            if spec["artifact_class"] == artifact_class:
                return spec
    raise KeyError(artifact_class)


class MaskingDistinguishesDeclaredFromUndeclared(unittest.TestCase):
    """Direct comparison tests, with variance forced rather than hoped for."""

    SPEC = {
        "artifact_class": "probe",
        "volatile_fields": [
            {"path": "stamped_at", "kind": "timestamp", "reason": "probe"},
            {"path": "rows[].stamped_at", "kind": "timestamp", "reason": "probe"},
        ],
    }

    def test_variance_confined_to_declared_fields_passes(self) -> None:
        first = {"value": 1, "stamped_at": "2026-08-22T07:00:00Z", "rows": [{"stamped_at": "a"}]}
        second = {"value": 1, "stamped_at": "2026-08-22T09:59:59Z", "rows": [{"stamped_at": "b"}]}
        outcome = determinism.compare(self.SPEC, first, second)
        self.assertEqual(outcome["verdict"], "PASS", outcome)
        self.assertEqual(outcome["undeclared_variance"], [])
        self.assertTrue(outcome["byte_identical_after_masking"])
        self.assertEqual(
            outcome["differing_field_paths"], ["rows[0].stamped_at", "stamped_at"]
        )

    def test_one_undeclared_field_fails(self) -> None:
        first = {"value": 1, "stamped_at": "2026-08-22T07:00:00Z"}
        second = {"value": 2, "stamped_at": "2026-08-22T07:00:00Z"}
        outcome = determinism.compare(self.SPEC, first, second)
        self.assertEqual(outcome["verdict"], "FAIL")
        self.assertEqual(outcome["undeclared_variance"], ["value"])
        self.assertFalse(outcome["byte_identical_after_masking"])

    def test_an_added_field_is_variance(self) -> None:
        outcome = determinism.compare(self.SPEC, {"a": 1}, {"a": 1, "b": 2})
        self.assertEqual(outcome["verdict"], "FAIL")
        self.assertEqual(outcome["undeclared_variance"], ["b"])

    def test_array_length_change_is_variance(self) -> None:
        first = {"rows": [{"stamped_at": "a"}]}
        second = {"rows": [{"stamped_at": "a"}, {"stamped_at": "b"}]}
        outcome = determinism.compare(self.SPEC, first, second)
        self.assertFalse(outcome["byte_identical_after_masking"])
        self.assertEqual(outcome["verdict"], "FAIL")

    def test_declaring_a_field_narrows_the_comparison_without_skipping_it(self) -> None:
        """A masked field still participates in the structural comparison."""
        first = {"stamped_at": "x"}
        second = {"stamped_at": {"nested": "x"}}
        outcome = determinism.compare(self.SPEC, first, second)
        self.assertEqual(outcome["verdict"], "FAIL")

    def test_index_collapsing(self) -> None:
        self.assertEqual(determinism.declared_path("rows[11].stamped_at"), "rows[].stamped_at")
        self.assertEqual(determinism.declared_path("a[0].b[3].c"), "a[].b[].c")
        self.assertEqual(determinism.declared_path("plain"), "plain")


class PlantedNonDeterminismIsCaught(unittest.TestCase):
    def setUp(self) -> None:
        self.outcomes = {
            outcome["artifact_class"]: outcome
            for outcome in determinism.check_specs(CONTRACT["fixture_generators"])
        }

    def test_each_fixture_produces_its_recorded_verdict(self) -> None:
        for spec in CONTRACT["fixture_generators"]:
            outcome = self.outcomes[spec["artifact_class"]]
            self.assertEqual(outcome["verdict"], spec["expected_verdict"], outcome)
            self.assertEqual(
                outcome["undeclared_variance"],
                sorted(spec["expected_undeclared_variance"]),
                outcome,
            )

    def test_the_planted_defect_is_caught_at_every_depth(self) -> None:
        undeclared = self.outcomes["planted-nondeterministic"]["undeclared_variance"]
        self.assertIn("run_id", undeclared)
        self.assertIn("nested.attempt_token", undeclared)
        self.assertIn("items[].salt", undeclared)

    def test_the_declared_timestamp_is_not_reported_as_a_defect(self) -> None:
        outcome = self.outcomes["planted-nondeterministic"]
        self.assertNotIn("generated_at", outcome["undeclared_variance"])


class RealArtifactClassesAreDeterministic(unittest.TestCase):
    def setUp(self) -> None:
        self.outcomes = determinism.check_specs(CONTRACT["generators"])
        self.report = determinism.build_report(self.outcomes)

    def test_every_real_class_is_byte_identical_after_masking(self) -> None:
        self.assertEqual(self.report["verdict"], "PASS", json.dumps(self.report, indent=2))
        for outcome in self.outcomes:
            self.assertEqual(outcome["undeclared_variance"], [], outcome)
            self.assertTrue(outcome["byte_identical_after_masking"], outcome)

    def test_the_classes_with_no_volatile_fields_are_fully_identical(self) -> None:
        for outcome in self.outcomes:
            if outcome["declared_volatile_fields"]:
                continue
            self.assertEqual(outcome["differing_field_paths"], [], outcome)


class ContractIsExplicit(unittest.TestCase):
    """Timestamp fields must be enumerated, not inferred from their names."""

    def test_every_volatile_field_declares_a_kind_and_a_reason(self) -> None:
        for key in ("generators", "fixture_generators"):
            for spec in CONTRACT[key]:
                for entry in spec.get("volatile_fields", []):
                    self.assertIn(entry["kind"], {"timestamp", "entropy", "host"}, entry)
                    self.assertTrue(entry.get("reason", "").strip(), entry)

    def test_result_document_timestamps_are_all_declared(self) -> None:
        self.assertEqual(
            sorted(
                entry["path"]
                for entry in spec_for("transactional-result")["volatile_fields"]
                if entry["kind"] == "timestamp"
            ),
            [
                "artifacts[].readback_verified_at",
                "attempt.heartbeat_at",
                "result_transaction.committed_at",
                "result_transaction.verified_at",
            ],
        )

    def test_no_generation_timestamp_in_a_real_result_document_is_undeclared(self) -> None:
        """Catches a new timestamp field appearing in make_result unannounced.

        Every field make_result stamps carries the same generation instant, so
        collecting the paths that share that value finds them all without
        guessing from field names.
        """
        import tempfile

        spec = spec_for("transactional-result")
        with tempfile.TemporaryDirectory(prefix="po03-a3-u05-") as scratch:
            document = determinism.run_generator(spec, Path(scratch))
        flat = determinism.flatten(document)
        instant = flat["attempt.heartbeat_at"]
        stamped = {
            determinism.declared_path(path) for path, value in flat.items() if value == instant
        }
        declared = {entry["path"] for entry in spec["volatile_fields"]}
        self.assertEqual(stamped - declared, set(), f"undeclared generation timestamps: {stamped - declared}")


class CommandLineBehaviour(unittest.TestCase):
    def run_checker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(CHECKER_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_real_classes_exit_zero(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("byte-identical across 2 runs", result.stdout)

    def test_planted_fixtures_exit_nonzero(self) -> None:
        result = self.run_checker("--fixtures")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("UNDECLARED_VARIANCE: run_id", result.stdout)

    def test_json_report_enumerates_the_timestamp_fields(self) -> None:
        result = self.run_checker("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-determinism-report-v1")
        self.assertEqual(report["runs_per_class"], 2)
        self.assertIn("attempt.heartbeat_at", report["enumerated_timestamp_fields"])
        self.assertIn("nonce", report["enumerated_entropy_fields"])

    def test_unknown_contract_schema_fails_closed(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "contract.json"
            bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
            result = self.run_checker("--contract", str(bad))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("DETERMINISM_ERROR", result.stderr)

    def test_unexpected_generator_exit_code_is_an_error(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            spec = dict(spec_for("path-scope-report"))
        spec["expected_exit_code"] = 0
        import tempfile

        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(RuntimeError):
                determinism.run_generator(spec, Path(scratch))


if __name__ == "__main__":
    unittest.main()
