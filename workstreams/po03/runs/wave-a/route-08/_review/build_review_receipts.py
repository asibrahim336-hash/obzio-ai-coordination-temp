#!/usr/bin/env python3
"""Materialize route-08 review receipts after the GPT outcomes were frozen."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
OUTCOMES_COMMIT = "011484c"
EARLIER = {
    *(f"PO03-WA-{number:03d}" for number in range(1, 9)),
    *(f"PO03-WA-{number:03d}" for number in range(33, 49)),
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def full_commit(short: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{short}^{{commit}}"],
        cwd=REPO,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def build() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    freeze_path = HERE / "OUTCOMES-FROZEN.json"
    freeze = read(freeze_path)
    freeze_sha = sha256(freeze_path)
    frozen_by_task = {row["task_id"]: row for row in freeze["outcomes"]}
    receipts: dict[str, dict[str, Any]] = {}
    comparisons = []

    for task_id, frozen in frozen_by_task.items():
        report_path = HERE / "reports" / f"{task_id}.json"
        report = read(report_path)
        position: dict[str, Any]
        if task_id in EARLIER:
            first_path = (
                REPO
                / "workstreams/po03/runs/wave-a/route-07/review/receipts"
                / f"{task_id}.json"
            )
            first = read(first_path)
            same = first["recommendation"] == frozen["recommendation"]
            comparison = {
                "task_id": task_id,
                "comparison": "AGREEMENT" if same else "DISAGREEMENT",
                "route_07_first_family": {
                    "family": first["reviewer_model_family"],
                    "receipt_uri": first_path.relative_to(REPO).as_posix(),
                    "receipt_sha256": sha256(first_path),
                    "recommendation": first["recommendation"],
                },
                "route_08_second_family": {
                    "family": "gpt",
                    "recommendation": frozen["recommendation"],
                },
                "terminal_acceptance_claimed": False,
            }
            comparisons.append(comparison)
            position = {
                "position": "SECOND_INDEPENDENT_CHALLENGER_FAMILY",
                "two_family_comparison": comparison,
                "consequential_terminal_acceptance_permitted_by_receipt": False,
            }
        else:
            position = {
                "position": "FIRST_INDEPENDENT_CHALLENGER_FAMILY",
                "second_family_review_required_for_consequential_terminal_acceptance": True,
                "consequential_terminal_acceptance_permitted_by_receipt": False,
            }

        receipts[task_id] = {
            "receipt_version": "PO03-WA-ROUTE-08-INDEPENDENT-REVIEW-RECEIPT-v1",
            "task_id": task_id,
            "route_id": frozen["route_id"],
            "reviewed_at": freeze["frozen_at"],
            "reviewer": {
                "function_id": "obzio.function.strategic-operations-orchestration",
                "appointment_id": (
                    "obzio.appointment.strategic-operations-orchestration.20260819.001"
                ),
                "reviewer_family": "gpt",
                "exact_model_configuration": "gpt-5.6-sol-xhigh",
                "runtime_binding": "cursor-cloud-agent",
                "authority_derived_from_runtime": False,
            },
            "blind_order": {
                "rubric_commit": freeze["rubric_commit"],
                "rubric_sha256": freeze["rubric_sha256"],
                "held_out_suite_sha256": freeze["held_out_suite_sha256"],
                "outcomes_freeze_commit": full_commit(OUTCOMES_COMMIT),
                "outcomes_freeze_uri": freeze_path.relative_to(REPO).as_posix(),
                "outcomes_freeze_sha256": freeze_sha,
                "route_07_reviews_opened_only_after_outcome_freeze": True,
            },
            "target_completed_result": report["completed_result"],
            "coordinator_completion": report["coordinator_completion"],
            "frozen_contracts": report["frozen_contracts"],
            "frozen_criteria_sha256": report["criteria_sha256"],
            "frozen_source_lock_sha256": report["source_lock_sha256"],
            "tests_actually_rerun": report["tests"],
            "hidden_cases": report["hidden_cases"],
            "defects": report["defects"],
            "limitations": report["limitations"],
            "exact_evidence": {
                "independent_test_report_uri": report_path.relative_to(REPO).as_posix(),
                "independent_test_report_sha256": sha256(report_path),
                "artifact_readback": report["artifact_readback"],
                "artifact_count": report["artifact_count"],
                "artifact_total_bytes": report["artifact_total_bytes"],
                "binding_failures": report["binding_failures"],
                "reject_reasons": report["reject_reasons"],
                "retest_reasons": report["retest_reasons"],
            },
            "family_review_status": position,
            "recommendation": frozen["recommendation"],
            "terminal_acceptance_claimed": False,
            "allowed_recommendations": [
                "RECOMMEND_ACCEPT",
                "RECOMMEND_REJECT",
                "RETEST",
            ],
            "decision_changed": [],
        }

    comparison_document = {
        "comparison_version": "PO03-WA-ROUTE-08-TWO-FAMILY-COMPARISON-v1",
        "outcomes_freeze_commit": full_commit(OUTCOMES_COMMIT),
        "outcomes_freeze_sha256": freeze_sha,
        "comparisons": sorted(comparisons, key=lambda row: row["task_id"]),
        "agreement_count": sum(row["comparison"] == "AGREEMENT" for row in comparisons),
        "disagreement_count": sum(
            row["comparison"] == "DISAGREEMENT" for row in comparisons
        ),
        "terminal_acceptance_claimed": False,
        "decision_changed": [],
    }
    return comparison_document, receipts


def main() -> int:
    comparison, receipts = build()
    receipt_dir = HERE / "receipts"
    receipt_dir.mkdir(exist_ok=True)
    for task_id, receipt in receipts.items():
        (receipt_dir / f"{task_id}.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
    (HERE / "two-family-comparisons.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "receipts": len(receipts),
                "comparisons": len(comparison["comparisons"]),
                "agreement_count": comparison["agreement_count"],
                "disagreement_count": comparison["disagreement_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
