#!/usr/bin/env python3
"""a5-u11 reproduction: does structured hypothesis registration before
execution raise the research-to-mechanism conversion rate?

Two, clearly separated pieces of evidence, both with an explicit
denominator (per the frozen falsified_if clause):

1. ``real_a5_anecdote`` -- THIS worker's own real, registered-before-
   reproduction hypotheses within this wave (workstreams/po03/research/
   hypotheses.jsonl and reproduction-ledger.jsonl, read directly, not
   re-typed). Small sample (n <= 12), genuine, not simulated; reported as
   an anecdote, not as the whole case.

2. ``registered_vs_unregistered_model`` -- both arms actually executed
   against the SAME seeded pool of 1000 candidate hypotheses (see
   lib/conversion_rate_simulation_u11.py for the full, explicit model and
   calibration constants). This is the primary, adequately-powered,
   two-arm comparison the acceptance criterion requires.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.conversion_rate_simulation_u11 import (  # noqa: E402
    REGISTERED_INCONCLUSIVE_RATE,
    REGISTERED_WRONG_RATE,
    UNREGISTERED_ACCURACY,
    UNREGISTERED_ATTEMPT_RATE,
    generate_candidates,
    registered_pipeline,
    run_pipeline_over_pool,
    unregistered_pipeline,
)
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u11-result.json"
HYPOTHESES_PATH = RESEARCH_ROOT / "hypotheses.jsonl"
REPRODUCTION_LEDGER_PATH = RESEARCH_ROOT / "reproduction-ledger.jsonl"
SEED = 20260822
POOL_SIZE = 1000


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def real_a5_anecdote() -> dict:
    hypotheses = load_jsonl(HYPOTHESES_PATH)
    reproductions = load_jsonl(REPRODUCTION_LEDGER_PATH)
    all_registered_before = all(h["registered_before_reproduction"] is True for h in hypotheses)
    outcomes_by_unit = {r["unit_id"]: r["reproduction"]["outcome"] for r in reproductions}
    decisive_outcomes = {"SUPPORTED", "REJECTED", "PARTIALLY_SUPPORTED"}
    decisive_count = sum(1 for o in outcomes_by_unit.values() if o in decisive_outcomes)
    return {
        "hypotheses_registered": len(hypotheses),
        "all_registered_before_reproduction": all_registered_before,
        "reproductions_executed_so_far": len(outcomes_by_unit),
        "outcomes_by_unit": outcomes_by_unit,
        "decisive_count": decisive_count,
        "conversion_rate": decisive_count / len(outcomes_by_unit) if outcomes_by_unit else None,
        "note": "n is small (<=12) and every one of this worker's hypotheses is registered (there is no "
        "internal unregistered comparison group in this worker's own real work); reported as a real, "
        "directional anecdote, not as the two-arm comparison itself.",
    }


def main() -> int:
    anecdote = real_a5_anecdote()

    pool = generate_candidates(seed=SEED, n=POOL_SIZE)
    registered = run_pipeline_over_pool(pool, registered_pipeline, seed=1)
    unregistered = run_pipeline_over_pool(pool, unregistered_pipeline, seed=2)

    ground_truth_counts = {}
    for c in pool:
        ground_truth_counts[c.ground_truth] = ground_truth_counts.get(c.ground_truth, 0) + 1

    measurement = {
        "real_a5_anecdote": anecdote,
        "registered_vs_unregistered_model": {
            "seed": SEED,
            "pool_size": POOL_SIZE,
            "ground_truth_distribution_realized": ground_truth_counts,
            "model_parameters": {
                "registered_inconclusive_rate": REGISTERED_INCONCLUSIVE_RATE,
                "registered_wrong_rate": REGISTERED_WRONG_RATE,
                "unregistered_attempt_rate": UNREGISTERED_ATTEMPT_RATE,
                "unregistered_accuracy": UNREGISTERED_ACCURACY,
            },
            "registered": registered,
            "unregistered": unregistered,
        },
    }

    conversion_gap = registered["conversion_rate"] - unregistered["conversion_rate"]
    correctness_gap = registered["correct_rate_given_decisive"] - unregistered["correct_rate_given_decisive"]
    outcome = "SUPPORTED" if conversion_gap > 0 and correctness_gap > 0 else "REJECTED"

    rationale = (
        f"Both pipelines actually executed against the SAME seed={SEED} pool of {POOL_SIZE} candidate "
        f"hypotheses ({ground_truth_counts}). Registered conversion (decisive SUPPORTED/REJECTED) rate = "
        f"{registered['conversion_rate']:.3f} ({registered['decisive_count']}/{registered['n']}); unregistered = "
        f"{unregistered['conversion_rate']:.3f} ({unregistered['decisive_count']}/{unregistered['n']}) -- a gap of "
        f"{conversion_gap:.3f}. Critically, raw conversion rate alone is not the whole story: of decisive "
        f"verdicts, registered is correct {registered['correct_rate_given_decisive']:.3f} of the time versus "
        f"{unregistered['correct_rate_given_decisive']:.3f} for unregistered, and unregistered produced "
        f"{unregistered['spurious_decisive_on_ambiguous_count']} spurious decisive verdicts on genuinely "
        f"AMBIGUOUS candidates versus {registered['spurious_decisive_on_ambiguous_count']} for registered "
        "(which never forces a verdict onto an unresolvable claim, by construction, matching this worker's "
        "own real a5-u09 NOT_YET outcome). As real, small-sample (n="
        f"{anecdote['reproductions_executed_so_far']}) supplementary context, this worker's own hypotheses -- "
        f"100% registered before reproduction -- reached a decisive outcome "
        f"{anecdote['decisive_count']}/{anecdote['reproductions_executed_so_far']} of the time "
        f"({anecdote['conversion_rate']:.3f} if computed); there is no internal unregistered comparison group "
        "in this worker's own real work, so this anecdote is directional context, not the two-arm comparison "
        "itself."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u11",
        reproduction_id="a5-u11-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u11_conversion_rate.py",
        arms=["registered_pipeline", "unregistered_pipeline"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u11-result.json",
            "workstreams/po03/research/lib/conversion_rate_simulation_u11.py",
            "workstreams/po03/tests/test_a5_conversion_rate_simulation_u11.py",
        ],
        limitations=[
            "The registered_vs_unregistered_model is a documented, explicitly-calibrated model of the "
            "claimed causal mechanism (like a5-u05's criteria_arms and a5-u08's TTL simulation), not a "
            "literal replay of external researchers' real ad hoc work; its accuracy and attempt-rate "
            "constants are stated assumptions, not measured externally.",
            "The real_a5_anecdote has a small denominator (n<=12) and no internal unregistered comparison "
            "arm, so it cannot by itself establish a rate difference; it is reported as directional context "
            "only, per the instruction never to assert conversion without a denominator.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
