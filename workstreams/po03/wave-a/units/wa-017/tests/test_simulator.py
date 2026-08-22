from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

import simulator
from architectures.central_gate import CentralGateFactory
from architectures.event_log import EventLogFactory
from architectures.lease_shards import LeaseShardFactory


WORKLOAD = UNIT_ROOT / "fixtures" / "frozen-simulation.json"
COMPARISON = UNIT_ROOT / "result" / "preregistered-comparison.json"


class FrozenInputsTests(unittest.TestCase):
    def setUp(self):
        self.workload = json.loads(WORKLOAD.read_text(encoding="utf-8"))
        self.comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))

    def test_workload_hash_and_bytes_are_preregistered(self):
        data = WORKLOAD.read_bytes()
        self.assertEqual(self.comparison["workload"]["bytes"], len(data))
        self.assertEqual(
            self.comparison["workload"]["sha256"],
            hashlib.sha256(data).hexdigest(),
        )

    def test_exact_hypothesis_is_preregistered(self):
        self.assertEqual("H-PO03-WA-017", self.comparison["hypothesis_id"])
        self.assertEqual(24, self.comparison["decision_rule"]["workload_completion_gate"]["accepted_task_count"])

    def test_three_contracts_have_four_independent_dimensions(self):
        contracts = self.comparison["candidate_contracts"]
        self.assertEqual(3, len(contracts))
        for field in (
            "scheduler",
            "concurrency_control",
            "completion_authority",
            "recovery_source",
            "mechanism_signature",
        ):
            self.assertEqual(3, len({contract[field] for contract in contracts}))

    def test_fixture_contains_only_sanitized_relative_work(self):
        self.assertFalse(self.workload["sanitization"]["contains_credentials"])
        self.assertFalse(self.workload["sanitization"]["contains_owner_identity_data"])
        self.assertFalse(self.workload["sanitization"]["contains_third_party_content"])
        self.assertFalse(self.workload["sanitization"]["external_effects"])
        for task in self.workload["tasks"]:
            self.assertFalse(task["write_key"].startswith("/"))
            self.assertNotIn("..", Path(task["write_key"]).parts)

    def test_tampered_workload_fails_closed(self):
        document = dict(self.workload)
        document["simulation_id"] = "TAMPERED"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workload.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen workload differs"):
                simulator.run(path, COMPARISON)

    def test_renamed_mechanism_fails_closed(self):
        document = json.loads(COMPARISON.read_text(encoding="utf-8"))
        document["candidate_contracts"][0]["mechanism_signature"] = "renamed-clone"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mechanism signature differs"):
                simulator.run(WORKLOAD, path)


class IndependenceTests(unittest.TestCase):
    def test_run_methods_are_defined_in_three_modules(self):
        methods = [
            CentralGateFactory.run,
            LeaseShardFactory.run,
            EventLogFactory.run,
        ]
        modules = {method.__module__ for method in methods}
        source_files = {Path(inspect.getsourcefile(method)).name for method in methods}
        bytecode = {method.__code__.co_code for method in methods}
        self.assertEqual(3, len(modules))
        self.assertEqual(
            {"central_gate.py", "event_log.py", "lease_shards.py"},
            source_files,
        )
        self.assertEqual(3, len(bytecode))

    def test_candidates_do_not_inherit_one_scheduler(self):
        for candidate in (
            CentralGateFactory,
            LeaseShardFactory,
            EventLogFactory,
        ):
            self.assertEqual((candidate, object), candidate.__mro__)

    def test_candidate_state_vocabularies_are_not_renamed_clones(self):
        sources = {
            "central": inspect.getsource(CentralGateFactory.run),
            "shards": inspect.getsource(LeaseShardFactory.run),
            "events": inspect.getsource(EventLogFactory.run),
        }
        self.assertIn("GLOBAL_DISPATCH", sources["central"])
        self.assertNotIn("GLOBAL_DISPATCH", sources["shards"])
        self.assertIn("SHARD_DISPATCH", sources["shards"])
        self.assertNotIn("SHARD_DISPATCH", sources["events"])
        self.assertIn("MATERIALIZED_ACCEPTED", sources["events"])
        self.assertNotIn("MATERIALIZED_ACCEPTED", sources["central"])


class ExecutedComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = simulator.run(WORKLOAD, COMPARISON)
        cls.second = simulator.run(WORKLOAD, COMPARISON)
        cls.by_id = {
            result["candidate_id"]: result
            for result in cls.first["candidates"]
        }

    def test_repeated_run_is_byte_deterministic(self):
        self.assertEqual(
            simulator.json_bytes(self.first),
            simulator.json_bytes(self.second),
        )

    def test_hypothesis_is_supported_by_preregistered_rules(self):
        self.assertEqual("SUPPORTED", self.first["hypothesis_outcome"])
        self.assertEqual("SUPPORTED", self.first["assessment"]["hypothesis_outcome"])
        self.assertTrue(all(self.first["assessment"]["gates"].values()))

    def test_exactly_three_candidates_execute(self):
        self.assertEqual(
            {"central-gate", "event-log", "lease-shards"},
            set(self.by_id),
        )

    def test_every_candidate_accepts_all_tasks(self):
        for candidate in self.by_id.values():
            self.assertTrue(candidate["completed_workload"])
            self.assertEqual(24, candidate["metrics"]["accepted_task_count"])
            self.assertEqual(24, len(candidate["accepted_tasks"]))

    def test_critical_safety_gate_is_zero(self):
        for candidate in self.by_id.values():
            for field in (
                "false_completions",
                "duplicate_external_effects",
                "lost_committed_results",
            ):
                self.assertEqual(0, candidate["metrics"][field])

    def test_central_gate_prevents_write_collision_and_exposure(self):
        metrics = self.by_id["central-gate"]["metrics"]
        self.assertEqual(0, metrics["collision_events"])
        self.assertEqual(0, metrics["unverified_exposure_ticks"])

    def test_lease_shards_expose_cross_shard_collision_not_unverified_results(self):
        metrics = self.by_id["lease-shards"]["metrics"]
        self.assertGreater(metrics["collision_events"], 0)
        self.assertEqual(0, metrics["unverified_exposure_ticks"])
        self.assertGreater(metrics["recovery_events"], 0)

    def test_event_log_exposes_unverified_results_before_reduction(self):
        metrics = self.by_id["event-log"]["metrics"]
        self.assertGreater(metrics["collision_events"], 0)
        self.assertGreater(metrics["unverified_exposure_ticks"], 0)
        self.assertGreater(metrics["verification_backlog_peak"], 0)

    def test_throughput_spread_meets_preregistered_threshold(self):
        self.assertGreaterEqual(
            self.first["assessment"]["throughput_spread_ratio"], 1.25
        )

    def test_every_pair_is_materially_different(self):
        rows = self.first["assessment"]["pairwise"]
        self.assertEqual(3, len(rows))
        self.assertTrue(all(row["passes"] for row in rows))

    def test_all_architectures_recover_each_fault_class(self):
        for candidate in self.by_id.values():
            trace_text = json.dumps(candidate["trace"], sort_keys=True)
            self.assertIn("PROVIDER", trace_text.upper())
            self.assertIn("STALE", trace_text.upper())
            self.assertIn("ARTIFACT", trace_text.upper())
            self.assertIn("DUPLICATE", trace_text.upper())
            self.assertGreaterEqual(candidate["metrics"]["rework_attempts"], 3)

    def test_event_projection_is_replay_based(self):
        evidence = self.by_id["event-log"]["mechanism_evidence"]
        self.assertIn("replayed", evidence["durable_projection"])
        self.assertGreater(evidence["event_count"], 24)

    def test_shard_projection_is_partitioned(self):
        evidence = self.by_id["lease-shards"]["mechanism_evidence"]
        self.assertEqual(
            "union of three shard projections", evidence["durable_projection"]
        )

    def test_central_verification_backlog_is_observed(self):
        self.assertGreater(
            self.by_id["central-gate"]["metrics"]["verification_backlog_peak"],
            1,
        )


class CliBoundaryTests(unittest.TestCase):
    def test_cli_refuses_output_outside_result_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            returncode = simulator.main(["--output", str(path)])
            self.assertEqual(2, returncode)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
