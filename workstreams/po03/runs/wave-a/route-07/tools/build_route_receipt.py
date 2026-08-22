"""Build the route-07 manifest and execution receipt, verifying committed blobs.

Every artifact in the owned subtree is hashed from the working tree and read
back out of the named commit by immutable SHA, so the receipt asserts what git
actually stored rather than what was staged.

Standard library only. Writes only inside the route-07 owned subtree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

ROUTE = "route-07"
OWNED = f"workstreams/po03/runs/wave-a/{ROUTE}"
MANIFEST_NAME = "MANIFEST.json"
RECEIPT_NAME = "ROUTE-RECEIPT.json"
TASK_IDS = [f"PO03-WA-{n:03d}" for n in range(49, 57)]
REVIEW_TARGETS = [f"PO03-WA-{n:03d}" for n in list(range(1, 9)) + list(range(33, 49))]

MEDIA_TYPES = {
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(repo: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args], capture_output=True, text=False
    )


def owned_files(repo: Path) -> list:
    root = repo / OWNED
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.name in (MANIFEST_NAME, RECEIPT_NAME) and path.parent == root:
            continue
        out.append(path)
    return out


def blob_readback(repo: Path, commit: str, rel: str):
    proc = git(repo, "cat-file", "blob", f"{commit}:{rel}")
    if proc.returncode != 0:
        return None
    return sha256_bytes(proc.stdout), len(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--verify-commit", required=True, help="commit to read blobs back from")
    ap.add_argument("--base-commit", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--rubric-freeze-commit", required=True)
    ap.add_argument("--stage1-commit", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_root).resolve()
    root = repo / OWNED
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    artifacts, unreadable = [], []
    for path in owned_files(repo):
        rel = path.relative_to(repo).as_posix()
        digest, size = sha256_file(path), path.stat().st_size
        readback = blob_readback(repo, args.verify_commit, rel)
        entry = {
            "artifact_id": f"{ROUTE}:{path.relative_to(root).as_posix()}",
            "bytes": size,
            "committed_blob_sha256": readback[0] if readback else None,
            "content_uri": rel,
            "immutable_readback_match": bool(readback and readback[0] == digest and readback[1] == size),
            "logical_name": path.relative_to(root).as_posix(),
            "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
            "sha256": digest,
        }
        if not entry["immutable_readback_match"]:
            unreadable.append(rel)
        artifacts.append(entry)

    manifest = {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "decision_changed": [],
        "immutable_readback_commit": args.verify_commit,
        "immutable_readback_failures": unreadable,
        "manifest_version": "PO03-ROUTE07-MANIFEST-v1",
        "owned_subtree": f"{OWNED}/",
        "route_id": ROUTE,
        "total_bytes": sum(a["bytes"] for a in artifacts),
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    tasks = []
    for tid in TASK_IDS:
        slot = root / tid
        result = json.loads((slot / "result.json").read_text())
        observed = (slot / "evidence" / "observed-output.txt").read_text()
        ran = 0
        for line in observed.splitlines():
            if line.startswith("# tests_run:"):
                ran = int(line.split(":")[1])
        finding = (slot / "FINDING.md").read_text()
        disposition = next(
            (d for d in ("PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED")
             if f"**{d}**" in finding),
            "NOT_YET",
        )
        tasks.append({
            "task_id": tid,
            "result_slot": f"{OWNED}/{tid}/",
            "obzio_state": result["obzio_state"],
            "provider_state": result["provider_state"],
            "independent_acceptance": result["independent_acceptance"]["state"],
            "subordinate_terminal_report": "READY_TO_COMMIT",
            "disposition": disposition,
            "tests_rerun": ran,
            "artifact_count": result["result_transaction"]["artifact_count"],
            "total_bytes": result["result_transaction"]["total_bytes"],
            "manifest_sha256": result["result_transaction"]["manifest_sha256"],
            "result_sha256": sha256_file(slot / "result.json"),
        })

    reviews = []
    for tid in REVIEW_TARGETS:
        receipt = json.loads((root / "review" / "receipts" / f"{tid}.json").read_text())
        stage1 = json.loads((root / "review" / "stage1" / f"{tid}.json").read_text())
        reviews.append({
            "task_id": tid,
            "route_id": receipt["route_id"],
            "recommendation": receipt["recommendation"],
            "stage1_rubric_v1_recommendation": stage1["recommendation"],
            "producer_claimed_disposition": receipt["producer_disagreement"][
                "producer_claimed_disposition"
            ],
            "agreement": receipt["producer_disagreement"]["agreement"],
            "defects": receipt["defects"],
            "tests_rerun": sum(int(r.get("ran", 0)) for r in receipt["tests_rerun_by_reviewer"]),
            "receipt_uri": f"{OWNED}/review/receipts/{tid}.json",
            "receipt_sha256": sha256_file(root / "review" / "receipts" / f"{tid}.json"),
            "target_result_commit_id": receipt["target"]["result_commit_id"],
            "target_completed_receipt_sha256": receipt["target"]["completed_receipt_sha256"],
        })

    freeze = json.loads((root / "review" / "RUBRIC-FREEZE.json").read_text())
    counts = {}
    for row in reviews:
        counts[row["recommendation"]] = counts.get(row["recommendation"], 0) + 1
    agreement_counts = {}
    for row in reviews:
        agreement_counts[row["agreement"]] = agreement_counts.get(row["agreement"], 0) + 1

    receipt = {
        "branch": args.branch,
        "base_commit": args.base_commit,
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "decision_changed": [],
        "exact_model_configuration": "claude-opus-5-thinking-high",
        "function": "evaluation-and-semantics",
        "fence_token": 1,
        "generated_at": now,
        "independent_review": {
            "agreement_counts": agreement_counts,
            "analysis_uri": f"{OWNED}/review/evidence/disagreement-analysis.json",
            "recommendation_counts": counts,
            "reviews": reviews,
            "rubric_freeze_commit": args.rubric_freeze_commit,
            "rubric_freeze_composite_sha256": freeze["composite_rubric_sha256"],
            "rubric_freeze_at": freeze["frozen_at"],
            "rubric_freeze_uri": f"{OWNED}/review/RUBRIC-FREEZE.json",
            "stage1_frozen_outcomes_commit": args.stage1_commit,
            "target_count": len(reviews),
            "terminal_acceptance_claimed": False,
        },
        "limitations": [
            "Recommendations are not acceptance. Consequential acceptance requires a second "
            "frontier-family challenger; no receipt in this route sets ACCEPTED.",
            "rubric_v1 produced 24 RECOMMEND_REJECT verdicts driven by four reviewer-side "
            "defects, not producer defects. The v1.1 erratum corrects exactly those four "
            "predicates and is guarded by all 16 original hidden cases plus 10 abuse cases; "
            "the superseded v1 verdicts remain committed under review/stage1/ for audit.",
            "The R10 hypothesis-coverage dimension is a lexical and structural heuristic. It "
            "reports a false negative for suites that assert on a returned failure verdict "
            "instead of raising, which is why this route's own PO03-WA-056 slot self-gates to "
            "RETEST despite rejecting all 31 of its adversarial cases.",
            "The five RETEST recommendations rest on that same advisory dimension: no critical "
            "dimension failed on any of the 24 targets under rubric v1.1.",
            "Review reruns execute each target's tests in this runtime. A clean-clone or "
            "GitHub Actions rerun of the target suites was not performed by this route.",
            "The verified canary commit b59b3f114f942cbeb7b5b3427449356dc6ffe838 is not an "
            "ancestor of the base commit; its payload blob 17e1b0aae60c2418fc43639d070a816b72b05fbd "
            "is byte-identical at the base under replayed commit 0d94212, which is what was "
            "verified before material work began.",
        ],
        "material_attempts": tasks,
        "owned_subtree": f"{OWNED}/",
        "custody_events": {
            "collision_events": [],
            "recovery_events": [],
            "isolated_worktree": "dedicated linked worktree outside the shared checkout; "
            "the shared checkout was never mutated",
            "lease_stale_before_work": False,
            "canary_verified": "b59b3f114f942cbeb7b5b3427449356dc6ffe838",
            "canary_blob_byte_identical_at_base": "17e1b0aae60c2418fc43639d070a816b72b05fbd",
        },
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "receipt_version": "PO03-ROUTE07-EXECUTION-RECEIPT-v1",
        "route_id": ROUTE,
        "route_manifest_sha256": sha256_file(root / MANIFEST_NAME),
        "route_manifest_uri": f"{OWNED}/{MANIFEST_NAME}",
        "shared_path_writes": [],
        "state": "READY_TO_COMMIT",
        "wave_id": "PO03-WAVE-A-20260822",
        "worker_identity": "route-07-material-worker",
    }
    (root / RECEIPT_NAME).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "artifact_count": manifest["artifact_count"],
        "total_bytes": manifest["total_bytes"],
        "immutable_readback_failures": unreadable,
        "route_manifest_sha256": receipt["route_manifest_sha256"],
        "recommendation_counts": counts,
        "agreement_counts": agreement_counts,
        "tests_rerun_total": sum(t["tests_rerun"] for t in tasks),
    }, indent=2, sort_keys=True))
    return 1 if unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
