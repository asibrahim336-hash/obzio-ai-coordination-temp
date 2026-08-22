"""Tests for a7-u03: every reported rate states an explicit numerator and
denominator, and the computation is reproducible from committed inputs.

workstreams/po03/evidence/snapshot-coupling.json: this cohort's own
`test_recomputation_matches_committed_report_except_generation_metadata`
was one of the eight replicated instances of the false-red snapshot-coupling
defect class -- it compared a committed report to a recomputation against
the *live* ledger, which grew from 319 to 345 rows after the report was
committed. Per the now-binding operating rule, the reproduction test below
asserts against the exact immutable commit this cohort measured against
(PIN_COMMIT, whose ledger state matches this report's own recorded
measured_against fields) instead of against live state, and a second set of
tests proves under mutation that the assertion still bites: it is not a
tautology that would pass regardless of the report, the generator or the
pin.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPO_ROOT / "workstreams/po03/metrics"))
from pin_support import materialize_commit_subset  # noqa: E402
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "compute_metrics.py"
SPEC = importlib.util.spec_from_file_location("compute_metrics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/metrics-report.json"

# The commit at which this cohort's own tools last regenerated
# metrics-report.json in lock-step with work-unit-runs.jsonl and the ledger.
# Its ledger state (345 rows, ledger_head_sha256 c89f8b9f...) is exactly what
# the currently committed report's own "measured_against" field records; see
# test_pin_commit_ledger_state_matches_the_committed_measured_against below.
# Superseded an earlier pin, dae059819d845c25dfc22ea7031c0988b07db23d (319
# rows), once the coordinator's ledger grew to 345 rows between sessions --
# the exact class of live-state drift this pinning scheme exists to survive.
PIN_COMMIT = "79453a7033d34cf7cfbbe3e64f4fab6ed1bbd34e"

# Every relative path compute_metrics.compute() reads, so the materialised
# snapshot is a faithful, self-contained reproduction of the pin -- including
# control_plane.py itself, so the projection logic used is also pinned, not
# whatever happens to be live in this worktree.
REQUIRED_RELATIVE_PATHS = [
    "workstreams/po03/tools/control_plane.py",
    "workstreams/po03/control/events/ledger.jsonl",
    "workstreams/po03/metrics/work-unit-runs.jsonl",
    "workstreams/po03/control/wave-a-spec.json",
    "workstreams/po03/control/work-unit-registry.jsonl",
    "workstreams/po03/research/hypotheses.jsonl",
    "workstreams/po03/research/reproduction-ledger.jsonl",
    "workstreams/po03/successor/lesson-lineage.json",
    "workstreams/po03/research/lesson-lineage.json",
    "workstreams/po03/review/luna/false-green-result.json",
]


def _compute_at_pin(commit: str = PIN_COMMIT):
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        materialize_commit_subset(REPO_ROOT, commit, REQUIRED_RELATIVE_PATHS, dest)
        return MODULE.compute(dest)

RATE_METRICS = (
    "independently_accepted_throughput",
    "first_pass_acceptance_rate",
    "escaped_defect_rate",
    "founder_interventions",
)


class TestComputeMetrics(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_measured_against_ledger_is_recorded(self):
        measured = self.report["measured_against"]
        self.assertIn("ledger_head_sha256", measured)
        self.assertIn("ledger_rows", measured)
        self.assertEqual(len(measured["ledger_head_sha256"]), 64)

    def test_every_rate_metric_has_explicit_numerator_and_denominator(self):
        for name in RATE_METRICS:
            metric = self.report["metrics"][name]
            if metric["value"] == "UNDEFINED_0_OF_0":
                self.assertEqual(metric["denominator"], 0)
            else:
                self.assertIn("numerator", metric)
                self.assertIn("denominator", metric)
                self.assertGreater(metric["denominator"], 0)
                self.assertAlmostEqual(metric["value"], metric["numerator"] / metric["denominator"])

    def test_rate_helper_zero_denominator_is_never_invented(self):
        result = MODULE.rate(0, 0)
        self.assertEqual(result["value"], "UNDEFINED_0_OF_0")
        self.assertNotIn("value", {"0": 0})  # sanity: 0 must not silently mean 0/0

    def test_rate_helper_normal_division(self):
        result = MODULE.rate(3, 12)
        self.assertEqual(result, {"numerator": 3, "denominator": 12, "value": 0.25})

    def test_not_yet_metrics_state_a_boundary_and_no_invented_value(self):
        for name in ("false_green_rate", "research_to_reproduction_conversion", "lesson_to_live_change_conversion", "successor_lift"):
            metric = self.report["metrics"][name]
            if metric["value"] == "NOT_YET":
                self.assertIn("boundary", metric)

    def test_context_waste_is_not_supported_with_boundary(self):
        metric = self.report["metrics"]["context_waste"]
        self.assertEqual(metric["value"], "NOT_SUPPORTED")
        self.assertIn("observed_boundary", metric)

    def test_pin_commit_ledger_state_matches_the_committed_measured_against(self):
        """PIN_COMMIT must actually be the commit this report claims to be
        measured against, or the pin below would be reproducing the wrong
        thing without anyone noticing."""
        pinned = _compute_at_pin()
        self.assertEqual(pinned["measured_against"], self.report["measured_against"])
        self.assertEqual(self.report["measured_against"]["ledger_rows"], 345)
        self.assertEqual(
            self.report["measured_against"]["ledger_head_sha256"],
            "c89f8b9f4ee6f223efe299287d9549773b5d1735963bed47a211d67cb89bbf09",
        )

    def test_recomputation_matches_committed_report_at_the_recorded_pin(self):
        """The report must be exactly reproducible from the ledger and
        work-unit-runs.jsonl as they existed at the recorded immutable pin --
        never from the live ledger, which mutates as the wave progresses
        (workstreams/po03/evidence/snapshot-coupling.json)."""
        recomputed = _compute_at_pin()
        self.assertEqual(recomputed, self.report)

    def test_pinned_reproduction_would_catch_a_mutated_report(self):
        """Prove the assertion above is not a tautology: if the committed
        report were wrong, the pinned recomputation would not equal it."""
        recomputed = _compute_at_pin()
        mutated_report = json.loads(json.dumps(self.report))
        mutated_report["metrics"]["first_pass_acceptance_rate"]["numerator"] += 1
        self.assertNotEqual(recomputed, mutated_report)

    def test_pinned_reproduction_would_catch_a_generator_regression(self):
        """Prove the assertion is not a tautology from the generator's side
        either: a change to the computation (here, a monkeypatched rate())
        must make the pinned recomputation disagree with the committed
        report."""
        original_rate = MODULE.rate
        try:
            MODULE.rate = lambda n, d: {"numerator": n, "denominator": d, "value": "TAMPERED"}
            tampered = _compute_at_pin()
        finally:
            MODULE.rate = original_rate
        self.assertNotEqual(tampered, self.report)

    def test_pinned_reproduction_would_catch_the_wrong_pin(self):
        """Prove the assertion is not a tautology from the pin's side
        either: a different immutable commit (this cohort's own earlier
        319-row-ledger checkpoint) must not reproduce this report."""
        older_pin = "dae059819d845c25dfc22ea7031c0988b07db23d"
        older = _compute_at_pin(older_pin)
        self.assertNotEqual(older["measured_against"]["ledger_rows"], self.report["measured_against"]["ledger_rows"])
        self.assertNotEqual(older, self.report)

    def test_orphan_and_false_complete_counts_have_explicit_denominators(self):
        counts = self.report["metrics"]["orphan_duplicate_collision_falsecomplete_counts"]
        for key in ("orphan_count", "duplicate_count", "collision_count", "false_complete_count"):
            self.assertIn(key, counts)
        self.assertIn("denominator_units_total", counts)
        self.assertIn("denominator_ledger_rows_total", counts)
        self.assertEqual(counts["orphan_count"], len(counts["orphan_units"]))
        self.assertEqual(counts["false_complete_count"], len(counts["false_complete_units"]))


if __name__ == "__main__":
    unittest.main()
