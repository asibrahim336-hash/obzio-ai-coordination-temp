"""Unit tests for the a5-u01 invariant/fault-class mapping model itself."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.counterfactual_engine import (  # noqa: E402
    FULL,
    NO_CHECKPOINT,
    NO_FENCE,
    NO_IDEMPOTENCY,
    NO_OUTBOX,
)
from lib.fault_matrix_u01 import (  # noqa: E402
    FAULT_TO_INVARIANT,
    build_survival_matrix,
    run_fault_crash_before_local_record,
    run_fault_duplicate_callback,
    run_fault_restart_with_no_checkpoint,
    run_fault_stale_writer_after_eviction,
)
from lib.counterfactual_engine import MinimalCustodyEngine  # noqa: E402


class TestFaultMatrixModel(unittest.TestCase):
    def test_full_config_survives_every_fault(self) -> None:
        for runner in (
            run_fault_duplicate_callback,
            run_fault_stale_writer_after_eviction,
            run_fault_crash_before_local_record,
            run_fault_restart_with_no_checkpoint,
        ):
            with self.subTest(runner=runner.__name__):
                engine = MinimalCustodyEngine(FULL)
                self.assertTrue(runner(engine, "u1"))

    def test_removing_idempotency_key_breaks_duplicate_callback_and_crash_retry(self) -> None:
        # Measured, not assumed: idempotency-key dedup is also the mechanism
        # that makes a post-crash retry safe, so removing it breaks BOTH
        # duplicate_callback and crash_before_local_record, not only the
        # former. This is documented as a finding in the u01 reproduction,
        # not silently special-cased away.
        self.assertFalse(run_fault_duplicate_callback(MinimalCustodyEngine(NO_IDEMPOTENCY), "u1"))
        self.assertFalse(run_fault_crash_before_local_record(MinimalCustodyEngine(NO_IDEMPOTENCY), "u1"))
        self.assertTrue(run_fault_stale_writer_after_eviction(MinimalCustodyEngine(NO_IDEMPOTENCY), "u1"))
        self.assertTrue(run_fault_restart_with_no_checkpoint(MinimalCustodyEngine(NO_IDEMPOTENCY), "u1"))

    def test_removing_fence_token_breaks_only_stale_writer(self) -> None:
        # fence_token is the one invariant with zero measured cross-effects:
        # removing it breaks exactly the fault class it names and nothing else.
        self.assertFalse(run_fault_stale_writer_after_eviction(MinimalCustodyEngine(NO_FENCE), "u1"))
        self.assertTrue(run_fault_duplicate_callback(MinimalCustodyEngine(NO_FENCE), "u1"))
        self.assertTrue(run_fault_crash_before_local_record(MinimalCustodyEngine(NO_FENCE), "u1"))
        self.assertTrue(run_fault_restart_with_no_checkpoint(MinimalCustodyEngine(NO_FENCE), "u1"))

    def test_removing_outbox_breaks_only_crash_before_record(self) -> None:
        self.assertFalse(run_fault_crash_before_local_record(MinimalCustodyEngine(NO_OUTBOX), "u1"))
        self.assertTrue(run_fault_duplicate_callback(MinimalCustodyEngine(NO_OUTBOX), "u1"))
        self.assertTrue(run_fault_stale_writer_after_eviction(MinimalCustodyEngine(NO_OUTBOX), "u1"))
        self.assertTrue(run_fault_restart_with_no_checkpoint(MinimalCustodyEngine(NO_OUTBOX), "u1"))

    def test_removing_checkpoint_cascades_into_three_fault_classes(self) -> None:
        # Measured, not assumed: checkpoint (a durable record store) is the
        # substrate idempotency-key dedup reads from. Removing it defeats
        # restart recovery directly AND silently defeats duplicate-callback
        # and crash-retry protection even though idempotency_key is still
        # nominally "on", because there is nowhere durable left to check
        # against. checkpoint is therefore the most load-bearing invariant
        # of the four, not a peer of equal, independent weight.
        self.assertFalse(run_fault_restart_with_no_checkpoint(MinimalCustodyEngine(NO_CHECKPOINT), "u1"))
        self.assertFalse(run_fault_duplicate_callback(MinimalCustodyEngine(NO_CHECKPOINT), "u1"))
        self.assertFalse(run_fault_crash_before_local_record(MinimalCustodyEngine(NO_CHECKPOINT), "u1"))
        self.assertTrue(run_fault_stale_writer_after_eviction(MinimalCustodyEngine(NO_CHECKPOINT), "u1"))

    def test_survival_matrix_matches_the_measured_dependency_graph(self) -> None:
        from lib.counterfactual_engine import ALL_CONFIGS

        matrix = build_survival_matrix(ALL_CONFIGS)
        self.assertTrue(all(matrix["FULL"][fault] for fault in FAULT_TO_INVARIANT))
        # Ground truth measured above, encoded once so the reproduction
        # script and this test cannot silently diverge.
        expected_survives = {
            "NO_FENCE_TOKEN": {
                "duplicate_callback": True,
                "stale_writer_after_eviction": False,
                "crash_before_local_record": True,
                "restart_with_no_checkpoint": True,
            },
            "NO_OUTBOX": {
                "duplicate_callback": True,
                "stale_writer_after_eviction": True,
                "crash_before_local_record": False,
                "restart_with_no_checkpoint": True,
            },
            "NO_CHECKPOINT": {
                "duplicate_callback": False,
                "stale_writer_after_eviction": True,
                "crash_before_local_record": False,
                "restart_with_no_checkpoint": False,
            },
            "NO_IDEMPOTENCY_KEY": {
                "duplicate_callback": False,
                "stale_writer_after_eviction": True,
                "crash_before_local_record": False,
                "restart_with_no_checkpoint": True,
            },
        }
        for config_label, expected_row in expected_survives.items():
            for fault_name, expected in expected_row.items():
                self.assertEqual(
                    matrix[config_label][fault_name],
                    expected,
                    f"{config_label}/{fault_name}: expected survived={expected}",
                )


if __name__ == "__main__":
    unittest.main()
