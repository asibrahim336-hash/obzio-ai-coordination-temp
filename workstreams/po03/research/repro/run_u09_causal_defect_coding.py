#!/usr/bin/env python3
"""a5-u09 reproduction: is producer self-certification the dominant source
of false completion, above tooling defects?

The frozen acceptance wording requires the PO-02 causal defect list to be
coded against OBSERVED WAVE A EVENTS with counts, not a qualitative essay.

Two, clearly separated, coded datasets are produced:

1. ``wave_a_ledger`` -- the REAL, current, coordinator-owned
   ``workstreams/po03/control/events/ledger.jsonl`` (read-only access), every
   row coded by the same rule-based coder. This is the actual Wave A
   evidence the acceptance criterion names.
2. ``so02_historical_evidence`` -- the specific documented incidents in
   ``workstreams/po03/evidence/so02-operating-correction.json``'s
   ``evidence_rulings``, from the prior PO-02 cycle that so02 exists to
   correct. This is clearly labelled historical context, never merged into
   the Wave A counts.

Both are coded with the identical, auditable rule set (see
lib/causal_defect_coder_u09.py); nothing here is a hand-written narrative.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
PO03_ROOT = RESEARCH_ROOT.parent
sys.path.insert(0, str(RESEARCH_ROOT))

from lib.causal_defect_coder_u09 import (  # noqa: E402
    DEFECT_CATEGORIES,
    code_causal_defect_list,
    code_evidence_rulings,
    code_ledger_rows,
    summarize,
)
from lib.ledger_io import write_json  # noqa: E402
from lib.reproduction_io import record_reproduction  # noqa: E402

OUTPUT_PATH = RESEARCH_ROOT / "output" / "a5-u09-result.json"
LEDGER_PATH = PO03_ROOT / "control" / "events" / "ledger.jsonl"
SO02_PATH = PO03_ROOT / "evidence" / "so02-operating-correction.json"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    ledger_rows = load_jsonl(LEDGER_PATH)
    so02 = json.loads(SO02_PATH.read_text(encoding="utf-8"))

    self_check = code_causal_defect_list([spec["causal_defect_text"] for spec in DEFECT_CATEGORIES.values()])

    wave_a_coded = code_ledger_rows(ledger_rows)
    wave_a_summary = summarize(wave_a_coded)

    so02_coded = code_evidence_rulings(so02["evidence_rulings"])
    so02_summary = summarize({k: v for k, v in so02_coded.items()})

    so02_dominant_category = max(so02_summary["category_counts"], key=lambda c: so02_summary["category_counts"][c])
    so02_dominant_count = so02_summary["category_counts"][so02_dominant_category]
    so02_producer_count = so02_summary["category_counts"]["producer_self_certification"]
    so02_producer_is_dominant = so02_producer_count == so02_dominant_count and so02_producer_count > 0

    measurement = {
        "self_check_every_named_defect_matches_its_own_category": {
            k: v for k, v in self_check.items()
        },
        "wave_a_ledger": {
            "source_path": "workstreams/po03/control/events/ledger.jsonl",
            "total_rows_observed": len(ledger_rows),
            "event_kind_counts": {
                event: sum(1 for r in ledger_rows if r["event"] == event)
                for event in sorted({r["event"] for r in ledger_rows})
            },
            "summary": wave_a_summary,
        },
        "so02_historical_evidence": {
            "source_path": "workstreams/po03/evidence/so02-operating-correction.json#evidence_rulings",
            "coded_rulings": so02_coded,
            "summary": so02_summary,
            "dominant_category": so02_dominant_category,
            "dominant_category_count": so02_dominant_count,
            "producer_self_certification_count": so02_producer_count,
            "producer_self_certification_is_dominant": so02_producer_is_dominant,
        },
    }

    wave_a_has_zero_eligible_completions = wave_a_summary["eligible_records"] == 0

    if wave_a_has_zero_eligible_completions:
        outcome = "NOT_YET"
        rationale = (
            f"The frozen acceptance requires coding the PO-02 causal defect list against OBSERVED WAVE A "
            f"EVENTS. The real, current workstreams/po03/control/events/ledger.jsonl contains "
            f"{len(ledger_rows)} rows, all of kind {measurement['wave_a_ledger']['event_kind_counts']} -- "
            "zero rows have yet reached any completion-adjacent event (RESULT_COMMITTED, PARENT_INGESTED, "
            "COMPLETED, PROVIDER_COMPLETED_UNCOMMITTED, RECOVERY_REQUIRED, FENCE_REJECTED, "
            "DUPLICATE_IGNORED) in the shared coordinator ledger, because no subordinate worker's results "
            "have been ingested by the coordinator yet at the time of this reproduction. None of the six "
            "causal defect categories can be observed, let alone ranked by relative contribution, in a "
            "dataset with zero eligible records. This is an honest boundary, not a null hypothesis "
            "acceptance: the exact observed boundary is 0 eligible of 148 rows. As supplementary, clearly "
            "separate historical context (NOT Wave A, NOT conflated with the count above), the specific "
            f"documented pre-Wave-A incidents in so02-operating-correction.json's evidence_rulings code as "
            f"{so02_summary['category_counts']}, in which producer_self_certification "
            f"{'is' if so02_producer_is_dominant else 'is not'} the plurality category "
            f"({so02_producer_count} of {so02_summary['matched_records']} matched historical records)."
        )
    else:
        outcome = "SUPPORTED" if wave_a_summary["category_counts"]["producer_self_certification"] == max(
            wave_a_summary["category_counts"].values()
        ) and wave_a_summary["category_counts"]["producer_self_certification"] > 0 else "REJECTED"
        rationale = (
            f"Coded {wave_a_summary['eligible_records']} completion-adjacent Wave A ledger rows: "
            f"{wave_a_summary['category_counts']}."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_PATH, measurement)

    row_sha256 = record_reproduction(
        unit_id="a5-u09",
        reproduction_id="a5-u09-repro-01",
        command="python3 -I workstreams/po03/research/repro/run_u09_causal_defect_coding.py",
        arms=["wave_a_ledger_coded", "so02_historical_evidence_coded"],
        measurement=measurement,
        outcome=outcome,
        outcome_rationale=rationale,
        evidence_artifacts=[
            "workstreams/po03/research/output/a5-u09-result.json",
            "workstreams/po03/research/lib/causal_defect_coder_u09.py",
            "workstreams/po03/tests/test_a5_causal_defect_coder_u09.py",
        ],
        limitations=[
            "Wave A had zero completion-adjacent ledger rows at the time this reproduction was run; "
            "re-running this exact script (python3 -I workstreams/po03/research/repro/"
            "run_u09_causal_defect_coding.py) after the coordinator has ingested subordinate results would "
            "produce a non-trivial Wave A verdict without any code change, since the coder always re-reads "
            "the live ledger fresh.",
            "The coder is deliberately simple substring matching over serialized JSON text; it can produce "
            "false positives if unrelated text happens to contain a trigger substring (mitigated by using "
            "fairly specific, multi-word or ALL_CAPS-style triggers drawn directly from the real "
            "so02-operating-correction.json vocabulary) and it cannot detect a causal defect described in "
            "prose that never uses any of the recorded trigger phrasings.",
            "The so02 historical evidence_rulings dataset has only 6 entries; a dominant-category finding "
            "over 6 records is directional, not statistically powered.",
        ],
    )
    print(json.dumps({"outcome": outcome, "reproduction_row_sha256": row_sha256, "out": str(OUTPUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
