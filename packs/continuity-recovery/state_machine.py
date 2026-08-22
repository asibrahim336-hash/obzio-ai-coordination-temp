"""continuity-recovery state machine.

CURRENT_STATE_RECOVERED is not a formality in this pack -- it is the entire
job. Everything else exists to prove that the recovery was honest.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine.machine import OperatorMachine
from obzio_spine.states import State
from obzio_spine.artefacts import write_json

import engine
import oracle
from checks import run_checks, REQUIRED_ARTEFACTS

PACK = "continuity-recovery"


def make_acceptor(reviewer_id, recovery_root):
    """Pre-commitment derived by walking the corpus independently.

    The corpus is the acceptor's input; the RECOVERY'S OUTPUT is what the
    anchoring check hides from it until after the commitment."""
    from obzio_spine.expectation import Acceptor
    return Acceptor(reviewer_id, oracle.derive_expectation(recovery_root),
                    oracle.inputs_digest(recovery_root))


def build_machine(run_dir, producer_id, commitments, recovery_root,
                  acceptor=None):
    m = OperatorMachine(PACK, run_dir, producer_id, commitments,
                        artefact_names=REQUIRED_ARTEFACTS)
    m._root = os.path.realpath(recovery_root)
    m.set_expectation_extractor(lambda mm: oracle.extract_actual(mm.run_dir))
    if acceptor is not None:
        m.register_expectation(acceptor.commitment())

    @m.guard(State.CURRENT_STATE_RECOVERED)
    def _recover(mm, **kw):
        if not os.path.isdir(mm._root):
            raise FileNotFoundError(f"recovery root {mm._root!r} is not a directory")
        # The output directory must not be inside the input, or the recovery
        # would start reading its own output on the second pass -- and the
        # determinism check would then be self-fulfilling.
        rd = os.path.realpath(mm.run_dir)
        if rd == mm._root or rd.startswith(mm._root + os.sep):
            raise ValueError(
                f"run_dir {rd!r} is inside the recovery root {mm._root!r}: "
                f"recovery would ingest its own output")
        files = engine.scan(mm._root)
        if not files:
            raise ValueError(f"recovery root {mm._root!r} contains no artefacts")
        mm._scanned = files
        mm._record("STATE_RECOVERED", {"files_available": len(files)})
        return True

    @m.guard(State.INPUT_ADMITTED)
    def _admit(mm, **kw):
        # This pack admits EXACTLY ONE kind of input: a directory of durable
        # artefacts. There is no parameter through which a caller could inject
        # remembered context, and that absence is the control.
        if any(k for k in kw):
            raise ValueError(
                f"continuity-recovery admits no side-channel input; got {list(kw)}")
        mm._record("INPUT_ADMITTED",
                   {"source": "durable artefacts only", "files": len(mm._scanned),
                    "conversation_history": None})
        return True

    @m.guard(State.ACTION_EXECUTED)
    def _execute(mm, **kw):
        out = engine.recover(mm._root)
        for name in ("recovered_state", "provenance", "gap_report"):
            p = os.path.join(mm.run_dir, f"{name}.json")
            write_json(p, out[name])
            mm.declare_artefact(name, p)
        mm._record("ACTION_EXECUTED", {
            "runs": out["recovered_state"]["run_count"],
            "facts": out["provenance"]["fact_count"],
            "gaps": out["gap_report"]["gap_count"],
            "contradictions": out["gap_report"]["contradiction_count"]})
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
