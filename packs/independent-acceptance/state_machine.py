"""independent-acceptance state machine.

Note the recursion this pack sits inside: this reviewer is itself a producing
operator, so ITS output must in turn be accepted by a different principal. The
gate applies to the reviewer exactly as it applies to everyone else. A review
that signs itself off is the same defect one level up.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from obzio_spine.machine import OperatorMachine
from obzio_spine.states import State

import engine
import oracle
from fence import (WriteFence, SubjectHandle, IndependenceProof,
                   ProductionAttemptError, IndependenceViolation)
from checks import run_checks, REQUIRED_ARTEFACTS

PACK = "independent-acceptance"


def make_acceptor(acceptor_id, subject_root, subject_required_artefacts,
                  reviewer_id):
    """Pre-commitment by the party who will accept the REVIEW.

    It may read the subject -- that is its input. It may not read the review's
    output, and the machine's anchoring check enforces that."""
    from obzio_spine.expectation import Acceptor
    return Acceptor(acceptor_id,
                    oracle.derive_expectation(subject_root,
                                              subject_required_artefacts,
                                              reviewer_id),
                    oracle.inputs_digest(subject_root,
                                         subject_required_artefacts, reviewer_id))


def build_machine(run_dir, reviewer_id, commitments, subject_root,
                  subject_required_artefacts, subject_pack_dir=None,
                  acceptor=None):
    """`reviewer_id` is this pack's PRODUCER id -- it produces a review.
    `commitments` therefore belong to a THIRD principal who accepts the review.
    """
    m = OperatorMachine(PACK, run_dir, reviewer_id, commitments,
                        artefact_names=REQUIRED_ARTEFACTS)
    m._subject_root = subject_root
    m._required = list(subject_required_artefacts)
    m._subject_pack_dir = subject_pack_dir
    m._fence = WriteFence(subject_root, run_dir)
    m.set_expectation_extractor(
        lambda mm: oracle.extract_actual(mm.run_dir, mm._subject_root,
                                         mm._required))
    if acceptor is not None:
        m.register_expectation(acceptor.commitment())

    @m.guard(State.CURRENT_STATE_RECOVERED)
    def _recover(mm, **kw):
        mm._handle = SubjectHandle(mm._subject_root)
        mm._proof = IndependenceProof(mm._handle)
        files = mm._handle.files()
        if not files:
            raise ValueError(f"subject {mm._subject_root!r} contains no files")
        mm._record("STATE_RECOVERED",
                   {"subject_files": len(files),
                    "snapshot_taken": len(mm._proof.before)})
        return True

    @m.guard(State.INPUT_ADMITTED)
    def _admit(mm, **kw):
        # The subject must name a producer, and it must not be this reviewer.
        producer = None
        if mm._handle.exists("return_state.json"):
            producer = mm._handle.read_json("return_state.json").get("producer_id")
        mm._subject_producer = producer
        if producer is not None and producer == mm.producer_id:
            raise PermissionError(
                f"cannot review own work: subject was produced by "
                f"{producer!r}, which is this reviewer")
        if not mm._required:
            raise ValueError("no required-artefact list supplied; a review with "
                             "no expectations cannot fail")
        mm._record("INPUT_ADMITTED",
                   {"subject_producer": producer, "required": mm._required})
        return True

    @m.guard(State.ACTION_EXECUTED)
    def _execute(mm, **kw):
        rv = engine.Review(mm._handle, mm._subject_pack_dir)
        findings = rv.run_all(mm._required)
        verdict = rv.verdict()

        # Re-verify independence BEFORE writing the verdict. If the subject
        # moved, the verdict is meaningless and must not be recorded as valid.
        mm._proof.verify()

        mm._review = rv
        outputs = ["review_scope.json", "findings.json", "verdict.json",
                   "independence_proof.json"]

        mm._fence.write_json(os.path.join(mm.run_dir, "review_scope.json"), {
            "reviewer_id": mm.producer_id,
            "subject_root": os.path.realpath(mm._subject_root),
            "subject_producer_id": mm._subject_producer,
            "subject_pack_dir": mm._subject_pack_dir,
            "required_artefacts": mm._required,
            "subject_files": mm._handle.files(),
            "probes_run": rv.probes_run,
            "recomputed_subject_checks": hasattr(rv, "recomputed"),
            "review_outputs": outputs,
        })
        mm._fence.write_json(os.path.join(mm.run_dir, "findings.json"),
                             [f.to_json() for f in findings])
        mm._fence.write_json(os.path.join(mm.run_dir, "verdict.json"), {
            "verdict": verdict,
            "blocking_count": len(rv.blocking),
            "advisory_count": len(findings) - len(rv.blocking),
            "reviewer_id": mm.producer_id,
            "subject_root": os.path.realpath(mm._subject_root),
            "rationale": ("no blocking findings" if verdict == engine.ACCEPT
                          else f"{len(rv.blocking)} blocking findings"),
        })
        mm._fence.write_json(os.path.join(mm.run_dir, "independence_proof.json"),
                             mm._proof.to_json())
        for n in ("review_scope", "findings", "verdict", "independence_proof"):
            mm.declare_artefact(n, os.path.join(mm.run_dir, f"{n}.json"))
        mm._record("ACTION_EXECUTED",
                   {"verdict": verdict, "findings": len(findings),
                    "blocking": len(rv.blocking), "probes": len(rv.probes_run)})
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
        mm._fence.write_json(os.path.join(mm.run_dir, "check_report.json"),
                             rep.to_json())
        mm._record("CHECKS_RUN", {"passed": rep.passed, "failures": len(rep.failures)})
        return rep.passed

    @m.guard(State.INDEPENDENT_ACCEPTANCE)
    def _submit(mm, **kw):
        # Final independence re-verification at submission.
        mm._proof.verify()
        mm._record("SUBMITTED_FOR_REVIEW", {"run_digest": mm.current_run_digest()})
        return True

    @m.guard(State.RETURN_STATE_WRITTEN)
    def _write_return(mm, **kw):
        mm._fence.check(os.path.join(mm.run_dir, "return_state.json"))
        mm.write_return_state(State.RETURN_STATE_WRITTEN)
        mm.flush_journal()
        return True

    @m.guard(State.COMPLETE)
    def _complete(mm, **kw):
        mm.write_return_state(State.COMPLETE)
        mm.flush_journal()
        return True

    return m
