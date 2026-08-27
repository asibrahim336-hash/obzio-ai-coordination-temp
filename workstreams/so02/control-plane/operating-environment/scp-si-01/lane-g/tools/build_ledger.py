#!/usr/bin/env python3
"""Build SCP-SI-01-ACCEPTED-UNIT.jsonl from recomputed git facts plus cited receipts.

Nothing here invents a number. Every field is one of:
  - recomputed directly from git history in this run (`wall_time_evidence:
    DIRECTLY_REPRODUCED`), by reading `raw/oe-lane-wall-time.jsonl`
    (itself produced by `extract_wall_time.py` against the fetched remote), or
  - transcribed from a specific, cited receipt already in this repository
    (`*_evidence: DOCUMENTED`, with a `sources` list naming the file), or
  - stated as `NOT_MEASURABLE` with the reason no instrument in this run could
    supply it (never filled with a plausible-looking placeholder).

The UNITS table below is the one place curated facts live; every row cites the
receipt it came from in its own `sources` field so a reader can check this
script's claims against the same repository it read them from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _find_repo_root(start: Path) -> Path:
    cur = start
    for _ in range(12):
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    raise RuntimeError("could not locate repository root by walking up from " + str(start))


REPO = _find_repo_root(HERE)
WALL_TIME_PATH = REPO / "receipts" / "so02" / "2026-08-27" / "scp-g" / "raw" / "oe-lane-wall-time.jsonl"
WALL_TIME_L3_PATH = REPO / "receipts" / "so02" / "2026-08-27" / "scp-g" / "raw" / "oe-lane-wall-time-l3-unfiltered.jsonl"


def load_wall_time() -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for path in (WALL_TIME_PATH, WALL_TIME_L3_PATH):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            facts[rec["branch"]] = rec
    return facts


def minutes_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    from datetime import datetime
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(end)
    return round((b - a).total_seconds() / 60.0, 1)


NOT_MEASURABLE_RUNTIME = (
    "Nothing available inside a Cloud Agent pod in this run exposes model compute time, "
    "token consumption or GPU/CPU seconds attributable to a lane. Wall time (elapsed clock "
    "time between commits) is a weak proxy at best, since it includes any idle time between "
    "an agent's turns and says nothing about how much of it was model inference versus tool "
    "execution versus the coordinator's own thinking time before dispatch."
)

MODEL_NOT_CONFIRMABLE = (
    "list-cloud-agents and run-info report originalModelName=null for every source='internal' "
    "(locally-dispatched subagent) entry observed in this run, including this lane's own "
    "run-info. The model named at dispatch time is therefore DOCUMENTED as what was requested, "
    "not DIRECTLY_REPRODUCED as an independently confirmed fact."
)

# ---------------------------------------------------------------------------
# The units table. One row per commissioned deliverable. Every claim here is
# cited; see each row's `sources`.
# ---------------------------------------------------------------------------

UNITS: list[dict[str, Any]] = [
    {
        "unit_id": "CUR-ORCH-QUAL-01",
        "programme": "PRE_OE_ROUTE_QUALIFICATION",
        "wave": None,
        "branch": "cursor/so02-cur-orch-qual-01",
        "provider_bcid": "bc-c6f63d58-9611-495a-96f6-2f2dcbef696d",
        "model_requested": "claude-opus-5-thinking-max / claude-opus-5-thinking-max-fast (root controller identity across this lineage; not a single-dispatch model field)",
        "dispatched_at": None,
        "dispatched_at_note": "no single dispatch record; this artifact accreted across a multi-day root-controller lineage. Its PRODUCTION commits (the unit actually judged) are isolated below.",
        "production_commit_range": ["04001dba1c689c90041ea383f3092213756c7ead", "11a60dcf6dbc2eac4e6d975efab5d985ebbabd62"],
        "delivered_at": "2026-08-22T13:50:10+00:00",
        "retries": None,
        "retries_evidence": "NOT_MEASURABLE",
        "retries_note": "predates the receipt-based retry-tracking convention this evidence chain later adopted; no per-attempt record exists for this artifact's own production.",
        "lease_conflicts": None,
        "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": 0,
        "ingestion_failures_evidence": "DOCUMENTED",
        "produced": True,
        "custody_verified_by_same_principal": True,
        "independently_judged": True,
        "judgment_mechanism": "OE-L3-INDEPENDENT-ACCEPTANCE: distinct model family (gpt-5.6-sol-xhigh vs producer's claude-opus-5-thinking-max-fast), criteria committed before verdict, criteria commit a provable git ancestor of the verdict commit, namespace-contained",
        "judgment_criteria_commit": "9a390df3ebdd19e1403317be24c74e6abc249415",
        "judgment_verdict_commit": "541eff445f2acd3cabea91b54c53afae237b9d59",
        "verdict": "INDEPENDENTLY_JUDGED_REFUSED",
        "is_accepted_unit": False,
        "defects_named_by_the_judgment": [
            "DEF-01-READBACK-SHAPE-NOT-TRUTH: a wholly forged read-back record passed the producer's own verifier",
            "DEF-02-DENYLIST-FAILS-OPEN: an IDLE-to-ERROR/FAILED capacity transition passed the producer's own detector silently",
        ],
        "what_survived_challenge": "R1 GitHub immutable-SHA custody, independently re-verified (AC-04); the 22-event hash chain (AC-09); no credential/strategy leakage (AC-11)",
        "evidence_label_for_verdict": "DOCUMENTED",
        "sources": [
            "receipts/so02/2026-08-22/oe-dispatch/CUR01-REFUSAL-INGESTION.json",
            "workstreams/so02/control-plane/operating-environment/scp-si-01/SCP-SI-01-BASELINE.yaml#cur_orch_qual_true_state",
        ],
        "notes": "The only artifact in this repository's full history that has ever been placed in front of a structurally independent acceptor. Its own producer's register (cursor/so02-cur-orch-qual-01 @ 11a60dcf) still reads REQUESTED_NOT_GRANTED; that is the frozen pre-verdict request state and is superseded by this REFUSED verdict, per the baseline's own resolution.",
    },
]


def _oe_lane(unit_id, branch, prefix_facts_key, provider_bcid, model_requested, wave,
             verdict, notes, sources, retries=0, lease_conflicts=None,
             ingestion_failures=0, retries_note=None, lease_note=None) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "programme": "OE_OPERATING_ENVIRONMENT",
        "wave": wave,
        "branch": branch,
        "provider_bcid": provider_bcid,
        "model_requested": model_requested,
        "_wall_time_key": prefix_facts_key,
        "retries": retries,
        "retries_evidence": "DOCUMENTED" if retries_note else ("DOCUMENTED" if retries == 0 else "NOT_MEASURABLE"),
        "retries_note": retries_note or "no retry evidence found for this lane's own production in the read receipts",
        "lease_conflicts": lease_conflicts,
        "lease_conflicts_evidence": "DOCUMENTED" if lease_note else "NOT_MEASURABLE",
        "lease_conflicts_note": lease_note,
        "ingestion_failures": ingestion_failures,
        "ingestion_failures_evidence": "DOCUMENTED",
        "produced": verdict != "FAILED_INCOMPLETE",
        "custody_verified_by_same_principal": verdict not in {"FAILED_INCOMPLETE"},
        "independently_judged": False,
        "judgment_mechanism": None,
        "verdict": verdict,
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DOCUMENTED",
        "sources": sources,
        "notes": notes,
    }


UNITS += [
    _oe_lane("OE-L1-CURSOR-BASELINE", "cursor/oe-l1-cursor-baseline-696d", "cursor/oe-l1-cursor-baseline-696d",
             "1b6c7644-72e0-4a31-96fd-c958df15de45", "claude-opus-5-thinking-max-fast (requested at dispatch)", "1",
             "VERIFIED_ADMISSIBLE",
             "Custody CUSTODY_SOUND, state transition READY_TO_COMMIT -> VERIFIED_ADMISSIBLE, explicitly 'not: ACCEPTED'. "
             "One lease-conflict exposure (shared-worktree collision, wave-wide) with a documented recovery via cherry-pick.",
             ["receipts/so02/2026-08-22/oe-dispatch/LANE-ADMISSION-L1-20260822T2046Z.json",
              "receipts/so02/2026-08-22/oe-l1-cursor-baseline/MANIFEST.json"],
             retries=1, retries_note="cherry-pick recovery from the shared detached HEAD after the SHARED_WORKTREE_COLLISION; LANE-ADMISSION-L1#custody_verification",
             lease_conflicts=1, lease_note="wave-1 SHARED_WORKTREE_COLLISION affected all 5 wave-1 lanes sharing /workspace; L1 was not the reported immune lane"),
    _oe_lane("OE-L2-CAPABILITY-RESEARCH", "cursor/oe-l2-capability-research-696d", "cursor/oe-l2-capability-research-696d",
             "69e38132-1353-45f9-ab32-75aa39d6980d", "claude-opus-5-thinking-max-fast (requested at dispatch)", "1",
             "VERIFIED_ADMISSIBLE",
             "Delivered; held /workspace HEAD at the moment the collision was observed (named as the branch occupying HEAD in the live reproduction).",
             ["receipts/so02/2026-08-22/oe-dispatch/SHARED-WORKTREE-COLLISION-LIVE-REPRODUCTION.json"],
             lease_conflicts=1, lease_note="observed holding /workspace HEAD at the moment of the live SHARED_WORKTREE_COLLISION reproduction"),
    _oe_lane("OE-L3-INDEPENDENT-ACCEPTANCE", "cursor/oe-l3-independent-acceptance-696d", "cursor/oe-l3-independent-acceptance-696d",
             "c0f87d27-7d2f-4ff4-87c7-ba27142c7b07", "gpt-5.6-sol-xhigh (requested at dispatch)", "1",
             "VERIFIED_ADMISSIBLE",
             "This lane IS the judgment mechanism for CUR-ORCH-QUAL-01, not a subject of one. Its own verdict artifact has "
             "itself never been independently re-judged by a further, separate acceptor; the root controller's own "
             "reproduction of 2 of its 4 defect claims is verification by the same principal that dispatched it, not a "
             "third independent layer.",
             ["receipts/so02/2026-08-22/oe-dispatch/CUR01-REFUSAL-INGESTION.json"],
             lease_conflicts=1, lease_note="wave-1 shared-worktree exposure; not reported immune"),
    _oe_lane("OE-L4-CURRENTNESS-RECOVERY", "cursor/oe-l4-currentness-recovery-696d", "cursor/oe-l4-currentness-recovery-696d",
             "70fdf034-7176-4f32-8a90-ef336bbaaffe", "claude-opus-5-thinking-max-fast (requested at dispatch)", "1",
             "VERIFIED_ADMISSIBLE",
             "Delivered. Explicitly documented as the one wave-1 lane structurally immune to the shared-worktree collision, "
             "because it independently created its own worktree at /tmp/oe-l4 before writing.",
             ["receipts/so02/2026-08-22/oe-dispatch/SHARED-WORKTREE-COLLISION-LIVE-REPRODUCTION.json#what_did_not_break"],
             lease_conflicts=0, lease_note="documented immune: 'One lane, OE-L4-CURRENTNESS-RECOVERY, independently created its own worktree ... and was structurally immune'"),
    _oe_lane("OE-L5-CHATGPT-SCALE", "cursor/oe-l5-chatgpt-scale-696d", "cursor/oe-l5-chatgpt-scale-696d",
             "dbee0722-4e75-49e4-bfe6-433ad10512b3", "claude-opus-5-thinking-max-fast (requested at dispatch)", "1",
             "VERIFIED_ADMISSIBLE",
             "Delivered; part of the wave-1 shared-worktree exposure, no immunity claimed for this lane in the record.",
             ["receipts/so02/2026-08-22/oe-dispatch/DISPATCH-RECORD-20260822T2012Z.json"],
             lease_conflicts=1, lease_note="wave-1 shared-worktree exposure; not reported immune"),
    _oe_lane("OE-W2-CURSOR-CONFIG", "cursor/oe-w2-cursor-config-696d", "cursor/oe-w2-cursor-config-696d",
             None, "NOT_MEASURABLE — no dispatch record with a model field exists for wave 2 in the receipts this lane read", "2",
             "VERIFIED_ADMISSIBLE",
             "First lane in the whole programme to achieve full manifest closure including its own read-back record. "
             "Dispatched via isolated per-lane worktrees (the wave-1 postmortem's mandated fix); no collision reported.",
             ["receipts/so02/2026-08-22/oe-dispatch/DERESTRICTION-APPLIED-20260822T2320Z.json#custody_of_the_two_integrated_lanes"],
             lease_conflicts=0, lease_note="no collision reported after the wave-1 fix (dedicated worktree per lane); absence-of-report is weaker evidence than a direct reproduction and is labelled as such"),
    _oe_lane("OE-W3-CREDENTIAL-ESTATE", "cursor/oe-w3-credential-estate-696d", "cursor/oe-w3-credential-estate-696d",
             None, "NOT_MEASURABLE — no dispatch record with a model field exists for wave 2", "2",
             "VERIFIED_ADMISSIBLE",
             "Delivered with the strongest self-check in the programme (hermetic container replay, NetworkMode=none) — "
             "still independently recomputed by the root controller rather than accepted. Falsified two claims this same "
             "root controller had already given the founder directly (COR-01, COR-02).",
             ["receipts/so02/2026-08-22/oe-dispatch/CORRECTIONS-20260822T2330Z.json"],
             lease_conflicts=0),
    _oe_lane("OE-W4-PLATFORM-ROLES", "cursor/oe-w4-platform-roles-696d", "cursor/oe-w4-platform-roles-696d",
             None, "NOT_MEASURABLE — no dispatch record with a model field exists for wave 2", "2",
             "VERIFIED_ADMISSIBLE",
             "Self-corrected its own register before commit after re-running an inventory that first returned an "
             "inconsistent count, and fixed a scanner defect that read supersession statements as re-inheritances.",
             ["receipts/so02/2026-08-22/oe-dispatch/DERESTRICTION-APPLIED-20260822T2320Z.json#custody_of_the_two_integrated_lanes"],
             retries=1, retries_note="re-ran its own model-configuration inventory after a first pass returned an inconsistent count (self-correction before commit)",
             lease_conflicts=0),
    _oe_lane("OE-W5-AGENTIC-OFFICE", "cursor/oe-w5-agentic-office-696d", "cursor/oe-w5-agentic-office-696d",
             "bc-42b8be39-e5be-5400-8535-019c4d9f13e1", "NOT_MEASURABLE — provider bcId matched by name in a concurrency census, but originalModelName is null for this internal-source run", "3",
             "VERIFIED_ADMISSIBLE",
             "Delivered; corrected a miscited command and re-verified its own guide's load-bearing claims before closing.",
             ["receipts/so02/2026-08-22/oe-w5-agentic-office/raw/list-cloud-agents-census.json"],
             lease_conflicts=0),
    _oe_lane("OE-W6-CHATGPT-CONNECTION", "cursor/oe-w6-chatgpt-connection-696d", "cursor/oe-w6-chatgpt-connection-696d",
             "bc-3cc25012-4770-5deb-b207-7d4ee809dcd1", "NOT_MEASURABLE — provider bcId matched by name; originalModelName null", "3",
             "FAILED_INCOMPLETE",
             "Provider error 'Activity task timed out' during analysis, after the network-bound harvest (79 sources) had "
             "already completed. Manifest ABSENT at the point of failure -> inadmissible as delivered, root-cause recorded "
             "as dispatch over-scoping (5 deliverables in one activity budget), not lane incapacity. Its provider agent "
             "record is still visible in ERROR status days later in this lane's own concurrency observation.",
             ["receipts/so02/2026-08-22/oe-dispatch/LANE-FAILURE-W6-20260823T0050Z.json"],
             ingestion_failures=1, lease_conflicts=0),
    _oe_lane("OE-W7-CHATGPT-ROUTE-EVIDENCE", "cursor/oe-w7-route-evidence-696d", "cursor/oe-w7-route-evidence-696d",
             "bc-10daec71-5a06-5a78-beb4-a6c2e97460da", "NOT_MEASURABLE — provider bcId matched by name; originalModelName null", "3-recovery",
             "VERIFIED_ADMISSIBLE",
             "One of two tighter recovery lanes re-dispatched after OE-W6's failure; reused the failed predecessor's "
             "harvest rather than re-fetching (28 of 28 overlapping fetches byte-identical), and produced the finding that "
             "withdrew a mis-specified founder question about a GitHub connector that does not exist.",
             ["receipts/so02/2026-08-22/oe-dispatch/LANE-FAILURE-W6-20260823T0050Z.json#recovery",
              "receipts/so02/2026-08-22/oe-dispatch/QUESTION-CORRECTION-20260823T0125Z.json"],
             lease_conflicts=0),
    _oe_lane("OE-W8-CHATGPT-CONSTITUTION", "cursor/oe-w8-chatgpt-constitution-696d", "cursor/oe-w8-chatgpt-constitution-696d",
             "bc-b0b15e5d-cd46-5eb2-82ad-53c13fd8b41b", "NOT_MEASURABLE — provider bcId matched by name; originalModelName null", "3-recovery",
             "VERIFIED_ADMISSIBLE",
             "The other recovery lane; nominated the founder action later found to require a device (macOS/Windows "
             "desktop app) the founder does not own (DEV-01), corrected before the ranked action list was finalised.",
             ["receipts/so02/2026-08-22/oe-dispatch/DEVICE-GATING-CORRECTION-20260823T0132Z.json"],
             lease_conflicts=0),
    _oe_lane("OE-W9-REASON-GATED-WRITES", "cursor/oe-w9-reason-gated-writes-696d", "cursor/oe-w9-reason-gated-writes-696d",
             None, "NOT_MEASURABLE — no dispatch record with a model field exists for wave 4", "4",
             "VERIFIED_ADMISSIBLE",
             "Built write_admission.py, the very gate this lane (G) is required to invoke. Directly reproduced the fact "
             "that list-cloud-agents shows no branchName for a running subagent lane, including its own — the concurrency "
             "instrument's blind spot this ledger also relies on and discloses.",
             ["workstreams/so02/control-plane/operating-environment/tools/concurrency_observer.py"],
             lease_conflicts=0),
    _oe_lane("OE-W10-PROVENANCE", "cursor/oe-w10-provenance-696d", "cursor/oe-w10-provenance-696d",
             None, "NOT_MEASURABLE — no dispatch record with a model field exists for wave 4", "4",
             "VERIFIED_ADMISSIBLE",
             "Re-derived all 86 constraints against quoted founder text; found 19 verdicts changed and 10 restated on "
             "re-derivation, which is itself evidence that a first-pass provenance classification is not self-verifying.",
             ["receipts/so02/2026-08-23/oe-w10-provenance/MANIFEST.json"],
             lease_conflicts=0),
]

# ---------------------------------------------------------------------------
# The current cohort, in flight. Observed, not assumed: what Lane G could see
# from its own pod at the moment of writing, no more.
# ---------------------------------------------------------------------------

SCP_SNAPSHOT_AT = "2026-08-27T05:19Z"

UNITS += [
    {
        "unit_id": "SCP-SI-01-BASELINE",
        "programme": "SCP_SI_01",
        "wave": None,
        "branch": "cursor/operating-environment-return-20260822-v001",
        "provider_bcid": "bc-c6f63d58-9611-495a-96f6-2f2dcbef696d",
        "model_requested": "NOT_MEASURABLE (coordinator identity persists across this cohort; no single dispatch model field for this specific commit)",
        "delivered_at": "2026-08-27T04:58:57+00:00",
        "wall_time_evidence": "DIRECTLY_REPRODUCED",
        "retries": 0, "retries_evidence": "DOCUMENTED",
        "lease_conflicts": 0, "lease_conflicts_evidence": "DOCUMENTED",
        "lease_conflicts_note": "coordinator wrote from its own root, per its own record; no lane was open yet",
        "ingestion_failures": 0, "ingestion_failures_evidence": "DOCUMENTED",
        "produced": True, "custody_verified_by_same_principal": True,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "VERIFIED_ADMISSIBLE",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-SI-01-BASELINE.json"],
        "notes": "The cohort's pre-lane freeze. decision_changed: [] — no founder action requested at this step.",
    },
    {
        "unit_id": "SCP-A-REFUSAL-REPAIR",
        "programme": "SCP_SI_01", "wave": None,
        "branch": "cursor/scp-a-refusal-repair-696d",
        "provider_bcid": "bc-ad6634d3-37ca-58f6-a071-cddbf1983fc4",
        "model_requested": "NOT_MEASURABLE (originalModelName null for this internal-source run, DIRECTLY_REPRODUCED via list-cloud-agents)",
        "delivered_at": "2026-08-27T05:14:00+00:00",
        "wall_time_evidence": "DIRECTLY_REPRODUCED",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": 0, "lease_conflicts_evidence": "DIRECTLY_REPRODUCED",
        "lease_conflicts_note": "Lane G observed a dedicated worktree for this lane at /tmp/lane-a, isolated from Lane G's own worktree; no shared-HEAD contention observed",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "ingestion_failures_note": "not yet integrated into the return branch as of this snapshot; nothing to admit or refuse yet",
        "produced": True, "custody_verified_by_same_principal": False,
        "custody_note": "3 commits pushed to its own branch and confirmed via git ls-remote (matches lane_guard's CONFIRMED_PUBLISHED); not yet root-controller-admitted",
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "IN_FLIGHT_PUBLISHED_NOT_YET_ADMITTED",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["git ls-remote origin refs/heads/cursor/scp-a-refusal-repair-696d (run by Lane G at snapshot time)"],
        "notes": f"Snapshot at {SCP_SNAPSHOT_AT}. Working on the CUR-ORCH-QUAL resubmission per its own commit subjects.",
    },
    {
        "unit_id": "SCP-B-IMPROVEMENT-CHAIN",
        "programme": "SCP_SI_01", "wave": None,
        "branch": "cursor/scp-b-improvement-chain-696d",
        "provider_bcid": "bc-1c0486c5-f59f-5aed-9490-4bcb33d6b0e3",
        "model_requested": "NOT_MEASURABLE (originalModelName null, internal source)",
        "delivered_at": None,
        "wall_time_evidence": "DIRECTLY_REPRODUCED", "wall_time_note": "no commit yet beyond the shared SCP-SI-01 baseline as of this snapshot",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": None, "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": False, "custody_verified_by_same_principal": False,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "IN_FLIGHT_NO_CONTENT_YET",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["/tmp/lane-b worktree, read-only observation by Lane G", "cursor-cloud list-cloud-agents"],
        "notes": f"Snapshot at {SCP_SNAPSHOT_AT}: status RUNNING, no delta against baseline yet.",
    },
    {
        "unit_id": "SCP-C-AUTHORSHIP-SIDECAR",
        "programme": "SCP_SI_01", "wave": None,
        "branch": "cursor/scp-c-authorship-sidecar-696d",
        "provider_bcid": "bc-479fe73d-737d-50f2-bca8-6dcd8eec9eca",
        "model_requested": "NOT_MEASURABLE (originalModelName null, internal source)",
        "delivered_at": "2026-08-27T05:15:06+00:00",
        "wall_time_evidence": "DIRECTLY_REPRODUCED",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": 0, "lease_conflicts_evidence": "DIRECTLY_REPRODUCED",
        "lease_conflicts_note": "dedicated worktree at /tmp/lane-c observed, isolated from Lane G's own",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": True, "custody_verified_by_same_principal": False,
        "custody_note": "1 commit exists locally in the lane's own worktree; git ls-remote for this branch returns nothing, so it is NOT yet published",
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "IN_FLIGHT_COMMITTED_NOT_YET_PUBLISHED",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["/tmp/lane-c worktree, read-only observation by Lane G", "git ls-remote origin (no cursor/scp-c-* ref found)"],
        "notes": f"Snapshot at {SCP_SNAPSHOT_AT}. Not a defect: a lane mid-run that has not pushed yet is IN_FLIGHT, not NOT_RETURNED (lane_guard.py's own distinction).",
    },
    {
        "unit_id": "SCP-D-FAILURE-TO-LEARNING",
        "programme": "SCP_SI_01", "wave": None,
        "branch": "cursor/scp-d-failure-to-learning-696d",
        "provider_bcid": "bc-bd66ebcf-87a3-5291-8628-3c52f93351a9",
        "model_requested": "NOT_MEASURABLE (originalModelName null, internal source)",
        "delivered_at": None,
        "wall_time_evidence": "DIRECTLY_REPRODUCED", "wall_time_note": "no commit yet beyond the shared SCP-SI-01 baseline as of this snapshot",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": None, "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": False, "custody_verified_by_same_principal": False,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "IN_FLIGHT_NO_CONTENT_YET",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["/tmp/lane-d worktree, read-only observation by Lane G", "cursor-cloud list-cloud-agents"],
        "notes": f"Snapshot at {SCP_SNAPSHOT_AT}: status RUNNING, no delta against baseline yet.",
    },
    {
        "unit_id": "SCP-E-HELD-OUT-ROUTE-QUALIFICATION",
        "programme": "SCP_SI_01", "wave": None,
        "branch": None,
        "provider_bcid": "bc-5f6e325d-fdb2-533d-9401-3b64fea0a953",
        "model_requested": "NOT_MEASURABLE",
        "delivered_at": None,
        "wall_time_evidence": "NOT_MEASURABLE",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": None, "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": None, "custody_verified_by_same_principal": False,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "NOT_OBSERVABLE_FROM_THIS_POD",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "NOT_MEASURABLE",
        "sources": ["cursor-cloud list-cloud-agents (status RUNNING; no local worktree visible to Lane G)"],
        "notes": "Visible as a RUNNING top-level agent by name only. No worktree for it exists on this pod's local disk, "
                 "so Lane G cannot read its branch, commits or content; this is a genuine instrument limit, not an absence of work.",
    },
    {
        "unit_id": "SCP-F-UNOBSERVED",
        "programme": "SCP_SI_01", "wave": None, "branch": None, "provider_bcid": None,
        "model_requested": None, "delivered_at": None, "wall_time_evidence": "NOT_MEASURABLE",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": None, "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": None, "custody_verified_by_same_principal": False,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "NOT_OBSERVED_IN_THIS_SNAPSHOT",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "NOT_MEASURABLE",
        "sources": ["workstreams/so02/control-plane/operating-environment/scp-si-01/SCP-SI-01-SYSTEM-MAP.md (names Lane F in the roster)"],
        "notes": "SCP-SI-01-SYSTEM-MAP.md names a Lane F. It did not appear in Lane G's list-cloud-agents snapshot and no "
                 "worktree for it was found on this pod. Recorded as NOT_OBSERVED rather than omitted or assumed absent.",
    },
    {
        "unit_id": "SCP-H-UNOBSERVED",
        "programme": "SCP_SI_01", "wave": None, "branch": None, "provider_bcid": None,
        "model_requested": None, "delivered_at": None, "wall_time_evidence": "NOT_MEASURABLE",
        "retries": None, "retries_evidence": "NOT_MEASURABLE",
        "lease_conflicts": None, "lease_conflicts_evidence": "NOT_MEASURABLE",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "produced": None, "custody_verified_by_same_principal": False,
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "NOT_OBSERVED_IN_THIS_SNAPSHOT",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "NOT_MEASURABLE",
        "sources": ["workstreams/so02/control-plane/operating-environment/scp-si-01/SCP-SI-01-SYSTEM-MAP.md (names Lane H: independent acceptance machinery)"],
        "notes": "Lane H is the cohort's own acceptance mechanism (row H: 'independent acceptance machinery', must not create "
                 "'a producer-authored verdict'). It did not appear in Lane G's snapshot. Until Lane H runs and its verdict "
                 "exists as a record, SCP-SI-01 has zero independently-judged units, by construction, regardless of how "
                 "many of A-G deliver.",
    },
    {
        "unit_id": "SCP-G-ACCEPTED-UNIT-ECONOMICS",
        "programme": "SCP_SI_01", "wave": None,
        "branch": "cursor/scp-g-accepted-unit-696d",
        "provider_bcid": "bc-3d7e54e1-452d-5069-8f46-80d399c529b6",
        "model_requested": "NOT_MEASURABLE (originalModelName null for this run's own run-info; DIRECTLY_REPRODUCED self-check)",
        "delivered_at": None,
        "wall_time_evidence": "DIRECTLY_REPRODUCED",
        "retries": 0, "retries_evidence": "DOCUMENTED",
        "lease_conflicts": 0, "lease_conflicts_evidence": "DIRECTLY_REPRODUCED",
        "lease_conflicts_note": "operated throughout from its own dedicated worktree at /tmp/lane-g; only read-only git operations (fetch, ls-remote) touched /workspace",
        "ingestion_failures": None, "ingestion_failures_evidence": "NOT_MEASURABLE",
        "ingestion_failures_note": "not yet root-controller-admitted as of authoring this ledger; this is self-reporting, not a claim of acceptance",
        "produced": True, "custody_verified_by_same_principal": True,
        "custody_note": "self-verified by this same lane via write_admission.py before push; not independently judged",
        "independently_judged": False, "judgment_mechanism": None,
        "verdict": "READY_TO_COMMIT",
        "is_accepted_unit": False,
        "evidence_label_for_verdict": "DIRECTLY_REPRODUCED",
        "sources": ["this lane's own commits and receipts"],
        "notes": "This deliverable, self-reported. Per its own definition, it is not an accepted unit until (if ever) Lane H "
                 "or an equivalent structurally independent acceptor judges it. That absence is stated, not hidden.",
    },
]


def to_jsonl(units: list[dict[str, Any]]) -> str:
    lines = []
    for unit in units:
        record = dict(unit)
        record.pop("_wall_time_key", None)
        lines.append(json.dumps(record, sort_keys=True, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def main() -> int:
    wall_time = load_wall_time()
    for unit in UNITS:
        key = unit.pop("_wall_time_key", None)
        if key and key in wall_time:
            fact = wall_time[key]
            unit["delivered_at"] = unit.get("delivered_at") or fact.get("last_commit_at")
            unit["dispatched_at_from_first_own_commit"] = fact.get("first_commit_at")
            unit["own_commit_count"] = fact.get("commit_count_matching_this_lane")
            if fact.get("first_commit_at") and fact.get("last_commit_at"):
                unit["wall_time_minutes_first_to_last_own_commit"] = minutes_between(
                    fact["first_commit_at"], fact["last_commit_at"])
            unit["wall_time_evidence"] = "DIRECTLY_REPRODUCED"
            unit["wall_time_source"] = "git log against origin/<branch>, filtered to this lane's own commit-subject prefix; see raw/oe-lane-wall-time.jsonl"
        elif "wall_time_evidence" not in unit:
            unit["wall_time_minutes_first_to_last_own_commit"] = None
            unit["wall_time_evidence"] = "NOT_MEASURABLE"
            unit["wall_time_note"] = "no matching git-derived record for this unit"
        if "runtime_compute_seconds" not in unit:
            unit["runtime_compute_seconds"] = None
            unit["runtime_evidence"] = "NOT_MEASURABLE"
            unit["runtime_not_measurable_reason"] = NOT_MEASURABLE_RUNTIME
        unit.setdefault("model_confirmed_by_instrument", False)
        unit.setdefault("model_confirmation_note", MODEL_NOT_CONFIRMABLE)

    out_path = HERE.parent / "SCP-SI-01-ACCEPTED-UNIT.jsonl"
    out_path.write_text(to_jsonl(UNITS), encoding="utf-8")
    print(f"wrote {len(UNITS)} unit records to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
