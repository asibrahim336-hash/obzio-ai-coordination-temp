#!/usr/bin/env python3
"""Append the seeded typed links to the canonical event log, hash chain intact.

The links live in `workstreams/so02/control-plane/state/events.jsonl` and
nowhere else. This script is the one-shot writer that puts them there; it is not
a store and holds no state of its own. It is idempotent: a node already present
in the log is skipped, so a re-run appends nothing and the chain head does not
move.

Every appended event is an ordinary SCF-01 event. `previous_event_sha256` links
to the current head, `sequence` continues monotonically, `event_sha256` is the
canonical digest computed by `scctl.canonical_event_hash`, and
`payload.decision_changed` is empty because a projection of existing evidence
binds no decision. `scctl.py validate` is the check that this was done right and
is run immediately afterwards.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[7]
CONTROL_PLANE = REPO_ROOT / "workstreams/so02/control-plane"
EVENTS_PATH = CONTROL_PLANE / "state/events.jsonl"
SEED_PATH = (Path(__file__).resolve().parents[1]
             / "chains/SCP-B-CHAIN-SEED-20260827-v001.json")

RECORDED_AT = "2026-08-27T05:15:00Z"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scctl = _load("scctl", CONTROL_PLANE / "tools/scctl.py")
improvement_chain = _load("improvement_chain", CONTROL_PLANE / "tools/improvement_chain.py")


def evidence_refs(node: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for citation in node.get("evidence_citations", []):
        ref = citation.get("artifact_path") or citation.get("locator")
        if ref and ref not in refs:
            refs.append(str(ref))
    return refs


def build_link(chain: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    link: dict[str, Any] = {
        "schema_id": improvement_chain.SCHEMA_ID,
        "schema_version": improvement_chain.SCHEMA_VERSION,
        "chain_id": chain["chain_id"],
        "chain_title": chain["title"],
        "node_id": node["node_id"],
        "node_kind": node["node_kind"],
        "derives_from": list(node.get("derives_from", [])),
        "occurred_at": node["occurred_at"],
        "title": node["title"],
        "statement": node["statement"],
        "evidence_label": node["evidence_label"],
        "evidence_citations": node["evidence_citations"],
        "provenance_class": node["provenance_class"],
        "provenance_basis": node.get("provenance_basis", ""),
    }
    for optional in ("founder_quote", "pending_successor", "verdict", "promotion",
                     "non_chronological_reason"):
        if node.get(optional) is not None:
            link[optional] = node[optional]
    return link


def prior_kind(chain_nodes: dict[str, Any], node: dict[str, Any]) -> str | None:
    parents = [chain_nodes[p]["node_kind"] for p in node.get("derives_from", [])
               if p in chain_nodes]
    return parents[0] if parents else None


def build_events(seed: dict[str, Any], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present = {
        entry["link"].get("node_id")
        for entry in improvement_chain.collect_links(existing)
    }
    contract_recorded = any(
        event.get("event_type") == improvement_chain.CONTRACT_EVENT_TYPE for event in existing
    )

    sequence = len(existing)
    previous = existing[-1]["event_sha256"] if existing else None
    actor, authority = seed["actor"], seed["authority"]
    appended: list[dict[str, Any]] = []

    def emit(event_type: str, subject: str, occurred_at: str,
             payload: dict[str, Any]) -> None:
        nonlocal sequence, previous
        sequence += 1
        event_id = f"SCF01-EVT-{sequence:04d}"
        event = {
            "aggregate_type": "strategic_control_function",
            "aggregate_id": "SCF-01",
            "actor": actor,
            "authority": authority,
            "strategy_snapshot_id": "CURRENT_ACTIVE_STRATEGY_SNAPSHOT_UNCHANGED",
            "event_id": event_id,
            "sequence": sequence,
            "previous_event_sha256": previous,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "recorded_at": RECORDED_AT,
            "subject": subject,
            "payload": payload,
            "idempotency_key": event_id,
        }
        event["event_sha256"] = scctl.canonical_event_hash(event)
        previous = event["event_sha256"]
        appended.append(event)

    if not contract_recorded:
        emit(
            improvement_chain.CONTRACT_EVENT_TYPE,
            "SCF-01/IMPROVEMENT-CHAIN",
            RECORDED_AT,
            {
                "prior_state": None,
                "new_state": "CONTRACT_LIVE_PROJECTION_OVER_EXISTING_EVENT_LOG",
                "evidence_refs": [
                    "workstreams/so02/control-plane/tools/improvement_chain.py",
                    "workstreams/so02/control-plane/state/control-plane.json",
                    ("workstreams/so02/control-plane/operating-environment/scp-si-01/lane-b/"
                     "tests/test_improvement_chain.py"),
                ],
                "decision_changed": [],
                "improvement_chain_contract": improvement_chain.declared_contract(),
                "no_new_store": (
                    "A link is an event in this file. The registry, currentness and recovery views "
                    "are projections of these events. Nothing was created that holds state."
                ),
            },
        )

    for chain in seed["chains"]:
        nodes = {node["node_id"]: node for node in chain["nodes"]}
        for node in chain["nodes"]:
            if node["node_id"] in present:
                continue
            link = build_link(chain, node)
            emit(
                improvement_chain.LINK_EVENT_TYPE,
                f"SCF-01/IMPROVEMENT-CHAIN/{node['node_id']}",
                node["occurred_at"],
                {
                    "prior_state": prior_kind(nodes, node),
                    "new_state": f"LINK_RECORDED_{node['node_kind']}",
                    "evidence_refs": evidence_refs(node),
                    "decision_changed": [],
                    improvement_chain.LINK_PAYLOAD_KEY: link,
                },
            )
    return appended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the appended events; without it, report only")
    args = parser.parse_args(argv)

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    existing = scctl.read_jsonl(EVENTS_PATH)
    appended = build_events(seed, existing)

    print(f"existing events   : {len(existing)}")
    print(f"events to append  : {len(appended)}")
    if not appended:
        print("nothing to do; every seeded node is already in the log")
        return 0

    combined = existing + appended
    errors: list[str] = []
    scctl.validate_events(combined, errors)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1

    chains, findings = improvement_chain.check_all(combined, REPO_ROOT)
    summary = improvement_chain.summarise(chains, findings)
    print(f"chains projected  : {summary['chain_count']}")
    print(f"nodes projected   : {summary['node_count']}")
    print(f"chain refused     : {summary['refused']}")
    for finding in summary["findings"]:
        print(f"  {finding['severity']}: [{finding['code']}] {finding['node_id']}")
        print(f"      {finding['detail']}")
    if summary["refused"]:
        print("REFUSED: the projected chain is broken; nothing written")
        return 1

    if not args.apply:
        print("dry run; pass --apply to write")
        return 0

    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        for event in appended:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(f"appended {len(appended)} events to {EVENTS_PATH.relative_to(REPO_ROOT)}")
    print(f"new head: {appended[-1]['event_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
