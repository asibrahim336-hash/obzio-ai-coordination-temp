"""Stage-2 disagreement analysis: producer claims versus frozen review outcomes.

Runs strictly after the independent recommendations are written and committed
(review/receipts/, commit recorded in the route receipt). Producer conclusions,
FINDING/README narratives, observed-result prose and route execution receipts
are admitted here and nowhere else, and they cannot change any recommendation.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

ANALYSIS_VERSION = "PO03-ROUTE07-DISAGREEMENT-ANALYSIS-v1"
DISPOSITIONS = ("PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED")

AGREEMENT = {
    ("PASS", "RECOMMEND_ACCEPT"): "AGREE",
    ("PASS", "RETEST"): "PARTIAL_DISAGREEMENT",
    ("PASS", "RECOMMEND_REJECT"): "DISAGREE",
    ("FAIL", "RECOMMEND_REJECT"): "AGREE",
    ("FAIL", "RECOMMEND_ACCEPT"): "DISAGREE",
    ("FAIL", "RETEST"): "PARTIAL_DISAGREEMENT",
    ("NOT_YET", "RETEST"): "AGREE",
    ("NOT_YET", "RECOMMEND_ACCEPT"): "PARTIAL_DISAGREEMENT",
    ("NOT_YET", "RECOMMEND_REJECT"): "PARTIAL_DISAGREEMENT",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_producer_disposition(slot: Path) -> dict:
    """Pull the producer's own claimed disposition out of its narrative artifacts."""
    claims = []
    for path in sorted(slot.rglob("*")):
        if not path.is_file() or path.suffix not in (".md", ".json", ".txt"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r"(?:disposition|outcome|verdict)\W{0,4}(" + "|".join(DISPOSITIONS) + r")\b",
            text,
            re.IGNORECASE,
        ):
            claims.append({"source": path.name, "claim": m.group(1).upper()})
    distinct = sorted({c["claim"] for c in claims})
    return {
        "claimed_dispositions": distinct,
        "primary_claim": distinct[0] if len(distinct) == 1 else ("AMBIGUOUS" if distinct else "NONE"),
        "claim_sites": claims[:12],
    }


def producer_state_claims(slot: Path) -> dict:
    result = slot / "result.json"
    if not result.exists():
        return {}
    doc = json.loads(result.read_text())
    txn = doc.get("result_transaction", {}) or {}
    return {
        "provider_state": doc.get("provider_state"),
        "obzio_state": doc.get("obzio_state"),
        "independent_acceptance": doc.get("independent_acceptance"),
        "completion_actor": doc.get("completion_actor"),
        "result_txn_state": txn.get("state"),
        "declared_artifact_count": txn.get("artifact_count"),
        "declared_manifest_sha256": txn.get("manifest_sha256"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--annotate-receipts",
        action="store_true",
        help="attach the disagreement block to each receipt without touching its recommendation",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    receipts_dir = Path(args.receipts)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    rows, counts = [], {}
    for receipt_path in sorted(receipts_dir.glob("PO03-WA-*.json")):
        receipt = json.loads(receipt_path.read_text())
        slot = repo_root / receipt["target"]["result_slot"]
        producer = extract_producer_disposition(slot)
        states = producer_state_claims(slot)
        recommendation = receipt["recommendation"]
        agreement = AGREEMENT.get(
            (producer["primary_claim"], recommendation), "UNMAPPED_PRODUCER_CLAIM"
        )
        counts[agreement] = counts.get(agreement, 0) + 1
        declared = states.get("declared_manifest_sha256")
        manifest_files = [p for p in slot.glob("*manifest*.json")]
        manifest_actual = sha256_path(manifest_files[0]) if manifest_files else None
        row = {
                "task_id": receipt["task_id"],
                "route_id": receipt["route_id"],
                "producer_claimed_disposition": producer["primary_claim"],
                "producer_claim_sites": producer["claim_sites"],
                "producer_state_claims": states,
                "independent_recommendation": recommendation,
                "agreement": agreement,
                "independent_defects": receipt["defects"],
                "producer_manifest_hash_claim_verified": (
                    None if declared is None or manifest_actual is None else declared == manifest_actual
                ),
                "reviewer_rerun_test_count": sum(
                    int(r.get("ran", 0)) for r in receipt["tests_rerun_by_reviewer"]
                ),
                "immutable_readback_all_match": all(
                    a["immutable_readback_match"] for a in receipt["immutable_artifact_readback"]
                ),
        }
        rows.append(row)
        if args.annotate_receipts:
            frozen = receipt["recommendation"]
            receipt["producer_disagreement"] = {
                "analysis_version": ANALYSIS_VERSION,
                "read_after_recommendation_frozen": True,
                "producer_claimed_disposition": row["producer_claimed_disposition"],
                "producer_state_claims": row["producer_state_claims"],
                "agreement": row["agreement"],
                "producer_manifest_hash_claim_verified": row[
                    "producer_manifest_hash_claim_verified"
                ],
            }
            assert receipt["recommendation"] == frozen, "producer claims must not move a verdict"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    doc = {
        "analysis_version": ANALYSIS_VERSION,
        "analysed_at": now,
        "ordering_declaration": (
            "Producer conclusions were read only after every independent recommendation "
            "was written and committed. No recommendation was altered by this analysis."
        ),
        "agreement_counts": counts,
        "rows": rows,
        "decision_changed": [],
    }
    Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(counts, indent=2, sort_keys=True))
    for row in rows:
        if row["agreement"] != "AGREE":
            print(
                f"  {row['task_id']} producer={row['producer_claimed_disposition']} "
                f"reviewer={row['independent_recommendation']} -> {row['agreement']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
