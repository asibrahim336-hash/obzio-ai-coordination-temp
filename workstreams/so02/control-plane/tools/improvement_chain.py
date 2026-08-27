#!/usr/bin/env python3
"""Typed improvement links, projected from `state/events.jsonl`. No new store.

The estate's recorded failure mode is a lesson written down while the mechanism
stays as it was. `l4-currentness-recovery/ledger/admission-ladder.json` already
names it:

    LESSON_DOCUMENTED — "A recorded lesson that changes no executable gate
    leaves the failure available."

That non-admissible class states the rule but cannot find a violation, because
nothing in the repository connected an observation to the mechanism that was
supposed to answer it. This module supplies the missing edges, as a **typed
dependency DAG over events that already live in the canonical hash-chained
log**:

    OBSERVATION -> DEFECT -> MECHANISM_CHANGE -> REGRESSION_TEST -> RERUN
                -> VERDICT -> CURRENTNESS_PROMOTION

## Why this is not a second ledger

There is no store here. A link is one ordinary event in
`workstreams/so02/control-plane/state/events.jsonl`, with `event_type`
`IMPROVEMENT_LINK_RECORDED` and one new optional payload key,
`payload.improvement_link`. The hash chain, the sequence rule, the idempotency
rule and `scctl.validate_events` govern these events exactly as they govern the
21 that preceded them. Every function below is a pure projection of that list.
Delete this module and no evidence is lost; only the view is.

## Backward compatibility, stated as a property rather than a hope

* An event with no `improvement_link` is untouched: `collect_links` skips it.
* The 21 pre-existing events produce zero links and zero findings.
* No existing key, event type, admission state or ladder requirement changes.
* `improvement_chain_contract` in `control-plane.json` is optional; a
  control-plane document without it validates exactly as before.

`test_improvement_chain.py` asserts each of those four as a test rather than
leaving them as claims.

## What it refuses

A chain that can only describe finished stories is not modelling this estate,
so an *open* chain is legal — but only when it declares what is missing, why,
and who owns it. The asymmetry is deliberate and is the whole design:

* A **missing successor** may be waived by a declared `pending_successor`.
  Nothing has been claimed yet, so admitting "the mechanism is not written" is
  an honest state.
* A **missing predecessor** may never be waived. A verdict with no rerun, or a
  promotion with no verdict, is a claim resting on nothing, and a declaration
  cannot supply the foundation it admits is absent.

Provenance and evidence labels are mandatory on every node, because an
unclassified constraint is not in force and an unlabelled claim is not evidence.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_ID = "SCP-B-IMPROVEMENT-CHAIN"
SCHEMA_VERSION = "1.0"

LINK_EVENT_TYPE = "IMPROVEMENT_LINK_RECORDED"
CONTRACT_EVENT_TYPE = "IMPROVEMENT_CHAIN_CONTRACT_RECORDED"
LINK_PAYLOAD_KEY = "improvement_link"

ERROR = "ERROR"
WARNING = "WARNING"

# Allowlist, not denylist. The estate has already been burned by a denylist of
# harmful states that passed everything nobody enumerated
# (DEF-02-DENYLIST-FAILS-OPEN, reproduced 2026-08-22). An unrecognised node kind
# is refused rather than ignored.
NODE_KINDS: tuple[str, ...] = (
    "OBSERVATION",
    "DEFECT",
    "MECHANISM_CHANGE",
    "REGRESSION_TEST",
    "RERUN",
    "VERDICT",
    "CURRENTNESS_PROMOTION",
)

EVIDENCE_LABELS = ("DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS")
PROVENANCE_CLASSES = ("FOUNDER_AUTHORED", "EARNED", "ASSISTANT_AUTHORED")

# predecessor kind -> the successor kinds an edge may reach
ALLOWED_EDGES: dict[str, frozenset[str]] = {
    "OBSERVATION": frozenset({"DEFECT"}),
    "DEFECT": frozenset({"MECHANISM_CHANGE"}),
    "MECHANISM_CHANGE": frozenset({"REGRESSION_TEST"}),
    "REGRESSION_TEST": frozenset({"RERUN"}),
    "RERUN": frozenset({"VERDICT"}),
    "VERDICT": frozenset({"CURRENTNESS_PROMOTION"}),
    "CURRENTNESS_PROMOTION": frozenset(),
}

# successor kind -> predecessor kind it must actually have. Never waivable.
REQUIRED_PREDECESSOR: dict[str, str] = {
    "DEFECT": "OBSERVATION",
    "MECHANISM_CHANGE": "DEFECT",
    "REGRESSION_TEST": "MECHANISM_CHANGE",
    "RERUN": "REGRESSION_TEST",
    "VERDICT": "RERUN",
    "CURRENTNESS_PROMOTION": "VERDICT",
}

# predecessor kind -> successor kind it must reach. Waivable by a declared
# pending_successor naming exactly that kind.
REQUIRED_SUCCESSOR: dict[str, str] = {
    "DEFECT": "MECHANISM_CHANGE",
    "MECHANISM_CHANGE": "REGRESSION_TEST",
    "REGRESSION_TEST": "RERUN",
}

# A promotion that raises a subject into one of these states is an acceptance
# claim, and an acceptance claim needs a verdict from somebody other than the
# producer. `currentctl.check_reproducibility` already refuses SELF_ACCEPTANCE
# for workstream evidence; this is the same rule on the chain.
ACCEPTANCE_CLASS_PROMOTIONS = frozenset({
    "ACCEPTED",
    "INDEPENDENTLY_ACCEPTED",
    "INDEPENDENTLY_VALIDATED",
    "QUALIFIED",
    "FOUNDER_ACCEPTED",
})

SHA256_HEX = frozenset("0123456789abcdef")


class Finding:
    """One refusal, with the node and evidence that produced it."""

    __slots__ = ("code", "severity", "chain_id", "node_id", "detail", "evidence")

    def __init__(self, code: str, severity: str, chain_id: str, node_id: str | None,
                 detail: str, evidence: dict[str, Any] | None = None) -> None:
        self.code = code
        self.severity = severity
        self.chain_id = chain_id
        self.node_id = node_id
        self.detail = detail
        self.evidence = evidence or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "chain_id": self.chain_id,
            "node_id": self.node_id,
            "detail": self.detail,
            "evidence": self.evidence,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Finding {self.code} {self.severity} {self.node_id or self.chain_id}>"


def urn(chain_id: str, node_id: str | None = None) -> str:
    return f"urn:obzio:chain:{chain_id}" + (f":{node_id}" if node_id else "")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# projection
# --------------------------------------------------------------------------


def collect_links(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every typed link carried by the event log, in ledger order.

    An event without `payload.improvement_link` contributes nothing, which is
    what makes appending this schema to a 21-event log a no-op for those 21.
    """
    links: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        link = payload.get(LINK_PAYLOAD_KEY)
        if not isinstance(link, dict):
            continue
        links.append({
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "event_sha256": event.get("event_sha256"),
            "sequence": event.get("sequence"),
            "occurred_at": event.get("occurred_at"),
            "recorded_at": event.get("recorded_at"),
            "subject": event.get("subject"),
            "link": link,
        })
    return links


def _node_from(entry: dict[str, Any]) -> dict[str, Any]:
    link = entry["link"]
    derives = link.get("derives_from")
    return {
        "node_id": link.get("node_id"),
        "chain_id": link.get("chain_id"),
        "node_kind": link.get("node_kind"),
        "title": link.get("title", ""),
        "statement": link.get("statement", ""),
        "derives_from": list(derives) if isinstance(derives, list) else derives,
        "evidence_label": link.get("evidence_label"),
        "evidence_citations": link.get("evidence_citations", []),
        "provenance_class": link.get("provenance_class"),
        "provenance_basis": link.get("provenance_basis", ""),
        "founder_quote": link.get("founder_quote"),
        "pending_successor": link.get("pending_successor"),
        "verdict": link.get("verdict"),
        "promotion": link.get("promotion"),
        "non_chronological_reason": link.get("non_chronological_reason"),
        "occurred_at": link.get("occurred_at") or entry.get("occurred_at"),
        "event_id": entry.get("event_id"),
        "event_sha256": entry.get("event_sha256"),
        "sequence": entry.get("sequence"),
        "urn": urn(str(link.get("chain_id")), str(link.get("node_id"))),
    }


def project_chains(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Group the links into chains. Pure function of the event list."""
    chains: dict[str, dict[str, Any]] = {}
    for entry in collect_links(events):
        node = _node_from(entry)
        chain_id = str(node["chain_id"])
        chain = chains.setdefault(chain_id, {
            "chain_id": chain_id,
            "urn": urn(chain_id),
            "nodes": {},
            "node_order": [],
        })
        node_id = str(node["node_id"])
        if node_id in chain["nodes"]:
            # Kept rather than overwritten so the duplicate is reportable.
            chain.setdefault("duplicate_node_ids", []).append(node_id)
            continue
        chain["nodes"][node_id] = node
        chain["node_order"].append(node_id)

    for chain in chains.values():
        _annotate(chain)
    return dict(sorted(chains.items()))


def _annotate(chain: dict[str, Any]) -> None:
    nodes: dict[str, Any] = chain["nodes"]
    successors: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for parent in node["derives_from"] or []:
            if parent in successors:
                successors[parent].append(node_id)
    for node_id, node in nodes.items():
        node["successors"] = sorted(successors[node_id])

    kinds = [node["node_kind"] for node in nodes.values()]
    pending = [
        {"node_id": node["node_id"], **node["pending_successor"]}
        for node in nodes.values()
        if isinstance(node["pending_successor"], dict)
    ]
    promotions = [node for node in nodes.values() if node["node_kind"] == "CURRENTNESS_PROMOTION"]

    chain["kind_counts"] = {kind: kinds.count(kind) for kind in NODE_KINDS if kind in kinds}
    chain["node_count"] = len(nodes)
    chain["pending"] = sorted(pending, key=lambda item: item["node_id"])
    chain["reaches_promotion"] = bool(promotions)
    chain["promoted_states"] = sorted(
        str((node.get("promotion") or {}).get("promoted_state"))
        for node in promotions
    )
    chain["chain_state"] = (
        "OPEN_SUCCESSOR_PENDING" if pending
        else "CLOSED_THROUGH_PROMOTION" if promotions
        else "OPEN_INCOMPLETE"
    )
    chain["next_required_node_kind"] = _next_required(chain)


def _next_required(chain: dict[str, Any]) -> str | None:
    """The deterministic recovery answer: what this chain owes next."""
    if chain["pending"]:
        return str(chain["pending"][0].get("node_kind"))
    present = set(chain["kind_counts"])
    for kind in NODE_KINDS:
        if kind not in present:
            return kind
    return None


# --------------------------------------------------------------------------
# refusal
# --------------------------------------------------------------------------


def _cited(node: dict[str, Any]) -> bool:
    citations = node.get("evidence_citations")
    return isinstance(citations, list) and bool(citations)


def check_chain(chain: dict[str, Any]) -> list[Finding]:
    """Refuse a broken chain. Every rule here is a refusal, not advice."""
    findings: list[Finding] = []
    chain_id = chain["chain_id"]
    nodes: dict[str, Any] = chain["nodes"]

    for node_id in chain.get("duplicate_node_ids", []):
        findings.append(Finding(
            "CHAIN_DUPLICATE_NODE_ID", ERROR, chain_id, node_id,
            f"node id {node_id} is recorded more than once; an identifier that resolves to two "
            "links cannot be an edge target",
        ))

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for node in nodes.values():
        by_kind.setdefault(str(node["node_kind"]), []).append(node)

    for node_id, node in sorted(nodes.items()):
        kind = node["node_kind"]

        if kind not in NODE_KINDS:
            findings.append(Finding(
                "CHAIN_NODE_KIND_UNKNOWN", ERROR, chain_id, node_id,
                f"node kind {kind!r} is not in the declared vocabulary {list(NODE_KINDS)}; an "
                "unrecognised kind is refused rather than passed, because a denylist fails open "
                "on every kind nobody enumerated",
            ))
            continue

        if node["chain_id"] != chain_id:
            findings.append(Finding(
                "CHAIN_ID_MISMATCH", ERROR, chain_id, node_id,
                f"node declares chain {node['chain_id']!r} but was grouped under {chain_id!r}",
            ))

        label = node["evidence_label"]
        if label not in EVIDENCE_LABELS:
            findings.append(Finding(
                "CHAIN_EVIDENCE_LABEL_INVALID", ERROR, chain_id, node_id,
                f"evidence label {label!r} is not one of {list(EVIDENCE_LABELS)}; an unlabelled "
                "claim is not evidence",
            ))
        elif label != "HYPOTHESIS" and not _cited(node):
            findings.append(Finding(
                "CHAIN_LINK_UNCITED", ERROR, chain_id, node_id,
                f"labelled {label} but cites no artifact; a link that cannot be cited is a "
                "hypothesis and must be labelled one",
            ))

        provenance = node["provenance_class"]
        if provenance not in PROVENANCE_CLASSES:
            findings.append(Finding(
                "CHAIN_PROVENANCE_UNCLASSIFIED", ERROR, chain_id, node_id,
                f"provenance class {provenance!r} is not one of {list(PROVENANCE_CLASSES)}; an "
                "unclassified constraint is not in force",
            ))
        elif provenance == "FOUNDER_AUTHORED" and not str(node.get("founder_quote") or "").strip():
            findings.append(Finding(
                "CHAIN_FOUNDER_PROVENANCE_UNQUOTED", ERROR, chain_id, node_id,
                "claims FOUNDER_AUTHORED provenance without a quoted founder utterance; git "
                "authorship is not founder authorship",
            ))
        elif provenance == "EARNED" and not str(node.get("provenance_basis") or "").strip():
            findings.append(Finding(
                "CHAIN_EARNED_PROVENANCE_NAMES_NO_DEFECT", ERROR, chain_id, node_id,
                "claims EARNED provenance without naming the defect it caught",
            ))

        derives = node["derives_from"]
        if not isinstance(derives, list):
            findings.append(Finding(
                "CHAIN_EDGE_LIST_MALFORMED", ERROR, chain_id, node_id,
                f"derives_from must be a list, got {type(derives).__name__}",
            ))
            derives = []

        for parent_id in derives:
            parent = nodes.get(parent_id)
            if parent is None:
                findings.append(Finding(
                    "CHAIN_EDGE_TARGET_MISSING", ERROR, chain_id, node_id,
                    f"derives from {parent_id!r}, which is not a node of this chain; an edge to "
                    "nothing is not a link",
                    {"missing_target": parent_id},
                ))
                continue
            parent_kind = str(parent["node_kind"])
            if kind not in ALLOWED_EDGES.get(parent_kind, frozenset()):
                findings.append(Finding(
                    "CHAIN_EDGE_KIND_NOT_ALLOWED", ERROR, chain_id, node_id,
                    f"edge {parent_kind} -> {kind} is not in the declared edge allowlist; "
                    f"{parent_kind} may only reach {sorted(ALLOWED_EDGES.get(parent_kind, ()))}",
                    {"from": parent_id, "from_kind": parent_kind, "to_kind": kind},
                ))
            elif parent.get("evidence_label") == "HYPOTHESIS" and kind == "CURRENTNESS_PROMOTION":
                findings.append(Finding(
                    "CHAIN_PROMOTION_RESTS_ON_HYPOTHESIS", ERROR, chain_id, node_id,
                    f"promotes on {parent_id}, which is labelled HYPOTHESIS; a hypothesis cannot "
                    "carry a currentness promotion",
                ))
            _check_chronology(findings, chain_id, node, parent)

        required_parent = REQUIRED_PREDECESSOR.get(str(kind))
        if required_parent:
            parents = [nodes[p]["node_kind"] for p in derives if p in nodes]
            if required_parent not in parents:
                findings.append(Finding(
                    "CHAIN_FOUNDATION_MISSING", ERROR, chain_id, node_id,
                    f"{kind} has no {required_parent} predecessor. This is never waivable: a "
                    "declaration that the foundation is missing cannot supply it, because the "
                    "claim above it has already been made",
                    {"required_predecessor": required_parent, "observed_predecessors": parents},
                ))

        findings.extend(_check_successor(chain_id, node, by_kind))
        findings.extend(_check_promotion(chain_id, node, nodes))

    findings.extend(_check_cycles(chain_id, nodes))
    return findings


def _check_chronology(findings: list[Finding], chain_id: str, node: dict[str, Any],
                      parent: dict[str, Any]) -> None:
    """An edge that runs backwards in time must say why.

    Improvement history in this estate is genuinely not linear: an independent
    refusal that names a defect is issued before the fix and sometimes re-read
    long after it. That is allowed, and recording it silently is not.
    """
    child_at, parent_at = str(node.get("occurred_at") or ""), str(parent.get("occurred_at") or "")
    if not child_at or not parent_at or child_at >= parent_at:
        return
    reason = str(node.get("non_chronological_reason") or "").strip()
    if reason:
        findings.append(Finding(
            "CHAIN_EDGE_NOT_CHRONOLOGICAL", WARNING, chain_id, str(node["node_id"]),
            f"occurred at {child_at}, before its predecessor {parent['node_id']} at {parent_at}; "
            f"declared reason: {reason}",
        ))
    else:
        findings.append(Finding(
            "CHAIN_EDGE_NOT_CHRONOLOGICAL", ERROR, chain_id, str(node["node_id"]),
            f"occurred at {child_at}, before its predecessor {parent['node_id']} at {parent_at}, "
            "with no declared reason; an undeclared backwards edge is a mis-recorded history",
        ))


def _check_successor(chain_id: str, node: dict[str, Any],
                     by_kind: dict[str, list[dict[str, Any]]]) -> list[Finding]:
    findings: list[Finding] = []
    kind = str(node["node_kind"])
    required = REQUIRED_SUCCESSOR.get(kind)
    if not required:
        return findings

    node_id = str(node["node_id"])
    satisfied = any(
        node_id in (candidate["derives_from"] or [])
        for candidate in by_kind.get(required, [])
    )
    pending = node.get("pending_successor")

    if satisfied:
        if isinstance(pending, dict):
            findings.append(Finding(
                "CHAIN_PENDING_ALREADY_SATISFIED", WARNING, chain_id, node_id,
                f"declares {required} pending while a {required} already derives from it; the "
                "declaration is stale and should be retired",
            ))
        return findings

    if not isinstance(pending, dict):
        findings.append(Finding(
            "CHAIN_LINK_DANGLING", ERROR, chain_id, node_id,
            f"{kind} reaches no {required} and declares none pending. A {kind.lower().replace('_', ' ')} "
            f"with no {required.lower().replace('_', ' ')} leaves the failure available; that is "
            "exactly the LESSON_DOCUMENTED class the admission ladder already refuses",
            {"required_successor": required},
        ))
        return findings

    if pending.get("node_kind") != required:
        findings.append(Finding(
            "CHAIN_PENDING_WRONG_KIND", ERROR, chain_id, node_id,
            f"declares {pending.get('node_kind')!r} pending, but what this {kind} owes next is "
            f"{required}",
        ))
    if pending.get("state") != "PENDING":
        findings.append(Finding(
            "CHAIN_PENDING_STATE_INVALID", ERROR, chain_id, node_id,
            f"pending_successor.state must be exactly 'PENDING', got {pending.get('state')!r}",
        ))
    if not str(pending.get("reason") or "").strip():
        findings.append(Finding(
            "CHAIN_PENDING_UNREASONED", ERROR, chain_id, node_id,
            f"declares {required} pending with no reason; a bare pending flag is an excuse, not a "
            "declaration",
        ))
    if not str(pending.get("owner") or "").strip():
        findings.append(Finding(
            "CHAIN_PENDING_UNOWNED", ERROR, chain_id, node_id,
            f"declares {required} pending with no owner; unowned pending work is how a defect "
            "becomes permanent",
        ))
    return findings


def _check_promotion(chain_id: str, node: dict[str, Any],
                     nodes: dict[str, Any]) -> list[Finding]:
    if node["node_kind"] != "CURRENTNESS_PROMOTION":
        return []
    findings: list[Finding] = []
    node_id = str(node["node_id"])
    promotion = node.get("promotion")
    if not isinstance(promotion, dict) or not str(promotion.get("promoted_state") or "").strip():
        findings.append(Finding(
            "CHAIN_PROMOTION_UNSTATED", ERROR, chain_id, node_id,
            "a currentness promotion must name the state it promotes; an unnamed promotion cannot "
            "be checked against its verdict",
        ))
        return findings

    promoted_state = str(promotion["promoted_state"])
    verdicts = [
        nodes[parent] for parent in (node["derives_from"] or [])
        if parent in nodes and nodes[parent]["node_kind"] == "VERDICT"
    ]
    for verdict_node in verdicts:
        verdict = verdict_node.get("verdict")
        if not isinstance(verdict, dict):
            findings.append(Finding(
                "CHAIN_VERDICT_UNSTATED", ERROR, chain_id, str(verdict_node["node_id"]),
                "a VERDICT node must carry a verdict object stating its value and whether it was "
                "independent",
            ))
            continue
        claimed = promotion.get("promoted_from_verdict_value")
        actual = verdict.get("verdict_value")
        if claimed is not None and claimed != actual:
            findings.append(Finding(
                "CHAIN_PROMOTION_CONTRADICTS_VERDICT", ERROR, chain_id, node_id,
                f"promotion records the verdict as {claimed!r} while {verdict_node['node_id']} "
                f"actually says {actual!r}",
            ))
        if promoted_state in ACCEPTANCE_CLASS_PROMOTIONS and verdict.get("independent") is not True:
            findings.append(Finding(
                "CHAIN_PROMOTION_ON_NON_INDEPENDENT_VERDICT", ERROR, chain_id, node_id,
                f"promotes to the acceptance-class state {promoted_state} on "
                f"{verdict_node['node_id']}, which is not an independent verdict; a producer "
                "cannot issue its own acceptance",
                {"promoted_state": promoted_state, "verdict": verdict},
            ))
    return findings


def _check_cycles(chain_id: str, nodes: dict[str, Any]) -> list[Finding]:
    """A cycle makes 'what does this rest on' unanswerable."""
    colour: dict[str, int] = {}
    findings: list[Finding] = []

    def walk(node_id: str, trail: list[str]) -> None:
        colour[node_id] = 1
        for parent in nodes[node_id]["derives_from"] or []:
            if parent not in nodes:
                continue
            if colour.get(parent) == 1:
                findings.append(Finding(
                    "CHAIN_CYCLE", ERROR, chain_id, node_id,
                    "the derivation graph contains a cycle: "
                    + " -> ".join(trail + [node_id, parent]),
                    {"cycle_through": parent},
                ))
                continue
            if colour.get(parent) is None:
                walk(parent, trail + [node_id])
        colour[node_id] = 2

    for node_id in sorted(nodes):
        if colour.get(node_id) is None:
            walk(node_id, [])
    return findings


def verify_citations(chains: dict[str, Any], repo_root: Path) -> list[Finding]:
    """Recompute every working-tree citation. A citation nobody can resolve is a claim.

    Only citations that offer both a path and a digest are recomputed here.
    A commit-pinned citation names bytes this checkout may not hold, and a
    locator names something outside the repository; both are recorded and
    neither is silently treated as verified.
    """
    findings: list[Finding] = []
    for chain_id, chain in chains.items():
        for node_id, node in sorted(chain["nodes"].items()):
            citations = node.get("evidence_citations")
            if not isinstance(citations, list):
                continue
            for position, citation in enumerate(citations):
                if not isinstance(citation, dict):
                    findings.append(Finding(
                        "CHAIN_CITATION_MALFORMED", ERROR, chain_id, node_id,
                        f"citation {position} is not an object",
                    ))
                    continue
                path = citation.get("artifact_path")
                digest = citation.get("sha256")
                if not path or not digest:
                    if not path and not citation.get("locator") and not citation.get("commit"):
                        findings.append(Finding(
                            "CHAIN_CITATION_UNADDRESSABLE", ERROR, chain_id, node_id,
                            f"citation {position} names neither an artifact path, a commit nor a "
                            "locator, so nothing can be reached from it",
                        ))
                    continue
                if len(str(digest)) != 64 or not set(str(digest)) <= SHA256_HEX:
                    findings.append(Finding(
                        "CHAIN_CITATION_HASH_MALFORMED", ERROR, chain_id, node_id,
                        f"citation {position} carries a malformed sha256 {digest!r}",
                    ))
                    continue
                target = repo_root / str(path)
                if not target.is_file():
                    findings.append(Finding(
                        "CHAIN_CITATION_ABSENT", ERROR, chain_id, node_id,
                        f"cites {path}, which does not exist in this checkout",
                        {"artifact_path": path},
                    ))
                    continue
                actual = sha256_bytes(target.read_bytes())
                if actual != digest:
                    findings.append(Finding(
                        "CHAIN_CITATION_HASH_MISMATCH", ERROR, chain_id, node_id,
                        f"cites {path} at {digest} but the checkout serves {actual}; the citation "
                        "addresses bytes that are no longer there",
                        {"artifact_path": path, "claimed": digest, "actual": actual},
                    ))
    return findings


def open_chain_findings(chains: dict[str, Any]) -> list[Finding]:
    """The recovery view: an open chain is a live recovery item, not a failure."""
    findings: list[Finding] = []
    for chain_id, chain in chains.items():
        for pending in chain["pending"]:
            findings.append(Finding(
                "CHAIN_SUCCESSOR_PENDING", WARNING, chain_id, str(pending.get("node_id")),
                f"{pending.get('node_kind')} is declared PENDING and owned by "
                f"{pending.get('owner')}: {pending.get('reason')}",
                {"pending": pending},
            ))
    return findings


def check_all(events: Sequence[dict[str, Any]],
              repo_root: Path | None = None) -> tuple[dict[str, Any], list[Finding]]:
    """Project, then refuse. Returns (chains, findings)."""
    chains = project_chains(events)
    findings: list[Finding] = []
    for chain in chains.values():
        findings.extend(check_chain(chain))
    findings.extend(open_chain_findings(chains))
    if repo_root is not None:
        findings.extend(verify_citations(chains, repo_root))
    return chains, findings


# --------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------


def declared_contract() -> dict[str, Any]:
    """The vocabulary and rules this module actually enforces, as data.

    `control-plane.json` records the same shape. `validate_contract` compares
    the two rather than trusting the document, so a contract that drifts from
    the code is caught instead of being read as a description of it.
    """
    return {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "canonical_store": "workstreams/so02/control-plane/state/events.jsonl",
        "new_store_created": False,
        "link_event_type": LINK_EVENT_TYPE,
        "contract_event_type": CONTRACT_EVENT_TYPE,
        "link_payload_key": LINK_PAYLOAD_KEY,
        "node_kinds": list(NODE_KINDS),
        "evidence_labels": list(EVIDENCE_LABELS),
        "provenance_classes": list(PROVENANCE_CLASSES),
        "allowed_edges": {k: sorted(v) for k, v in ALLOWED_EDGES.items()},
        "required_predecessor": dict(REQUIRED_PREDECESSOR),
        "required_successor": dict(REQUIRED_SUCCESSOR),
        "successor_waivable_by_declared_pending": True,
        "predecessor_waivable": False,
        "acceptance_class_promotions": sorted(ACCEPTANCE_CLASS_PROMOTIONS),
    }


def validate_contract(contract: Any) -> list[str]:
    """Compare a recorded contract with the enforced one. Empty means they agree."""
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["improvement-chain contract: must be an object"]
    enforced = declared_contract()
    for key, expected in enforced.items():
        if key not in contract:
            errors.append(f"improvement-chain contract: missing {key}")
            continue
        actual = contract[key]
        if isinstance(expected, dict) and isinstance(actual, dict):
            normalised = {k: sorted(v) if isinstance(v, list) else v for k, v in actual.items()}
            if normalised != expected:
                errors.append(
                    f"improvement-chain contract: {key} drifted from the enforced rule set"
                )
        elif actual != expected:
            errors.append(
                f"improvement-chain contract: {key} records {actual!r} but the module enforces "
                f"{expected!r}"
            )
    return errors


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def summarise(chains: dict[str, Any], findings: Iterable[Finding]) -> dict[str, Any]:
    findings = list(findings)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    labels: dict[str, int] = {}
    for chain in chains.values():
        for node in chain["nodes"].values():
            key = str(node.get("evidence_label"))
            labels[key] = labels.get(key, 0) + 1
    return {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "chain_count": len(chains),
        "node_count": sum(chain["node_count"] for chain in chains.values()),
        "chain_states": {
            chain_id: chain["chain_state"] for chain_id, chain in chains.items()
        },
        "next_required_node_kind": {
            chain_id: chain["next_required_node_kind"] for chain_id, chain in chains.items()
        },
        "evidence_label_counts": dict(sorted(labels.items())),
        "finding_counts": dict(sorted(counts.items())),
        "refused": any(finding.severity == ERROR for finding in findings),
        "findings": [finding.as_dict() for finding in findings],
    }


def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if isinstance(value, dict):
            events.append(value)
    return events
