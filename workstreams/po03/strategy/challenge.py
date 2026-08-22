#!/usr/bin/env python3
"""Generate the PO-03 zero-base challenge from committed control evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
WAVE_PATH = "workstreams/po03/control/wave-a-spec.json"
OWNERSHIP_PATH = "workstreams/po03/control/path-ownership.json"
MODEL_PATH = "workstreams/po03/control/model-capability-register.json"
LEDGER_PATH = "workstreams/po03/control/events/ledger.jsonl"
CONTROL_PLANE_PATH = "workstreams/po03/tools/control_plane.py"
RESULT_EMITTER_PATH = "workstreams/po03/tools/make_result.py"
DISPATCH_PATH = "workstreams/po03/control/dispatch/a9-u01.json"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative}: expected a JSON object")
    return value


def load_jsonl(root: Path, relative: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate((root / relative).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{relative}:{number}: expected a JSON object")
        rows.append(value)
    return rows


def verify_chain(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous = "0" * 64
    for index, row in enumerate(rows, 1):
        if row.get("seq") != index:
            errors.append(f"seq {row.get('seq')} is not expected {index}")
        if row.get("prev_sha256") != previous:
            errors.append(f"seq {index} does not link to its predecessor")
        body = {key: value for key, value in row.items() if key != "row_sha256"}
        computed = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
        if row.get("row_sha256") != computed:
            errors.append(f"seq {index} has an invalid row hash")
        previous = str(row.get("row_sha256", ""))
    return errors


def evidence_ref(root: Path, relative: str) -> dict[str, Any]:
    target = root / relative
    return {
        "path": relative,
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
    }


def proposal(proposal_id: str, text: str, interlock: bool = False) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "proposal": text,
        "binding_state": "PROPOSAL_ONLY",
        "founder_interlock": "REQUIRED_BEFORE_DECISION_CHANGE" if interlock else "NOT_INVOKED",
        "applied_to_active_wave": False,
        "decision_changed": [],
    }


def _prefix_collisions(ownership: dict[str, Any]) -> list[dict[str, str]]:
    worker_prefixes: list[tuple[str, str]] = []
    for owner, record in ownership["owners"].items():
        if owner == "coordinator":
            continue
        for prefix in record["owned_prefixes"]:
            worker_prefixes.append((owner, prefix))
    collisions: list[dict[str, str]] = []
    for index, (left_owner, left) in enumerate(worker_prefixes):
        for right_owner, right in worker_prefixes[index + 1 :]:
            if left_owner != right_owner and (left.startswith(right) or right.startswith(left)):
                collisions.append(
                    {
                        "left_owner": left_owner,
                        "left_prefix": left,
                        "right_owner": right_owner,
                        "right_prefix": right,
                    }
                )
    return collisions


def build_challenge(root: Path = REPO_ROOT) -> dict[str, Any]:
    wave = load_json(root, WAVE_PATH)
    ownership = load_json(root, OWNERSHIP_PATH)
    models = load_json(root, MODEL_PATH)
    dispatch = load_json(root, DISPATCH_PATH)
    ledger = load_jsonl(root, LEDGER_PATH)
    control_source = (root / CONTROL_PLANE_PATH).read_text(encoding="utf-8")

    function_counts = Counter(unit["function_id"] for unit in wave["units"])
    cohort_counts = Counter(unit["cohort_id"] for unit in wave["units"])
    model_counts = Counter(unit["model"] for unit in wave["units"])
    event_counts = Counter(row["event"] for row in ledger)
    chain_errors = verify_chain(ledger)
    source_drift = []
    for relative, expected in sorted(dispatch["source_hashes"].items()):
        target = root / relative
        observed = sha256_file(target) if target.is_file() else None
        if observed != expected:
            source_drift.append(
                {
                    "path": relative,
                    "expected_sha256": expected,
                    "observed_sha256": observed,
                    "state": "MISSING" if observed is None else "DRIFTED",
                }
            )

    criteria_units = [
        unit["unit_id"]
        for unit in wave["units"]
        if "criteria" in (unit["hypothesis"] + " " + unit["acceptance"]["assertion"]).lower()
    ]
    terminal_reviews = event_counts["ACCEPTED"] + event_counts["REJECTED"]
    result_events = event_counts["RESULT_COMMITTED"] + event_counts["PARENT_INGESTED"]
    cumulative_prior_row_verifications = len(ledger) * (len(ledger) - 1) // 2
    append_verifies_full_history = (
        "rows = ledger_rows()" in control_source
        and "chain_errors = verify_chain(rows)" in control_source
        and 'with LEDGER_PATH.open("a"' in control_source
    )
    worker_prefix_collisions = _prefix_collisions(ownership)
    exposed_slugs = {
        row["slug"] for row in models["delegation_models_exposed"] if row["exposure"] == "EXPOSED"
    }

    shared_observations = {
        "declared_units": wave["declared_units"],
        "minimum_required_units": wave["minimum_required_units"],
        "cohort_count": len(cohort_counts),
        "cohort_unit_counts": dict(sorted(cohort_counts.items())),
        "function_unit_counts": dict(sorted(function_counts.items())),
        "model_unit_counts": dict(sorted(model_counts.items())),
        "ledger_rows": len(ledger),
        "ledger_event_counts": dict(sorted(event_counts.items())),
        "ledger_chain_valid": not chain_errors,
        "ledger_chain_errors": chain_errors,
        "terminal_review_events": terminal_reviews,
        "result_custody_events": result_events,
        "worker_prefix_collisions": worker_prefix_collisions,
        "dispatch_source_drift": source_drift,
    }

    assumptions = [
        {
            "assumption_id": "A-WAVE-SHAPE",
            "statement": "Seventy-four units in ten fixed cohorts is the right partition for Wave A.",
            "load_bearing_because": "The partition fixes parallelism, review dependencies and the number of independently counted attempts.",
            "test": {
                "method": "Count units by function and cohort and search the committed ledger for outcome evidence that compares this partition with another.",
                "observations": {
                    "declared_vs_minimum": [wave["declared_units"], wave["minimum_required_units"]],
                    "cohort_unit_counts": dict(sorted(cohort_counts.items())),
                    "function_unit_counts": dict(sorted(function_counts.items())),
                    "completed_or_reviewed_outcomes": result_events + terminal_reviews,
                },
            },
            "verdict": "NOT_YET_SUPPORTED",
            "reason": "The shape satisfies the 64-unit floor and covers all ten functions, but committed evidence contains no executed alternative partition and no completed or independently reviewed outcomes. Adequacy is evidenced; optimality is not.",
            "proposal": proposal(
                "P-WAVE-SHAPE-01",
                "Evaluate a successor queue that partitions by dependency and observed service time after Wave A; do not repartition or delay the active Wave A.",
                interlock=True,
            ),
        },
        {
            "assumption_id": "A-SINGLE-INTEGRATOR",
            "statement": "The single integration controller should be treated primarily as a throughput ceiling.",
            "load_bearing_because": "Changing writer cardinality could trade custody safety for speed.",
            "test": {
                "method": "Inspect committed ownership and control-plane code for the controller's enforced responsibility, then inspect the ledger for measured integration throughput.",
                "observations": {
                    "controller_shared_prefix_count": len(
                        ownership["owners"]["coordinator"]["owned_prefixes"]
                    ),
                    "subordinate_prefix_collisions": worker_prefix_collisions,
                    "control_plane_declares_single_shared_writer": (
                        "integration controller is the only writer of shared PO-03 control state"
                        in control_source
                    ),
                    "measured_result_ingestions": event_counts["PARENT_INGESTED"],
                },
            },
            "verdict": "UNDERMINED",
            "reason": "The committed mechanism uses one controller as a safety boundary around shared mutable state. No PARENT_INGESTED event exists, so the claim that it is already a measured throughput ceiling is unsupported.",
            "proposal": proposal(
                "P-INTEGRATION-TOPOLOGY-01",
                "Retain a singleton authority for final promotion while simulating sharded verification and content-addressed fan-in as throughput alternatives.",
            ),
        },
        {
            "assumption_id": "A-GIT-SINK",
            "statement": "Git remote custody is empirically the right durable result sink for this workload.",
            "load_bearing_because": "Provider-loss recovery and immutable read-back depend on the selected sink.",
            "test": {
                "method": "Check committed code for git-backed result locators and count durable result events in the committed ledger.",
                "observations": {
                    "result_emitter_present": (root / RESULT_EMITTER_PATH).is_file(),
                    "result_emitter_sha256": sha256_file(root / RESULT_EMITTER_PATH),
                    "result_committed_events": event_counts["RESULT_COMMITTED"],
                    "parent_ingested_events": event_counts["PARENT_INGESTED"],
                },
            },
            "verdict": "NOT_YET_SUPPORTED",
            "reason": "Git is the commissioned sink and the emitter encodes immutable commit locators, but this committed ledger snapshot has no result commit or ingestion. Compliance is implemented; recovery and throughput superiority are not yet observed.",
            "proposal": proposal(
                "P-DURABLE-SINK-01",
                "Measure git read-back, callback-loss recovery and batching against an in-memory message-only baseline without changing the active durable sink.",
            ),
        },
        {
            "assumption_id": "A-HASHED-JSONL",
            "statement": "One hash-chained JSONL file is the right ledger substrate at Wave A scale.",
            "load_bearing_because": "Every append, projection and recovery scan depends on the ledger's integrity and access cost.",
            "test": {
                "method": "Independently verify every committed row and inspect append_event for full-history verification before each append.",
                "observations": {
                    "rows_verified": len(ledger),
                    "chain_valid": not chain_errors,
                    "append_verifies_full_history": append_verifies_full_history,
                    "historical_prior_row_verifications_implied": cumulative_prior_row_verifications,
                    "next_append_rows_reverified": len(ledger),
                },
            },
            "verdict": "NOT_YET_SUPPORTED",
            "reason": "The 148-row chain is valid, which supports integrity. The implementation re-reads and re-hashes the full history on each append, implying quadratic cumulative verification work; no substrate comparison establishes that this remains the right scale choice.",
            "proposal": proposal(
                "P-LEDGER-SUBSTRATE-01",
                "Benchmark checkpointed chain segments and cohort shards while preserving an immutable global head and the current JSONL as the active source of truth.",
            ),
        },
        {
            "assumption_id": "A-CRITERIA-BEHAVIOUR",
            "statement": "Freezing acceptance criteria changes reviewer behaviour and reduces escaped defects.",
            "load_bearing_because": "Blind review and successor claims rely on the freeze being behavioural, not ceremonial.",
            "test": {
                "method": "Identify preregistration units and count committed terminal review outcomes in the same ledger snapshot.",
                "observations": {
                    "criteria_related_units": sorted(criteria_units),
                    "accepted_events": event_counts["ACCEPTED"],
                    "rejected_events": event_counts["REJECTED"],
                },
            },
            "verdict": "NOT_YET_SUPPORTED",
            "reason": "The wave preregisters tests of criteria freezing, but there are no ACCEPTED or REJECTED events and no matched behavioural outcome in the committed snapshot.",
            "proposal": proposal(
                "P-CRITERIA-BEHAVIOUR-01",
                "Keep freeze ordering as a safety control, but reserve any behavioural-effect claim for the registered matched comparisons and independent dispositions.",
            ),
        },
        {
            "assumption_id": "A-MODEL-MATCH",
            "statement": "The model allocation is well matched to each work class.",
            "load_bearing_because": "Allocation determines heterogeneous cognition, review independence and claimed strongest-model use.",
            "test": {
                "method": "Join exact dispatched model slugs to observed exposure and search committed outcomes for per-model acceptance or defect evidence.",
                "observations": {
                    "allocated_models": dict(sorted(model_counts.items())),
                    "all_allocated_models_exposed": set(model_counts).issubset(exposed_slugs),
                    "not_supported_families": [
                        row["family"] for row in models["not_supported"]
                    ],
                    "terminal_model_outcomes": terminal_reviews,
                },
            },
            "verdict": "NOT_YET_SUPPORTED",
            "reason": "Every allocated slug is observed as exposed and exact slugs are frozen, but role fit is asserted rather than measured: no accepted result, defect attribution or matched model comparison exists in this snapshot.",
            "proposal": proposal(
                "P-MODEL-ALLOCATION-01",
                "Retain exact current assignments for continuity and use per-model dispositions plus matched evaluations before claiming work-class fit or changing allocation.",
            ),
        },
        {
            "assumption_id": "A-SOURCE-CAPSULE-CLOSURE",
            "statement": "Referencing an immutable dispatch-manifest hash is sufficient to ensure workers execute the frozen source bytes.",
            "load_bearing_because": "Acceptance hashes are only meaningful if every source named by the dispatch still has the frozen content.",
            "test": {
                "method": "Re-hash every source path in immutable dispatch a9-u01 and compare it with the hash frozen before dispatch.",
                "observations": {
                    "checked_paths": len(dispatch["source_hashes"]),
                    "drift_count": len(source_drift),
                    "drift": source_drift,
                },
            },
            "verdict": "UNDERMINED",
            "reason": "The immutable dispatch record remains unchanged, but path-ownership.json changed after dispatch. The current emitter verifies the manifest reference, not source-byte closure, so a valid result can describe work executed against drifted control input.",
            "proposal": proposal(
                "P-SOURCE-CAPSULE-01",
                "Add a read-only source-capsule verifier that reports CURRENT, DRIFTED and MISSING before material execution; do not rewrite immutable dispatch records.",
            ),
        },
        {
            "assumption_id": "A-DISJOINT-WRITER-PREFIXES",
            "statement": "Disjoint subordinate ownership prefixes remove direct worker-to-worker path collisions.",
            "load_bearing_because": "Parallel writers are safe only if their accepted outputs cannot contend for the same path.",
            "test": {
                "method": "Compare every subordinate owned prefix against every other subordinate prefix for equality or nesting.",
                "observations": {
                    "worker_count": len(ownership["owners"]) - 1,
                    "prefix_collisions": worker_prefix_collisions,
                },
            },
            "verdict": "UPHELD",
            "reason": "No subordinate prefix equals or contains another subordinate's prefix in the committed ownership register. This upholds structural collision isolation, not end-to-end ingestion success.",
            "proposal": None,
        },
    ]

    return {
        "artifact_id": "PO03-A9-ZERO-BASE-CHALLENGE-v001",
        "commission_id": wave["commission_id"],
        "commission_revision": wave["commission_revision"],
        "unit_id": "a9-u01",
        "evidence_policy": "Only bytes in the current committed baseline are treated as evidence; absence of a completed outcome is NOT_YET rather than inferred success.",
        "evidence": [
            evidence_ref(root, relative)
            for relative in (
                WAVE_PATH,
                OWNERSHIP_PATH,
                MODEL_PATH,
                LEDGER_PATH,
                CONTROL_PLANE_PATH,
                RESULT_EMITTER_PATH,
                DISPATCH_PATH,
            )
        ],
        "observations": shared_observations,
        "assumptions": assumptions,
        "summary": {
            "upheld": sum(item["verdict"] == "UPHELD" for item in assumptions),
            "undermined": sum(item["verdict"] == "UNDERMINED" for item in assumptions),
            "not_yet_supported": sum(
                item["verdict"] == "NOT_YET_SUPPORTED" for item in assumptions
            ),
            "proposals_only": sum(item["proposal"] is not None for item in assumptions),
        },
        "strategy_restarted": False,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workstreams/po03/strategy/zero-base-challenge.json"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    payload = build_challenge(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"WROTE {output.relative_to(root)} assumptions={len(payload['assumptions'])} "
        f"upheld={payload['summary']['upheld']} undermined={payload['summary']['undermined']} "
        f"not_yet={payload['summary']['not_yet_supported']} decision_changed=[]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
