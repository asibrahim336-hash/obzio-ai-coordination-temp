#!/usr/bin/env python3
"""a5-u12 recurrence probe for a5-u06's mechanism change.

Deliberately side-effect-free: unlike run_u06_mutation_testing.py, this
script never calls record_reproduction and never writes
research/output/a5-u06-result.json, so it can be invoked repeatedly (as a
genuinely fresh subprocess, with a caller-chosen --seed) for recurrence
testing without mutating the original, already-committed a5-u06 evidence.
It replicates the identical core comparison (real, unmutated
validate_contracts.py source, mutated in memory only, run through both the
existing example-based suite and the property harness) and prints only a
JSON measurement to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.mutation_engine_u06 import (  # noqa: E402
    MUTANTS,
    apply_mutant,
    load_module_from_source,
    read_real_source,
    run_existing_suite_against_module,
)
from lib.property_harness_u06 import run_all_properties  # noqa: E402


def property_harness_killed(module, seed: int) -> bool:
    report = run_all_properties(module.validate_result, seed=seed, trials_per_property=60)
    return any(not prop["passed"] for prop in report.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260822)
    args = parser.parse_args()

    real_source = read_real_source()
    per_mutant = []
    existing_missed_property_caught = 0

    for mutant in MUTANTS:
        mutated_source = apply_mutant(real_source, mutant)
        module = load_module_from_source(mutated_source, f"recurrence-mutant-{mutant['id']}")
        existing_result = run_existing_suite_against_module(module)
        existing_killed = existing_result["killed"]
        property_killed = property_harness_killed(module, args.seed)
        if not existing_killed and property_killed:
            existing_missed_property_caught += 1
        per_mutant.append(
            {"mutant_id": mutant["id"], "existing_suite_killed": existing_killed, "property_harness_killed": property_killed}
        )

    measurement = {
        "seed": args.seed,
        "total_mutants": len(MUTANTS),
        "existing_missed_property_caught_count": existing_missed_property_caught,
        "per_mutant": per_mutant,
    }
    print(json.dumps(measurement))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
