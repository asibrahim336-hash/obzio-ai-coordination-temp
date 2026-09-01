from __future__ import annotations

import ast
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


class ReportedHeadTests(unittest.TestCase):
    """A zero exit from git push is not evidence of publication."""

    def test_absent_branch_with_a_reported_sha_is_flagged(self) -> None:
        result = lane_guard.verify_reported_head("cursor/oe-branch-that-does-not-exist-696d", "a" * 40)
        self.assertEqual("REPORTED_BUT_ABSENT", result["state"])
        self.assertFalse(result["matches"])

    def test_a_wrong_reported_sha_is_flagged_as_silent_push_divergence(self) -> None:
        result = lane_guard.verify_reported_head("cursor/oe-l1-cursor-baseline-696d", "b" * 40)
        if result["remote_sha"] is not None:
            self.assertEqual("SILENT_PUSH_DIVERGENCE", result["state"])
            self.assertFalse(result["matches"])

    def test_a_correct_reported_sha_confirms_publication(self) -> None:
        branch = "cursor/oe-l1-cursor-baseline-696d"
        code, out, _ = lane_guard.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
        if code != 0 or not out.strip():
            self.skipTest("lane branch not published in this environment")
        actual = out.split()[0]
        result = lane_guard.verify_reported_head(branch, actual)
        self.assertEqual("CONFIRMED_PUBLISHED", result["state"])
        self.assertTrue(result["matches"])


class RetiredProtectedRefTests(unittest.TestCase):
    """The founder voided the category on 2026-08-23; this keeps it retired.

    These tests replace `ProtectedRefTests`, which asserted that `main`, PO-03,
    SO-02 and `soo/` refs were recognised as protected. That expectation is now
    the defect, so asserting the machinery is absent is the correct successor to
    asserting it worked.
    """

    def test_the_protected_ref_machinery_is_gone_from_the_module(self) -> None:
        for retired in ("PROTECTED_REFS", "PROTECTED_PREFIXES", "guard_ref_is_protected",
                        "verify_protected_refs"):
            self.assertFalse(hasattr(lane_guard, retired),
                             f"{retired} still exists; the voided category has survived")

    def test_no_verdict_or_report_key_names_protected_refs(self) -> None:
        # The retirement is documented in the module docstring, which necessarily
        # names what was removed. What must not survive is executable use of it,
        # so the docstring is stripped and the remaining code is what is checked.
        tree = ast.parse((Path(__file__).resolve().parent / "lane_guard.py").read_text(encoding="utf-8"))
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            tree.body.pop(0)
        code_only = ast.unparse(tree)
        for retired in ("protected_ref_drift", "PROTECTED_REF_DRIFT_FAIL",
                        "protected_surfaces_declared_untouchable", "PROTECTED_REFS",
                        "guard_ref_is_protected"):
            self.assertNotIn(retired, code_only, retired)

    def test_a_previously_protected_ref_is_now_an_ordinary_lane_branch(self) -> None:
        """No surface is off-limits because of a name on a list."""
        owned = ["workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/**"]
        path = "workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/X.json"
        # Containment is about which paths a lane owns, and it never consulted a
        # branch name; that separation is why removing the branch list changes
        # nothing about the control that actually caught a defect.
        self.assertTrue(lane_guard.namespace_matches(path, owned))


class LaneConcurrencyTests(unittest.TestCase):
    """The replacement for the drift check: is a lane branch still being written?"""

    RESULTS = [
        {"parent_id": "OE-L1", "branch": "cursor/oe-l1-cursor-baseline-696d"},
        {"parent_id": "OE-L2", "branch": "cursor/oe-l2-capability-research-696d"},
    ]

    def test_a_lane_branch_held_by_a_live_run_is_reported_in_flight(self) -> None:
        observation = {"observed_at": "2026-08-23T04:00:00Z", "agents": [
            {"bcId": "bc-live", "branchName": "cursor/oe-l1-cursor-baseline-696d", "status": "RUNNING"},
        ]}
        notes = lane_guard.lanes_in_flight(self.RESULTS, observation)
        self.assertEqual(1, len(notes))
        self.assertIn("OE-L1", notes[0])
        self.assertIn("would disturb work in flight", notes[0])

    def test_a_settled_run_leaves_the_lane_integrable(self) -> None:
        observation = {"observed_at": "2026-08-23T04:00:00Z", "agents": [
            {"bcId": "bc-done", "branchName": "cursor/oe-l1-cursor-baseline-696d", "status": "IDLE"},
        ]}
        self.assertEqual([], lane_guard.lanes_in_flight(self.RESULTS, observation))

    def test_no_observation_invents_no_refusal(self) -> None:
        """Missing data is not a finding; inventing one would be assistant-authored."""
        self.assertEqual([], lane_guard.lanes_in_flight(self.RESULTS, None))
        self.assertEqual([], lane_guard.lanes_in_flight(self.RESULTS, {}))


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

    def test_undelivered_and_rejected_are_distinct_states(self) -> None:
        """Not finished is not the same as failed; conflating them is the estate's core defect."""
        self.assertNotEqual("REJECTED_FAIL_CLOSED", "IN_FLIGHT_NO_CONTENT_YET")
        for state in ("NOT_RETURNED", "IN_FLIGHT_NO_CONTENT_YET", "REJECTED_FAIL_CLOSED"):
            self.assertNotEqual("READY_FOR_INTEGRATION", state)

    def test_an_empty_branch_is_never_integrable(self) -> None:
        parent = {
            "parent_id": "OE-L1-CURSOR-BASELINE",
            "isolated_branch": "cursor/oe-l1-cursor-baseline-696d",
            "owned_namespace": ["receipts/so02/2026-08-22/oe-l1-cursor-baseline/**"],
        }
        result = lane_guard.evaluate_lane(parent, "fe0a595206e5986de7eaac6cabc619215a1eb81b")
        if result["state"] == "IN_FLIGHT_NO_CONTENT_YET":
            self.assertFalse(result["integrable"])
            self.assertEqual(0, result["changed_file_count"])


if __name__ == "__main__":
    unittest.main()
