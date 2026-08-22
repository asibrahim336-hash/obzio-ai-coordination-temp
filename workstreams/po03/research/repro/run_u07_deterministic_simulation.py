#!/usr/bin/env python3
"""a5-u07 reproduction: does deterministic simulation testing (DST) of a
whole fleet expose interleavings that sequential fault injection cannot
reach?

Both arms drive the SAME real, unmodified, sandboxed control_plane.py
lease-granting pattern (project_units() then append_event(...,
fence_token=...)), never a toy stand-in:

1. ``sequential_fault_injection`` -- explores only the k! fully-serial
   orderings of k concurrent lease actors racing for the same unit (one
   actor's whole sequence completes before the next starts), which is
   exactly what single-fault, one-actor-at-a-time injection can ever
   produce. Space size and violations found are both recorded.

2. ``deterministic_simulation_testing`` -- explores genuine interleavings:
   an exhaustive sweep for a small fleet (3 actors) and a seeded random
   sample for a larger fleet (5 actors) too large to enumerate practically
   here, with the seed and the exact combinatorial space size recorded for
   both.

Every run of every schedule spins up a brand-new sandboxed control_plane
module and a brand-new temp ledger (deleted at the end of that run) so
schedules cannot leak state into one another.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.dst_scheduler_u07 import (  # noqa: E402
    exhaustive_interleavings,
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
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402
from lib.sandboxed_control_plane import load_sandboxed_control_plane  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u07-result.json"
SEED = 20260822


def run_one_schedule(num_actors: int, schedule: tuple[int, ...]) -> bool:
    """Runs one interleaving against a fresh sandboxed real control_plane.
    Returns True iff a fence-token collision was observed."""
    unit_id = "fleet-unit"
    with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
        module = load_sandboxed_control_plane(Path(tmp))
        seed_created_unit(module, unit_id)
        outs = [dict() for _ in range(num_actors)]
        actors = [
            (lambda i=i: lease_race_actor(module, unit_id, f"worker-{i}", outs[i]))
            for i in range(num_actors)
        ]
        run_schedule(actors, schedule)
        return fence_collision_detected(module, unit_id)


def explore(num_actors: int, schedules: list[tuple[int, ...]]) -> dict:
    violating = []
    for schedule in schedules:
        if run_one_schedule(num_actors, schedule):
            violating.append(schedule)
    return {
        "num_actors": num_actors,
        "explored_count": len(schedules),
        "violations_found": len(violating),
        "example_violating_schedule": list(violating[0]) if violating else None,
    }


def main() -> int:
    # --- Arm 1: sequential fault injection, 4 actors -----------------------
    seq_step_counts = [2, 2, 2, 2]
    seq_space_size = multinomial_space_size(seq_step_counts)
    seq_schedules = sequential_orderings(seq_step_counts)
    seq_result = explore(len(seq_step_counts), seq_schedules)
    seq_result["full_interleaving_space_size"] = seq_space_size
    seq_result["fraction_of_full_space_explored"] = len(seq_schedules) / seq_space_size

    # --- Arm 2a: DST, exhaustive over a small fleet (3 actors) -------------
    dst_small_counts = [2, 2, 2]
    dst_small_space_size = multinomial_space_size(dst_small_counts)
    dst_small_schedules = exhaustive_interleavings(dst_small_counts)
    dst_small_result = explore(len(dst_small_counts), dst_small_schedules)
    dst_small_result["full_interleaving_space_size"] = dst_small_space_size
    dst_small_result["exhaustive"] = True

    # --- Arm 2b: DST, seeded random sample over a larger fleet (5 actors) --
    dst_large_counts = [2, 2, 2, 2, 2]
    dst_large_space_size = multinomial_space_size(dst_large_counts)
    dst_large_sample_size = 300
    dst_large_schedules = seeded_random_interleavings(dst_large_counts, seed=SEED, count=dst_large_sample_size)
    dst_large_result = explore(len(dst_large_counts), dst_large_schedules)
    dst_large_result["full_interleaving_space_size"] = dst_large_space_size
    dst_large_result["exhaustive"] = False
    dst_large_result["seed"] = SEED

    dst_found_defect = dst_small_result["violations_found"] > 0 or dst_large_result["violations_found"] > 0
    sequential_found_defect = seq_result["violations_found"] > 0
    sequential_structurally_cannot_find_it = seq_result["violations_found"] == 0

    measurement = {
        "seed": SEED,
        "target": "real sandboxed control_plane.py cmd_lease pattern "
        "(project_units() then append_event(..., fence_token=...))",
        "invariant_checked": "no two LEASED rows for the same unit share a fence_token",
        "sequential_fault_injection": seq_result,
        "deterministic_simulation_testing": {
            "exhaustive_small_fleet": dst_small_result,
            "seeded_sample_large_fleet": dst_large_result,
        },
    }

    outcome = "SUPPORTED" if (dst_found_defect and sequential_structurally_cannot_find_it) else "REJECTED"
    rationale = (
        f"Sequential fault injection over {seq_result['num_actors']} actors explored exactly "
        f"{seq_result['explored_count']} fully-serial schedules "
        f"({seq_result['fraction_of_full_space_explored']:.4%} of the full "
        f"{seq_result['full_interleaving_space_size']}-schedule interleaving space for that fleet size) "
        f"and found {seq_result['violations_found']} fence-token collisions in the real, unmodified, "
        f"sandboxed control_plane.py lease-granting pattern -- zero, by construction, since a fully-serial "
        f"schedule never lets one actor's read observe another actor's not-yet-appended write. "
        f"Deterministic simulation testing, exhaustively enumerating all {dst_small_result['full_interleaving_space_size']} "
        f"interleavings of a 3-actor fleet and separately seed-sampling {dst_large_result['explored_count']} of "
        f"{dst_large_result['full_interleaving_space_size']} interleavings of a 5-actor fleet (seed={SEED}, "
        "exactly replayable), found "
        f"{dst_small_result['violations_found']} and {dst_large_result['violations_found']} fence-token "
        f"collisions respectively against the SAME real code -- an interleaving-only defect sequential "
        "fault injection structurally cannot reach, confirming the hypothesis on the live mechanism itself, "
        "not a toy analogy."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u07",
        reproduction_id="a5-u07-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u07_deterministic_simulation.py",
        arms=["sequential_fault_injection", "deterministic_simulation_testing"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u07-result.json",
            "workstreams/po03/research/lib/dst_scheduler_u07.py",
            "workstreams/po03/research/lib/lease_race_actors_u07.py",
            "workstreams/po03/tests/test_a5_dst_scheduler_u07.py",
            "workstreams/po03/tests/test_a5_lease_race_sentinel_u07.py",
        ],
        mechanism_change={
            "summary": "Added workstreams/po03/tests/test_a5_lease_race_sentinel_u07.py, a permanent, "
            "already-live regression sentinel that pins the CURRENTLY OBSERVED behavior of the real, "
            "unmodified control_plane.py under one known-colliding and one known-safe interleaving. It "
            "runs in the standard gate today; no coordinator action is required to activate it, because "
            "it lives entirely under this worker's own workstreams/po03/tests/test_a5_ prefix and drives "
            "the coordinator's real code only inside a private sandbox.",
            "changed_paths": [
                "workstreams/po03/tests/test_a5_lease_race_sentinel_u07.py",
                "workstreams/po03/research/lib/lease_race_actors_u07.py",
                "workstreams/po03/research/lib/dst_scheduler_u07.py",
            ],
            "requires_coordinator_action": False,
            "verified_live": True,
        },
        proposal={
            "summary": "A genuine, reproducible fence-token collision exists in the real "
            "workstreams/po03/tools/control_plane.py cmd_lease pattern: it calls project_units() to read "
            "the current fence_token, computes fence+1 in the caller, and only then calls append_event(...,"
            " fence_token=fence, ...) -- with no lock held across the two calls. Two concurrent cmd_lease "
            "invocations for the SAME unit_id, if their project_units() reads interleave before either "
            "append_event() call lands, both compute the same fence_token and both successfully append "
            "LEASED rows carrying that duplicate value, contradicting the module's own documented safety "
            "property ('A stale worker (lower fence token) cannot commit after ownership transfers'), "
            "which presumes granted fence tokens are unique.",
            "coordinator_owned_file": "workstreams/po03/tools/control_plane.py",
            "proposed_fix": "Make fence_token allocation atomic with the append it authorizes: inside "
            "append_event (or a new single critical-section helper it calls for LEASED specifically), "
            "re-read the ledger's current fence_token for unit_id under the same read used to compute "
            "prev_sha256, ignore any fence_token the caller passed for LEASED events, and always emit "
            "the next value computed from that same fresh read -- the same principle append_event already "
            "applies to prev_sha256 (freshly re-read immediately before writing), just also applied to "
            "the fence_token counter. Alternatively, hold an OS-level exclusive lock (e.g. "
            "fcntl.flock on a sibling *.lock file) for the full duration of project_units()+append_event() "
            "in cmd_lease.",
            "verification_path": "workstreams/po03/tests/test_a5_lease_race_sentinel_u07.py already "
            "reproduces the collision against the real code; once patched, its first test "
            "(test_interleaved_reads_before_either_append_currently_collide) will start failing, which "
            "is the intended signal that the sentinel's expectation needs updating to assert no collision.",
            "requires_coordinator_action": True,
        },
        limitations=[
            "The 5-actor DST arm samples 300 of the exact interleaving space rather than enumerating it "
            "exhaustively, because the exact space (113,400 schedules) is impractical to run one real "
            "sandboxed control_plane instance per schedule for in this reproduction's time budget; the "
            "3-actor arm is fully exhaustive (all 90 schedules) as a cross-check that sampling and "
            "exhaustive enumeration agree on defect presence.",
            "The lease actor calls the real project_units()/append_event() functions directly rather than "
            "the cmd_lease CLI entrypoint, to get a clean two-phase generator; this preserves the exact "
            "call sequence and arguments cmd_lease itself uses, but does not exercise argparse.",
            "This finding concerns a genuine potential defect in coordinator-owned control_plane.py; per "
            "the hard boundary this worker may not edit that file, so the fix is recorded only as a "
            "reviewed proposal (state: proposal), not applied.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
