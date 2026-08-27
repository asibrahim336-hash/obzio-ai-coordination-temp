#!/usr/bin/env python3
"""Add ICH-08 to the chain seed: the concurrency gate this lane tripped.

The eighth chain is the only one this lane found by being wrong rather than by
looking. It declared its own branch absent from the remote, the gate admitted the
false declaration, and the reason it admitted it is a fail-open worth recording.

Idempotent. Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[7]
SEED = (REPO_ROOT / "workstreams/so02/control-plane/operating-environment/scp-si-01/"
        "lane-b/chains/SCP-B-CHAIN-SEED-20260827-v001.json")

REPRO = "receipts/so02/2026-08-27/scp-b/reproductions/MOVEMENT-GATE-FAILOPEN-REPRO.json"
SUPERSEDED_ADMISSION = ("receipts/so02/2026-08-27/scp-b/admission/"
                        "WRITE-ADMISSION-SCP-B-01-SUPERSEDED-FALSE-OBSERVATION.json")
OBSERVATION = ("workstreams/so02/control-plane/operating-environment/scp-si-01/"
               "lane-b/chains/CONCURRENCY-OBSERVATION-SCP-B.json")


def sha256_of(rel: str) -> str:
    return hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()


CHAIN = {
    "chain_id": "ICH-08-MOVEMENT-GATE-FAILS-OPEN",
    "title": "Omitting one optional field skips the concurrency gate's only independent signal",
    "note": (
        "Found by tripping it, not by reading it. This lane's own write declaration "
        "asserted that its branch did not exist on the remote; the branch existed at "
        "a1592234, and the gate returned SETTLED. Seeded because a chain that only "
        "records defects the lane found in other people's work is not a chain that "
        "models this estate either."
    ),
    "nodes": [
        {
            "node_id": "ICH-08-OBS",
            "node_kind": "OBSERVATION",
            "occurred_at": "2026-08-27T05:58:00Z",
            "derives_from": [],
            "title": "A false declaration was admitted, and git push is what revealed it",
            "statement": (
                "Lane B's write declaration carried ref_sha_at_observation: null with the "
                "stated ground that the ref did not exist on the remote yet. "
                "write_admission returned WRITE_ADMITTED with concurrency "
                "SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT. The subsequent push printed "
                "'a1592234..a24b0b6d' — a range, not a new-branch line — so the ref had "
                "existed all along, published earlier in this same run. The gate admitted "
                "a statement that was false about the very ref it was gating."
            ),
            "evidence_label": "DIRECTLY_REPRODUCED",
            "provenance_class": "EARNED",
            "provenance_basis": (
                "The silent-push defect seeded as ICH-04 is why this lane reads push "
                "output and re-checks with ls-remote instead of trusting exit 0. That "
                "habit, earned from a previous defect, is what surfaced this one."
            ),
            "evidence_citations": [
                {"artifact_path": SUPERSEDED_ADMISSION, "sha256": sha256_of(SUPERSEDED_ADMISSION),
                 "field": "the retained WRITE_ADMITTED obtained on the false observation"},
                {"artifact_path": OBSERVATION, "sha256": sha256_of(OBSERVATION),
                 "field": "correction"},
            ],
        },
        {
            "node_id": "ICH-08-DEF",
            "node_kind": "DEFECT",
            "occurred_at": "2026-08-27T06:02:00Z",
            "derives_from": ["ICH-08-OBS"],
            "title": "DEF-SCP-B-MOVEMENT-GATE-FAILS-OPEN",
            "statement": (
                "concurrency_verdict branches on `moved is True` and on `not observable`, "
                "so the third outcome — observable, movement not determinable, which is "
                "what observe_ref_movement honestly returns when recorded_sha is None — "
                "reaches the terminal else and is reported SETTLED and writable. Three "
                "cases were run against the live remote: the field omitted gives SETTLED "
                "and writable true; a deliberately wrong SHA gives "
                "IN_FLIGHT_REF_MOVED_SINCE_DECLARATION and writable false; the truthful "
                "SHA passes. The gate is therefore not weak but skippable, and it is "
                "skipped by default for any declaration whose reversal is "
                "DELETE_CREATED_REF, since that method carries no recorded_sha at all. "
                "The module's own docstring calls ref movement 'the only signal that can "
                "catch a writer the agent layer cannot see'."
            ),
            "evidence_label": "DIRECTLY_REPRODUCED",
            "provenance_class": "EARNED",
            "provenance_basis": (
                "DEF-SCP-B-MOVEMENT-GATE-FAILS-OPEN, reproduced in three cases against "
                "the live remote. Same class as ICH-02: the branch enumerates the "
                "outcomes that are unsafe and lets the remainder, including 'could not "
                "tell', reach a permissive default. ICH-02's fix was to invert to an "
                "allowlist, and that is the fix shape here."
            ),
            "pending_successor": {
                "node_kind": "MECHANISM_CHANGE",
                "state": "PENDING",
                "owner": "owner of the write-admission subsystem: lane D, or the SCP-SI-01 coordinator as declared fallback",
                "reason": (
                    "Every lane in this cohort is currently pushing through this gate. A "
                    "lane that is itself being gated cannot change the gate's verdict "
                    "logic mid-cohort without becoming the producer of its own admission "
                    "criteria, which is the self-acceptance shape the estate refused in "
                    "CUR-ORCH-QUAL-01. Lane B corrected its own observation so the check "
                    "runs against a real value, re-admitted, and routed the fix."
                ),
                "candidate_mechanisms": [
                    "Invert the branch to an allowlist: writable only when movement is "
                    "observed and moved is False. Every other outcome, including None, "
                    "refuses.",
                    "Refuse a declaration that omits ref_sha_at_observation for a ref that "
                    "ls-remote shows present, and accept the omission only for a ref the "
                    "remote genuinely does not have — the one case where None is honest.",
                    "Give DELETE_CREATED_REF a recorded_sha of its own, or require the "
                    "concurrency block to supply one, so the movement check is never "
                    "silently unarmed by the choice of reversal method.",
                ],
                "expires_when": "a mechanism change link derives from this defect",
            },
            "evidence_citations": [
                {"artifact_path": REPRO, "sha256": sha256_of(REPRO),
                 "field": "cases.A_recorded_sha_omitted, cases.B_recorded_sha_wrong"},
            ],
        },
    ],
}


def main() -> int:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    seed["chains"] = [c for c in seed["chains"] if c["chain_id"] != CHAIN["chain_id"]]
    seed["chains"].append(CHAIN)
    seed["open_chains_with_a_pending_mechanism"] = [
        c["chain_id"] for c in seed["chains"]
        if any(n.get("pending_successor") for n in c["nodes"])
    ]
    SEED.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "chains": [c["chain_id"] for c in seed["chains"]],
        "open": seed["open_chains_with_a_pending_mechanism"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
