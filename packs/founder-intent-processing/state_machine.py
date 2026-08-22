"""founder-intent-processing state machine."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine.machine import OperatorMachine
from obzio_spine.states import State
from obzio_spine.artefacts import write_json, read_json

import engine
import oracle
from checks import run_checks, REQUIRED_ARTEFACTS

PACK = "founder-intent-processing"


def make_acceptor(reviewer_id, correction_text, surface_registry):
    """Pre-commitment derived from the correction and registry ONLY.

    PARTIAL_ORACLE: covers the literal claims and the structural invariants.
    It deliberately does not commit to the implications -- see oracle.py."""
    from obzio_spine.expectation import Acceptor
    return Acceptor(reviewer_id,
                    oracle.derive_expectation(correction_text, surface_registry),
                    oracle.inputs_digest(correction_text, surface_registry))


def build_machine(run_dir, producer_id, commitments, correction_text,
                  surface_registry, received_at="unknown", acceptor=None):
    m = OperatorMachine(PACK, run_dir, producer_id, commitments,
                        artefact_names=REQUIRED_ARTEFACTS)
    m.set_expectation_extractor(lambda mm: oracle.extract_actual(mm.run_dir))
    if acceptor is not None:
        m.register_expectation(acceptor.commitment())
    m._inputs = {"text": correction_text, "registry": surface_registry,
                 "received_at": received_at}

    @m.guard(State.CURRENT_STATE_RECOVERED)
    def _recover(mm, **kw):
        # The surface registry IS the current state for this pack: you cannot
        # know what a correction affects without knowing what exists.
        reg = mm._inputs["registry"]
        if not isinstance(reg, dict) or not reg:
            raise ValueError("empty surface registry: nothing to assess impact against")
        for name, meta in reg.items():
            if "tags" not in meta:
                raise ValueError(f"surface {name!r} has no tags; cannot be routed")
        mm._record("STATE_RECOVERED", {"surfaces_known": len(reg)})
        return True

    @m.guard(State.INPUT_ADMITTED)
    def _admit(mm, **kw):
        t = mm._inputs["text"]
        if not isinstance(t, str) or not t.strip():
            raise ValueError("empty correction")
        # Admission does NOT normalise the text. Normalising would break every
        # verbatim span downstream.
        if t != t:
            raise AssertionError("unreachable")
        mm._record("INPUT_ADMITTED", {"chars": len(t)})
        return True

    @m.guard(State.ACTION_EXECUTED)
    def _execute(mm, **kw):
        src = mm._inputs["text"]
        reg = mm._inputs["registry"]
        claims = engine.extract_claims(src)
        imps = engine.derive_implications(claims, reg)
        impact = engine.map_surfaces(imps, reg)
        orders = engine.emit_change_orders(imps, impact)

        write_json(os.path.join(mm.run_dir, "correction.json"), {
            "source_text": src,
            "received_at": mm._inputs["received_at"],
            "char_count": len(src),
            "registry_surfaces": sorted(reg),
        })
        write_json(os.path.join(mm.run_dir, "interpretation.json"), {
            "literal_claims": [c.to_json() for c in claims],
            "system_implications": [i.to_json() for i in imps],
            "separation_note": (
                "literal_claims reproduce the founder's words at the given "
                "byte spans; system_implications are the operator's inferences "
                "and are not attributable to the founder"),
        })
        write_json(os.path.join(mm.run_dir, "surface_impact.json"), impact)
        write_json(os.path.join(mm.run_dir, "change_orders.json"),
                   [o.to_json() for o in orders])

        for n in ("correction", "interpretation", "surface_impact", "change_orders"):
            mm.declare_artefact(n, os.path.join(mm.run_dir, f"{n}.json"))
        mm._record("ACTION_EXECUTED", {"claims": len(claims),
                                       "implications": len(imps),
                                       "orders": len(orders)})
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
    def _submit(mm, **kw):
        mm._record("SUBMITTED_FOR_REVIEW", {"run_digest": mm.current_run_digest()})
        return True

    @m.guard(State.RETURN_STATE_WRITTEN)
    def _write_return(mm, **kw):
        mm.write_return_state(State.RETURN_STATE_WRITTEN)
        mm.flush_journal()
        return True

    @m.guard(State.COMPLETE)
    def _complete(mm, **kw):
        mm.write_return_state(State.COMPLETE)
        mm.flush_journal()
        return True

    return m
