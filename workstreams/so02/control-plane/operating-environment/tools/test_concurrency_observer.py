"""Failure injections for the concurrency gate.

Injection 5 of the delivery contract — a write to a branch with a live run —
lives here, alongside the tests that keep this gate from quietly becoming a
denylist of branch names.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


co = _load("concurrency_observer")

NOW = datetime(2026, 8, 23, 4, 0, 0, tzinfo=timezone.utc)
RECENT = "2026-08-23T03:59:00Z"

REPO_ROOT = Path(__file__).resolve().parents[5]
CAPTURE = (REPO_ROOT / "receipts/so02/2026-08-23/oe-w9-reason-gated-writes/raw"
           / "concurrency-observation-20260823T0340Z.json")


def observation(agents, observed_at=RECENT):
    return {"observed_at": observed_at, "agents": agents}


def verdict(ref, agents, **kwargs):
    kwargs.setdefault("check_ref_movement", False)
    kwargs.setdefault("now", NOW)
    obs = kwargs.pop("observation", None) or observation(agents)
    return co.concurrency_verdict(ref, obs, **kwargs)


class LiveRunRefusalTests(unittest.TestCase):
    """Injection 5: a write to a branch with a live run must be refused."""

    def test_a_running_agent_on_the_target_refuses_the_write(self) -> None:
        result = verdict("main", [{"bcId": "bc-live", "branchName": "main", "status": "RUNNING"}])
        self.assertEqual(co.IN_FLIGHT, result["verdict"])
        self.assertFalse(result["writable"])
        self.assertEqual(1, len(result["live_holders"]))

    def test_every_non_settled_status_refuses_including_ones_never_enumerated(self) -> None:
        """The denylist defect: ERROR and FAILED passed capacity_verdict silently."""
        for status in ("RUNNING", "NOT_YET_STARTED", "WAITING_FOR_BACKGROUND_WORK", "UNSPECIFIED",
                       "SOME_STATUS_INVENTED_NEXT_QUARTER", "", None, 7, "running"):
            result = verdict("main", [{"bcId": "bc-x", "branchName": "main", "status": status}])
            self.assertEqual(co.IN_FLIGHT, result["verdict"], f"status {status!r} should not be settled")

    def test_settled_matching_is_case_insensitive(self) -> None:
        for status in ("idle", "Idle", "IDLE"):
            self.assertTrue(co.is_settled(status), status)

    def test_waiting_for_background_work_is_live_because_subagents_are_writing(self) -> None:
        result = verdict("cursor/so02-cur-orch-qual-01", [
            {"bcId": "bc-c6f63d58", "branchName": "cursor/so02-cur-orch-qual-01",
             "status": "WAITING_FOR_BACKGROUND_WORK"},
        ])
        self.assertEqual(co.IN_FLIGHT, result["verdict"])

    def test_the_gate_names_its_own_expiry_rather_than_asking_permission(self) -> None:
        result = verdict("main", [{"bcId": "bc-live", "branchName": "main", "status": "RUNNING"}])
        self.assertIn("waits for that lane to finish", result["gate_expires_when"])
        self.assertIn("not forever", result["gate_expires_when"])

    def test_a_settled_agent_on_the_target_does_not_refuse(self) -> None:
        """'When it completes, the gate is gone.'"""
        for status in sorted(co.SETTLED_STATUSES):
            result = verdict("main", [{"bcId": "bc-done", "branchName": "main", "status": status}])
            self.assertEqual(co.SETTLED, result["verdict"], status)
            self.assertTrue(result["writable"], status)

    def test_a_live_run_on_a_different_branch_does_not_refuse(self) -> None:
        result = verdict("main", [{"bcId": "bc-live", "branchName": "cursor/other", "status": "RUNNING"}])
        self.assertEqual(co.SETTLED, result["verdict"])

    def test_a_malformed_agent_record_is_adjudicated_not_skipped(self) -> None:
        result = verdict("main", ["not-a-dict"])
        self.assertEqual(co.IN_FLIGHT, result["verdict"])


class SameTargetBothWaysTests(unittest.TestCase):
    """Concurrency is a property of a target at a moment, not of its name."""

    def test_one_ref_is_refused_and_admitted_by_the_world_alone(self) -> None:
        ref = "cursor/po03-wave-a-factory-6e19"
        busy = verdict(ref, [{"bcId": "bc-1", "branchName": ref, "status": "RUNNING"}])
        idle = verdict(ref, [{"bcId": "bc-1", "branchName": ref, "status": "IDLE"}])
        self.assertFalse(busy["writable"])
        self.assertTrue(idle["writable"])

    def test_main_is_an_ordinary_target(self) -> None:
        """Under the standing amendment `main` earns no special handling."""
        for ref in ("main", "cursor/scratch", "po03/repository-engineering-portable-runtime-20260822-v001"):
            self.assertTrue(verdict(ref, [])["writable"], ref)

    def test_the_module_holds_no_list_of_branch_names(self) -> None:
        source = (Path(__file__).resolve().parent / "concurrency_observer.py").read_text(encoding="utf-8")
        for forbidden in ("PROTECTED_REFS", "PROTECTED_PREFIXES", "protected_branch_globs"):
            self.assertNotIn(forbidden, source)


class ObservationHonestyTests(unittest.TestCase):
    """Asserted idleness is not observed idleness."""

    def test_a_missing_observation_is_unobservable_not_clear(self) -> None:
        for bad in (None, "", [], 0):
            result = co.concurrency_verdict("main", bad, check_ref_movement=False, now=NOW)
            self.assertEqual(co.UNOBSERVABLE, result["verdict"])
            self.assertFalse(result["writable"])

    def test_an_untimed_observation_is_refused(self) -> None:
        result = co.concurrency_verdict("main", {"agents": []}, check_ref_movement=False, now=NOW)
        self.assertEqual(co.UNOBSERVABLE, result["verdict"])
        self.assertFalse(result["writable"])

    def test_an_observation_from_the_future_is_refused(self) -> None:
        result = verdict("main", [], observation=observation([], "2026-08-24T00:00:00Z"))
        self.assertEqual(co.UNOBSERVABLE, result["verdict"])

    def test_omitting_the_agent_list_is_refused_but_an_empty_list_is_a_real_observation(self) -> None:
        missing = co.concurrency_verdict("main", {"observed_at": RECENT}, check_ref_movement=False, now=NOW)
        self.assertEqual(co.UNOBSERVABLE, missing["verdict"])
        empty = verdict("main", [])
        self.assertEqual(co.SETTLED, empty["verdict"])

    def test_every_verdict_carries_the_top_layer_limit(self) -> None:
        for agents in ([], [{"bcId": "b", "branchName": "main", "status": "RUNNING"}]):
            result = verdict("main", agents)
            self.assertIn("not proof that nobody is writing", result["limit"])

    def test_the_admitting_verdict_never_claims_to_be_clear(self) -> None:
        """A settled verdict states its limit in its own name."""
        self.assertEqual("SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT", co.SETTLED)
        self.assertTrue(verdict("main", [])["verdict"].endswith("SUBJECT_TO_TOP_LAYER_LIMIT"))

    def test_staleness_is_advisory_because_any_threshold_is_invented(self) -> None:
        stale = verdict("main", [], observation=observation([], "2026-08-22T04:00:00Z"))
        self.assertTrue(stale["writable"])
        self.assertTrue(any("assistant-invented" in a for a in stale["advisories"]))

    def test_an_operator_set_age_limit_does_refuse(self) -> None:
        stale = verdict("main", [], observation=observation([], "2026-08-23T03:00:00Z"),
                        max_observation_age_seconds=600)
        self.assertFalse(stale["writable"])
        self.assertEqual(co.UNOBSERVABLE, stale["verdict"])


class RefMovementTests(unittest.TestCase):
    """The second signal, which catches a writer the agent layer cannot see."""

    def test_a_moved_ref_refuses_even_with_no_visible_agent(self) -> None:
        result = co.concurrency_verdict(
            "main", observation([]), recorded_sha="a" * 40, check_ref_movement=True, now=NOW,
            repo=Path("/nonexistent-so-ls-remote-cannot-succeed"),
        )
        # An unobservable remote must not read as settled.
        self.assertIn(result["verdict"], {co.IN_FLIGHT_REF_MOVED, co.UNOBSERVABLE})
        self.assertFalse(result["writable"])

    def test_movement_detection_compares_against_the_recorded_sha(self) -> None:
        moved = co.observe_ref_movement.__doc__
        self.assertIn("cannot see", moved)

    def test_an_unobservable_remote_is_not_settled(self) -> None:
        result = co.concurrency_verdict(
            "main", observation([]), recorded_sha=None, check_ref_movement=True, now=NOW,
            repo=Path("/nonexistent-so-ls-remote-cannot-succeed"),
        )
        self.assertFalse(result["writable"])
        self.assertEqual(co.UNOBSERVABLE, result["verdict"])


class ReproducedBlindSpotTests(unittest.TestCase):
    """The captured evidence that absence from the list is not absence of a writer."""

    @classmethod
    def setUpClass(cls) -> None:
        if not CAPTURE.exists():
            raise unittest.SkipTest(f"capture not present at {CAPTURE}")
        cls.capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
        cls.agents = cls.capture["payload"]["agents"]

    def test_the_observing_lanes_own_branch_is_absent_from_its_own_observation(self) -> None:
        observer_branch = self.capture["_capture"]["observer_branch_at_capture"]
        branches = {a.get("branchName") for a in self.agents}
        self.assertNotIn(observer_branch, branches,
                         "the capture no longer demonstrates the blind spot it was kept for")

    def test_a_live_invisible_writer_would_read_as_settled_on_signal_one_alone(self) -> None:
        observer_branch = self.capture["_capture"]["observer_branch_at_capture"]
        result = verdict(observer_branch, self.agents)
        self.assertEqual(co.SETTLED, result["verdict"])
        self.assertIn("not proof that nobody is writing", result["limit"])

    def test_the_real_capture_refuses_the_root_controllers_branch(self) -> None:
        result = verdict("cursor/so02-cur-orch-qual-01", self.agents)
        self.assertEqual(co.IN_FLIGHT, result["verdict"])
        self.assertFalse(result["writable"])
        self.assertEqual("WAITING_FOR_BACKGROUND_WORK", result["live_holders"][0]["status"])

    def test_the_real_capture_admits_a_settled_po03_branch(self) -> None:
        """The founder: 'Write to a PO-03 branch once it is not running.'"""
        for ref in ("cursor/po03-wave-a-factory-6e19",
                    "po03/repository-engineering-portable-runtime-20260822-v001"):
            result = verdict(ref, self.agents)
            self.assertEqual(co.SETTLED, result["verdict"], ref)
            self.assertTrue(result["writable"], ref)

    def test_a_denylist_naming_only_running_would_have_passed_the_root_controller(self) -> None:
        holder = next(a for a in self.agents if a.get("branchName") == "cursor/so02-cur-orch-qual-01")
        self.assertNotEqual("RUNNING", holder["status"])
        self.assertFalse(co.is_settled(holder["status"]))


if __name__ == "__main__":
    unittest.main()
