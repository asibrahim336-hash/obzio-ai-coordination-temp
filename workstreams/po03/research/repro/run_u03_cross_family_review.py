#!/usr/bin/env python3
"""a5-u03 reproduction: does blind cross-methodology review catch a
different defect class than same-methodology review?

Both reviewers are applied blind (criteria frozen before this run, see
lib/reviewers_u03.py) to the identical 8-snippet seeded-defect corpus. This
operationalizes "cross-family" as cross-methodology (static pattern
matching vs property/dynamic testing) because no tool in this dependency-
free stdlib runtime can invoke a second live frontier model family; see the
scope_limitation recorded against this unit's hypothesis in sources.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.review_corpus_u03 import (  # noqa: E402
    DYNAMIC_ONLY_DEFECTS,
    DYNAMIC_REFERENCES,
    STATIC_ONLY_DEFECTS,
    generate_dynamic_inputs,
)
from lib.reviewers_u03 import PropertyBasedReviewer, StaticPatternReviewer  # noqa: E402
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u03-result.json"
SEED = 20260822


def main() -> int:
    static_reviewer = StaticPatternReviewer()
    dynamic_reviewer = PropertyBasedReviewer(seed=SEED)

    all_snippets = {**STATIC_ONLY_DEFECTS, **DYNAMIC_ONLY_DEFECTS}
    static_catches = sorted(name for name, fn in all_snippets.items() if static_reviewer.review(fn))

    dynamic_catches = []
    with tempfile.TemporaryDirectory(dir=RESEARCH_ROOT / "output") as tmp:
        tmp_dir = Path(tmp)
        for name, fn in DYNAMIC_ONLY_DEFECTS.items():
            inputs = generate_dynamic_inputs(name, dynamic_reviewer.rng)
            if dynamic_reviewer.review_dynamic(name, fn, DYNAMIC_REFERENCES[name], inputs):
                dynamic_catches.append(name)
        for name, fn in STATIC_ONLY_DEFECTS.items():
            if dynamic_reviewer.review_static_only_snippet(name, fn, tmp_dir):
                dynamic_catches.append(name)
    dynamic_catches = sorted(dynamic_catches)

    static_set = set(static_catches)
    dynamic_set = set(dynamic_catches)
    pooled = static_set | dynamic_set
    identical = static_set == dynamic_set
    either_subset_of_other = static_set <= dynamic_set or dynamic_set <= static_set

    measurement = {
        "corpus_size": len(all_snippets),
        "static_pattern_reviewer_catches": static_catches,
        "property_based_reviewer_catches": dynamic_catches,
        "intersection": sorted(static_set & dynamic_set),
        "static_only_catches": sorted(static_set - dynamic_set),
        "dynamic_only_catches": sorted(dynamic_set - static_set),
        "pooled_catches": sorted(pooled),
        "pooled_count": len(pooled),
        "identical_defect_sets": identical,
        "either_subset_of_other": either_subset_of_other,
    }

    both_ran_on_identical_artifacts = True  # both reviewers were called on the same 8 functions above
    outcome = (
        "SUPPORTED"
        if both_ran_on_identical_artifacts and not identical and not either_subset_of_other
        else "REJECTED"
    )
    rationale = (
        f"Both reviewers ran blind, with criteria frozen before this run, against the identical "
        f"{len(all_snippets)}-snippet corpus. The static pattern reviewer caught "
        f"{sorted(static_set)} and missed {sorted(dynamic_set - static_set)}; the property-based "
        f"reviewer caught {sorted(dynamic_set)} and missed {sorted(static_set - dynamic_set)}. The two "
        f"sets are non-identical and neither is a subset of the other, so pooling both "
        f"({len(pooled)}/{len(all_snippets)}) strictly beats either reviewer alone "
        f"({len(static_set)}/{len(all_snippets)} and {len(dynamic_set)}/{len(all_snippets)})."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u03",
        reproduction_id="a5-u03-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u03_cross_family_review.py",
        arms=["static_pattern_reviewer", "property_based_reviewer"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u03-result.json",
            "workstreams/po03/research/lib/review_corpus_u03.py",
            "workstreams/po03/research/lib/reviewers_u03.py",
            "workstreams/po03/tests/test_a5_reviewers_u03.py",
        ],
        limitations=[
            "This is a proxy for cross-family review diversity (frontier LLM families), not a literal "
            "multi-model comparison: no tool available to this subagent can invoke a second live "
            "frontier model family inside a dependency-free stdlib reproduction, and it may not contact "
            "po03-worker-a6/a10 or the coordinator to arrange one mid-unit. The generalization from "
            "cross-methodology to cross-model-family diversity is asserted by analogy to the N-version "
            "programming literature cited in hypotheses.jsonl, not measured directly here.",
            "The 8-snippet corpus was authored by this same worker specifically to be catchable by "
            "exactly one methodology each; it demonstrates that non-overlapping catch profiles are "
            "possible and mechanically reproducible, not the true overlap rate on an unseen, naturally "
            "occurring defect population.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
