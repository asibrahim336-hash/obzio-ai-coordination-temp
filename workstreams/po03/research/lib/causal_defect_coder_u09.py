"""a5-u09: a rule-based (not qualitative-only) coder that maps observed
events and evidence records onto the six named PO-02 causal defects from
``workstreams/po03/evidence/so02-operating-correction.json``, so relative
contribution can be reported with counts.

Every category has an explicit, auditable list of trigger substrings.
Coding a record is pure substring matching over its serialized text against
every category's triggers -- a documented, reproducible rule, not a
judgment call made silently by hand. A record may match zero, one, or
several categories; multi-matches are recorded, not hidden.
"""

from __future__ import annotations

import json
from typing import Any

DEFECT_CATEGORIES: dict[str, dict[str, Any]] = {
    "producer_self_certification": {
        "causal_defect_text": "worker self-report could represent completion",
        "triggers": [
            "producer_reported",
            "completion_reported",
            "self-report",
            "self_report",
            "worker self-report",
        ],
    },
    "discretionary_persistence": {
        "causal_defect_text": "durable result persistence was discretionary",
        "triggers": [
            "bytes_not_present",
            "uncommitted",
            "unrecovered",
            "not present",
            "discretionary",
        ],
    },
    "schema_allowed_nulls": {
        "causal_defect_text": "task schema allowed completed with null result and empty artifacts",
        "triggers": [
            "null result",
            "empty artifacts",
            "allowed completed with null",
        ],
    },
    "no_custody_invariants": {
        "causal_defect_text": "no lease, fence token, checkpoint, result transaction, commit marker, "
        "parent acknowledgement or replay",
        "triggers": [
            "unrecovered_after_four_founder_reported_routes",
            "no lease",
            "no fence",
            "no checkpoint",
            "no commit marker",
            "no replay",
        ],
    },
    "provider_route_as_custody": {
        "causal_defect_text": "provider return route was treated as result custody",
        "triggers": [
            "live_conflict",
            "provider_completed_uncommitted",
            "provider return route",
        ],
    },
    "scale_outpaced_capacity": {
        "causal_defect_text": "scale increased without proportional recovery and acceptance capacity",
        "triggers": [
            "not_yet_reconciled",
            "exact_worker_denominator",
            "scale increased",
        ],
    },
}


def code_text(text: str) -> list[str]:
    lowered = text.lower()
    matches = []
    for category_id, spec in DEFECT_CATEGORIES.items():
        if any(trigger in lowered for trigger in spec["triggers"]):
            matches.append(category_id)
    return matches


def code_evidence_rulings(evidence_rulings: dict[str, str]) -> dict[str, list[str]]:
    """Codes each (key, value) pair of an evidence_rulings-style mapping.
    Both the field name and its value are searched, since some categories
    are only distinguishable by field name (e.g. exact_worker_denominator)."""
    coded = {}
    for key, value in evidence_rulings.items():
        combined = f"{key} {value}"
        coded[key] = code_text(combined)
    return coded


def code_causal_defect_list(causal_defects: list[str]) -> dict[str, list[str]]:
    """Sanity-check coding of so02's own causal_defects prose list against
    the same trigger rules, so each category is verified to actually match
    its own source sentence at least once."""
    coded = {}
    for i, defect_text in enumerate(causal_defects):
        coded[f"causal_defect_{i}"] = code_text(defect_text)
    return coded


def code_ledger_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Codes real, observed control_plane.py ledger rows. Only rows whose
    event reaches a completion-adjacent state (RESULT_COMMITTED,
    PARENT_INGESTED, COMPLETED, PROVIDER_COMPLETED_UNCOMMITTED,
    RECOVERY_REQUIRED, FENCE_REJECTED, DUPLICATE_IGNORED) are even eligible
    to exhibit any of the six causal defects; earlier lifecycle events
    (CREATED, LEASED, RUNNING, CHECKPOINTED) structurally cannot, since no
    completion or persistence claim has been made yet."""
    eligible_events = {
        "RESULT_COMMITTED",
        "PARENT_INGESTED",
        "COMPLETED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
        "RECOVERY_REQUIRED",
        "FENCE_REJECTED",
        "DUPLICATE_IGNORED",
    }
    coded = {}
    for row in rows:
        row_key = f"{row['unit_id']}#{row['seq']}"
        if row["event"] not in eligible_events:
            coded[row_key] = None  # not eligible, not "zero matches" -- structurally exempt
            continue
        combined = json.dumps(row, sort_keys=True)
        coded[row_key] = code_text(combined)
    return coded


def summarize(coded: dict[str, list[str] | None]) -> dict[str, Any]:
    total_records = len(coded)
    eligible = {k: v for k, v in coded.items() if v is not None}
    counts = {cat: 0 for cat in DEFECT_CATEGORIES}
    matched_records = 0
    for cats in eligible.values():
        if cats:
            matched_records += 1
        for c in cats:
            counts[c] += 1
    return {
        "total_records": total_records,
        "eligible_records": len(eligible),
        "ineligible_records": total_records - len(eligible),
        "matched_records": matched_records,
        "category_counts": counts,
    }
