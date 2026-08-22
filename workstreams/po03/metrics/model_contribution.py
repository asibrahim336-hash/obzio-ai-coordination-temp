#!/usr/bin/env python3
"""a7-u06: per-model contribution and cross-family disagreement, computed per
exact model slug from committed dispositions, with no attribution to Auto.

Inputs: workstreams/po03/metrics/work-unit-runs.jsonl (a7-u02, ledger-only),
workstreams/po03/control/model-capability-register.json (slug -> family),
workstreams/po03/control/path-ownership.json (owner -> model,
cross_family_review_matrix: reviewer -> [producers reviewed]).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


NON_EXACT_SLUGS = {"inherit", "auto", "Auto", "AUTO"}

REASONING_SUFFIXES = ("-xhigh-fast", "-high-fast", "-xhigh", "-high", "-max", "-fast")


def resolve_family(slug: str | None, slug_to_family: dict[str, str]) -> str:
    """Resolve a model slug to its family, first from the register's exact
    slug list, then by stripping a known reasoning suffix (the family name is
    the slug with its trailing '-thinking-<setting>' or '-<setting>' removed).
    Never falls back to a guess beyond this deterministic string rule."""
    if slug is None:
        return "UNKNOWN_FAMILY_NOT_IN_REGISTER"
    if slug in slug_to_family:
        return slug_to_family[slug]
    if "-thinking-" in slug:
        return slug.split("-thinking-")[0]
    for suffix in REASONING_SUFFIXES:
        if slug.endswith(suffix):
            return slug[: -len(suffix)]
    return "UNKNOWN_FAMILY_NOT_IN_REGISTER"


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": "UNDEFINED_0_OF_0"}
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator}


COMMITTED_OUTCOMES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}


def compute(root: Path) -> dict[str, Any]:
    runs_path = root / "workstreams/po03/metrics/work-unit-runs.jsonl"
    all_rows = load_jsonl(runs_path)
    meta = next(r for r in all_rows if r["record_type"] == "generation_metadata")
    unit_rows = [r for r in all_rows if r["record_type"] == "unit_run"]

    model_register = json.loads(
        (root / "workstreams/po03/control/model-capability-register.json").read_text(encoding="utf-8")
    )
    slug_to_family = {
        entry["slug"]: entry["family"] for entry in model_register.get("delegation_models_exposed", [])
    }

    path_ownership = json.loads((root / "workstreams/po03/control/path-ownership.json").read_text(encoding="utf-8"))
    owners = path_ownership.get("owners", {})
    cross_family_matrix = path_ownership.get("cross_family_review_matrix", {})

    excluded: list[dict[str, Any]] = []
    per_model: dict[str, dict[str, Any]] = {}

    for row in unit_rows:
        model = row["exact_model_and_reasoning"]
        if model in NON_EXACT_SLUGS or model is None:
            excluded.append({"unit_id": row["unit_id"], "model_value": model, "reason": "EXCLUDED_NOT_EXACT_SLUG"})
            continue
        bucket = per_model.setdefault(
            model,
            {
                "model_slug": model,
                "family": resolve_family(model, slug_to_family),
                "dispatched_count": 0,
                "result_committed_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "unit_ids": [],
            },
        )
        bucket["dispatched_count"] += 1
        bucket["unit_ids"].append(row["unit_id"])
        if row["current_obzio_state"] in COMMITTED_OUTCOMES or row["result_commit_and_readback"]["result_commit_id"]:
            bucket["result_committed_count"] += 1
        if row["independent_disposition"] == "ACCEPTED":
            bucket["accepted_count"] += 1
        elif row["independent_disposition"] == "REJECTED":
            bucket["rejected_count"] += 1

    per_model_contribution = {}
    for slug, bucket in sorted(per_model.items()):
        bucket["unit_ids"] = sorted(bucket["unit_ids"])
        bucket["result_commit_rate"] = rate(bucket["result_committed_count"], bucket["dispatched_count"])
        bucket["acceptance_rate"] = rate(bucket["accepted_count"], bucket["dispatched_count"])
        per_model_contribution[slug] = bucket

    # --- per_model_disagreement: for each reviewer owner in the cross-family matrix,
    # for each producer owner it reviews, count REJECTED vs total dispositions on that
    # producer's units, keyed by (producer_family, reviewer_family).
    owner_to_model = {owner: entry.get("model") for owner, entry in owners.items()}
    rows_by_unit = {row["unit_id"]: row for row in unit_rows}

    disagreement_pairs: dict[str, dict[str, Any]] = {}
    for reviewer_owner, producer_owners in cross_family_matrix.items():
        if not isinstance(producer_owners, list):
            # "rule" is a prose description of the matrix's invariant, not an
            # owner -> [owners] mapping; every other key's value is a list.
            continue
        reviewer_model = owner_to_model.get(reviewer_owner)
        reviewer_family = resolve_family(reviewer_model, slug_to_family)
        for producer_owner in producer_owners:
            producer_model = owner_to_model.get(producer_owner)
            producer_family = resolve_family(producer_model, slug_to_family)
            pair_key = f"{producer_family}::reviewed_by::{reviewer_family}"
            pair = disagreement_pairs.setdefault(
                pair_key,
                {
                    "producer_family": producer_family,
                    "reviewer_family": reviewer_family,
                    "producer_owners": [],
                    "reviewer_owner": reviewer_owner,
                    "rejected_count": 0,
                    "accepted_count": 0,
                },
            )
            if producer_owner not in pair["producer_owners"]:
                pair["producer_owners"].append(producer_owner)
            producer_unit_ids = [
                unit_id for unit_id, row in rows_by_unit.items() if row["owner"] == producer_owner
            ]
            for unit_id in producer_unit_ids:
                disposition = rows_by_unit[unit_id]["independent_disposition"]
                if disposition == "REJECTED":
                    pair["rejected_count"] += 1
                elif disposition == "ACCEPTED":
                    pair["accepted_count"] += 1

    per_model_disagreement = {}
    for pair_key, pair in sorted(disagreement_pairs.items()):
        pair["producer_owners"] = sorted(pair["producer_owners"])
        total = pair["rejected_count"] + pair["accepted_count"]
        pair["disagreement_rate"] = rate(pair["rejected_count"], total)
        per_model_disagreement[pair_key] = pair

    return {
        "protocol_version": "OBZIO-MODEL-CONTRIBUTION-v1",
        "unit_id": "a7-u06",
        "measured_against": {
            "ledger_head_sha256": meta["ledger_head_sha256"],
            "ledger_rows": meta["ledger_rows"],
        },
        "excluded_not_exact_slug": excluded,
        "auto_attribution_count": len(excluded),
        "per_model_contribution": per_model_contribution,
        "per_model_disagreement": per_model_disagreement,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/model-contribution-report.json")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = compute(root)

    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(canonical({"wrote": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
