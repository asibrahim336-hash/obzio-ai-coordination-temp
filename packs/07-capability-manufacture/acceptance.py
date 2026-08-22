"""
Pack 07 - commit-first acceptance.

The producer's `assessment.json` is a candidate answer to "did a capability
arrive?". An acceptor that reads it and then re-checks it is anchored to it -
a confident MATERIAL verdict biases the re-check exactly when it should not.

So the acceptor runs the probes ITSELF, against the same quarantine, in its own
scratch directory, and commits its own verdict before the artefact window
opens. Quarantine is vendor input that both parties observe; `assessment.json`
is the producer's claim and is not an input to the expectation.

derive_expectation() takes the objective only. It never sees the workdir.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict

import _spine
from _spine import BASIS_INDEPENDENT_SOURCE, Objective, read_json
from state_machine import (
    CommissionSpec, CommissionValidator, Deliverable, Probe, Verdict,
)

OBJECTIVE_KIND = "commissioned-capability"


def objective_for(spec: CommissionSpec, quarantine) -> Objective:
    return Objective(
        objective_id=f"commission:{spec.commission_id}",
        kind=OBJECTIVE_KIND,
        declared={"spec": spec.to_dict(), "quarantine": str(quarantine)},
        derivable=True,
        independence_basis=BASIS_INDEPENDENT_SOURCE,
        note="the acceptor executes the vendor artefacts itself; the "
             "producer's assessment is not an input",
    )


def _spec_from_declared(d: Dict[str, Any]) -> CommissionSpec:
    dels = []
    for x in d["deliverables"]:
        pr = x.get("probe")
        dels.append(Deliverable(
            path=x["path"], kind=x["kind"],
            must_define=tuple(x.get("must_define", ())),
            min_bytes=x.get("min_bytes", 1),
            probe=(Probe(argv=tuple(pr.get("argv", ())),
                         expect_exit=pr.get("expect_exit", 0),
                         expect_stdout_contains=tuple(
                             pr.get("expect_stdout_contains", ())),
                         timeout_s=pr.get("timeout_s", 15.0))
                   if pr else None)))
    return CommissionSpec(
        commission_id=d["commission_id"], vendor=d["vendor"],
        deliverables=tuple(dels),
        min_probes_passed=d.get("min_probes_passed", 1),
        max_prose_ratio=d.get("max_prose_ratio", 2.0))


def derive_expectation(objective: Objective) -> Dict[str, Any]:
    """Run the probes independently and record our own verdict."""
    spec = _spec_from_declared(objective.declared["spec"])
    quarantine = Path(objective.declared["quarantine"])
    scratch = Path(tempfile.mkdtemp(prefix="acceptor-07-"))
    validator = CommissionValidator(quarantine, scratch)
    a = validator.validate(spec, spec.digest())
    return {
        "verdict": a.verdict,
        "probes_defined": a.probes_defined,
        "probes_passed": a.probes_passed,
        "missing": sorted(a.missing),
        "type_failures_count": len(a.type_failures),
        "deliverable_digests": {r["path"]: r["sha256"] for r in a.deliverables},
    }


def compare_to_expectation(expected: Dict[str, Any], workdir: Path) -> bool:
    """One bit. The producer's verdict must equal the one the acceptor reached
    by running the code itself."""
    if expected["verdict"] != Verdict.MATERIAL.value:
        return False
    try:
        a = read_json(Path(workdir) / "assessment.json")
    except Exception:  # noqa: BLE001
        return False
    if a.get("verdict") != expected["verdict"]:
        return False
    if a.get("probes_passed") != expected["probes_passed"]:
        return False
    if a.get("probes_defined") != expected["probes_defined"]:
        return False
    if sorted(a.get("missing", [])) != expected["missing"]:
        return False
    seen = {r["path"]: r.get("sha256") for r in a.get("deliverables", [])}
    return seen == expected["deliverable_digests"]
