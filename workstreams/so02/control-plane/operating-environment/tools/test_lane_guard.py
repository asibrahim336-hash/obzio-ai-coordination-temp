from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "lane_guard.py"
SPEC = importlib.util.spec_from_file_location("lane_guard", MODULE_PATH)
lane_guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(lane_guard)


class NamespaceContainmentTests(unittest.TestCase):
    """The control that the live worktree collision proved was missing."""

    OWNED = [
        "workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/**",
        "receipts/so02/2026-08-22/oe-l1-cursor-baseline/**",
    ]

    def test_owned_paths_are_accepted(self) -> None:
        for path in (
            "workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/BASELINE.json",
            "workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/deep/nested/file.md",
            "receipts/so02/2026-08-22/oe-l1-cursor-baseline/MANIFEST.json",
        ):
            self.assertTrue(lane_guard.namespace_matches(path, self.OWNED), path)

    def test_another_lanes_path_is_rejected(self) -> None:
        self.assertFalse(lane_guard.namespace_matches(
            "workstreams/so02/control-plane/operating-environment/l2-capability-research/MAP.json",
            self.OWNED,
        ))

    def test_shared_projection_state_is_rejected(self) -> None:
        for path in (
            "workstreams/so02/control-plane/operating-environment/GROUP-MANIFEST-OE-20260822-v001.json",
            "workstreams/so02/control-plane/state/control-plane.json",
            "workstreams/so02/control-plane/state/events.jsonl",
        ):
            self.assertFalse(lane_guard.namespace_matches(path, self.OWNED), path)

    def test_sibling_prefix_is_not_treated_as_owned(self) -> None:
        self.assertFalse(lane_guard.namespace_matches(
            "receipts/so02/2026-08-22/oe-l1-cursor-baseline-EXTRA/MANIFEST.json",
            self.OWNED,
        ))

    def test_global_state_and_po03_paths_are_rejected(self) -> None:
        for path in ("state/ACTIVE_CONTROL_POINTER_CURRENT.json", "workstreams/po03/COMMISSION.md", "main.py"):
            self.assertFalse(lane_guard.namespace_matches(path, self.OWNED), path)


class CollisionDetectionTests(unittest.TestCase):
    def test_two_lanes_claiming_one_path_is_detected(self) -> None:
        results = [
            {"parent_id": "OE-L1", "changed_files": ["a.json", "shared.json"]},
            {"parent_id": "OE-L2", "changed_files": ["b.json", "shared.json"]},
        ]
        collisions = lane_guard.detect_path_collisions(results)
        self.assertEqual(1, len(collisions))
        self.assertIn("shared.json", collisions[0])

    def test_disjoint_lanes_produce_no_collision(self) -> None:
        results = [
            {"parent_id": "OE-L1", "changed_files": ["a.json"]},
            {"parent_id": "OE-L2", "changed_files": ["b.json"]},
        ]
        self.assertEqual([], lane_guard.detect_path_collisions(results))

    def test_one_lane_listing_a_path_twice_is_not_a_collision(self) -> None:
        results = [{"parent_id": "OE-L1", "changed_files": ["a.json", "a.json"]}]
        self.assertEqual([], lane_guard.detect_path_collisions(results))


class ProtectedRefTests(unittest.TestCase):
    def test_protected_branches_are_recognised(self) -> None:
        for branch in (
            "main",
            "so02/strategic-control-plane-migration-20260822-v001",
            "cursor/so02-cur-orch-qual-01",
            "cursor/operating-environment-return-20260822-v001",
            "cursor/po03-wave-a-factory-6e19",
            "po03/repository-engineering-portable-runtime-20260822-v001",
            "soo/v003-currentness-repair-20260820",
            "packs/operator-fleet-v1-20260820",
        ):
            self.assertTrue(lane_guard.guard_ref_is_protected(branch), branch)

    def test_lane_branches_are_not_protected(self) -> None:
        for branch in (
            "cursor/oe-l1-cursor-baseline-696d",
            "cursor/oe-l3-independent-acceptance-696d",
        ):
            self.assertFalse(lane_guard.guard_ref_is_protected(branch), branch)


class LaneVerdictTests(unittest.TestCase):
    """A lane that did not push must never be assumed successful."""

    def test_absent_branch_is_not_returned_and_not_integrable(self) -> None:
        parent = {
            "parent_id": "OE-LX",
            "isolated_branch": "cursor/oe-branch-that-does-not-exist-696d",
            "owned_namespace": ["receipts/so02/2026-08-22/oe-lx/**"],
        }
        result = lane_guard.evaluate_lane(parent, "fe0a595206e5986de7eaac6cabc619215a1eb81b")
        self.assertEqual("NOT_RETURNED", result["state"])
        self.assertFalse(result["integrable"])


if __name__ == "__main__":
    unittest.main()
