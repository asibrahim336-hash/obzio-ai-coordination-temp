#!/usr/bin/env python3
"""Add ICH-07 to the chain seed: DEF-SCP-01, mechanism change pending.

Kept as a script rather than a hand edit so the seed file's provenance is
reproducible: the seed is the input to `append_chain_links.py`, and a chain seed
that cannot be rebuilt is exactly the unreproducible evidence class this estate
refuses. Idempotent — running it twice leaves one ICH-07.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[7]
SEED = (REPO_ROOT / "workstreams/so02/control-plane/operating-environment/scp-si-01/"
        "lane-b/chains/SCP-B-CHAIN-SEED-20260827-v001.json")
INTEGRATION_COMMIT = "f0fb3f51a25db67b33bdd558c73055f3d02ddb60"

DEFECT_DOC = ("workstreams/so02/control-plane/operating-environment/scp-si-01/"
              "DEFECT-SCP-01-SUPERSESSION-READS-AS-TAMPERING.json")
REPRO_DOC = "receipts/so02/2026-08-27/scp-b/reproductions/SUPERSESSION-CONFLATION-REPRO.json"


def sha256_of(rel: str) -> str:
    return hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()


CHAIN = {
    "chain_id": "ICH-07-SUPERSESSION-READS-AS-TAMPERING",
    "title": "One finding code for a superseded artifact and a tampered one",
    "note": (
        "Picked up mid-run. The coordinator published DEF-SCP-01 to the integration "
        "branch at f0fb3f51 after this lane was dispatched, and routed it here as "
        "secondary precisely because its mechanism change is PENDING. The lane "
        "re-derived it against the live module instead of accepting the report, then "
        "recorded it open. This is the second chain in the seed whose successor is "
        "declared rather than shipped, and the first that arrived from outside the lane."
    ),
    "nodes": [
        {
            "node_id": "ICH-07-OBS",
            "node_kind": "OBSERVATION",
            "occurred_at": "2026-08-27T05:26:00Z",
            "derives_from": [],
            "title": "An integrity ERROR fired on an artifact nobody tampered with",
            "statement": (
                "currentctl compile emits EVIDENCE_HASH_MISMATCH at ERROR severity on "
                "urn:obzio:l4:workstream:WS-SO02-CONTROL-PLANE, because the ledger's "
                "recorded digest for scctl.py no longer matches the working tree. "
                "Walking this branch's history for that path shows the recorded digest "
                "e6d0b2d8 was correct at commit 9887f33e, was moved to 76b2ca1f by the "
                "authorised EC-13 purge at 3b97d6ff, and was moved again to 70a6494a by "
                "this lane's own admitted write at a1592234. Two authorised changes, two "
                "identical integrity alarms, no tampering at any point."
            ),
            "evidence_label": "DIRECTLY_REPRODUCED",
            "provenance_class": "EARNED",
            "provenance_basis": (
                "DEF-SCP-01, found by the coordinator during verification of lane E and "
                "reproduced independently here. The coordinator's hash walk ended at "
                "76b2ca1f; this lane's walk finds a third digest beyond it, so the "
                "reproduction is not a restatement of the original observation."
            ),
            "evidence_citations": [
                {"artifact_path": REPRO_DOC, "sha256": sha256_of(REPRO_DOC),
                 "field": "steps[0] the alarm fires, steps[1] the hash walk"},
                {"artifact_path": DEFECT_DOC, "sha256": sha256_of(DEFECT_DOC),
                 "field": "reproduction.hash_walk"},
            ],
        },
        {
            "node_id": "ICH-07-DEF",
            "node_kind": "DEFECT",
            "occurred_at": "2026-08-27T05:32:00Z",
            "derives_from": ["ICH-07-OBS"],
            "title": "DEF-SCP-01 — EVIDENCE_HASH_MISMATCH conflates supersession with corruption",
            "statement": (
                "The checker hashes working-tree bytes and compares against the recorded "
                "digest, so one ERROR code covers two situations demanding opposite "
                "responses: an artifact altered behind the ledger's back, and an artifact "
                "that legitimately moved on. The deeper finding, which the routing did not "
                "state, is that the distinction is not merely uncomputed but uncomputable "
                "from what the ledger holds: 0 of 5 hash-bound evidence entries carry any "
                "commit the digest was taken at. A lane that shipped only the comparison "
                "the defect asks for would produce a checker with nothing to compare "
                "against, failing closed across the entire ledger. The mechanism change is "
                "therefore a schema addition first and a finding-code split second."
            ),
            "evidence_label": "DIRECTLY_REPRODUCED",
            "provenance_class": "EARNED",
            "provenance_basis": (
                "DEF-SCP-01. Same class as the five chains already seeded: an alarm that "
                "fires on normal operation is a control that will be ignored, which is the "
                "estate's own LESSON_DOCUMENTED failure wearing a different hat."
            ),
            "pending_successor": {
                "node_kind": "MECHANISM_CHANGE",
                "state": "PENDING",
                "owner": "lane D (owning, per DEF-SCP-01 routing); SCP-SI-01 coordinator (declared fallback)",
                "reason": (
                    "The fix is routed to lane D, which owns failure-to-learning. Lane B's "
                    "commission is the chain itself. Landing the split from this lane would "
                    "put two lanes' mechanism changes on one artifact inside one cohort, "
                    "which is the collision this seed already carries as ICH-03, and would "
                    "make this lane the producer and the acceptor of its own fix. The chain "
                    "records the defect with the successor declared, which is what the "
                    "pending mechanism exists for."
                ),
                "candidate_mechanisms": [
                    "Add a required recorded_at_commit to every hash-bound ledger evidence "
                    "entry, and report EVIDENCE_ANCHOR_MISSING where it is absent rather "
                    "than defaulting to either verdict.",
                    "Split the code: EVIDENCE_SUPERSEDED at INFO when the digest was correct "
                    "at its anchor and has since changed, EVIDENCE_HASH_MISMATCH at ERROR "
                    "when it was wrong at its own anchor.",
                    "Regression test the three cases the defect names, including the one "
                    "that matters — correct at anchor, changed at tip — asserting INFO and "
                    "not ERROR.",
                ],
                "expires_when": "a mechanism change link derives from this defect",
            },
            "evidence_citations": [
                {"artifact_path": REPRO_DOC, "sha256": sha256_of(REPRO_DOC),
                 "field": "steps[2] the distinction is not computable"},
                {"artifact_path": DEFECT_DOC, "sha256": sha256_of(DEFECT_DOC),
                 "field": "required_mechanism_change"},
            ],
        },
    ],
}


def main() -> int:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    seed["integration_commit_audited_against"] = INTEGRATION_COMMIT
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
        "integration_commit_audited_against": INTEGRATION_COMMIT,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
