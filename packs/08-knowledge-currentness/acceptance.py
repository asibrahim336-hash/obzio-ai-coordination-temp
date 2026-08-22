"""
Pack 08 - commit-first acceptance.

WHY THIS PACK IS THE CLEANEST FIT
---------------------------------
The acceptor can answer the question itself. "Is the live file still equal to
the pinned digest?" is decidable by reading the file - no producer artefact
required. So the acceptor reads the pinned paths, computes its OWN verdict per
key, hash-commits that, and only then opens the producer's drift report.

This structurally kills the carried-forward-MATCH class rather than detecting
it. Under the old anchored design the acceptor re-ran the producer's checks
over the producer's evidence log; a MATCH backed by convincing-looking evidence
had to be caught by a rule. Now the acceptor has already written down DRIFT
from its own read before it ever sees the claim. No rule is consulted. The
verdicts simply differ, and divergence defaults REJECT.

derive_expectation() is never handed the workdir - see the signature.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import _spine
from _spine import (
    BASIS_INDEPENDENT_SOURCE, Objective, read_json,
)
from state_machine import Pinboard, Verdict

OBJECTIVE_KIND = "pinned-state-currentness"


def objective_for(pinboard_path, keys, max_staleness_s) -> Objective:
    """Declared before the run. Everything the acceptor needs, and nothing the
    producer produced."""
    board = Pinboard(pinboard_path)
    declared = {
        "max_staleness_s": max_staleness_s,
        "pins": {k: {"path": board.pins[k].path,
                     "pinned_digest": board.pins[k].pinned_digest,
                     "pinned_bytes": board.pins[k].pinned_bytes}
                 for k in sorted(keys)},
    }
    return Objective(
        objective_id=f"currentness:{Path(pinboard_path).name}",
        kind=OBJECTIVE_KIND,
        declared=declared,
        derivable=True,
        independence_basis=BASIS_INDEPENDENT_SOURCE,
        note="the acceptor reads the pinned paths directly; the producer's "
             "report is not an input to the expectation",
    )


def derive_expectation(objective: Objective) -> Dict[str, Any]:
    """The acceptor's OWN answer, committed before any artefact is opened.

    Note the signature: there is no workdir parameter. The only inputs are the
    objective and the filesystem paths it names."""
    out: Dict[str, Any] = {"verdicts": {}, "live_digests": {}}
    for key, pin in sorted(objective.declared["pins"].items()):
        p = Path(pin["path"])
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            out["verdicts"][key] = Verdict.MISSING.value
            out["live_digests"][key] = None
            continue
        digest = hashlib.sha256(data).hexdigest()
        out["live_digests"][key] = digest
        out["verdicts"][key] = (Verdict.MATCH.value
                                if digest == pin["pinned_digest"]
                                else Verdict.DRIFT.value)
    return out


def compare_to_expectation(expected: Dict[str, Any], workdir: Path) -> bool:
    """One bit. The producer's published verdicts must agree, key for key, with
    what the acceptor independently wrote down first."""
    try:
        report = read_json(Path(workdir) / "drift_report.json")
    except Exception:  # noqa: BLE001
        return False

    rows = {r.get("key"): r for r in report.get("rows", [])}
    exp_v = expected["verdicts"]
    if set(rows) != set(exp_v):
        return False

    for key, want in exp_v.items():
        row = rows[key]
        got = row.get("downgraded_from") or row.get("verdict")
        if got != want:
            return False
        if want in (Verdict.MATCH.value, Verdict.DRIFT.value):
            if row.get("live_digest") != expected["live_digests"][key]:
                return False
    return True
