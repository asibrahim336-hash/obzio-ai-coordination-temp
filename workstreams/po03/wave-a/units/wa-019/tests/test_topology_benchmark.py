from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(UNIT_ROOT))

from benchmark.model import load_workload  # noqa: E402
from benchmark.runner import (  # noqa: E402
    FALSIFIABLE_HYPOTHESIS,
    HYPOTHESIS_ID,
    main,
    run_matched_benchmark,
    run_topology,
)


FIXTURE = UNIT_ROOT / "fixtures" / "sanitized-wave-workload.json"
TOPOLOGIES = ("centralized", "sharded", "event-sourced")


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_workload(FIXTURE)

    def test_fixture_is_repository_native_and_sanitized(self):
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            "4e4641e96cc0ad6e48f58e06140d33b0410e6072",
            raw["provenance"]["repository_source_commit"],
        )
        self.assertFalse(raw["sanitization"]["contains_secrets"])
        self.assertFalse(raw["sanitization"]["contains_external_identifiers"])
        self.assertFalse(raw["sanitization"]["third_party_content"])

    def test_fixture_digest_is_over_exact_bytes(self):
        observed = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(observed, self.workload.fixture_sha256)
        self.assertEqual(64, len(observed))

    def test_fixture_contains_32_unique_tasks(self):
        ids = [task.task_id for task in self.workload.tasks]
        self.assertEqual(32, len(ids))
        self.assertEqual(32, len(set(ids)))

    def test_fixture_exercises_all_four_shards(self):
        self.assertEqual({0, 1, 2, 3}, {task.shard for task in self.workload.tasks})

    def test_fault_is_frozen_and_hits_an_existing_shard(self):
        self.assertEqual("COORDINATOR_PROCESS_LOSS", self.workload.fault.kind)
        self.assertEqual(8, self.workload.fault.tick)
        self.assertEqual(0, self.workload.fault.target_shard)

    def test_matched_capacity_is_explicit(self):
        self.assertEqual(4, self.workload.config.worker_slots)
        self.assertEqual(4, self.workload.config.coordination_ops_per_tick)


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workload = load_workload(FIXTURE)
        cls.report = run_matched_benchmark(cls.workload)

    def result(self, topology, scenario="coordinator_loss"):
        return self.report["candidates"][topology][scenario]

    def test_exact_hypothesis_is_not_rephrased(self):
        assessment = self.report["hypothesis_assessment"]
        self.assertEqual("H-PO03-WA-019", HYPOTHESIS_ID)
        self.assertEqual(
            "Centralized, sharded, and event-sourced coordination topologies "
            "produce distinguishable accepted-throughput and recovery outcomes.",
            FALSIFIABLE_HYPOTHESIS,
        )
        self.assertEqual(FALSIFIABLE_HYPOTHESIS, assessment["falsifiable_hypothesis"])

    def test_all_three_candidates_are_executed(self):
        self.assertEqual(set(TOPOLOGIES), set(self.report["candidates"]))

    def test_every_candidate_receives_identical_fixture_bytes(self):
        digests = {
            self.result(topology)["workload_sha256"] for topology in TOPOLOGIES
        }
        self.assertEqual({self.workload.fixture_sha256}, digests)

    def test_report_uses_a_clean_clone_portable_fixture_path(self):
        self.assertEqual(
            "fixtures/sanitized-wave-workload.json",
            self.report["fixture"]["path"],
        )
        self.assertNotIn("/tmp/", json.dumps(self.report))

    def test_every_candidate_receives_the_same_capacity(self):
        controls = {
            tuple(sorted(self.result(topology)["coordination"].items()))
            for topology in TOPOLOGIES
        }
        self.assertEqual(1, len(controls))

    def test_baselines_accept_every_task(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                baseline = self.result(topology, "baseline")
                self.assertTrue(baseline["all_tasks_accepted"])
                self.assertEqual(32, baseline["accepted_count"])
                self.assertEqual(0, baseline["duplicate_acceptances"])

    def test_faulted_candidates_accept_every_task_exactly_once(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                result = self.result(topology)
                self.assertTrue(result["all_tasks_accepted"])
                self.assertEqual(32, result["accepted_count"])
                self.assertEqual(32, len(set(result["accepted_order"])))
                self.assertEqual(0, result["duplicate_acceptances"])

    def test_centralized_candidate_loses_global_volatile_work(self):
        recovery = self.result("centralized")["recovery"]
        self.assertEqual(4, recovery["impacted_tasks"])
        self.assertEqual(12, recovery["lost_work_ticks"])
        self.assertEqual(0, recovery["accepted_during_outage"])

    def test_sharded_candidate_isolates_fault_and_keeps_accepting(self):
        recovery = self.result("sharded")["recovery"]
        self.assertEqual(2, recovery["impacted_tasks"])
        self.assertEqual(7, recovery["lost_work_ticks"])
        self.assertEqual(3, recovery["accepted_during_outage"])

    def test_event_sourced_candidate_replays_without_lost_work(self):
        recovery = self.result("event-sourced")["recovery"]
        self.assertEqual(0, recovery["lost_work_ticks"])
        self.assertEqual(51, recovery["replayed_events"])
        self.assertEqual(7, recovery["recovery_ticks"])

    def test_faulted_accepted_throughputs_are_pairwise_distinct(self):
        throughputs = {
            self.result(topology)["accepted_throughput_per_tick"]
            for topology in TOPOLOGIES
        }
        self.assertEqual({0.744186, 0.864865, 0.761905}, throughputs)

    def test_faulted_recovery_vectors_are_pairwise_distinct(self):
        vectors = {
            (
                self.result(topology)["recovery"]["recovery_ticks"],
                self.result(topology)["recovery"]["accepted_during_outage"],
                self.result(topology)["recovery"]["lost_work_ticks"],
                self.result(topology)["recovery"]["replayed_events"],
            )
            for topology in TOPOLOGIES
        }
        self.assertEqual(3, len(vectors))

    def test_hypothesis_is_supported_under_preregistered_rule(self):
        assessment = self.report["hypothesis_assessment"]
        self.assertEqual("SUPPORTED", assessment["outcome"])
        self.assertTrue(assessment["accepted_throughput_distinguishable"])
        self.assertTrue(assessment["recovery_outcomes_distinguishable"])
        self.assertTrue(assessment["all_candidates_safe_in_model"])

    def test_repeated_matched_runs_are_byte_deterministic(self):
        second = run_matched_benchmark(self.workload)
        first_bytes = json.dumps(self.report, sort_keys=True, separators=(",", ":"))
        second_bytes = json.dumps(second, sort_keys=True, separators=(",", ":"))
        self.assertEqual(first_bytes, second_bytes)

    def test_trace_digests_are_stable(self):
        expected = {
            "centralized": "8659953c4ab63df4ae220a687234d728281fbb0363fcb89a3545aab2baebdb22",
            "sharded": "d606f36f1e72531b382f943f5ecbeb173d7d92af98ad609d2925c7fceead0eaf",
            "event-sourced": "356a1b704eb9edd2906fa5b51c2645c20271fe49372ff4be1723b99f701d5f1b",
        }
        self.assertEqual(
            expected,
            {topology: self.result(topology)["trace_sha256"] for topology in TOPOLOGIES},
        )

    def test_unknown_topology_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown topology"):
            run_topology(self.workload, "renamed-clone")


class ExecutableEntryPointTests(unittest.TestCase):
    def run_candidate(self, filename):
        completed = subprocess.run(
            [sys.executable, "-I", str(UNIT_ROOT / "candidates" / filename)],
            cwd=UNIT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_centralized_script_is_executable(self):
        output = self.run_candidate("centralized.py")
        self.assertEqual("centralized", output["result"]["candidate"])

    def test_sharded_script_is_executable(self):
        output = self.run_candidate("sharded.py")
        self.assertEqual("sharded", output["result"]["candidate"])

    def test_event_sourced_script_is_executable(self):
        output = self.run_candidate("event_sourced.py")
        self.assertEqual("event-sourced", output["result"]["candidate"])

    def test_candidate_sources_do_not_import_network_clients(self):
        forbidden = ("requests", "urllib", "http.client", "socket")
        for path in sorted((UNIT_ROOT / "benchmark").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for name in forbidden:
                with self.subTest(path=path.name, name=name):
                    self.assertNotIn(f"import {name}", text)

    def test_output_option_creates_a_missing_parent_directory(self):
        with tempfile.TemporaryDirectory(dir=UNIT_ROOT) as temporary:
            output = Path(temporary) / "nested" / "result.json"
            with redirect_stdout(io.StringIO()):
                returncode = main(["--topology", "all", "--output", str(output)])
            self.assertEqual(0, returncode)
            self.assertEqual(
                "SUPPORTED",
                json.loads(output.read_text(encoding="utf-8"))[
                    "hypothesis_assessment"
                ]["outcome"],
            )


if __name__ == "__main__":
    unittest.main()
