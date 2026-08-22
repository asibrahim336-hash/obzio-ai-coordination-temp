"""
Obzio operator spine (shared, byte-identical across all five packs).

Provides:
  * Phase           - the mandated nine-phase lifecycle
  * Ledger          - append-only, hash-chained, on-disk (JSONL) run ledger
  * AcceptanceGate  - HMAC gate; the key lives outside the producing process
  * IndependentAcceptor - re-derives the verdict from artefacts on disk
  * Run             - the state machine; refuses to self-advance past
                      MACHINE_CHECKS_PASSED without a foreign acceptance token

HARD RULE ENFORCED HERE (not prose):
    Run.advance(target) raises SelfAcceptanceRefused when
    target >= Phase.INDEPENDENT_ACCEPTANCE and the run holds no
    verified AcceptanceToken minted by an acceptor_id != producer_id.

Stdlib only.
"""
from __future__ import annotations

import enum
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SPINE_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------
class Phase(enum.IntEnum):
    PREFLIGHT = 0
    CURRENT_STATE_RECOVERED = 1
    INPUT_ADMITTED = 2
    ACTION_EXECUTED = 3
    REQUIRED_ARTEFACTS_PRESENT = 4
    MACHINE_CHECKS_PASSED = 5
    INDEPENDENT_ACCEPTANCE = 6
    RETURN_STATE_WRITTEN = 7
    COMPLETE = 8


#: Highest phase the producing process may reach on its own authority.
PRODUCER_CEILING = Phase.MACHINE_CHECKS_PASSED


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class SpineError(Exception):
    """Base for every refusal raised by the spine."""


class PhaseOrderError(SpineError):
    pass


class SelfAcceptanceRefused(SpineError):
    pass


class AcceptanceRefused(SpineError):
    pass


class TokenInvalid(SpineError):
    pass


class PeekedBeforeCommit(SpineError):
    """The acceptor opened the producer's artefacts before committing its own
    answer. That is the ANCHORED configuration and it is refused."""


class NoPrecommitment(SpineError):
    pass


class CommitmentMismatch(SpineError):
    pass


class NoIndependentExpectation(SpineError):
    """The objective has no independently derivable expectation. Refusing to
    fabricate one - see BOUNDARIES.md, acceptance labelled BEHAVIOURAL_ONLY."""


class AcceptanceBudgetExhausted(SpineError):
    pass


class LedgerTampered(SpineError):
    pass


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def canon(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_bytes(canon(obj))


def sha256_file(p: os.PathLike | str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: os.PathLike | str, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def read_json(path: os.PathLike | str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


GENESIS = "GENESIS"


# --------------------------------------------------------------------------
# Append-only hash-chained ledger
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    seq: int
    ts: float
    kind: str
    payload: Dict[str, Any]
    prev: str
    digest: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Ledger:
    """Append-only JSONL ledger. Every entry commits to the entry before it."""

    def __init__(self, path: os.PathLike | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: List[Entry] = []
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.entries.append(Entry(**json.loads(line)))

    @staticmethod
    def _digest(seq: int, ts: float, kind: str, payload: Dict[str, Any], prev: str) -> str:
        return sha256_obj(
            {"seq": seq, "ts": ts, "kind": kind, "payload": payload, "prev": prev}
        )

    def head(self) -> str:
        return self.entries[-1].digest if self.entries else GENESIS

    def append(self, kind: str, payload: Dict[str, Any]) -> Entry:
        seq = len(self.entries)
        ts = time.time()
        prev = self.head()
        e = Entry(
            seq=seq,
            ts=ts,
            kind=kind,
            payload=payload,
            prev=prev,
            digest=self._digest(seq, ts, kind, payload, prev),
        )
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(e.to_dict(), sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.entries.append(e)
        return e

    def verify_chain(self) -> None:
        prev = GENESIS
        for i, e in enumerate(self.entries):
            if e.seq != i:
                raise LedgerTampered(f"seq gap at index {i}: {e.seq}")
            if e.prev != prev:
                raise LedgerTampered(f"broken link at seq {e.seq}")
            recomputed = self._digest(e.seq, e.ts, e.kind, e.payload, e.prev)
            if recomputed != e.digest:
                raise LedgerTampered(f"payload edited at seq {e.seq}")
            prev = e.digest

    def kinds(self) -> List[str]:
        return [e.kind for e in self.entries]


# --------------------------------------------------------------------------
# Deterministic check reporting
# --------------------------------------------------------------------------
@dataclass
class CheckReport:
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def failed(self) -> List[str]:
        return [c["name"] for c in self.checks if not c["ok"]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "n_checks": len(self.checks),
            "failed": self.failed,
            "checks": self.checks,
        }

    def digest(self) -> str:
        return sha256_obj(self.to_dict())


# --------------------------------------------------------------------------
# Acceptance
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class AcceptanceToken:
    run_id: str
    ledger_head: str
    acceptor_id: str
    verdict: str
    issued_at: float
    check_digest: str
    mac: str
    precommit_digest: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AcceptanceGate:
    """
    Holds the acceptance key. In deployment this key file is owned by the
    acceptor principal and is NOT readable by the producing process
    (see BOUNDARIES.md: enforcement is filesystem permissions, which a
    single-uid sandbox cannot demonstrate).
    """

    def __init__(self, key: bytes):
        if len(key) < 16:
            raise ValueError("acceptance key too short")
        self._key = key

    @classmethod
    def from_keyfile(cls, path: os.PathLike | str) -> "AcceptanceGate":
        with open(path, "rb") as fh:
            return cls(fh.read().strip())

    @classmethod
    def generate_keyfile(cls, path: os.PathLike | str) -> "AcceptanceGate":
        key = secrets.token_hex(32).encode()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(key)
        os.chmod(p, 0o400)
        return cls(key)

    def _mac(self, run_id: str, head: str, acceptor_id: str, verdict: str,
             issued_at: float, check_digest: str, precommit_digest: str = "") -> str:
        return hmac.new(
            self._key,
            canon({
                "run_id": run_id, "ledger_head": head, "acceptor_id": acceptor_id,
                "verdict": verdict, "issued_at": issued_at,
                "check_digest": check_digest, "precommit_digest": precommit_digest,
            }),
            hashlib.sha256,
        ).hexdigest()

    def mint(self, run_id: str, head: str, acceptor_id: str, verdict: str,
             check_digest: str, precommit_digest: str = "") -> AcceptanceToken:
        issued_at = time.time()
        return AcceptanceToken(
            run_id=run_id, ledger_head=head, acceptor_id=acceptor_id,
            verdict=verdict, issued_at=issued_at, check_digest=check_digest,
            precommit_digest=precommit_digest,
            mac=self._mac(run_id, head, acceptor_id, verdict, issued_at,
                          check_digest, precommit_digest),
        )

    def verify(self, token: AcceptanceToken, run_id: str, head: str,
               producer_id: str) -> None:
        if token.acceptor_id == producer_id:
            raise SelfAcceptanceRefused(
                f"acceptor_id {token.acceptor_id!r} == producer_id; "
                "self-acceptance is refused"
            )
        if token.run_id != run_id:
            raise TokenInvalid(f"token minted for run {token.run_id!r}, not {run_id!r}")
        if token.ledger_head != head:
            raise TokenInvalid(
                "token does not bind the current ledger head "
                f"(token={token.ledger_head[:12]}, actual={head[:12]}); "
                "pre-minted or superseded acceptance is refused"
            )
        expect = self._mac(token.run_id, token.ledger_head, token.acceptor_id,
                           token.verdict, token.issued_at, token.check_digest,
                           token.precommit_digest)
        if not hmac.compare_digest(expect, token.mac):
            raise TokenInvalid("acceptance MAC does not verify")
        if token.verdict != "PASS":
            raise AcceptanceRefused(f"acceptance verdict is {token.verdict!r}")


class AnchoredAcceptor:
    """
    THE REFUTED DESIGN. Kept so each pack can prove its token is now refused.

    It reads the candidate (the producer's workdir) and then decides. A verifier
    that reads first and judges after is anchored to what it read: it is
    evaluating "is this defensible?" instead of "what is the answer?". Being
    unforgeable does not make it unanchored.

    `Run.advance` refuses any token from this class, because no
    ACCEPTOR_PRECOMMIT precedes it in the ledger. Use CommitFirstAcceptor.
    """

    def __init__(self, acceptor_id: str, gate: AcceptanceGate,
                 verifier: Callable[[Path], CheckReport]):
        self.acceptor_id = acceptor_id
        self._gate = gate
        self._verifier = verifier

    def review(self, run: "Run") -> AcceptanceToken:
        if self.acceptor_id == run.producer_id:
            raise SelfAcceptanceRefused(
                f"acceptor {self.acceptor_id!r} is the producer; refused"
            )
        run.ledger.verify_chain()
        report = self._verifier(Path(run.workdir))
        run.ledger.append(
            "INDEPENDENT_REVIEW",
            {
                "acceptor_id": self.acceptor_id,
                "independent": True,
                "report": report.to_dict(),
                "check_digest": report.digest(),
            },
        )
        if not report.ok:
            raise AcceptanceRefused(
                f"independent re-derivation failed: {report.failed}"
            )
        return self._gate.mint(run.run_id, run.ledger.head(), self.acceptor_id,
                               "PASS", report.digest())


# --------------------------------------------------------------------------
# The state machine
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# COMMIT-FIRST ACCEPTANCE
#
# A verifier that reads the candidate and then judges it is anchored to the
# candidate: it evaluates "is this defensible?" rather than "what is the
# answer?". The correction is not to hide the candidate - obscurity is not the
# active ingredient - but to make the verifier COMMIT ITS OWN ANSWER FIRST,
# bound to the run, before any producer artefact is opened. The candidate may
# then be fully visible.
#
# Three parts, all enforced below:
#   1. precommit()  derives an expectation from the OBJECTIVE and the world.
#                   It is never handed the workdir. It hash-commits the result
#                   into the ledger before the artefact window can open.
#   2. decide()     opens the window, compares producer artefacts to the
#                   PRE-COMMITTED expectation. Divergence defaults REJECT.
#   3. the channel  returns ONE BIT plus the commitment reveal. No rubric, no
#                   diff, no failed-check list - a verbose channel leaks the
#                   rubric and lets the producer hill-climb it.
# --------------------------------------------------------------------------

#: an objective whose expectation cannot be independently derived
BASIS_NONE = "NONE"
#: expectation derived from a source the producer does not control
BASIS_INDEPENDENT_SOURCE = "INDEPENDENT_SOURCE"
#: expectation derived from data the producer itself supplied - arithmetic can
#: be checked, magnitudes cannot. Acceptance is BEHAVIOURAL_ONLY for magnitude.
BASIS_PRODUCER_SUPPLIED = "PRODUCER_SUPPLIED"


@dataclass(frozen=True)
class Objective:
    """What the run is for, declared before it starts, in terms the acceptor
    can act on WITHOUT reading anything the producer wrote."""

    objective_id: str
    kind: str
    declared: Dict[str, Any]
    derivable: bool = True
    independence_basis: str = BASIS_INDEPENDENT_SOURCE
    note: str = ""

    def digest(self) -> str:
        return sha256_obj({"objective_id": self.objective_id, "kind": self.kind,
                           "declared": self.declared,
                           "derivable": self.derivable,
                           "independence_basis": self.independence_basis})

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "digest": self.digest()}


@dataclass(frozen=True)
class Reveal:
    """Opens the commitment. sha256(canon(expected) || nonce) must equal the
    expected_digest recorded in the ledger before the window opened."""

    expected: Any
    nonce: str

    def digest(self) -> str:
        return sha256_bytes(canon(self.expected) + self.nonce.encode())

    def to_dict(self) -> Dict[str, Any]:
        return {"expected": self.expected, "nonce": self.nonce,
                "digest": self.digest()}


@dataclass(frozen=True)
class Precommitment:
    run_id: str
    acceptor_id: str
    objective_digest: str
    expected_digest: str
    ledger_head_at_commit: str
    ledger_seq: int
    committed_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceOutcome:
    """THE ACCEPTANCE CHANNEL. One bit, plus the reveal that proves the bit was
    decided against a commitment made before the artefacts were opened.

    There is deliberately no `reason`, `failed`, `report`, `diff` or `message`
    field. Diagnostics go to the acceptor's own audit file, which the producer
    is not meant to read (BEHAVIOURAL_ONLY under one uid - see BOUNDARIES)."""

    run_id: str
    accept: bool
    reveal: Reveal
    precommitment: Precommitment
    token: Optional[AcceptanceToken] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "accept": self.accept,
                "reveal": self.reveal.to_dict(),
                "precommitment": self.precommitment.to_dict(),
                "token": self.token.to_dict() if self.token else None}


class RejectedByAcceptor(AcceptanceRefused):
    """Single bit: REJECT. Carries the reveal and nothing else."""

    def __init__(self, outcome: AcceptanceOutcome):
        super().__init__("REJECT")
        self.outcome = outcome


class ArtefactWindow:
    """The only sanctioned way for an acceptor to reach producer artefacts.

    Opening it writes ACCEPTOR_WINDOW_OPENED to the ledger. The precommitment
    must already be there at a lower seq, so the ordering is evidence rather
    than convention."""

    def __init__(self, run: "Run", acceptor_id: str):
        self.run = run
        self.acceptor_id = acceptor_id
        self._open = False
        self.opened_seq: Optional[int] = None

    def open(self) -> int:
        e = self.run.ledger.append("ACCEPTOR_WINDOW_OPENED",
                                   {"acceptor_id": self.acceptor_id})
        self._open = True
        self.opened_seq = e.seq
        return e.seq

    def path(self) -> Path:
        if not self._open:
            raise PeekedBeforeCommit(
                f"acceptor {self.acceptor_id!r} tried to read producer artefacts "
                "before committing its own answer")
        return Path(self.run.workdir)


def _last_seq(ledger: Ledger, kind: str, acceptor_id: str,
              before: Optional[int] = None) -> Optional[int]:
    """Highest seq of `kind` for this acceptor, optionally below `before`.

    LAST, not first: an acceptance round that was rejected leaves its own
    precommitment and window in the ledger, and a later round must be judged
    against its OWN pair, not against the wreckage of the previous one."""
    found = None
    for e in ledger.entries:
        if e.kind != kind or e.payload.get("acceptor_id") != acceptor_id:
            continue
        if before is not None and e.seq >= before:
            continue
        found = e.seq
    return found


def precommit_seq(ledger: Ledger, acceptor_id: str,
                  before: Optional[int] = None) -> Optional[int]:
    return _last_seq(ledger, "ACCEPTOR_PRECOMMIT", acceptor_id, before)


def window_seq(ledger: Ledger, acceptor_id: str,
               before: Optional[int] = None) -> Optional[int]:
    return _last_seq(ledger, "ACCEPTOR_WINDOW_OPENED", acceptor_id, before)


def decision_seq(ledger: Ledger, acceptor_id: str) -> int:
    """Seq of this acceptor's most recent decision, or -1."""
    s = _last_seq(ledger, "ACCEPTANCE_DECISION", acceptor_id)
    return -1 if s is None else s


class CommitFirstAcceptor:
    """
    `derive(objective) -> expected`   MUST NOT touch the producer's workdir.
                                      It is not given the path.
    `compare(expected, workdir) -> bool`  one bit, nothing else.
    """

    MAX_ATTEMPTS = 2

    def __init__(self, acceptor_id: str, gate: AcceptanceGate,
                 derive: Callable[[Objective], Any],
                 compare: Callable[[Any, Path], bool],
                 audit_path: Optional[os.PathLike | str] = None,
                 max_attempts: int = MAX_ATTEMPTS):
        self.acceptor_id = acceptor_id
        self._gate = gate
        self._derive = derive
        self._compare = compare
        self._audit_path = Path(audit_path) if audit_path else None
        self.max_attempts = int(max_attempts)
        self._reveal: Optional[Reveal] = None
        self._pre: Optional[Precommitment] = None

    # -- private diagnostics; never returned through the channel ----------
    def _audit(self, row: Dict[str, Any]) -> None:
        if self._audit_path is None:
            return
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **row},
                                sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- phase 1 ----------------------------------------------------------
    def precommit(self, run: "Run", objective: Objective) -> Precommitment:
        if self.acceptor_id == run.producer_id:
            raise SelfAcceptanceRefused(
                f"acceptor {self.acceptor_id!r} is the producer; refused")
        if not objective.derivable or objective.independence_basis == BASIS_NONE:
            raise NoIndependentExpectation(
                f"objective {objective.objective_id!r} declares no independently "
                f"derivable expectation ({objective.note or 'no basis given'}). "
                "Refusing to fabricate a commitment; route to attested "
                "acceptance and label it BEHAVIOURAL_ONLY.")

        # No window may have been opened in THIS round, i.e. since this
        # acceptor's last decision. Windows belonging to earlier, already
        # decided rounds are history, not a peek.
        last_decision = decision_seq(run.ledger, self.acceptor_id)
        win = window_seq(run.ledger, self.acceptor_id)
        if win is not None and win > last_decision:
            raise PeekedBeforeCommit(
                f"acceptor {self.acceptor_id!r} opened the artefact window at "
                f"seq {win} in this round; a commitment made after reading the "
                "candidate is anchored to it and is refused")

        attempts = sum(1 for e in run.ledger.entries
                       if e.kind == "ACCEPTANCE_DECISION"
                       and e.payload.get("acceptor_id") == self.acceptor_id)
        if attempts >= self.max_attempts:
            raise AcceptanceBudgetExhausted(
                f"{attempts} acceptance decision(s) already made on run "
                f"{run.run_id}; budget is {self.max_attempts}. Conservative "
                "update on reject: a rejected run is not re-graded indefinitely.")

        expected = self._derive(objective)          # NO workdir, by signature
        nonce = secrets.token_hex(16)
        reveal = Reveal(expected=expected, nonce=nonce)
        e = run.ledger.append("ACCEPTOR_PRECOMMIT", {
            "acceptor_id": self.acceptor_id,
            "objective_digest": objective.digest(),
            "expected_digest": reveal.digest(),
            "independence_basis": objective.independence_basis,
            "attempt": attempts + 1,
        })
        self._reveal = reveal
        self._pre = Precommitment(
            run_id=run.run_id, acceptor_id=self.acceptor_id,
            objective_digest=objective.digest(), expected_digest=reveal.digest(),
            ledger_head_at_commit=run.ledger.head(), ledger_seq=e.seq,
            committed_at=time.time())
        self._audit({"kind": "PRECOMMIT", "run_id": run.run_id,
                     "acceptor_id": self.acceptor_id,
                     "expected_digest": reveal.digest()})
        return self._pre

    # -- phase 2 ----------------------------------------------------------
    def decide(self, run: "Run") -> AcceptanceOutcome:
        if self._pre is None or self._reveal is None:
            raise NoPrecommitment("decide() called before precommit()")
        if self._pre.run_id != run.run_id:
            raise CommitmentMismatch("precommitment belongs to another run")

        run.ledger.verify_chain()
        window = ArtefactWindow(run, self.acceptor_id)
        window.open()                                   # ledger records the order
        agree = bool(self._compare(self._reveal.expected, window.path()))

        run.ledger.append("ACCEPTANCE_DECISION", {
            "acceptor_id": self.acceptor_id,
            "accept": agree,
            "expected_digest": self._pre.expected_digest,
            "reveal": self._reveal.to_dict(),
            "precommit_seq": self._pre.ledger_seq,
            "window_seq": window.opened_seq,
        })
        self._audit({"kind": "DECISION", "run_id": run.run_id, "accept": agree,
                     "expected": self._reveal.expected})

        if not agree:
            out = AcceptanceOutcome(run_id=run.run_id, accept=False,
                                    reveal=self._reveal, precommitment=self._pre)
            raise RejectedByAcceptor(out)

        token = self._gate.mint(run.run_id, run.ledger.head(), self.acceptor_id,
                                "PASS", self._pre.expected_digest,
                                precommit_digest=self._pre.expected_digest)
        return AcceptanceOutcome(run_id=run.run_id, accept=True,
                                 reveal=self._reveal, precommitment=self._pre,
                                 token=token)


class AttestedAcceptance:
    """For objectives with no independently derivable expectation.

    Produces no machine guarantee. It stamps `machine_enforced: false` into the
    ledger and the return state so the artefact says out loud that this run was
    accepted on a human's word."""

    def __init__(self, attestor_id: str, gate: AcceptanceGate):
        self.acceptor_id = attestor_id
        self._gate = gate

    def attest(self, run: "Run", objective: Objective,
               statement: str) -> AcceptanceOutcome:
        if self.acceptor_id == run.producer_id:
            raise SelfAcceptanceRefused("attestor is the producer; refused")
        nonce = secrets.token_hex(16)
        reveal = Reveal(expected={"attested": True, "statement": statement,
                                  "machine_enforced": False}, nonce=nonce)
        e = run.ledger.append("ACCEPTOR_PRECOMMIT", {
            "acceptor_id": self.acceptor_id,
            "objective_digest": objective.digest(),
            "expected_digest": reveal.digest(),
            "independence_basis": BASIS_NONE,
            "machine_enforced": False,
            "attestation": statement,
        })
        pre = Precommitment(run_id=run.run_id, acceptor_id=self.acceptor_id,
                            objective_digest=objective.digest(),
                            expected_digest=reveal.digest(),
                            ledger_head_at_commit=run.ledger.head(),
                            ledger_seq=e.seq, committed_at=time.time())
        ArtefactWindow(run, self.acceptor_id).open()
        run.ledger.append("ACCEPTANCE_DECISION", {
            "acceptor_id": self.acceptor_id, "accept": True,
            "expected_digest": reveal.digest(), "reveal": reveal.to_dict(),
            "precommit_seq": pre.ledger_seq, "machine_enforced": False,
        })
        token = self._gate.mint(run.run_id, run.ledger.head(), self.acceptor_id,
                                "PASS", reveal.digest(),
                                precommit_digest=reveal.digest())
        return AcceptanceOutcome(run_id=run.run_id, accept=True, reveal=reveal,
                                 precommitment=pre, token=token)


class Run:
    """
    Strict, single-step lifecycle. Enforcement summary:

      * advance() must target exactly phase+1 (no skipping, no rewind)
      * target >= INDEPENDENT_ACCEPTANCE without a verified foreign token
        raises SelfAcceptanceRefused
      * the token must bind the ledger head at verification time, so a token
        minted before the checks ran (or before later ledger writes) is refused
    """

    def __init__(self, pack: str, workdir: os.PathLike | str, producer_id: str,
                 gate: AcceptanceGate, run_id: Optional[str] = None,
                 mandate: Optional[Dict[str, Any]] = None):
        self.pack = pack
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.producer_id = producer_id
        self.run_id = run_id or uuid.uuid4().hex
        self.mandate = dict(mandate or {})
        self._gate = gate
        self.phase: Optional[Phase] = None
        self._acceptance: Optional[AcceptanceToken] = None
        self.ledger = Ledger(self.workdir / "run_ledger.jsonl")

    # -- introspection ----------------------------------------------------
    @property
    def accepted(self) -> bool:
        return self._acceptance is not None

    def next_phase(self) -> Phase:
        return Phase.PREFLIGHT if self.phase is None else Phase(int(self.phase) + 1)

    def require_phase(self, p: Phase) -> None:
        if self.phase != p:
            raise PhaseOrderError(f"require {p.name}, at {self.phase and self.phase.name}")

    # -- the gate ---------------------------------------------------------
    def advance(self, target: Phase, evidence: Optional[Dict[str, Any]] = None,
                token: Optional[AcceptanceToken] = None) -> Phase:
        evidence = dict(evidence or {})
        expected = self.next_phase()
        if target != expected:
            raise PhaseOrderError(
                f"out-of-order advance: at "
                f"{self.phase.name if self.phase is not None else 'START'}, "
                f"next must be {expected.name}, got {target.name}"
            )
        if target >= Phase.INDEPENDENT_ACCEPTANCE and self._acceptance is None:
            if token is None:
                raise SelfAcceptanceRefused(
                    f"{self.pack}: producer {self.producer_id!r} may not advance "
                    f"to {target.name}; producer ceiling is "
                    f"{PRODUCER_CEILING.name} and no acceptance token was presented"
                )
            self._gate.verify(token, self.run_id, self.ledger.head(), self.producer_id)
            self._verify_commit_first(token)
            self._acceptance = token
            evidence = {
                **evidence,
                "acceptance": token.to_dict(),
                "acceptor_id": token.acceptor_id,
            }

        if target > Phase.INDEPENDENT_ACCEPTANCE and self._acceptance is None:
            raise SelfAcceptanceRefused(
                f"{self.pack}: {target.name} requires a prior INDEPENDENT_ACCEPTANCE"
            )

        self.ledger.append(
            "PHASE",
            {
                "phase": target.name,
                "phase_ord": int(target),
                "run_id": self.run_id,
                "producer_id": self.producer_id,
                "pack": self.pack,
                "evidence": evidence,
            },
        )
        self.phase = target
        return target

    def _verify_commit_first(self, token: AcceptanceToken) -> None:
        """The fifth arm of the gate. Forgery, self-issuance, replay and
        head-staleness are all checked by AcceptanceGate.verify; this checks
        that the acceptor was not ANCHORED - that it committed its own answer
        into the ledger before it opened the producer's artefacts."""
        aid = token.acceptor_id
        decisions = [e for e in self.ledger.entries
                     if e.kind == "ACCEPTANCE_DECISION"
                     and e.payload.get("acceptor_id") == aid]
        if not decisions:
            raise NoPrecommitment(
                f"acceptor {aid!r} presented a token with no recorded decision. "
                "A verifier that read the candidate and then judged it is "
                "anchored to it; that design is refused.")
        last = decisions[-1]
        if not last.payload.get("accept"):
            raise AcceptanceRefused("last recorded decision was REJECT")

        # the round that produced this decision
        pre_seq = precommit_seq(self.ledger, aid, before=last.seq)
        if pre_seq is None:
            raise NoPrecommitment(
                f"acceptor {aid!r} presented a token with no ACCEPTOR_PRECOMMIT "
                "in the ledger. A verifier that read the candidate and then "
                "judged it is anchored to it; that design is refused.")
        win_seq = window_seq(self.ledger, aid, before=last.seq)
        if win_seq is None or win_seq < pre_seq:
            raise PeekedBeforeCommit(
                f"acceptor {aid!r}: artefact window at seq {win_seq} does not "
                f"follow the commitment at seq {pre_seq}")

        pre_entry = next(e for e in self.ledger.entries if e.seq == pre_seq)
        committed = pre_entry.payload.get("expected_digest")
        if token.precommit_digest != committed:
            raise CommitmentMismatch(
                f"token binds {token.precommit_digest[:12]}, ledger committed "
                f"{str(committed)[:12]}")
        rev = last.payload.get("reveal") or {}
        opened = Reveal(expected=rev.get("expected"), nonce=rev.get("nonce", ""))
        if opened.digest() != committed:
            raise CommitmentMismatch(
                "the revealed expectation does not open the commitment made "
                "before the artefacts were read")
        # conservative update on reject: the winning commitment must postdate
        # every earlier rejection, so a rejected run is re-derived, not re-argued
        for d in decisions[:-1]:
            if not d.payload.get("accept") and d.seq > pre_seq:
                raise CommitmentMismatch(
                    f"precommitment at seq {pre_seq} predates a REJECT at seq "
                    f"{d.seq}; a rejected run needs a fresh commitment")

    def accept_with(self, outcome: AcceptanceOutcome) -> Phase:
        """Advance to INDEPENDENT_ACCEPTANCE on a commit-first outcome."""
        if not outcome.accept or outcome.token is None:
            raise AcceptanceRefused("REJECT")
        return self.advance(Phase.INDEPENDENT_ACCEPTANCE, token=outcome.token)

    def note(self, kind: str, payload: Dict[str, Any]) -> Entry:
        return self.ledger.append(kind, payload)

    def write_return_state(self, extra: Optional[Dict[str, Any]] = None) -> Path:
        if self._acceptance is None:
            raise SelfAcceptanceRefused("return state may not be written unaccepted")
        path = self.workdir / "return_state.json"
        write_json(path, {
            "pack": self.pack,
            "run_id": self.run_id,
            "producer_id": self.producer_id,
            "acceptor_id": self._acceptance.acceptor_id,
            "acceptance": self._acceptance.to_dict(),
            "ledger_head": self.ledger.head(),
            "ledger_entries": len(self.ledger.entries),
            "spine_version": SPINE_VERSION,
            "mandate": self.mandate,
            "acceptance_model": "COMMIT_FIRST",
            "precommit_digest": self._acceptance.precommit_digest,
            "independence_basis": self._independence_basis(),
            "acceptance_machine_enforced": self._acceptance_machine_enforced(),
            **(extra or {}),
        })
        return path


    def _precommit_entry(self):
        aid = self._acceptance.acceptor_id if self._acceptance else None
        for e in self.ledger.entries:
            if e.kind == "ACCEPTOR_PRECOMMIT" and e.payload.get("acceptor_id") == aid:
                return e
        return None

    def _independence_basis(self) -> str:
        e = self._precommit_entry()
        return (e.payload.get("independence_basis", BASIS_NONE) if e else BASIS_NONE)

    def _acceptance_machine_enforced(self) -> bool:
        e = self._precommit_entry()
        if e is None:
            return False
        return e.payload.get("machine_enforced", True) is not False


def phase_sequence_from_ledger(ledger: Ledger) -> List[str]:
    return [e.payload["phase"] for e in ledger.entries if e.kind == "PHASE"]


def validate_phase_sequence(seq: List[str]) -> Optional[str]:
    """Return None if the observed phase sequence is legal, else the reason."""
    if not seq:
        return "no phases recorded"
    names = [p.name for p in Phase]
    if seq != names[: len(seq)]:
        return f"illegal phase sequence: {seq}"
    return None


# --------------------------------------------------------------------------
# Reusable deterministic checks (spine-level invariants)
# --------------------------------------------------------------------------
def load_jsonl(path: os.PathLike | str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def check_required_files(rep: CheckReport, workdir: Path,
                         required: List[str]) -> None:
    missing = [f for f in required
               if not (workdir / f).exists() or (workdir / f).stat().st_size == 0]
    rep.add("required_artefacts_present", not missing,
            f"missing/empty: {missing}" if missing else f"{len(required)} present")


def check_run_ledger(rep: CheckReport, workdir: Path) -> Optional[Ledger]:
    p = workdir / "run_ledger.jsonl"
    if not p.exists():
        rep.add("run_ledger_present", False, "run_ledger.jsonl absent")
        return None
    rep.add("run_ledger_present", True, "")
    led = Ledger(p)
    try:
        led.verify_chain()
        rep.add("run_ledger_chain_intact", True, f"{len(led.entries)} entries")
    except LedgerTampered as e:
        rep.add("run_ledger_chain_intact", False, str(e))
        return led

    seq = phase_sequence_from_ledger(led)
    reason = validate_phase_sequence(seq)
    rep.add("phase_sequence_legal", reason is None, reason or " -> ".join(seq))
    return led


def check_acceptance_provenance(rep: CheckReport, led: Optional[Ledger]) -> None:
    """No phase at or beyond INDEPENDENT_ACCEPTANCE may exist in the ledger
    without an acceptance recorded by a principal other than the producer."""
    if led is None:
        rep.add("acceptance_provenance", False, "no ledger")
        return
    problems: List[str] = []
    accepted_by: Optional[str] = None
    for e in led.entries:
        if e.kind != "PHASE":
            continue
        ph = e.payload.get("phase_ord", -1)
        producer = e.payload.get("producer_id")
        ev = e.payload.get("evidence") or {}
        if ph == int(Phase.INDEPENDENT_ACCEPTANCE):
            acc = ev.get("acceptance")
            if not acc:
                problems.append(f"seq {e.seq}: INDEPENDENT_ACCEPTANCE with no token")
            elif acc.get("acceptor_id") == producer:
                problems.append(f"seq {e.seq}: self-accepted by {producer!r}")
            elif acc.get("verdict") != "PASS":
                problems.append(f"seq {e.seq}: verdict {acc.get('verdict')!r}")
            else:
                accepted_by = acc.get("acceptor_id")
        elif ph > int(Phase.INDEPENDENT_ACCEPTANCE) and accepted_by is None:
            problems.append(f"seq {e.seq}: {e.payload.get('phase')} before acceptance")
    rep.add("acceptance_provenance", not problems,
            "; ".join(problems) if problems
            else f"independently accepted by {accepted_by!r}")


def check_independent_review_recorded(rep: CheckReport,
                                      led: Optional[Ledger]) -> None:
    """Implication: if the run reached INDEPENDENT_ACCEPTANCE, a review entry
    must exist. Stated this way on purpose - the acceptor itself runs the
    checks BEFORE writing its review entry, so an unconditional form would be
    unsatisfiable at the only moment that matters."""
    if led is None:
        rep.add("independent_review_recorded", False, "no ledger")
        return
    revs = [e for e in led.entries if e.kind == "INDEPENDENT_REVIEW"]
    accepted = any(e.kind == "PHASE"
                   and e.payload.get("phase_ord", -1) >= int(Phase.INDEPENDENT_ACCEPTANCE)
                   for e in led.entries)
    if not accepted:
        rep.add("independent_review_recorded", True,
                f"n/a: pre-acceptance ({len(revs)} review entries so far)")
        return
    ok = bool(revs) and all(r.payload.get("independent") for r in revs)
    rep.add("independent_review_recorded", ok,
            f"{len(revs)} review entr(y|ies)" if ok else "accepted with no review entry")


def check_pack_manifest(rep: CheckReport, pack_dir: Path) -> None:
    """Verify the control code itself has not been edited since manifesting."""
    man = pack_dir / "MANIFEST.json"
    if not man.exists():
        rep.add("pack_manifest_intact", False, "MANIFEST.json absent")
        return
    try:
        data = read_json(man)
    except Exception as e:  # noqa: BLE001
        rep.add("pack_manifest_intact", False, f"unparseable: {e}")
        return
    bad: List[str] = []
    for entry in data.get("files", []):
        f = pack_dir / entry["path"]
        if not f.exists():
            bad.append(f"{entry['path']}: absent")
            continue
        if f.stat().st_size != entry["bytes"]:
            bad.append(f"{entry['path']}: size {f.stat().st_size} != {entry['bytes']}")
        elif sha256_file(f) != entry["sha256"]:
            bad.append(f"{entry['path']}: sha256 mismatch")
    rep.add("pack_manifest_intact", not bad,
            "; ".join(bad) if bad else f"{len(data.get('files', []))} files verified")


def check_commit_first_ordering(rep: CheckReport, led: Optional[Ledger]) -> None:
    """Acceptance implies: a precommitment exists, it precedes the artefact
    window, and the revealed expectation opens it."""
    if led is None:
        rep.add("commit_first_ordering", False, "no ledger")
        return
    accepted = [e for e in led.entries if e.kind == "PHASE"
                and e.payload.get("phase_ord", -1) >= int(Phase.INDEPENDENT_ACCEPTANCE)]
    if not accepted:
        rep.add("commit_first_ordering", True, "n/a: pre-acceptance")
        rep.add("acceptance_channel_is_one_bit", True, "n/a: pre-acceptance")
        return

    problems: List[str] = []
    basis = None
    for e in led.entries:
        if e.kind != "ACCEPTANCE_DECISION":
            continue
        aid = e.payload.get("acceptor_id")
        pre = precommit_seq(led, aid, before=e.seq)
        win = window_seq(led, aid, before=e.seq)
        if pre is None:
            problems.append(f"{aid}: decision with no precommitment")
            continue
        if win is None:
            problems.append(f"{aid}: decision with no window record")
        elif win < pre:
            problems.append(f"{aid}: window opened at {win} before commit at {pre}")
        rev = e.payload.get("reveal") or {}
        opened = Reveal(expected=rev.get("expected"), nonce=rev.get("nonce", ""))
        if opened.digest() != e.payload.get("expected_digest"):
            problems.append(f"{aid}: reveal does not open the commitment")
    for e in led.entries:
        if e.kind == "ACCEPTOR_PRECOMMIT":
            basis = e.payload.get("independence_basis", BASIS_NONE)
    rep.add("commit_first_ordering", not problems,
            "; ".join(problems) if problems
            else f"commitment precedes window; reveal opens it; basis={basis}")

    # the channel carried one bit: the decision entry has an accept flag and a
    # reveal, and nothing that could function as a rubric
    leaky = []
    banned = {"failed", "report", "checks", "diff", "reason", "guidance",
              "message", "rubric"}
    for e in led.entries:
        if e.kind == "ACCEPTANCE_DECISION":
            hit = banned & set(e.payload)
            if hit:
                leaky.append(f"{e.payload.get('acceptor_id')}: {sorted(hit)}")
    rep.add("acceptance_channel_is_one_bit", not leaky,
            "; ".join(leaky) if leaky
            else "decision entries carry accept + reveal only")
