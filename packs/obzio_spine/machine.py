"""The operator state machine.

Design rules, all enforced in code rather than asserted in prose:

  1. Transitions are strictly linear. advance() moves exactly one state.
     There is no goto, no skip, no retreat.
  2. Each transition has a GUARD. The guard is a callable that must return
     True. A guard that raises is a failed transition, not a crash to ignore.
  3. The INDEPENDENT_ACCEPTANCE -> RETURN_STATE_WRITTEN transition is the only
     one that cannot be driven by the producer. It requires a Reveal that
     opens a commitment the producer does not hold the preimage for.
  4. Every transition appends to an append-only journal. The journal is the
     artefact a continuity operator reads to rebuild state.
"""

import json
import os
import time

from . import acceptance as acc
from . import expectation as exp
from .artefacts import write_json, read_json, run_digest
from .states import State, TERMINAL, GATED_TRANSITION, next_state


class TransitionError(RuntimeError):
    pass


class GuardFailure(TransitionError):
    pass


class OperatorMachine:
    """One machine per run. Not reusable, not resettable -- a machine you can
    rewind is a machine that can launder a failed run into a passed one."""

    def __init__(
        self,
        pack: str,
        run_dir: str,
        producer_id: str,
        commitments: "acc.AcceptanceCommitments",
        clock=None,
        artefact_names=(),
    ):
        if commitments.reviewer_id == producer_id:
            # Refused at construction: a machine built with the producer as its
            # own reviewer must never exist, not merely fail later.
            raise acc.SelfAcceptanceError(
                f"machine for producer {producer_id!r} was handed commitments "
                f"owned by {commitments.reviewer_id!r} -- same principal"
            )
        self.pack = pack
        self.run_dir = os.path.abspath(run_dir)
        self.producer_id = producer_id
        self.commitments = commitments
        self._clock = clock or (lambda: time.time())
        self.state = State.PREFLIGHT
        self.journal = []
        self.artefacts = {}          # logical name -> abspath
        self.check_report = None
        self.verdict = None
        # ---- commit-first acceptance state ----
        self.artefact_names = tuple(artefact_names)
        self._expectation_commitment = None
        self._expectation_extractor = None
        self._accepted_expectation = None
        self._divergences = []
        self._accepted_digest = None
        self._guards = {}
        self._finalised = False
        os.makedirs(self.run_dir, exist_ok=True)
        self._record("MACHINE_INIT", {"pack": pack, "producer_id": producer_id,
                                      "reviewer_id": commitments.reviewer_id})
        # The journal is the artefact a continuity operator reads. Writing it
        # only at COMPLETE meant an interrupted run left NO journal at all --
        # exactly the run whose state most needs recovering. It is now flushed
        # after every transition, so the record survives an abort at any point.
        self.flush_journal()

    # ---------- commit-first registration ----------

    def register_expectation(self, commitment: "exp.ExpectationCommitment"):
        """Register the acceptor's pre-commitment. PREFLIGHT only.

        THE ANCHORING CHECK. If any declared artefact already exists on disk,
        the acceptor could have read it before committing, and the commitment
        proves nothing about independence. Refused mechanically -- this does
        not rely on the acceptor promising it looked away."""
        if self.state is not State.PREFLIGHT:
            raise exp.AnchoringError(
                f"expectation must be committed at PREFLIGHT, before any "
                f"artefact exists; machine is already at {self.state.name}")
        if self._expectation_commitment is not None:
            raise exp.AnchoringError(
                "an expectation is already committed; re-committing would let "
                "the acceptor revise after seeing the work")
        present = [n for n in self.artefact_names
                   if os.path.exists(os.path.join(self.run_dir, n))]
        if present:
            raise exp.AnchoringError(
                f"refusing to accept a commitment: artefacts {present} already "
                f"exist, so the acceptor may have been anchored by reading "
                f"them before committing")
        self._expectation_commitment = commitment
        self._record("EXPECTATION_COMMITTED", {
            "reviewer_id": commitment.reviewer_id,
            "derivation": commitment.derivation,
            "commitment": commitment.commitment[:16] + "...",
            "inputs_digest": commitment.inputs_digest[:16] + "..."})
        self.flush_journal()
        return self

    def set_expectation_extractor(self, fn):
        """Pack-supplied: reads the produced artefacts and returns the fields
        the pre-committed expectation is compared against."""
        self._expectation_extractor = fn
        return self

    @property
    def acceptance_independence(self) -> str:
        c = self._expectation_commitment
        if c is None:
            return "UNCOMMITTED"
        return ("BEHAVIOURAL_ONLY" if c.derivation == exp.Derivation.NONE
                else c.derivation)

    # ---------- journal ----------

    def _record(self, event: str, detail: dict):
        self.journal.append({
            "seq": len(self.journal),
            "event": event,
            "state": self.state.name,
            "ts": round(self._clock(), 6),
            "detail": detail,
        })

    def journal_path(self) -> str:
        return os.path.join(self.run_dir, "journal.json")

    def flush_journal(self) -> str:
        return write_json(self.journal_path(), self.journal)

    # ---------- guards ----------

    def guard(self, target: "State"):
        """Register the guard for entering `target`. Decorator."""
        def deco(fn):
            self._guards[State(target)] = fn
            return fn
        return deco

    # ---------- artefacts ----------

    def declare_artefact(self, name: str, path: str):
        self.artefacts[name] = os.path.abspath(path)

    def artefact_paths(self):
        return [self.artefacts[k] for k in sorted(self.artefacts)]

    def current_run_digest(self) -> str:
        return run_digest(self.artefact_paths())

    # ---------- the transition ----------

    def advance(self, acceptance: "exp.AcceptanceReturn" = None, **kw):
        """Move exactly one state forward. Returns the new state.

        `acceptance` is the SINGLE-BIT return from the acceptor, carrying the
        verdict bit plus both reveals. It replaces the old `reveal=` parameter,
        which allowed a bare acceptance token with no pre-committed
        expectation -- the anchored configuration."""
        if self._finalised:
            raise TransitionError("machine is finalised; no further transitions")
        if self.state is TERMINAL:
            raise TransitionError("already COMPLETE")

        target = next_state(self.state)

        # Leaving PREFLIGHT without a commitment is refused: commit-first is
        # mandatory. A pack with no derivable expectation must say so by
        # committing Derivation.NONE, which is recorded and labelled
        # BEHAVIOURAL_ONLY -- never silently skipped.
        if self.state is State.PREFLIGHT and self._expectation_commitment is None:
            raise exp.AnchoringError(
                "no acceptance expectation was committed before work began; "
                "commit-first is mandatory. A pack with no independently "
                "derivable expectation must register Derivation.NONE "
                "explicitly rather than omit the commitment")

        # ---- THE GATE ----------------------------------------------------
        # This is the whole point of the pack. A producer calling advance()
        # with no reveal, or a self-issued reveal, or a stale reveal, does not
        # get past here.
        if (self.state, target) == GATED_TRANSITION:
            if acceptance is None:
                raise acc.AcceptanceError(
                    "INDEPENDENT_ACCEPTANCE -> RETURN_STATE_WRITTEN requires an "
                    "acceptance return issued by an independent acceptor; the "
                    "producing process cannot advance itself past this state"
                )
            reveal = acceptance.acceptance_reveal
            expected = self.current_run_digest()

            # 1. Unforgeability + identity separation (unchanged).
            verdict = acc.verify(
                reveal=reveal,
                commitments=self.commitments,
                expected_run_digest=expected,
                producer_id=self.producer_id,
            )

            # 2. The expectation must open the commitment made at PREFLIGHT.
            #    This is what stops an acceptor retrofitting an expectation to
            #    whatever the artefacts happen to say.
            committed = exp.verify_expectation(
                acceptance.expectation_reveal, self._expectation_commitment)

            # 3. Compare artefacts against the PRE-COMMITTED expectation.
            if committed.derivation == exp.Derivation.NONE:
                agrees, divergences = True, []
            elif self._expectation_extractor is None:
                raise exp.DivergenceError(
                    "an expectation was committed but the pack supplied no "
                    "extractor, so it can never be compared")
            else:
                actual = self._expectation_extractor(self)
                agrees, divergences = exp.compare(committed, actual)
            self._divergences = divergences

            # 4. DIVERGENCE DEFAULTS TO REJECT -- enforced here, by the
            #    machine, so it does not depend on the acceptor choosing to be
            #    strict. An acceptor that says ACCEPT over a divergence is
            #    overridden.
            if not agrees:
                self.verdict = acc.REJECT
                self._record("DIVERGENCE_FORCED_REJECT", {
                    "reviewer_id": reveal.reviewer_id,
                    "divergent_fields": sorted(d["field"] for d in divergences),
                    "acceptor_said": verdict})
                self.flush_journal()
                raise exp.DivergenceError(
                    f"REJECT: producer artefacts diverge from the acceptor's "
                    f"pre-committed expectation in "
                    f"{len(divergences)} field(s). Detail is written to the "
                    f"acceptor's sink, not returned to the producer.")

            # 5. The single bit.
            if verdict != acc.ACCEPT or not acceptance.accept:
                self.verdict = acc.REJECT
                self._record("ACCEPTANCE_REJECTED",
                             {"reviewer_id": reveal.reviewer_id, "bit": 0})
                self.flush_journal()
                raise acc.AcceptanceError(
                    f"REJECT (bit=0) from acceptor {reveal.reviewer_id}. "
                    f"No rationale is returned to the producer by design.")

            self.verdict = verdict
            self._accepted_digest = expected
            self._accepted_expectation = committed
            self._record("ACCEPTANCE_VERIFIED", {
                "reviewer_id": reveal.reviewer_id,
                "run_digest": expected,
                "bit": 1,
                "derivation": committed.derivation,
                "expectation_digest": committed.digest()[:16] + "...",
            })
        elif acceptance is not None:
            # A reveal supplied anywhere else is a category error, and silently
            # ignoring it would let a caller believe a gate was crossed.
            raise TransitionError(
                f"acceptance return supplied for ungated transition "
                f"{self.state.name} -> {target.name}"
            )

        # ---- post-acceptance tamper detection ----------------------------
        # Checked BEFORE the terminal guard runs. If this ran after, a tampered
        # run would get its return_state.json rewritten to say COMPLETE and
        # only then fail -- leaving a durable artefact that lies.
        if target is TERMINAL and self._accepted_digest is not None:
            now = self.current_run_digest()
            if now != self._accepted_digest:
                self._record("POST_ACCEPTANCE_TAMPER",
                             {"accepted": self._accepted_digest, "now": now})
                raise TransitionError(
                    "artefacts changed after acceptance: accepted digest "
                    f"{self._accepted_digest[:16]}... but now {now[:16]}...")

        # ---- guard -------------------------------------------------------
        g = self._guards.get(target)
        if g is not None:
            try:
                ok = g(self, **kw)
            except Exception as e:
                self._record("GUARD_ERROR", {"target": target.name, "error": repr(e)})
                self.flush_journal()
                raise GuardFailure(
                    f"guard for {target.name} raised: {e!r}"
                ) from e
            if ok is not True:
                self._record("GUARD_REFUSED", {"target": target.name, "returned": repr(ok)})
                self.flush_journal()
                raise GuardFailure(
                    f"guard for {target.name} refused (returned {ok!r}, needs True)"
                )

        prev = self.state
        self.state = target
        self._record("TRANSITION", {"from": prev.name, "to": target.name})
        self.flush_journal()

        if target is TERMINAL:
            self._finalised = True

        return self.state

    # ---------- return state ----------

    def return_state(self, as_state: "State" = None) -> dict:
        """`as_state` is the state being ENTERED. Guards run before the
        transition commits, so reporting self.state here would record the
        state the machine is leaving -- an off-by-one in the durable record."""
        return {
            "pack": self.pack,
            "producer_id": self.producer_id,
            "reviewer_id": self.commitments.reviewer_id,
            "final_state": (as_state or self.state).name,
            "verdict": self.verdict,
            "accepted_run_digest": self._accepted_digest,
            "acceptance_independence": self.acceptance_independence,
            "expectation_digest": (self._accepted_expectation.digest()
                                   if self._accepted_expectation else None),
            "expectation_covers": (list(self._accepted_expectation.covers)
                                   if self._accepted_expectation else []),
            "expectation_uncovered": (list(self._accepted_expectation.uncovered)
                                      if self._accepted_expectation else []),
            "artefacts": {
                k: os.path.basename(v) for k, v in sorted(self.artefacts.items())
            },
            "checks": self.check_report.to_json() if self.check_report else None,
            "journal_events": len(self.journal),
        }

    def write_return_state(self, as_state: "State" = None) -> str:
        return write_json(os.path.join(self.run_dir, "return_state.json"),
                          self.return_state(as_state))
