#!/usr/bin/env python3
"""a5-u12 recurrence probe for a5-u07's mechanism change.

Deliberately side-effect-free (no record_reproduction, no
research/output/a5-u07-result.json write), so it can be invoked repeatedly
as a genuinely fresh subprocess with a caller-chosen --seed for recurrence
testing without mutating the original, already-committed a5-u07 evidence.
Replicates the identical core comparison against the real, sandboxed
control_plane.py lease-granting pattern and prints only a JSON measurement
to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.dst_scheduler_u07 import (  # noqa: E402
    multinomial_space_size,
    run_schedule,
    seeded_random_interleavings,
    sequential_orderings,
)
from lib.lease_race_actors_u07 import (  # noqa: E402
    fence_collision_detected,
    lease_race_actor,
    seed_created_unit,
)
from lib.sandboxed_control_plane import load_sandboxed_control_plane  # noqa: E402


def run_one_schedule(num_actors: int, schedule: tuple[int, ...]) -> bool:
    unit_id = "recurrence-fleet-unit"
    with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
        module = load_sandboxed_control_plane(Path(tmp))
        seed_created_unit(module, unit_id)
        outs = [dict() for _ in range(num_actors)]
        actors = [(lambda i=i: lease_race_actor(module, unit_id, f"worker-{i}", outs[i])) for i in range(num_actors)]
        run_schedule(actors, schedule)
        return fence_collision_detected(module, unit_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--sample-size", type=int, default=300)
    args = parser.parse_args()

    seq_counts = [2, 2, 2, 2]
    seq_schedules = sequential_orderings(seq_counts)
    seq_violations = sum(1 for s in seq_schedules if run_one_schedule(len(seq_counts), s))

    dst_counts = [2, 2, 2, 2, 2]
    dst_space_size = multinomial_space_size(dst_counts)
    dst_schedules = seeded_random_interleavings(dst_counts, seed=args.seed, count=args.sample_size)
    dst_violations = sum(1 for s in dst_schedules if run_one_schedule(len(dst_counts), s))

    measurement = {
        "seed": args.seed,
        "sequential_explored": len(seq_schedules),
        "sequential_violations_found": seq_violations,
        "dst_space_size": dst_space_size,
        "dst_explored": len(dst_schedules),
        "dst_violations_found": dst_violations,
    }
    print(json.dumps(measurement))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
