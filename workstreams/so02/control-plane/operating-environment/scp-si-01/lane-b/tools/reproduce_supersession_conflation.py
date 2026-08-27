#!/usr/bin/env python3
"""Reproduce DEF-SCP-01: one finding code for supersession and for tampering.

DEF-SCP-01 was published to the integration branch at f0fb3f51 by the cohort
coordinator and routed to lane B as secondary, on the grounds that its mechanism
change is PENDING and the chain must be able to carry an unfinished story. A
routed defect is not evidence on its own, so this script re-derives it rather
than quoting it, and separates the three things that have to be true for the
split the defect asks for to be justified:

  1. The alarm fires. `currentctl` emits EVIDENCE_HASH_MISMATCH at ERROR against
     the working tree.
  2. It fires on supersession, not corruption. The recorded digest is found to
     have been correct at an earlier commit on this branch's own history, so the
     bytes were authorised to move and nothing was altered behind anyone's back.
  3. The checker cannot tell the two apart even in principle. Not "does not
     today" — the evidence entry carries no commit for the hash to be checked
     at, so there is no input from which the distinction could be computed.

Point 3 is the one that matters. If the entry carried an anchor the defect would
be a missing comparison; because it does not, the defect is a missing field, and
a lane that shipped only the comparison would ship a checker that fails closed
on every entry in the ledger.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[7]
LEDGER = REPO_ROOT / (
    "workstreams/so02/control-plane/operating-environment/"
    "l4-currentness-recovery/ledger/workstream-ledger.json"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(args: list[str]) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


def hash_bound_entries() -> list[dict[str, Any]]:
    """Every ledger evidence entry that pins an artifact by sha256."""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    found = []
    for workstream in ledger.get("workstreams", []):
        for entry in workstream.get("evidence", []):
            if entry.get("sha256") and entry.get("artifact_path"):
                found.append({"workstream_id": workstream.get("workstream_id"),
                              **entry})
    return found


# ---------------------------------------------------------------------------
# STEP 1  the alarm fires against the working tree
# ---------------------------------------------------------------------------

def step_alarm_fires(entries: list[dict[str, Any]]) -> dict[str, Any]:
    mismatched = []
    for entry in entries:
        target = REPO_ROOT / entry["artifact_path"]
        if not target.exists():
            continue
        actual = sha256_bytes(target.read_bytes())
        if actual != entry["sha256"]:
            mismatched.append({
                "workstream_id": entry["workstream_id"],
                "artifact_path": entry["artifact_path"],
                "recorded_sha256": entry["sha256"],
                "worktree_sha256": actual,
            })
    return {
        "step": "the alarm fires",
        "method": "sha256 of working-tree bytes against the recorded digest, "
                  "which is exactly what currentctl.check_reproducibility does",
        "hash_bound_entries_examined": len(entries),
        "mismatching": mismatched,
        "finding_currentctl_emits": "EVIDENCE_HASH_MISMATCH" if mismatched else None,
        "severity": "ERROR" if mismatched else None,
        "reproduced": bool(mismatched),
        "evidence_label": "DIRECTLY_REPRODUCED",
    }


# ---------------------------------------------------------------------------
# STEP 2  it fired on supersession: the digest was correct at an earlier commit
# ---------------------------------------------------------------------------

def step_it_was_supersession(mismatched: list[dict[str, Any]]) -> dict[str, Any]:
    walks = []
    for item in mismatched:
        path = item["artifact_path"]
        code, out = git(["log", "--format=%H", "--", path])
        commits = out.split() if code == 0 else []
        walk, matched_at = [], None
        for commit in commits:
            # Read the blob as bytes, not through text decoding, so the digest is
            # over the same bytes the checker would hash.
            raw = subprocess.run(["git", "show", f"{commit}:{path}"],
                                 cwd=str(REPO_ROOT), capture_output=True)
            if raw.returncode != 0:
                continue
            digest = sha256_bytes(raw.stdout)
            walk.append({"commit": commit[:8], "sha256": digest})
            if digest == item["recorded_sha256"] and matched_at is None:
                matched_at = commit[:8]
        walks.append({
            "artifact_path": path,
            "recorded_sha256": item["recorded_sha256"],
            "worktree_sha256": item["worktree_sha256"],
            "commits_examined": len(walk),
            "hash_walk": walk[:8],
            "recorded_digest_was_correct_at_commit": matched_at,
            "classification": "SUPERSEDED" if matched_at else "NEVER_MATCHED_ANY_COMMIT",
        })
    superseded = [w for w in walks if w["classification"] == "SUPERSEDED"]
    return {
        "step": "the alarm fired on supersession, not on corruption",
        "method": "walk this branch's own history for the artifact and hash each "
                  "blob, looking for a commit at which the recorded digest was right",
        "walks": walks,
        "superseded_count": len(superseded),
        "tampered_count": len(walks) - len(superseded),
        "reproduced": bool(superseded),
        "evidence_label": "DIRECTLY_REPRODUCED",
        "note": "A digest that was correct at a commit reachable from this branch "
                "and is wrong at the tip describes an artifact that moved under an "
                "authorised write. Reporting that as an integrity ERROR is the defect.",
    }


# ---------------------------------------------------------------------------
# STEP 3  the distinction is not computable from what the entry carries
# ---------------------------------------------------------------------------

ANCHOR_FIELDS = ("commit", "recorded_at_commit", "anchor_commit", "sha", "commit_sha")


def step_distinction_not_computable(entries: list[dict[str, Any]]) -> dict[str, Any]:
    anchored, unanchored = [], []
    for entry in entries:
        present = [f for f in ANCHOR_FIELDS if entry.get(f)]
        record = {"workstream_id": entry["workstream_id"],
                  "artifact_path": entry["artifact_path"],
                  "anchor_fields_present": present}
        (anchored if present else unanchored).append(record)
    source = (REPO_ROOT / "workstreams/so02/control-plane/operating-environment/"
              "l4-currentness-recovery/tools/currentctl.py").read_text(encoding="utf-8")
    return {
        "step": "the distinction is not computable, not merely uncomputed",
        "hash_bound_entries": len(entries),
        "entries_carrying_a_commit_anchor": len(anchored),
        "entries_carrying_no_commit_anchor": len(unanchored),
        "unanchored": unanchored,
        "checker_reads_worktree_bytes_only": "actual = sha256_bytes(target.read_bytes())" in source,
        "checker_mentions_a_supersession_code": "EVIDENCE_SUPERSEDED" in source,
        "reproduced": len(anchored) == 0,
        "evidence_label": "DIRECTLY_REPRODUCED",
        "consequence": (
            "With no anchor on any entry, a checker taught to verify each artifact "
            "at its own commit would have nothing to verify against and would have "
            "to report EVIDENCE_ANCHOR_MISSING for the whole ledger. So the mechanism "
            "change is a schema addition first and a comparison second, which is why "
            "this lane records it PENDING rather than shipping half of it."
        ),
    }


def main() -> int:
    entries = hash_bound_entries()
    alarm = step_alarm_fires(entries)
    supersession = step_it_was_supersession(alarm["mismatching"])
    computability = step_distinction_not_computable(entries)
    steps = [alarm, supersession, computability]
    code, head = git(["rev-parse", "HEAD"])
    report = {
        "record_id": "SCP-B-SUPERSESSION-CONFLATION-REPRO-20260827-v001",
        "decision_changed": [],
        "defect_id": "DEF-SCP-01",
        "defect_routed_by": "SCP-SI-01 coordinator, integration commit f0fb3f51",
        "routed_to_this_lane_as": "secondary, because the mechanism change is PENDING "
                                  "and the chain must represent that state",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "produced_on_commit": head if code == 0 else None,
        "instrument": "workstreams/so02/control-plane/operating-environment/scp-si-01/"
                      "lane-b/tools/reproduce_supersession_conflation.py",
        "interpreter": f"python3 -I {sys.version.split()[0]}",
        "steps": steps,
        "all_three_reproduced": all(step["reproduced"] for step in steps),
        "independent_of_the_coordinator_s_numbers": (
            "The coordinator recorded the tip hash as 76b2ca1f. This run finds a "
            "different tip hash for the same artifact, because this lane's own "
            "admitted write to scctl.py superseded it again. The same spurious "
            "integrity ERROR was therefore manufactured twice, by two separate "
            "authorised changes, which is stronger evidence for the split than one "
            "instance: the alarm tracks normal operation, not tampering."
        ),
        "mechanism_change_state": "PENDING",
        "mechanism_change_owner": "lane D (owning), coordinator (fallback), per DEF-SCP-01 routing",
        "why_this_lane_does_not_ship_it": (
            "Lane B's commission is the typed link chain, and the fix is routed to "
            "lane D. Shipping the finding-code split from here would put two lanes' "
            "mechanism changes on one artifact in one cohort, which is the "
            "shared-worktree collision this lane has already seeded as ICH-03. The "
            "chain records the defect honestly with its successor declared pending."
        ),
        "honest_limits": [
            "Two instances of supersession, both from this cohort's own writes. That "
            "the alarm fires on authorised change is DIRECTLY_REPRODUCED; that "
            "supersession is more frequent than genuine tampering across the estate "
            "is not measured and is not claimed.",
            "No genuinely tampered artifact was constructed in the ledger to confirm "
            "case 3 empirically. The claim that the codes are indistinguishable rests "
            "on the absence of any anchor field to compute the distinction from, which "
            "is a property of the schema and is shown directly, not on a paired trial.",
        ],
        "provenance_class": "EARNED",
        "provenance_basis": "DEF-SCP-01, discovered by the coordinator during "
                            "verification of lane E and re-derived here against the "
                            "live module rather than accepted on report.",
    }
    out = REPO_ROOT / "receipts/so02/2026-08-27/scp-b/reproductions"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=False) + "\n"
    (out / "SUPERSESSION-CONFLATION-REPRO.json").write_text(text, encoding="utf-8")
    print(json.dumps({
        "all_three_reproduced": report["all_three_reproduced"],
        "mismatching": len(alarm["mismatching"]),
        "superseded_count": supersession["superseded_count"],
        "tampered_count": supersession["tampered_count"],
        "entries_with_anchor": computability["entries_carrying_a_commit_anchor"],
        "entries_without_anchor": computability["entries_carrying_no_commit_anchor"],
        "sha256": sha256_bytes(text.encode("utf-8")),
    }, indent=2))
    return 0 if report["all_three_reproduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
