"""Falsification tests for the PO03-WA-040 shared-path controller gate.

The distinguishing assertion in this slot is temporal: for every refused
write the test asserts that the target file does not exist on disk after the
attempt.  A gate that reported the violation only after writing would pass a
verdict-only test and fail these.

The policy fixture mirrors the shape of the real
``workstreams/po03/control/path-ownership.json`` but is constructed in the
test, so nothing in the repository is read or written.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "shared_path_controller_gate.py"
SPEC = importlib.util.spec_from_file_location("shared_path_controller_gate", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


CONTROLLER_ID = "controller-run-fixture"
CONTROLLER_FENCE = 7
OWNED = "workstreams/po03/runs/wave-a/route-05/PO03-WA-040"

POLICY_DOCUMENT = {
    "allowlist": ["workstreams/po03/", "receipts/po03/", ".github/workflows/po03-"],
    "controller_run_id": CONTROLLER_ID,
    "controller_shared_paths": [
        "workstreams/po03/control/**",
        "workstreams/po03/metrics/**",
        "workstreams/po03/evidence/**",
        "workstreams/po03/successor/**",
        "receipts/po03/**",
        ".github/workflows/po03-*.yml",
    ],
}


class GateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-040-")
        self.root = Path(self._tmp.name)
        self.policy = G.OwnershipPolicy.from_path_ownership(POLICY_DOCUMENT, CONTROLLER_FENCE)

    def tearDown(self):
        self._tmp.cleanup()

    def gate(self, actor_id: str, fence_token: int = 1, owned: str = OWNED):
        return G.SharedPathControllerGate(self.root, self.policy, G.Identity(actor_id, fence_token), owned)

    def assert_absent(self, relative: str):
        self.assertFalse((self.root / relative).exists(), f"{relative} should not exist on disk")


class SharedPathClassificationTests(GateFixture):
    def test_control_paths_are_shared(self):
        self.assertTrue(G.is_shared_path(self.policy, "workstreams/po03/control/leases/route-05.json"))

    def test_metrics_evidence_and_receipts_are_shared(self):
        for path in (
            "workstreams/po03/metrics/work-unit-runs.jsonl",
            "workstreams/po03/evidence/source-lock.json",
            "receipts/po03/receipt.json",
        ):
            self.assertTrue(G.is_shared_path(self.policy, path), path)

    def test_workflow_glob_is_shared(self):
        self.assertTrue(G.is_shared_path(self.policy, ".github/workflows/po03-contracts.yml"))

    def test_unrelated_workflow_is_not_shared(self):
        self.assertFalse(G.is_shared_path(self.policy, ".github/workflows/other.yml"))

    def test_route_subtree_is_not_shared(self):
        self.assertFalse(G.is_shared_path(self.policy, OWNED + "/result.json"))


class WorkerRefusalTests(GateFixture):
    def test_worker_shared_path_write_is_refused_before_commit(self):
        gate = self.gate("route-05-worker")
        target = "workstreams/po03/control/leases/route-05.json"
        gate.stage(target, b"{\"fence_token\": 99}")
        decision = gate.precommit_check()
        self.assertFalse(decision.admissible)
        self.assertEqual(G.REJECTED_NOT_CONTROLLER, decision.violations[0].verdict)
        with self.assertRaises(G.GateViolationError):
            gate.commit()
        self.assert_absent(target)

    def test_forged_controller_id_without_the_fence_token_is_refused(self):
        gate = self.gate(CONTROLLER_ID, fence_token=CONTROLLER_FENCE - 1)
        target = "workstreams/po03/control/outbox.jsonl"
        gate.stage(target, b"forged\n")
        decision = gate.precommit_check()
        self.assertEqual(G.REJECTED_STALE_FENCE, decision.violations[0].verdict)
        with self.assertRaises(G.GateViolationError):
            gate.commit()
        self.assert_absent(target)

    def test_worker_write_to_a_sibling_route_is_refused(self):
        gate = self.gate("route-05-worker")
        target = "workstreams/po03/runs/wave-a/route-04/PO03-WA-025/result.json"
        gate.stage(target, b"x")
        decision = gate.precommit_check()
        self.assertEqual(G.REJECTED_OUTSIDE_OWNED_SUBTREE, decision.violations[0].verdict)
        self.assert_absent(target)

    def test_write_outside_the_allowlist_entirely_is_refused(self):
        gate = self.gate("route-05-worker")
        target = "docs/roadmap.md"
        gate.stage(target, b"x")
        decision = gate.precommit_check()
        self.assertEqual(G.REJECTED_OUTSIDE_ALLOWLIST, decision.violations[0].verdict)
        self.assert_absent(target)

    def test_one_violation_refuses_the_whole_batch(self):
        gate = self.gate("route-05-worker")
        gate.stage(OWNED + "/result.json", b"legitimate")
        gate.stage("workstreams/po03/control/events/events.jsonl", b"illegitimate")
        gate.precommit_check()
        with self.assertRaises(G.GateViolationError):
            gate.commit()
        self.assert_absent(OWNED + "/result.json")
        self.assert_absent("workstreams/po03/control/events/events.jsonl")


class ControllerAdmissionTests(GateFixture):
    def test_controller_with_current_fence_may_write_shared_paths(self):
        gate = self.gate(CONTROLLER_ID, fence_token=CONTROLLER_FENCE)
        target = "workstreams/po03/control/events/events.jsonl"
        gate.stage(target, b"{\"event\": \"ok\"}\n")
        self.assertTrue(gate.precommit_check().admissible)
        self.assertEqual([target], gate.commit())
        self.assertEqual(b"{\"event\": \"ok\"}\n", (self.root / target).read_bytes())

    def test_worker_may_write_its_own_subtree(self):
        gate = self.gate("route-05-worker")
        target = OWNED + "/result.json"
        gate.stage(target, b"{}")
        self.assertTrue(gate.precommit_check().admissible)
        self.assertEqual([target], gate.commit())
        self.assertEqual(b"{}", (self.root / target).read_bytes())


class FailClosedTests(GateFixture):
    def test_commit_without_precommit_check_is_refused(self):
        gate = self.gate("route-05-worker")
        target = OWNED + "/result.json"
        gate.stage(target, b"{}")
        with self.assertRaises(G.GateNotCheckedError):
            gate.commit()
        self.assert_absent(target)

    def test_staging_after_the_check_invalidates_the_decision(self):
        gate = self.gate("route-05-worker")
        gate.stage(OWNED + "/a.json", b"a")
        gate.precommit_check()
        gate.stage(OWNED + "/b.json", b"b")
        with self.assertRaises(G.GateNotCheckedError):
            gate.commit()
        self.assert_absent(OWNED + "/a.json")

    def test_swapping_the_staged_set_after_the_check_is_refused(self):
        """Time-of-check/time-of-use: pass with a benign set, then swap."""
        gate = self.gate("route-05-worker")
        gate.stage(OWNED + "/benign.json", b"benign")
        decision = gate.precommit_check()
        self.assertTrue(decision.admissible)
        # Reach past the API to simulate a compromised caller mutating the set
        # without going through stage(), which would have cleared the decision.
        gate._staged[0] = (
            G.StagedWrite("route-05-worker", "workstreams/po03/control/outbox.jsonl", "0" * 64, 3),
            b"bad",
        )
        with self.assertRaises(G.StagedSetChangedError):
            gate.commit()
        self.assert_absent("workstreams/po03/control/outbox.jsonl")

    def test_staged_digest_is_order_independent(self):
        a = G.StagedWrite("w", "p/a", "a" * 64, 1)
        b = G.StagedWrite("w", "p/b", "b" * 64, 2)
        self.assertEqual(G.staged_digest([a, b]), G.staged_digest([b, a]))

    def test_staged_digest_changes_with_content(self):
        a = G.StagedWrite("w", "p/a", "a" * 64, 1)
        a2 = G.StagedWrite("w", "p/a", "c" * 64, 1)
        self.assertNotEqual(G.staged_digest([a]), G.staged_digest([a2]))

    def test_nothing_is_staged_to_disk_before_commit(self):
        gate = self.gate("route-05-worker")
        gate.stage(OWNED + "/result.json", b"{}")
        gate.precommit_check()
        self.assertEqual([], list(self.root.iterdir()))

    def test_malformed_policy_is_refused(self):
        with self.assertRaises(ValueError):
            G.OwnershipPolicy.from_path_ownership({"allowlist": []}, 1)


class CommandLineTests(GateFixture):
    def _run(self, actor_id: str, fence: int, *targets: str):
        policy_path = self.root / "path-ownership.json"
        policy_path.write_text(json.dumps(POLICY_DOCUMENT), encoding="utf-8")
        args = [
            sys.executable,
            str(MODULE_PATH),
            "--path-ownership",
            str(policy_path),
            "--actor-id",
            actor_id,
            "--fence-token",
            str(fence),
            "--controller-fence-token",
            str(CONTROLLER_FENCE),
            "--owned-subtree",
            OWNED,
            "--json",
        ]
        for target in targets:
            args.extend(["--target", target])
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def test_worker_owned_write_exits_zero(self):
        proc = self._run("route-05-worker", 1, OWNED + "/result.json")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["admissible"])

    def test_worker_shared_write_exits_one(self):
        proc = self._run("route-05-worker", 1, "workstreams/po03/control/leases/route-05.json")
        self.assertEqual(1, proc.returncode)
        report = json.loads(proc.stdout)
        self.assertEqual(1, report["violations"])
        self.assertEqual(G.REJECTED_NOT_CONTROLLER, report["verdicts"][0]["verdict"])

    def test_controller_shared_write_exits_zero(self):
        proc = self._run(CONTROLLER_ID, CONTROLLER_FENCE, "workstreams/po03/control/leases/route-05.json")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_unreadable_policy_exits_two(self):
        proc = subprocess.run(
            [
                sys.executable, str(MODULE_PATH),
                "--path-ownership", str(self.root / "missing.json"),
                "--actor-id", "w", "--fence-token", "1", "--controller-fence-token", "1",
                "--owned-subtree", OWNED, "--target", "x",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, proc.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
