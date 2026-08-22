"""Permanent regression sentinel for a5-u07's finding: control_plane.py's
``cmd_lease`` pattern (``project_units()`` then ``append_event(...,
fence_token=...)``) is a two-phase, unlocked read-then-append. When two
concurrent lease attempts for the SAME unit interleave between those two
phases, both can compute the same "next" fence_token from the same stale
read and both append LEASED rows carrying that duplicate fence_token.

This test drives the REAL, unmodified, sandboxed control_plane.py (never
edited, never the shared coordinator ledger) through one concrete
known-colliding interleaving and one concrete known-safe (fully serial)
interleaving, and pins the CURRENTLY OBSERVED behavior of the live
mechanism for both:

* interleaved reads before either append -> fence-token collision (defect
  present today).
* fully serial (no interleaving) -> no collision.

This is a live, standing part of the gate (python3 -I -m unittest discover
-s workstreams/po03/tests). It exists so that if the coordinator patches
cmd_lease's race window, this test's first assertion starts failing loudly
(a deliberate, visible signal that the recorded defect was fixed and this
sentinel's expectation must be updated) instead of the fix going
unverified. It is a5-u07's second, independently-triggerable regression
asset alongside a5-u06's property-testing suite.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.dst_scheduler_u07 import run_schedule  # noqa: E402
from lib.lease_race_actors_u07 import (  # noqa: E402
    fence_collision_detected,
    lease_race_actor,
    seed_created_unit,
)
from lib.sandboxed_control_plane import load_sandboxed_control_plane  # noqa: E402


class TestLeaseRaceSentinel(unittest.TestCase):
    def _fresh_sandbox_with_unit(self, tmp_dir: str, unit_id: str):
        module = load_sandboxed_control_plane(Path(tmp_dir))
        seed_created_unit(module, unit_id)
        return module

    def test_interleaved_reads_before_either_append_currently_collide(self) -> None:
        unit_id = "sentinel-unit-interleaved"
        with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
            module = self._fresh_sandbox_with_unit(tmp, unit_id)
            out_a: dict = {}
            out_b: dict = {}
            actors = [
                lambda: lease_race_actor(module, unit_id, "worker-a", out_a),
                lambda: lease_race_actor(module, unit_id, "worker-b", out_b),
            ]
            # read(A), read(B), append(A), append(B): both actors read the
            # fence_token before either has appended its own LEASED row.
            run_schedule(actors, (0, 1, 0, 1))

            self.assertEqual(out_a["computed_fence"], out_b["computed_fence"])
            self.assertTrue(
                fence_collision_detected(module, unit_id),
                "expected the currently-live control_plane.py to exhibit a fence-token "
                "collision under this interleaving; if this now fails, the coordinator's "
                "cmd_lease race window has been closed and this sentinel should be updated "
                "to record the fix rather than deleted silently.",
            )

    def test_fully_serial_scheduling_never_collides(self) -> None:
        unit_id = "sentinel-unit-serial"
        with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
            module = self._fresh_sandbox_with_unit(tmp, unit_id)
            out_a: dict = {}
            out_b: dict = {}
            actors = [
                lambda: lease_race_actor(module, unit_id, "worker-a", out_a),
                lambda: lease_race_actor(module, unit_id, "worker-b", out_b),
            ]
            # A fully completes (read, append) before B starts at all.
            run_schedule(actors, (0, 0, 1, 1))

            self.assertNotEqual(out_a["computed_fence"], out_b["computed_fence"])
            self.assertFalse(fence_collision_detected(module, unit_id))


if __name__ == "__main__":
    unittest.main()
