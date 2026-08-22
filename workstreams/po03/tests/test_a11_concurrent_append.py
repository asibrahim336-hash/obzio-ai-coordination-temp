"""a11-u02 recurrence tests: the append path is serialised across processes.

Frozen hypothesis (dispatch a11-u02): "append_event performs an unlocked
read-verify-append, so concurrent appends assign duplicate sequence numbers and
break the hash chain."  Cohort a2 measured 200 of 200 violating interleavings.

The acceptance contract asks for at least 200 concurrent append interleavings
from *separate processes*, so this test spawns real interpreters rather than
threads: a threading test would be satisfied by the GIL in places where two
processes are not.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import test_a11_support as support

APPENDERS = 10
APPENDS_EACH = 20
TOTAL_APPENDS = APPENDERS * APPENDS_EACH

WORKER_SOURCE = '''
import importlib.util
import json
import sys
import time
from pathlib import Path

module_path, control_dir, unit_id, worker_index, count, go_file = sys.argv[1:7]
spec = importlib.util.spec_from_file_location("cp_child", module_path)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

control = Path(control_dir)
cp.LEDGER_PATH = control / "events" / "ledger.jsonl"
cp.REGISTRY_PATH = control / "work-unit-registry.jsonl"
cp.RECOVERY_PATH = control / "recovery-state.json"
cp.DISPATCH_DIR = control / "dispatch"
cp.PATH_OWNERSHIP_PATH = control / "path-ownership.json"

# Every appender waits on the same file so the writes actually collide instead
# of being serialised by process start-up latency.
deadline = time.monotonic() + 30
while not Path(go_file).exists():
    if time.monotonic() > deadline:
        raise SystemExit("start barrier never opened")
    time.sleep(0.001)

failures = []
for index in range(int(count)):
    try:
        cp.append_event(
            unit_id,
            "CHECKPOINTED",
            actor="po03-worker-a11test",
            fence_token=1,
            payload={"checkpoint_seq": index + 1, "appender": int(worker_index)},
        )
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")
print(json.dumps({"appender": int(worker_index), "failures": failures}))
'''


class MultiProcessAppendTests(support.ControlPlaneHarness):
    """200 concurrent appends from separate processes must not corrupt the chain."""

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")
        self.worker = self.base / "appender.py"
        self.worker.write_text(WORKER_SOURCE, encoding="utf-8")

    def _run_appenders(self, appenders: int = APPENDERS, each: int = APPENDS_EACH) -> list[dict]:
        go = self.base / "go"
        procs = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(self.worker),
                    str(support.CONTROL_PLANE_PATH),
                    str(self.control),
                    "h-u01",
                    str(index),
                    str(each),
                    str(go),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(appenders)
        ]
        time.sleep(0.3)  # let every child reach the barrier before opening it
        go.write_text("go", encoding="utf-8")
        reports = []
        for proc in procs:
            out, err = proc.communicate(timeout=180)
            self.assertEqual(0, proc.returncode, f"appender crashed: {err}")
            reports.append(json.loads(out.strip().splitlines()[-1]))
        return reports

    def test_two_hundred_concurrent_appends_keep_the_chain_intact(self):
        if support.LOCK_MECHANISM_EXPECTED is None:
            self.skipTest("advisory locking is NOT_SUPPORTED on this platform")
        reports = self._run_appenders()
        failures = [item for report in reports for item in report["failures"]]
        self.assertEqual([], failures, "no appender may be turned away")

        rows = self.cp.ledger_rows()
        appended = [row for row in rows if row["event"] == "CHECKPOINTED"]
        self.assertEqual(TOTAL_APPENDS, len(appended))

        sequences = [row["seq"] for row in rows]
        self.assertEqual(len(sequences), len(set(sequences)), "sequence numbers must be unique")
        self.assertEqual(list(range(1, len(rows) + 1)), sequences, "sequence numbers must be monotonic")
        self.assertEqual([], self.cp.verify_chain(rows), "the hash chain must verify")

        # Every appender's work survived: no write was silently lost to a race.
        by_appender: dict[int, int] = {}
        for row in appended:
            by_appender[row["payload"]["appender"]] = by_appender.get(row["payload"]["appender"], 0) + 1
        self.assertEqual({index: APPENDS_EACH for index in range(APPENDERS)}, by_appender)

    def test_no_row_is_ever_partially_written(self):
        """A torn line would be a corrupt ledger row, not merely a lost append."""
        if support.LOCK_MECHANISM_EXPECTED is None:
            self.skipTest("advisory locking is NOT_SUPPORTED on this platform")
        self._run_appenders(appenders=8, each=5)
        text = self.cp.LEDGER_PATH.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        for line in text.splitlines():
            json.loads(line)  # raises if any line was interleaved mid-write


class LockContractTests(support.ControlPlaneHarness):
    """The bounded wait and its timeout behaviour are part of the contract."""

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01")

    def test_the_platform_lock_mechanism_is_named_not_assumed(self):
        self.assertIn(self.cp.LOCK_MECHANISM, ("fcntl.flock", "msvcrt.locking", "NOT_SUPPORTED"))
        if self.cp.LOCK_MECHANISM == "NOT_SUPPORTED":
            with self.assertRaises(self.cp.LedgerLockUnavailable):
                self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER, fence_token=1)

    @staticmethod
    def _reap(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

    def test_a_held_lock_makes_the_append_fail_rather_than_race(self):
        if self.cp.LOCK_MECHANISM == "NOT_SUPPORTED":
            self.skipTest("advisory locking is NOT_SUPPORTED on this platform")
        holder = self.base / "holder.py"
        holder.write_text(
            "import importlib.util, sys, time\n"
            "from pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('cp_hold', sys.argv[1])\n"
            "cp = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(cp)\n"
            "cp.LEDGER_PATH = Path(sys.argv[2]) / 'events' / 'ledger.jsonl'\n"
            "with cp.ledger_lock():\n"
            "    Path(sys.argv[3]).write_text('held')\n"
            "    time.sleep(float(sys.argv[4]))\n",
            encoding="utf-8",
        )
        held = self.base / "held"
        proc = subprocess.Popen(
            [sys.executable, "-I", str(holder), str(support.CONTROL_PLANE_PATH), str(self.control),
             str(held), "5"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self._reap, proc)
        deadline = time.monotonic() + 30
        while not held.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(held.exists(), "holder process never took the lock")
        started = time.monotonic()
        with self.assertRaises(self.cp.LedgerLockUnavailable) as ctx:
            with self.cp.ledger_lock(timeout=0.5):
                pass
        waited = time.monotonic() - started
        self.assertIn("refusing to append without exclusion", str(ctx.exception))
        self.assertGreaterEqual(waited, 0.4, "the wait must be bounded, not instant")
        self.assertLess(waited, 5.0, "the wait must be bounded, not indefinite")

    def test_the_lock_is_reentrant_within_one_thread(self):
        """ingest_result holds the lock across its dedupe check and its append."""
        if self.cp.LOCK_MECHANISM == "NOT_SUPPORTED":
            self.skipTest("advisory locking is NOT_SUPPORTED on this platform")
        with self.cp.ledger_lock():
            self.cp.append_event("h-u01", "RUNNING", actor=support.OWNER, fence_token=1)
        self.assertEqual("RUNNING", self.state_of("h-u01"))

    def test_lock_file_is_not_the_ledger(self):
        """The lock must not be taken on the append target itself."""
        self.assertNotEqual(self.cp.lock_path(), self.cp.LEDGER_PATH)


if __name__ == "__main__":
    unittest.main()
