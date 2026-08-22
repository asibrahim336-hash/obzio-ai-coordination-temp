#!/usr/bin/env python3
"""a5-u05 reproduction: preregistered vs post-hoc acceptance criteria.

Both arms are run against the identical five buggy candidate implementations
of the same spec. The preregistered suite is derived once from the written
spec, before any candidate is inspected. The post-hoc suite is derived, for
each candidate separately, from that candidate's own output on a small
happy-path sample -- modelling a reviewer who writes checks by watching the
code run rather than from the spec.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.criteria_arms_u05 import (  # noqa: E402
    BOUNDARY_INPUT_FOR_DEFECT,
    CANDIDATE_IMPLEMENTATIONS,
    POST_HOC_HAPPY_PATH_SAMPLE,
    PREREGISTERED_SUITE,
    SPEC_TEXT,
    generate_post_hoc_suite,
    run_post_hoc_suite_against_spec,
    run_preregistered_suite,
)
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u05-result.json"


def main() -> int:
    per_candidate = {}
    prereg_escaped = 0
    posthoc_escaped = 0
    for name, fn in CANDIDATE_IMPLEMENTATIONS.items():
        prereg_failures = run_preregistered_suite(fn)
        posthoc_oracle = generate_post_hoc_suite(fn)
        posthoc_failures = run_post_hoc_suite_against_spec(posthoc_oracle)
        prereg_caught = len(prereg_failures) > 0
        posthoc_caught = len(posthoc_failures) > 0
        if not prereg_caught:
            prereg_escaped += 1
        if not posthoc_caught:
            posthoc_escaped += 1
        per_candidate[name] = {
            "boundary_input": BOUNDARY_INPUT_FOR_DEFECT[name],
            "preregistered_caught_defect": prereg_caught,
            "preregistered_failing_cases": prereg_failures,
            "post_hoc_caught_defect": posthoc_caught,
            "post_hoc_oracle": posthoc_oracle,
        }

    total = len(CANDIDATE_IMPLEMENTATIONS)
    measurement = {
        "spec_text": SPEC_TEXT,
        "preregistered_suite_inputs": PREREGISTERED_SUITE,
        "post_hoc_happy_path_sample": POST_HOC_HAPPY_PATH_SAMPLE,
        "candidates": total,
        "preregistered_escaped_defects": prereg_escaped,
        "post_hoc_escaped_defects": posthoc_escaped,
        "preregistered_escape_rate": prereg_escaped / total,
        "post_hoc_escape_rate": posthoc_escaped / total,
        "per_candidate": per_candidate,
    }

    both_arms_measured = True
    preregistered_strictly_better = prereg_escaped < posthoc_escaped
    outcome = "SUPPORTED" if both_arms_measured and preregistered_strictly_better else "REJECTED"
    rationale = (
        f"Across {total} candidate implementations of the same written spec, each seeded with exactly "
        f"one boundary-condition defect, the preregistered suite (derived once from the spec before any "
        f"candidate was inspected) caught {total - prereg_escaped}/{total} defects "
        f"({prereg_escaped} escaped). The post-hoc suite (derived per-candidate from that candidate's own "
        f"output on a fixed happy-path sample that never touches the violated boundary) caught "
        f"{total - posthoc_escaped}/{total} defects ({posthoc_escaped} escaped). Both arms were run "
        f"against every candidate; the escape-rate gap ({prereg_escaped}/{total} vs {posthoc_escaped}/{total}) "
        f"is the measured effect, not an assumed one."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u05",
        reproduction_id="a5-u05-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u05_preregistered_criteria.py",
        arms=["preregistered_criteria", "post_hoc_criteria"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u05-result.json",
            "workstreams/po03/research/lib/criteria_arms_u05.py",
            "workstreams/po03/tests/test_a5_criteria_arms_u05.py",
        ],
        proposal={
            "summary": "Adopt preregistration as a standing PO-03 practice: acceptance criteria for a "
            "work unit should be frozen from the dispatch record's acceptance wording before the "
            "reproduction is inspected. This is already the per-unit protocol this worker followed for "
            "all twelve a5 units (see hypotheses.jsonl, registered_before_reproduction=true).",
            "coordinator_action_required": "none for a5 specifically -- offered as supporting evidence for "
            "keeping the existing 'freeze exact source SHAs, evaluation criteria and expected evidence "
            "before reading producer narratives' rule in COMMISSION.md item 2",
            "disposition": "RETAIN",
        },
        limitations=[
            "The five candidates were authored by this worker to each violate exactly one boundary the "
            "happy-path sample does not touch; it demonstrates the escape mechanism is real and "
            "reproducible, not the natural base rate of post-hoc criteria failure on unseen code.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
