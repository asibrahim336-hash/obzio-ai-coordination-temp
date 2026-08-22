from __future__ import annotations

import importlib.util
import json
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/po03/strategy/semantic_check.py"
SNAPSHOT_MODULE_PATH = ROOT / "workstreams/po03/strategy/snapshot_fixture.py"
RESULT_PATH = ROOT / "workstreams/po03/strategy/semantic-check-results.json"
SNAPSHOT_COMMIT = "7f1a208f207525b459fac1f0661ff2f1191fdde9"

SPEC = importlib.util.spec_from_file_location("po03_a9_semantic_check", MODULE_PATH)
assert SPEC and SPEC.loader
semantic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(semantic)

SNAPSHOT_SPEC = importlib.util.spec_from_file_location(
    "po03_a9_semantic_snapshot", SNAPSHOT_MODULE_PATH
)
assert SNAPSHOT_SPEC and SNAPSHOT_SPEC.loader
snapshot = importlib.util.module_from_spec(SNAPSHOT_SPEC)
SNAPSHOT_SPEC.loader.exec_module(snapshot)


class SemanticCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    def test_results_reproduce_from_pinned_pointer_chain(self) -> None:
        with snapshot.materialize_commit(ROOT, SNAPSHOT_COMMIT) as snapshot_root:
            recorded = json.loads(
                (snapshot_root / RESULT_PATH.relative_to(ROOT)).read_text(
                    encoding="utf-8"
                )
            )
            rebuilt = semantic.build_report(snapshot_root)
        self.assertEqual(self.report, recorded)
        self.assertEqual(self.report, rebuilt)
        self.assertEqual(self.report["decision_changed"], [])
        self.assertFalse(self.report["strategy_restarted"])

    def test_existing_taxonomy_gate_still_passes_and_is_not_replaced(self) -> None:
        gate = self.report["existing_taxonomy_gate"]
        self.assertEqual(gate["exit_code"], 0)
        self.assertIn("OPERATOR TAXONOMY CHECK: PASS", gate["stdout"])
        self.assertIn("complements and does not replace", self.report["scope"])
        self.assertTrue(self.report["summary"]["existing_taxonomy_gate_passed"])

    def test_current_selected_actor_chain_is_transitively_consistent(self) -> None:
        chain = self.report["current_chain"]
        self.assertEqual(chain["transitive_error_count"], 0)
        self.assertEqual(chain["transitive_errors"], [])
        self.assertEqual(chain["control_pointer_projection_mismatches"], [])
        self.assertEqual(
            chain["function_id"],
            "obzio.function.strategic-operations-orchestration",
        )

    def test_checker_reports_operator_and_state_contract_ambiguities(self) -> None:
        finding_ids = {row["finding_id"] for row in self.report["findings"]}
        required = {
            "PO03-ACTIVE-COMMISSION-ROUTE-INCOMPLETE",
            "PO03-LIFECYCLE-CONTRADICTS-LEDGER",
            "ACTIVE-STACK-RETURN-EVALUATION-ROUTE-IMPLICIT",
            "ALIAS-TARGET-NAMESPACE-NOT-MACHINE-RESOLVABLE",
            "RESULT-VALIDATOR-ACCEPTS-UNDECLARED-FIELD",
            "RESULT-VALIDATOR-ACCEPTS-UNKNOWN-PROVIDER-STATE",
            "RESULT-VALIDATOR-ACCEPTS-UNKNOWN-TRANSACTION-STATE",
        }
        self.assertTrue(required.issubset(finding_ids))
        self.assertGreater(self.report["summary"]["operator_taxonomy_findings"], 0)
        self.assertGreater(self.report["summary"]["state_contract_findings"], 0)

    def test_contract_probes_execute_the_existing_validator(self) -> None:
        contract = self.report["state_contract"]
        self.assertTrue(contract["schema_validator_state_enums_equal"])
        probes = {row["probe_id"]: row for row in contract["validator_probes"]}
        self.assertEqual(
            set(probes),
            {"top-level-extension", "provider-state", "transaction-state"},
        )
        for probe in probes.values():
            self.assertTrue(probe["accepted"])
            self.assertEqual(probe["validator_exit_code"], 0)
            self.assertIn("VALID result", probe["validator_output"])

    def test_duplicate_json_keys_are_rejected_before_semantic_resolution(self) -> None:
        with self.assertRaises(semantic.DuplicateKeyError):
            semantic.parse_json_text('{"function_id":"a","function_id":"b"}', "fixture")

    def test_every_resolution_stays_nonbinding(self) -> None:
        for row in self.report["findings"]:
            self.assertEqual(row["decision_changed"], [])
            self.assertEqual(row["resolution"]["binding_state"], "PROPOSAL_ONLY")
            self.assertFalse(row["resolution"]["applied"])
            self.assertEqual(row["resolution"]["decision_changed"], [])
        self.assertEqual(semantic.strict_exit_code(self.report), 4)

    def test_check_requires_no_outside_allowlist_write(self) -> None:
        writes: list[Path] = []
        original_write_text = Path.write_text

        def recording_write_text(path: Path, *args: object, **kwargs: object) -> int:
            writes.append(path.resolve())
            return original_write_text(path, *args, **kwargs)

        with mock.patch.object(Path, "write_text", recording_write_text):
            fresh_report = semantic.build_report(ROOT)

        scope = fresh_report["write_scope"]
        self.assertFalse(scope["outside_allowlist_write_required"])
        self.assertTrue(scope["implementation"].startswith("workstreams/po03/strategy/"))
        self.assertTrue(scope["output"].startswith("workstreams/po03/strategy/"))
        expected_writes = {
            (
                ROOT
                / f"workstreams/po03/strategy/.semantic-probe-{probe_id}.json"
            ).resolve()
            for probe_id in (
                "top-level-extension",
                "provider-state",
                "transaction-state",
            )
        }
        self.assertEqual(set(writes), expected_writes)
        strategy_root = (ROOT / "workstreams/po03/strategy").resolve()
        self.assertTrue(all(path.is_relative_to(strategy_root) for path in writes))
        self.assertTrue(all(not path.exists() for path in writes))


if __name__ == "__main__":
    unittest.main()
