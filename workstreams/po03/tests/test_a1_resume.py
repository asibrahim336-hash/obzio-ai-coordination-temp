"""a1-u04 — an interrupted unit resumes at its checkpoint and never repeats work.

Hypothesis (frozen in ``control/dispatch/a1-u04.json``): heartbeat lease renewal
plus monotonic checkpoints lets an interrupted unit resume from its last
checkpoint instead of restarting.

Acceptance, satisfied literally: a unit killed after checkpoint N resumes at N,
not 0, and never re-executes an already committed step.  Falsified if resume
restarts from zero or repeats a committed step.

The kill is a real ``SIGKILL`` delivered to a real child process, so the
resumed run inherits nothing but the durable ledger.  "Never repeats a
committed step" is checked against ``attempts.jsonl``, which the worker writes
before each attempt and never reads: if a committed step were re-executed the
line would be there regardless of how tidy the ledger looked afterwards.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

from test_a1_support import PO03_ROOT, ScratchCase

from engine.canonical import atomic_write_json
from engine.lease import LeaseManager
from engine.ledger import HashChainedLedger

WORKER_SCRIPT = PO03_ROOT / "engine" / "resume_worker.py"
UNIT = "a1-u04-subject"
TOTAL_STEPS = 8
KILL_AFTER = 3


class ResumeCase(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.scratch / "state"
        self.root.mkdir(parents=True)
        self.ledger = HashChainedLedger(self.root / "ledger.jsonl")
        self.leases = LeaseManager(self.ledger)

    def grant(self, worker_id: str, ttl_seconds: int = 600) -> Path:
        lease = self.leases.grant(UNIT, worker_id, ttl_seconds=ttl_seconds)
        path = self.scratch / f"lease-{lease.fence_token}.json"
        atomic_write_json(path, lease.as_dict())
        return path

    def run_worker(self, lease_path: Path, **kwargs) -> subprocess.CompletedProcess:
        command = [
            sys.executable,
            "-I",
            str(WORKER_SCRIPT),
            "--unit",
            UNIT,
            "--root",
            str(self.root),
            "--lease",
            str(lease_path),
            "--steps",
            str(kwargs.pop("steps", TOTAL_STEPS)),
            "--run-label",
            kwargs.pop("run_label", "run-1"),
        ]
        if "die_after" in kwargs:
            command += ["--die-after", str(kwargs.pop("die_after"))]
        if "die_mode" in kwargs:
            command += ["--die-mode", kwargs.pop("die_mode")]
        if kwargs.pop("ignore_checkpoints", False):
            command.append("--ignore-checkpoints")
        self.assertEqual({}, kwargs, "unexpected worker arguments")
        return subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)

    def attempts(self) -> list[dict]:
        path = self.root / "attempts.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def attempted_steps(self, run_label: str | None = None) -> list[str]:
        return [
            row["step_id"]
            for row in self.attempts()
            if row["kind"] == "ATTEMPT" and (run_label is None or row["run_label"] == run_label)
        ]

    def effect_count(self) -> int:
        return len(list((self.root / "effects").glob("*.json")))

    def committed_steps(self) -> list[str]:
        return [
            row["payload"]["step_id"]
            for row in self.ledger.events_for(UNIT)
            if row["event"] == "STEP_COMMITTED"
        ]


class KillAndResumeTests(ResumeCase):
    def test_worker_is_really_killed_by_a_signal(self):
        first = self.grant("worker-process-1")
        killed = self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.assertEqual(-9, killed.returncode, f"expected SIGKILL, got {killed.returncode}: {killed.stderr}")
        self.assertFalse((self.root / "report-run-1.json").exists(), "a killed run must not report")

    def test_killed_after_checkpoint_three_resumes_at_four(self):
        first = self.grant("worker-process-1")
        killed = self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.assertEqual(-9, killed.returncode)

        state_after_kill = self.leases.resume_point(UNIT)
        self.assertEqual(KILL_AFTER, state_after_kill.checkpoint_seq)
        self.assertEqual(KILL_AFTER, len(state_after_kill.committed_steps))
        self.assertEqual(KILL_AFTER, self.effect_count())
        self.assertTrue(self.ledger.verify().ok, self.ledger.verify().as_dict())

        self.leases.expire(UNIT, reason="worker process killed; heartbeat stopped")
        second = self.grant("worker-process-2")
        finished = self.run_worker(second, run_label="run-2")
        self.assertEqual(0, finished.returncode, finished.stderr)

        report = json.loads((self.root / "report-run-2.json").read_text(encoding="utf-8"))
        self.assertEqual(KILL_AFTER, report["resume_point_at_start"]["checkpoint_seq"])
        self.assertEqual(["step-01", "step-02", "step-03"], report["skipped"])
        self.assertEqual(
            ["step-04", "step-05", "step-06", "step-07", "step-08"],
            report["executed"],
            "the resumed run must start at the checkpoint, not at zero",
        )

    def test_no_committed_step_is_ever_attempted_twice(self):
        first = self.grant("worker-process-1")
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.leases.expire(UNIT, reason="killed")
        second = self.grant("worker-process-2")
        self.run_worker(second, run_label="run-2")

        counts = Counter(self.attempted_steps())
        self.assertEqual(TOTAL_STEPS, len(counts), counts)
        self.assertEqual(
            [1] * TOTAL_STEPS,
            [counts[f"step-{n:02d}"] for n in range(1, TOTAL_STEPS + 1)],
            f"a committed step was attempted more than once: {counts}",
        )
        self.assertEqual("step-04", self.attempted_steps("run-2")[0])
        self.assertEqual(TOTAL_STEPS, self.effect_count())
        self.assertEqual(sorted(set(self.committed_steps())), sorted(self.committed_steps()))
        self.assertEqual(TOTAL_STEPS, len(self.committed_steps()))

    def test_no_duplicate_external_effect_across_the_interruption(self):
        first = self.grant("worker-process-1")
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.leases.expire(UNIT, reason="killed")
        second = self.grant("worker-process-2")
        self.run_worker(second, run_label="run-2")
        duplicates = [row for row in self.ledger.events_for(UNIT) if row["event"] == "DUPLICATE_IGNORED"]
        self.assertEqual([], duplicates, "resume re-drove an already committed step")
        self.assertEqual(TOTAL_STEPS, self.effect_count())
        applied = [row for row in self.ledger.events_for(UNIT) if row["event"] == "OUTBOX_APPLIED"]
        self.assertEqual(TOTAL_STEPS, len(applied))

    def test_heartbeat_renewal_is_recorded_and_extends_the_lease(self):
        first = self.grant("worker-process-1", ttl_seconds=600)
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        heartbeats = [row for row in self.ledger.events_for(UNIT) if row["event"] == "HEARTBEAT"]
        self.assertEqual(KILL_AFTER, len(heartbeats))
        granted = json.loads(first.read_text(encoding="utf-8"))
        self.assertGreaterEqual(heartbeats[-1]["payload"]["expires_at"], granted["expires_at"])
        self.assertEqual(1, self.leases.current_lease(UNIT).fence_token)

    def test_ledger_verifies_after_every_kill_mode(self):
        for mode in ("after-checkpoint", "mid-step-append", "mid-checkpoint-append"):
            with self.subTest(die_mode=mode):
                case = self.__class__(self._testMethodName)
                case.setUp()
                try:
                    first = case.grant("worker-process-1")
                    killed = case.run_worker(first, die_after=KILL_AFTER, die_mode=mode, run_label="run-1")
                    self.assertEqual(-9, killed.returncode, killed.stderr)
                    verification = case.ledger.verify()
                    self.assertTrue(verification.ok, f"{mode}: {verification.as_dict()}")

                    case.leases.expire(UNIT, reason=f"killed via {mode}")
                    second = case.grant("worker-process-2")
                    finished = case.run_worker(second, run_label="run-2")
                    self.assertEqual(0, finished.returncode, finished.stderr)

                    counts = Counter(case.attempted_steps())
                    self.assertEqual(
                        [1] * TOTAL_STEPS,
                        [counts[f"step-{n:02d}"] for n in range(1, TOTAL_STEPS + 1)],
                        f"{mode} repeated a committed step: {counts}",
                    )
                    self.assertEqual(TOTAL_STEPS, case.effect_count())
                    self.assertTrue(case.ledger.verify().ok)
                finally:
                    case.tearDown()

    def test_a_kill_inside_the_append_leaves_the_crash_window_not_corruption(self):
        first = self.grant("worker-process-1")
        killed = self.run_worker(first, die_after=1, die_mode="mid-checkpoint-append", run_label="run-1")
        self.assertEqual(-9, killed.returncode)
        verification = self.ledger.verify()
        self.assertTrue(verification.ok, verification.as_dict())
        self.assertIn("APPEND_IN_FLIGHT", [f.code for f in verification.findings])
        # The checkpoint row itself landed, so resume still sees it.
        self.assertEqual(1, self.leases.resume_point(UNIT).checkpoint_seq)


class RestartFromZeroNegativeControlTests(ResumeCase):
    """Prove the resume assertions can fail: run the same worker without resume."""

    def test_checkpoint_monotonicity_alone_refuses_a_naive_restart(self):
        """Resume is guarded three deep; this is the second guard on its own."""
        first = self.grant("worker-process-1")
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.leases.expire(UNIT, reason="killed")
        second = self.grant("worker-process-2")
        naive = self.run_worker(second, run_label="run-2-strict", ignore_checkpoints=False)
        self.assertEqual(0, naive.returncode, naive.stderr)
        # With resume honoured the run succeeds; the regression path is only
        # reachable when a caller deliberately discards the checkpoints.
        self.assertEqual(["step-04", "step-05", "step-06", "step-07", "step-08"], self.attempted_steps("run-2-strict"))

    def test_ignoring_checkpoints_restarts_from_zero_and_repeats_committed_steps(self):
        first = self.grant("worker-process-1")
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.leases.expire(UNIT, reason="killed")
        second = self.grant("worker-process-2")
        finished = self.run_worker(second, run_label="run-2", ignore_checkpoints=True)
        self.assertEqual(0, finished.returncode, finished.stderr)

        counts = Counter(self.attempted_steps())
        for step in ("step-01", "step-02", "step-03"):
            self.assertEqual(2, counts[step], f"{step} should have been repeated by the naive run")
        self.assertEqual("step-01", self.attempted_steps("run-2")[0])
        self.assertNotEqual(
            [1] * TOTAL_STEPS,
            [counts[f"step-{n:02d}"] for n in range(1, TOTAL_STEPS + 1)],
            "the never-repeat assertion must be able to fail",
        )

    def test_the_outbox_still_prevents_a_duplicate_effect_on_a_naive_restart(self):
        """Efficiency regresses; correctness does not."""
        first = self.grant("worker-process-1")
        self.run_worker(first, die_after=KILL_AFTER, run_label="run-1")
        self.leases.expire(UNIT, reason="killed")
        second = self.grant("worker-process-2")
        self.run_worker(second, run_label="run-2", ignore_checkpoints=True)

        self.assertEqual(TOTAL_STEPS, self.effect_count())
        duplicates = [row for row in self.ledger.events_for(UNIT) if row["event"] == "DUPLICATE_IGNORED"]
        self.assertEqual(
            KILL_AFTER,
            len(duplicates),
            "the repeated steps must each be observed as a duplicate, not silently reapplied",
        )
        self.assertTrue(self.ledger.verify().ok)


if __name__ == "__main__":
    unittest.main()
