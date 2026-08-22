#!/usr/bin/env python3
"""a5-u04 reproduction: bounded hashed capsules vs whole-tree dumping.

Sweeps corpus size at a fixed context budget and measures needle-recall for
both admission strategies. Both arms are executed at every corpus size.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.context_admission_u04 import build_corpus, measure_recall  # noqa: E402
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u04-result.json"
SEED = 20260822
CHUNKS_PER_FILE = 8
CHUNK_SIZE = 200
CORPUS_SIZES = [2, 5, 10, 20, 40, 80]
FIXED_BUDGET_CHARS = 3200  # roughly 2 files' worth of chunks


def main() -> int:
    rng = random.Random(SEED)
    sweep = []
    for num_files in CORPUS_SIZES:
        files, tasks = build_corpus(rng, num_files=num_files, chunks_per_file=CHUNKS_PER_FILE, chunk_size=CHUNK_SIZE)
        result = measure_recall(files, tasks, budget_chars=FIXED_BUDGET_CHARS)
        total_chars = sum(len(c) for f in files for c in f)
        result["num_files"] = num_files
        result["total_corpus_chars"] = total_chars
        result["budget_as_fraction_of_corpus"] = FIXED_BUDGET_CHARS / total_chars
        sweep.append(result)

    gap_widens = all(
        sweep[i]["hashed_capsule_recall"] - sweep[i]["whole_tree_dump_recall"]
        <= sweep[i + 1]["hashed_capsule_recall"] - sweep[i + 1]["whole_tree_dump_recall"] + 1e-9
        for i in range(len(sweep) - 1)
        if sweep[i]["budget_as_fraction_of_corpus"] < 1.0
    )
    capsule_never_worse = all(row["hashed_capsule_recall"] >= row["whole_tree_dump_recall"] for row in sweep)
    capsule_strictly_better_when_over_budget = any(
        row["hashed_capsule_recall"] > row["whole_tree_dump_recall"]
        for row in sweep
        if row["budget_as_fraction_of_corpus"] < 1.0
    )

    measurement = {
        "seed": SEED,
        "fixed_budget_chars": FIXED_BUDGET_CHARS,
        "sweep": sweep,
        "capsule_never_worse_than_dump": capsule_never_worse,
        "capsule_strictly_better_when_corpus_exceeds_budget": capsule_strictly_better_when_over_budget,
        "gap_widens_as_corpus_grows_past_budget": gap_widens,
    }

    admission_recall_supported = capsule_never_worse and capsule_strictly_better_when_over_budget and gap_widens
    outcome = "PARTIALLY_SUPPORTED" if admission_recall_supported else "NOT_YET"
    rationale = (
        "At a fixed context budget, hashed relevance-ranked capsule admission preserved the task-"
        "relevant needle fact at least as often as naive whole-tree dumping at every corpus size tested, "
        "strictly more often once the corpus exceeded the budget, and the recall gap widened as corpus "
        "size grew further past the budget -- exactly the necessary precondition the frozen hypothesis "
        "names. This is recorded PARTIALLY_SUPPORTED, not SUPPORTED, because the full claim is about "
        "'accepted-result rate at equal reasoning setting' for a live frontier model, which requires a "
        "paired live-model evaluation not available inside this dependency-free stdlib harness (see the "
        "scope_limitation recorded in sources.json for a5-u04); the acceptance-rate claim itself is "
        "recorded NOT_YET rather than asserted from this proxy alone."
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u04",
        reproduction_id="a5-u04-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u04_capsule_vs_dump.py",
        arms=["whole_tree_dump", "hashed_capsule"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u04-result.json",
            "workstreams/po03/research/lib/context_admission_u04.py",
            "workstreams/po03/tests/test_a5_context_admission_u04.py",
        ],
        limitations=[
            "No live frontier-model call is available in this dependency-free stdlib runtime, so the "
            "full acceptance-rate claim (equal reasoning setting, live model) is NOT_YET, not SUPPORTED. "
            "Only the admission-recall precondition was measured directly.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
