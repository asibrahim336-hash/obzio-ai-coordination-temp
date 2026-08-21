"""strategic-orchestration state machine.

Wires this pack's real work (engine.py) and its checks into the shared
lifecycle, and installs guards specific to orchestration.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine.machine import OperatorMachine
from obzio_spine.states import State
from obzio_spine.artefacts import write_json, read_json
from obzio_spine import acceptance as acc

import engine
import oracle
from checks import run_checks, REQUIRED_ARTEFACTS

PACK = "strategic-orchestration"


def make_acceptor(reviewer_id, objective_doc, spec, returns):
    """Build the acceptor's pre-commitment from the DECLARED INPUTS ONLY.

    Call this BEFORE build_machine. The acceptor derives its own expected
    reconciliation via oracle.py -- which does not import engine.py -- so it
    is not reading the producer's output and cannot be anchored by it."""
    from obzio_spine.expectation import Acceptor
    return Acceptor(reviewer_id,
                    oracle.derive_expectation(objective_doc, spec, returns),
                    oracle.inputs_digest(objective_doc, spec, returns))


def build_machine(run_dir, producer_id, commitments, objective_doc, spec, returns,
                  acceptor=None):
    """Construct a fully-guarded orchestration machine.

    `returns` is what came back from the commissioned operators. It is passed
    in rather than generated here: an orchestrator that manufactures its own
    returns is reconciling against itself.
    """
    m = OperatorMachine(PACK, run_dir, producer_id, commitments,
                        artefact_names=REQUIRED_ARTEFACTS)
    m._inputs = {"objective_doc": objective_doc, "spec": spec, "returns": returns}
    m.set_expectation_extractor(lambda mm: oracle.extract_actual(mm.run_dir))
    if acceptor is not None:
        # Registered at PREFLIGHT, before a single artefact exists. The machine
        # refuses the registration otherwise.
        m.register_expectation(acceptor.commitment())

    @m.guard(State.CURRENT_STATE_RECOVERED)
    def _recover(mm, **kw):
        # Orchestration recovers from any prior journal in the run dir. A fresh
        # run legitimately recovers an empty state -- but it must say so.
        prior = os.path.join(mm.run_dir, "return_state.json")
        mm._recovered = read_json(prior) if os.path.exists(prior) else {"prior_run": None}
        mm._record("STATE_RECOVERED", {"had_prior": mm._recovered.get("prior_run") is not None})
        return True

    @m.guard(State.INPUT_ADMITTED)
    def _admit(mm, **kw):
        d = mm._inputs["objective_doc"]
        for k in ("id", "statement", "budget_units", "deadline_iso"):
            if k not in d:
                raise ValueError(f"objective missing required field {k!r}")
        if int(d["budget_units"]) <= 0:
            raise ValueError("objective budget must be positive")
        if not mm._inputs["spec"]:
            raise ValueError("empty decomposition spec: nothing to commission")
        mm._objective = engine.Objective(
            id=d["id"], statement=d["statement"],
            budget_units=int(d["budget_units"]), deadline_iso=d["deadline_iso"],
            non_goals=list(d.get("non_goals", [])),
        )
        mm._ceiling = d.get("orchestrator_max_authority", "PROPOSE_ONLY")
        mm._record("INPUT_ADMITTED", {"objective": d["id"], "spec_rows": len(mm._inputs["spec"])})
        return True

    @m.guard(State.ACTION_EXECUTED)
    def _execute(mm, **kw):
        comms = engine.decompose(mm._objective, mm._inputs["spec"])
        routing = engine.route(comms)
        recon = engine.reconcile(comms, mm._inputs["returns"])

        obj_doc = mm._objective.to_json()
        obj_doc["orchestrator_max_authority"] = mm._ceiling

        paths = {
            "objective": os.path.join(mm.run_dir, "objective.json"),
            "commissions": os.path.join(mm.run_dir, "commissions.json"),
            "routing_table": os.path.join(mm.run_dir, "routing_table.json"),
            "reconciliation": os.path.join(mm.run_dir, "reconciliation.json"),
        }
        write_json(paths["objective"], obj_doc)
        write_json(paths["commissions"], [c.to_json() for c in comms])
        write_json(paths["routing_table"], routing)
        write_json(paths["reconciliation"], recon)
        for name, p in paths.items():
            mm.declare_artefact(name, p)
        mm._record("ACTION_EXECUTED",
                   {"commissions": len(comms), "waves": len(routing["waves"]),
                    "reconciled": recon["reconciled"]})
        return True

    @m.guard(State.REQUIRED_ARTEFACTS_PRESENT)
    def _present(mm, **kw):
        missing = [a for a in REQUIRED_ARTEFACTS
                   if not os.path.exists(os.path.join(mm.run_dir, a))]
        if missing:
            raise FileNotFoundError(f"required artefacts absent: {missing}")
        return True

    @m.guard(State.MACHINE_CHECKS_PASSED)
    def _checks(mm, **kw):
        rep = run_checks(mm.run_dir)
        mm.check_report = rep
        write_json(os.path.join(mm.run_dir, "check_report.json"), rep.to_json())
        mm._record("CHECKS_RUN", {"passed": rep.passed, "failures": len(rep.failures)})
        return rep.passed

    @m.guard(State.INDEPENDENT_ACCEPTANCE)
    def _ready_for_review(mm, **kw):
        # Entering the gate state only means the work is presentable. Leaving
        # it is what requires the reviewer.
        mm._record("SUBMITTED_FOR_REVIEW", {"run_digest": mm.current_run_digest()})
        return True

    @m.guard(State.RETURN_STATE_WRITTEN)
    def _write_return(mm, **kw):
        mm.write_return_state(State.RETURN_STATE_WRITTEN)
        mm.flush_journal()
        return True

    @m.guard(State.COMPLETE)
    def _complete(mm, **kw):
        # Rewritten at COMPLETE so the durable record a continuity operator
        # reads says COMPLETE, not the intermediate state.
        mm.write_return_state(State.COMPLETE)
        mm.flush_journal()
        return True

    return m
