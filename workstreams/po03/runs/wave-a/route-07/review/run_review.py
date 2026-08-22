"""Stage-1 blind review driver for the 24 coordinator-completed Wave A results.

Stage 1 consumes only frozen criteria (task inputs, acceptance contracts, the
source lock, the transactional-result schema) and the mechanical content of each
producer result slot. It never parses a producer's own PASS/FAIL claim, FINDING
narrative or route execution receipt; those are read in stage 2
(disagreement_v1.py) strictly after the stage-1 outcomes are hashed.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rubric_v1 as rb  # noqa: E402

REVIEWER_ID = "po03-route-07-independent-reviewer"
REVIEWER_FUNCTION = "evaluation-and-semantics"
REVIEWER_FAMILY = "claude-opus-5"
RECEIPT_VERSION = "PO03-ROUTE07-INDEPENDENT-REVIEW-RECEIPT-v1"

TARGET_ROUTES = {
    "route-01": [f"PO03-WA-{n:03d}" for n in range(1, 9)],
    "route-05": [f"PO03-WA-{n:03d}" for n in range(33, 41)],
    "route-06": [f"PO03-WA-{n:03d}" for n in range(41, 49)],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_blob_readback(repo_root: Path, commit: str, rel: str):
    """Read the artifact back out of the immutable commit, not the worktree."""
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo_root), "cat-file", "blob", f"{commit}:{rel}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return sha256_bytes(proc.stdout), len(proc.stdout)


def load_frozen(repo_root: Path) -> dict:
    ev = repo_root / "workstreams/po03/evidence"
    return {
        "criteria_freeze_sha256": sha256_path(ev / "criteria-freeze.json"),
        "criteria_freeze": json.loads((ev / "criteria-freeze.json").read_text()),
        "source_lock_sha256": sha256_path(ev / "source-lock.json"),
    }


def load_completions(repo_root: Path) -> dict:
    out = {}
    for route in TARGET_ROUTES:
        doc = json.loads(
            (repo_root / f"workstreams/po03/control/completions/{route}.json").read_text()
        )
        for tr in doc["task_results"]:
            out[tr["task_id"]] = {
                "route_id": route,
                "coordinator_state": doc["state"],
                "coordinator_independent_acceptance": doc["independent_acceptance"],
                **tr,
            }
    return out


def build_cohort(repo_root: Path, task_meta: dict) -> dict:
    cohort = {}
    for tid, meta in task_meta.items():
        slot = repo_root / meta["result_slot"]
        if not slot.is_dir():
            continue
        cohort[tid] = {
            p.name: p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(slot.rglob("*.py"))
            if "__pycache__" not in p.parts
        }
    return cohort


def load_task_meta(repo_root: Path) -> dict:
    meta = {}
    for route, tids in TARGET_ROUTES.items():
        for tid in tids:
            base = repo_root / f"workstreams/po03/control/tasks/{tid}"
            inp = json.loads((base / "input.json").read_text())
            meta[tid] = {
                "route_id": route,
                "result_slot": inp["result_slot"].rstrip("/"),
                "owned_prefix": inp["result_slot"].rstrip("/"),
                "frozen_hypothesis": inp["frozen_hypothesis"],
                "function": inp["function"],
                "acceptance_contract_sha256": inp["acceptance_contract_sha256"],
                "acceptance_contract_uri": inp["acceptance_contract_uri"],
                "immutable_input_manifest_sha256": inp["immutable_input_manifest_sha256"],
                "acceptance_contract": json.loads(
                    (repo_root / inp["acceptance_contract_uri"]).read_text()
                ),
            }
    return meta


def artifact_readback(repo_root: Path, slot: Path, commit: str) -> list:
    rows = []
    for path in sorted(slot.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(repo_root).as_posix()
        worktree = sha256_path(path)
        blob = git_blob_readback(repo_root, commit, rel)
        rows.append(
            {
                "path": rel,
                "sha256": worktree,
                "bytes": path.stat().st_size,
                "immutable_commit_sha256": blob[0] if blob else None,
                "immutable_readback_match": bool(blob and blob[0] == worktree),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--base-commit", required=True)
    ap.add_argument("--rubric-freeze", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    freeze = json.loads(Path(args.rubric_freeze).read_text())

    frozen = load_frozen(repo_root)
    task_meta = load_task_meta(repo_root)
    completions = load_completions(repo_root)
    cohort = build_cohort(repo_root, task_meta)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = {
        "receipt_version": RECEIPT_VERSION,
        "reviewed_at": now,
        "reviewer_id": REVIEWER_ID,
        "reviewer_function": REVIEWER_FUNCTION,
        "reviewer_model_family": REVIEWER_FAMILY,
        "base_commit": args.base_commit,
        "rubric_freeze": freeze,
        "criteria_freeze_sha256": frozen["criteria_freeze_sha256"],
        "source_lock_sha256": frozen["source_lock_sha256"],
        "recommendations": {},
        "decision_changed": [],
    }

    for tid in sorted(task_meta):
        meta = task_meta[tid]
        comp = completions[tid]
        slot = repo_root / meta["result_slot"]
        review = rb.review_slot(
            repo_root=repo_root,
            slot_rel=meta["result_slot"],
            task_id=tid,
            hypothesis=meta["frozen_hypothesis"],
            acceptance_sha=meta["acceptance_contract_sha256"],
            manifest_sha=meta["immutable_input_manifest_sha256"],
            owned_prefix=meta["owned_prefix"],
            cohort=cohort,
        )
        readback = artifact_readback(repo_root, slot, args.base_commit) if slot.is_dir() else []
        rerun = []
        for d in review.dimensions:
            if d.dimension == "R2_TESTS_RERUN" and isinstance(d.evidence, list):
                rerun = d.evidence
        receipt = {
            "receipt_version": RECEIPT_VERSION,
            "task_id": tid,
            "route_id": meta["route_id"],
            "function": meta["function"],
            "frozen_hypothesis": meta["frozen_hypothesis"],
            "reviewed_at": now,
            "reviewer_id": REVIEWER_ID,
            "reviewer_function": REVIEWER_FUNCTION,
            "reviewer_model_family": REVIEWER_FAMILY,
            "review_order": "BLIND_STAGE_1_CRITERIA_ONLY",
            "frozen_criteria": {
                "criteria_freeze_uri": "workstreams/po03/evidence/criteria-freeze.json",
                "criteria_freeze_sha256": frozen["criteria_freeze_sha256"],
                "source_lock_uri": "workstreams/po03/evidence/source-lock.json",
                "source_lock_sha256": frozen["source_lock_sha256"],
                "acceptance_contract_uri": meta["acceptance_contract_uri"],
                "acceptance_contract_sha256": meta["acceptance_contract_sha256"],
                "immutable_input_manifest_sha256": meta["immutable_input_manifest_sha256"],
            },
            "rubric_freeze": freeze,
            "target": {
                "result_slot": meta["result_slot"],
                "result_uri": comp["result_uri"],
                "result_commit_id": comp["result_commit_id"],
                "completed_receipt_sha256": comp["completed_receipt_sha256"],
                "parent_ingested_receipt_sha256": comp["parent_ingested_receipt_sha256"],
                "coordinator_state": comp["coordinator_state"],
                "reviewed_at_base_commit": args.base_commit,
            },
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "critical": d.dimension in rb.CRITICAL,
                    "verdict": d.verdict,
                    "detail": d.detail,
                    "evidence": d.evidence,
                }
                for d in review.dimensions
            ],
            "tests_rerun_by_reviewer": rerun,
            "hidden_cases": freeze["hidden_cases"],
            "immutable_artifact_readback": readback,
            "defects": review.defects,
            "limitations": review.limitations,
            "recommendation": review.recommendation,
            "terminal_acceptance_claimed": False,
            "acceptance_authority_note": (
                "Consequential acceptance requires a second frontier-family challenger. "
                "This receipt is a recommendation only and never sets ACCEPTED."
            ),
            "decision_changed": [],
        }
        (out_dir / f"{tid}.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary["recommendations"][tid] = {
            "route_id": meta["route_id"],
            "recommendation": review.recommendation,
            "defect_count": len(review.defects),
            "tests_rerun": sum(int(r.get("ran", 0)) for r in rerun),
            "readback_all_match": all(r["immutable_readback_match"] for r in readback) if readback else False,
        }

    (out_dir.parent / "evidence" / "stage1-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["recommendations"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
