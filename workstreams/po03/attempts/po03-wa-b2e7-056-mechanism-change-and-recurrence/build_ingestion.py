#!/usr/bin/env python3
"""Build controller-ingestion ledgers from committed-shape reproduction evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
ATTEMPTS = REPO / "workstreams/po03/attempts"
UNITS = {
    "H-001": "po03-wa-b2e7-050-reproduction-context-admission",
    "H-002": "po03-wa-b2e7-051-reproduction-verifier-first",
    "H-003": "po03-wa-b2e7-052-reproduction-independent-review",
    "H-004": "po03-wa-b2e7-053-reproduction-outbox-durability",
    "H-005": "po03-wa-b2e7-054-reproduction-checkpoint-granularity",
    "H-006": "po03-wa-b2e7-055-reproduction-scale-versus-acceptance",
}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def compact_metrics(hypothesis_id: str, measurement: dict[str, object]) -> dict[str, object]:
    if hypothesis_id == "H-001":
        return {
            "bounded_recovery": measurement["arms"]["bounded_hashed_capsule"]["mean_required_field_recovery"],
            "dump_recovery": measurement["arms"]["indiscriminate_full_dump"]["mean_required_field_recovery"],
            "delta": measurement["bounded_minus_dump_recovery"],
        }
    if hypothesis_id == "H-002":
        return {
            "frozen_false_green": measurement["arms"]["criteria_frozen_before_output"]["false_green_rate"],
            "adapted_false_green": measurement["arms"]["criteria_adapted_after_output"]["false_green_rate"],
            "reduction": measurement["false_green_rate_reduction"],
        }
    if hypothesis_id == "H-003":
        return {
            "different_family_identity_verified": measurement["different_family_identity_verified"],
            "structural_detection": measurement["arms"]["structural_blind_profile"]["detection_rate"],
            "adversarial_detection": measurement["arms"]["adversarial_blind_profile"]["detection_rate"],
            "disagreement": measurement["reviewer_disagreement_rate"],
        }
    if hypothesis_id == "H-004":
        return {
            "report_only_recovered": measurement["arms"]["report_only"]["recovered_result_fraction"],
            "outbox_recovered": measurement["arms"]["transactional_outbox_with_readback"]["recovered_result_fraction"],
            "losses_injected": measurement["losses_injected"],
        }
    if hypothesis_id == "H-005":
        return {
            "every_step_mean_rework": measurement["arms"]["1"]["mean_reworked_steps"],
            "all_or_nothing_mean_rework": measurement["arms"]["20"]["mean_reworked_steps"],
            "reduction_fraction": measurement["granularity_1_rework_reduction_fraction"],
        }
    levels = {str(level["concurrency"]): level for level in measurement["levels"]}
    return {
        "concurrency_4_good_throughput": levels["4"]["independently_accepted_good_results_per_slot"],
        "concurrency_32_good_throughput": levels["32"]["independently_accepted_good_results_per_slot"],
        "concurrency_4_escape_fraction": levels["4"]["escaped_defect_fraction_of_accepted"],
        "concurrency_32_escape_fraction": levels["32"]["escaped_defect_fraction_of_accepted"],
    }


def main() -> int:
    hypothesis_path = ATTEMPTS / "po03-wa-b2e7-049-hypothesis-register/hypotheses.jsonl"
    hypotheses = {
        entry["hypothesis_id"]: entry
        for entry in (json.loads(line) for line in hypothesis_path.read_text().splitlines())
    }
    ledger = []
    measurements: dict[str, dict[str, object]] = {}
    for hypothesis_id, task_id in UNITS.items():
        unit = ATTEMPTS / task_id
        measurement_path = unit / "measurement.json"
        preregister_path = unit / "preregister.json"
        measurement = load_json(measurement_path)
        measurements[hypothesis_id] = measurement
        ledger.append(
            {
                "hypothesis_id": hypothesis_id,
                "hypothesis_hash": hypotheses[hypothesis_id]["hypothesis_hash"],
                "reproduction_task_id": task_id,
                "reproduction_executed": True,
                "preregister_sha256": hashlib.sha256(preregister_path.read_bytes()).hexdigest(),
                "measurement_sha256": hashlib.sha256(measurement_path.read_bytes()).hexdigest(),
                "sample_size": measurement.get("sample_size", measurement.get("sample_size_slots_per_level")),
                "verdict": measurement["verdict"],
                "metrics": compact_metrics(hypothesis_id, measurement),
                "decision_changed": [],
            }
        )
    ledger_path = ROOT / "reproduction_ledger.jsonl"
    ledger_path.write_bytes(b"".join(canonical(entry) for entry in ledger))

    scale = compact_metrics("H-006", measurements["H-006"])
    reject_scale = (
        scale["concurrency_32_good_throughput"] < scale["concurrency_4_good_throughput"]
        and scale["concurrency_32_escape_fraction"] > scale["concurrency_4_escape_fraction"]
    )
    changes = {
        "protocol": "PO03-MECHANISM-CHANGE-v1",
        "mechanism_changes": [
            {
                "change_id": "MC-001-bounded-hashed-context-admission",
                "supported_by": UNITS["H-001"],
                "measured_effect": compact_metrics("H-001", measurements["H-001"]),
                "staged_artifact": "staged_mechanisms/context_capsule.py",
                "controller_promotion_status": "STAGED_NOT_PROMOTED",
                "recurrence_command": "python3 -I test_recurrence.py staged_mechanisms",
            },
            {
                "change_id": "MC-002-atomic-outbox-readback",
                "supported_by": UNITS["H-004"],
                "measured_effect": compact_metrics("H-004", measurements["H-004"]),
                "staged_artifact": "staged_mechanisms/durable_outbox.py",
                "controller_promotion_status": "STAGED_NOT_PROMOTED",
                "recurrence_command": "python3 -I test_recurrence.py staged_mechanisms",
            },
        ],
        "evidence_backed_rejections": [
            {
                "rejection_id": "MR-001-concurrency-only-scale-to-32",
                "tempting_change": "Raise attempt concurrency to 32 while acceptance remains 4 and recovery remains 2 per slot.",
                "status": "REJECTED_BY_REPRODUCTION" if reject_scale else "NOT_REJECTED",
                "supported_by": UNITS["H-006"],
                "measured_effect": scale,
            }
        ],
        "strategy_status": "PROPOSAL_ONLY",
        "decision_changed": [],
    }
    changes_path = ROOT / "mechanism_changes.json"
    changes_path.write_bytes(canonical(changes))
    print(
        json.dumps(
            {
                "reproductions": len(ledger),
                "mechanism_changes": len(changes["mechanism_changes"]),
                "evidence_backed_rejections": sum(
                    item["status"] == "REJECTED_BY_REPRODUCTION"
                    for item in changes["evidence_backed_rejections"]
                ),
                "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
                "changes_sha256": hashlib.sha256(changes_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
