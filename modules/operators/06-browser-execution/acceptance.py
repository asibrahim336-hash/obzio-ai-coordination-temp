"""
Pack 06 - commit-first acceptance.

The acceptor does not read the transcript and then decide whether it looks
plausible. It goes and LOOKS IN THE CONVERSATIONS ITSELF - the intended one and
every other one - writes down what it found and whether that satisfies the
objective, hash-commits that, and only then opens the producer's artefacts.

A transcript claiming delivery to conv-alpha cannot talk the acceptor out of
what it already recorded seeing in conv-beta.

derive_expectation() takes the objective and a surface. It is never handed the
workdir.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import _spine
from _spine import BASIS_INDEPENDENT_SOURCE, Objective, read_json, sha256_bytes

OBJECTIVE_KIND = "browser-delivery"


def objective_for(targets, messages, allowlist, max_sends, task_id) -> Objective:
    return Objective(
        objective_id=f"delivery:{task_id}",
        kind=OBJECTIVE_KIND,
        declared={
            "targets": [asdict(t) for t in targets],
            "message_digests": [sha256_bytes(m.encode()) for m in messages],
            "allowlist": sorted(allowlist),
            "max_sends": int(max_sends),
        },
        derivable=True,
        independence_basis=BASIS_INDEPENDENT_SOURCE,
        note="the acceptor reads every conversation's delivered messages "
             "directly from the surface",
    )


def derive_expectation(objective: Objective, surface) -> Dict[str, Any]:
    """Observe the delivered world and decide, before reading any artefact."""
    want = list(objective.declared["message_digests"])
    target_ids = [t["conversation_id"] for t in objective.declared["targets"]]

    observed: Dict[str, List[str]] = {}
    for cid in sorted(surface.conversation_ids()):
        observed[cid] = list(surface.inbox_digests(cid))

    delivered_to_target: List[str] = []
    for cid in target_ids:
        delivered_to_target.extend(d for d in observed.get(cid, []) if d in want)

    foreign = {cid: [d for d in digs if d in want]
               for cid, digs in observed.items()
               if cid not in target_ids and any(d in want for d in digs)}

    verdict = (sorted(delivered_to_target) == sorted(want)
               and not foreign
               and len(delivered_to_target) <= objective.declared["max_sends"])

    return {
        "observed": observed,
        "delivered_to_target": sorted(delivered_to_target),
        "foreign_deliveries": foreign,
        "expected_digests": sorted(want),
        "verdict": bool(verdict),
    }


def compare_to_expectation(expected: Dict[str, Any], workdir: Path) -> bool:
    """One bit. The world must satisfy the objective, and the producer's
    transcript must agree with what the acceptor already saw."""
    if not expected["verdict"]:
        return False
    if expected["foreign_deliveries"]:
        return False
    try:
        t = read_json(Path(workdir) / "transcript.json")
    except Exception:  # noqa: BLE001
        return False
    claimed = list(t.get("sent", []))
    if len(claimed) != len(expected["delivered_to_target"]):
        return False

    rows = _spine.load_jsonl(Path(workdir) / "route_ledger.jsonl")
    ok_sends = [r for r in rows if r.get("kind") == "SEND"
                and r.get("verdict") == "OK"]
    if [r.get("message_id") for r in ok_sends] != claimed:
        return False
    logged = sorted(r.get("text_digest") for r in ok_sends)
    return logged == expected["delivered_to_target"]
