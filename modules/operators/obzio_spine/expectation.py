"""Commit-first acceptance: defeating the ANCHORED verifier.

THE DEFECT THIS FIXES
---------------------
The acceptance gate in `acceptance.py` proves two things well:
  * the acceptor is a different identity from the producer
  * the acceptance token binds this exact artefact set

It proves NOTHING about whether the acceptor formed an independent judgement.
An acceptor that is handed the workdir, reads the artefacts, re-runs the
producer's own checks and then decides is ANCHORED to the thing it is judging.
Identity separation does not fix anchoring: a different principal reading the
same artefacts through the same lens will ratify what it reads.

Unforgeable is not the same property as unanchored. The old design had the
first and claimed the second.

THE PROTOCOL
------------
  1. BEFORE any artefact exists, the acceptor derives its OWN expected result
     from the run's DECLARED INPUTS ONLY, and commits a hash of it:

         C_exp = sha256(domain|EXPECT|salt|expectation_digest|inputs_digest)

     The commitment is registered with the machine while it is still in
     PREFLIGHT. The machine refuses the registration if any declared artefact
     already exists on disk -- that is the anchoring check, and it is
     mechanical, not a promise.

  2. The producer runs. It never sees the expectation, only the opaque commit.

  3. At the gate the acceptor reveals salt + expectation. The machine:
       a. verifies the commitment opens (the expectation is the pre-committed
          one, not one retrofitted to match the artefacts)
       b. compares the producer's artefacts against that expectation
       c. DIVERGENCE DEFAULTS TO REJECT -- enforced by the machine, so it does
          not depend on the acceptor choosing to be strict

  4. The channel back to the producer carries ONE BIT plus the reveal. No
     rubric, no diff, no findings, no guidance. A verbose channel hands the
     producer the rubric and re-creates the exploit it was meant to close.
     Divergence detail is written to the ACCEPTOR's own sink, which the
     producer does not read.

WHAT COMMIT-FIRST DOES AND DOES NOT BUY -- read this before trusting it
-----------------------------------------------------------------------
It defeats ANCHORING: the acceptor cannot be swayed by artefact content it had
not yet seen when it committed.

It does NOT defeat a SHARED BLIND SPOT. If the acceptor derives its
expectation by calling the producer's own engine, the two are the same
function and will agree on the same wrong answer. Such an expectation proves
reproducibility, not correctness. `Derivation.SHARED_ENGINE` marks that case
honestly, and packs are expected to avoid it.

The strong form is `Derivation.INDEPENDENT_ORACLE`: the expectation is
computed by separately-written code that does not import the producer's
engine. That still shares a *conception* -- both were designed by the same
author against the same spec -- so even the strong form is not the
independence of two adversarial parties. It is the independence of two
implementations.
"""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, asdict, field
from typing import Any

DOMAIN = "obzio.expectation.v1"


class AnchoringError(RuntimeError):
    """The acceptor could have seen the artefacts before committing."""


class ExpectationError(RuntimeError):
    """The revealed expectation does not open its commitment."""


class DivergenceError(RuntimeError):
    """Producer artefacts diverge from the pre-committed expectation."""


class Derivation:
    """How independently was the expectation derived? Stated, not assumed."""
    INDEPENDENT_ORACLE = "INDEPENDENT_ORACLE"   # separate code, no engine import
    PARTIAL_ORACLE = "PARTIAL_ORACLE"           # covers a subset of the output
    SHARED_ENGINE = "SHARED_ENGINE"             # same code -- proves only reproducibility
    NONE = "NONE"                               # no derivable expectation exists

    ALL = (INDEPENDENT_ORACLE, PARTIAL_ORACLE, SHARED_ENGINE, NONE)
    #: Derivations that constitute a real independence claim.
    INDEPENDENT = (INDEPENDENT_ORACLE, PARTIAL_ORACLE)


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def canonical_digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Expectation:
    """What the acceptor independently expects, derived from inputs alone."""
    fields: dict
    derivation: str
    covers: tuple = ()          # which aspects of the output this constrains
    uncovered: tuple = ()       # what it deliberately does NOT constrain

    def __post_init__(self):
        if self.derivation not in Derivation.ALL:
            raise ValueError(f"unknown derivation {self.derivation!r}")

    def digest(self) -> str:
        return canonical_digest({"fields": self.fields,
                                 "derivation": self.derivation})

    def to_json(self):
        d = asdict(self)
        d["covers"] = list(self.covers)
        d["uncovered"] = list(self.uncovered)
        d["digest"] = self.digest()
        return d


@dataclass(frozen=True)
class ExpectationCommitment:
    """Producer-visible. Opaque: reveals nothing about the expectation."""
    reviewer_id: str
    commitment: str
    inputs_digest: str
    derivation: str             # disclosed so the producer knows the STRENGTH
                                # of the claim, never its content

    def to_json(self):
        return asdict(self)


@dataclass(frozen=True)
class ExpectationReveal:
    """Crosses the boundary at gate time, alongside the single verdict bit."""
    reviewer_id: str
    salt: str
    expectation: "Expectation"
    inputs_digest: str

    def to_json(self):
        return {"reviewer_id": self.reviewer_id, "salt": self.salt,
                "expectation": self.expectation.to_json(),
                "inputs_digest": self.inputs_digest}


class Acceptor:
    """Held by the acceptor. Generates the commitment before work begins."""

    def __init__(self, reviewer_id: str, expectation: "Expectation",
                 inputs_digest: str):
        self.reviewer_id = reviewer_id
        self.expectation = expectation
        self.inputs_digest = inputs_digest
        self._salt = secrets.token_hex(32)

    def commitment(self) -> "ExpectationCommitment":
        return ExpectationCommitment(
            reviewer_id=self.reviewer_id,
            commitment=_h(DOMAIN, "EXPECT", self._salt,
                          self.expectation.digest(), self.inputs_digest),
            inputs_digest=self.inputs_digest,
            derivation=self.expectation.derivation,
        )

    def reveal(self) -> "ExpectationReveal":
        return ExpectationReveal(self.reviewer_id, self._salt,
                                 self.expectation, self.inputs_digest)


def verify_expectation(reveal: "ExpectationReveal",
                       commitment: "ExpectationCommitment") -> "Expectation":
    """Return the pre-committed expectation, or raise."""
    if reveal.reviewer_id != commitment.reviewer_id:
        raise ExpectationError(
            f"expectation revealed by {reveal.reviewer_id!r} but committed by "
            f"{commitment.reviewer_id!r}")
    if reveal.inputs_digest != commitment.inputs_digest:
        raise ExpectationError(
            "expectation is bound to a different set of declared inputs")
    recomputed = _h(DOMAIN, "EXPECT", reveal.salt,
                    reveal.expectation.digest(), reveal.inputs_digest)
    if not hmac.compare_digest(recomputed, commitment.commitment):
        raise ExpectationError(
            "revealed expectation does not open the commitment: it was not the "
            "expectation held before the artefacts were produced")
    if reveal.expectation.derivation != commitment.derivation:
        raise ExpectationError(
            f"derivation changed between commit ({commitment.derivation}) and "
            f"reveal ({reveal.expectation.derivation})")
    return reveal.expectation


def compare(expectation: "Expectation", actual_fields: dict):
    """Compare committed expectation against observed reality.

    Returns (agrees: bool, divergences: list). The bool is the ONLY thing that
    may reach the producer. The divergence list goes to the acceptor's own
    sink."""
    divergences = []
    for k, want in sorted(expectation.fields.items()):
        if k not in actual_fields:
            divergences.append({"field": k, "expected": want, "actual": "<ABSENT>"})
        elif actual_fields[k] != want:
            divergences.append({"field": k, "expected": want,
                                "actual": actual_fields[k]})
    return (not divergences), divergences


@dataclass(frozen=True)
class AcceptanceReturn:
    """THE SINGLE-BIT CHANNEL.

    Everything the producer receives about the acceptance decision. One bit
    (`accept`), plus the cryptographic material needed to verify that bit was
    issued by the committed acceptor.

    There is deliberately NO note, NO rationale, NO diff, NO finding list and
    NO score. Those fields existed in an earlier version of this spine and
    were a rubric leak: a producer that learns WHY it was rejected learns what
    to change to pass without becoming correct, which is the exploit.

    Rejection detail is written to the acceptor's own sink instead. The
    producer can be told THAT it failed. It is not told WHAT to fix."""
    accept: bool
    acceptance_reveal: Any          # obzio_spine.acceptance.Reveal
    expectation_reveal: "ExpectationReveal"

    def bit(self) -> int:
        return 1 if self.accept else 0

    def to_json(self):
        """Deliberately omits the acceptance secret; this is for logging.

        Tolerates missing reveals: a logging helper that raises turns a
        diagnosable failure into an undiagnosable one."""
        r = getattr(self.expectation_reveal, "reviewer_id", None)
        return {"accept": self.accept, "bit": self.bit(), "reviewer_id": r}


def write_rejection_sink(sink_dir: str, run_label: str, divergences,
                         verdict: str) -> str:
    """Divergence detail, written where the ACCEPTOR can read it and the
    producer cannot. Kept out of the producer's run directory on purpose."""
    os.makedirs(sink_dir, exist_ok=True)
    path = os.path.join(sink_dir, f"divergence_{run_label}.json")
    payload = {"run_label": run_label, "verdict": verdict,
               "divergence_count": len(divergences), "divergences": divergences,
               "note": ("this file is the acceptor's record. It is NOT returned "
                        "to the producer: the producer receives one bit.")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return path
