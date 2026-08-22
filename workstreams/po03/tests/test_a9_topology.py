from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/po03/strategy/topology_sim.py"
CANDIDATE_PATH = ROOT / "workstreams/po03/strategy/topology-candidates.json"
COMPARISON_PATH = ROOT / "workstreams/po03/strategy/topology-comparison.json"

SPEC = importlib.util.spec_from_file_location("po03_a9_topology", MODULE_PATH)
assert SPEC and SPEC.loader
topology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(topology)


class TopologySimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidates = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        cls.comparison = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))

    def test_artifacts_reproduce_byte_semantics(self) -> None:
        candidates, comparison = topology.build_artifacts(ROOT)
        self.assertEqual(self.candidates, candidates)
        self.assertEqual(self.comparison, comparison)

    def test_at_least_three_materially_different_topologies_are_concrete(self) -> None:
        rows = self.candidates["topologies"]
        self.assertGreaterEqual(len(rows), 3)
        shapes = {
            (
                row["verification_writers"],
                row["final_promotion_authorities"],
                tuple(row["mutable_coordination_surfaces"]),
                str(row["batch_size"]),
            )
            for row in rows
        }
        self.assertEqual(len(shapes), len(rows))
        for row in rows:
            self.assertTrue(row["scheduling"])
            self.assertTrue(row["collision_rule"])
            self.assertTrue(row["recovery_rule"])
            self.assertEqual(row["binding_state"], "PROPOSAL_ONLY")
            self.assertFalse(row["applied_to_active_wave"])
            self.assertEqual(row["decision_changed"], [])

    def test_simulation_uses_all_wave_a_units_and_injects_recovery(self) -> None:
        workload = self.comparison["workload"]
        self.assertEqual(workload["declared_units"], 74)
        self.assertEqual(workload["simulated_units"], 74)
        self.assertEqual(sum(workload["cohort_counts"].values()), 74)
        self.assertGreater(self.comparison["failure_fixture"]["downtime_ticks"], 0)
        for row in self.comparison["results"]:
            self.assertEqual(row["completed_units"], 74)
            self.assertEqual(row["result_loss_count"], 0)
            self.assertGreater(row["recovery_to_success_ticks"], 0)
            self.assertGreater(row["throughput_units_per_tick"], 0)

    def test_collision_and_throughput_results_separate_the_candidates(self) -> None:
        by_id = {
            row["topology_id"]: row for row in self.comparison["results"]
        }
        self.assertEqual(by_id["T1-CENTRAL-SERIAL"]["collision_attempts"], 0)
        self.assertEqual(by_id["T2-COHORT-SHARDS"]["collision_attempts"], 0)
        self.assertGreater(by_id["T3-OPTIMISTIC-PEERS"]["collision_attempts"], 0)
        self.assertEqual(by_id["T4-CONTENT-FANIN"]["collision_attempts"], 0)
        self.assertGreater(
            by_id["T4-CONTENT-FANIN"]["throughput_units_per_tick"],
            by_id["T2-COHORT-SHARDS"]["throughput_units_per_tick"],
        )
        self.assertGreater(
            by_id["T2-COHORT-SHARDS"]["throughput_units_per_tick"],
            by_id["T1-CENTRAL-SERIAL"]["throughput_units_per_tick"],
        )

    def test_single_final_authority_is_not_the_simulated_throughput_unit(self) -> None:
        candidates = {
            row["topology_id"]: row for row in self.candidates["topologies"]
        }
        results = {
            row["topology_id"]: row for row in self.comparison["results"]
        }
        self.assertEqual(candidates["T1-CENTRAL-SERIAL"]["final_promotion_authorities"], 1)
        self.assertEqual(candidates["T4-CONTENT-FANIN"]["final_promotion_authorities"], 1)
        self.assertGreater(
            results["T4-CONTENT-FANIN"]["throughput_units_per_tick"],
            results["T1-CENTRAL-SERIAL"]["throughput_units_per_tick"],
        )
        self.assertIn(
            "safety property",
            self.comparison["comparison"]["finding"],
        )

    def test_no_simulated_result_binds_a_decision(self) -> None:
        self.assertEqual(self.candidates["decision_changed"], [])
        self.assertEqual(self.comparison["decision_changed"], [])
        self.assertEqual(
            self.comparison["proposal"]["binding_state"],
            "PROPOSAL_ONLY",
        )
        self.assertEqual(self.comparison["proposal"]["decision_changed"], [])


if __name__ == "__main__":
    unittest.main()
