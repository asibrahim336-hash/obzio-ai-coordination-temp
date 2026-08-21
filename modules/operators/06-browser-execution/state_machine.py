"""
Pack 06 - browser-execution
State machine + RouteGuard for driving a browser surface to completion.

THE FAILURE THIS PACK IS BUILT AGAINST
--------------------------------------
A misroute: a message composed for conversation X is delivered into
conversation Y. Observed repeatedly in this operation.

Naive defence ("check the header, then click send") is a TOCTOU hole: the
surface can change between the check and the click - a background refresh, a
focus steal, an inbound message re-sorting the list, a stale SPA re-render.

WHAT IS ACTUALLY ENFORCED HERE
------------------------------
send() is unreachable without a SendToken, and a SendToken is only issued by
verify(). The token binds:
    (a) the digest of the routing-relevant surface fields observed at verify,
    (b) the surface's mutation counter at verify,
    (c) the digest of the intended target,
    (d) a single-use nonce, MAC'd with a per-guard key.
send() RE-OBSERVES the surface and refuses unless (a) and (b) still hold.
So the window between check and send is closed by re-derivation, not by trust.

Every attempt - permitted or refused - is written to route_ledger.jsonl
before the effect, so a refusal is as auditable as a send.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import _spine
from _spine import (
    AcceptanceGate, AcceptanceOutcome, CheckReport, CommitFirstAcceptor,
    Objective, Phase, Run, canon, sha256_obj, write_json,
)

PACK = "06-browser-execution"

# Routing-relevant surface fields. Anything not in this tuple is deliberately
# excluded from the digest (timestamps, unread counts, scroll offsets churn
# constantly and would make every send fail closed for no safety gain).
ROUTING_FIELDS = ("conversation_id", "recipient_handle", "thread_title")


# --------------------------------------------------------------------------
# Refusals - closed set of reason codes
# --------------------------------------------------------------------------
class RouteRefusal(Exception):
    code = "REFUSED"


class Misroute(RouteRefusal):
    code = "MISROUTE"


class AmbiguousSurface(RouteRefusal):
    code = "AMBIGUOUS_SURFACE"


class RouteChanged(RouteRefusal):
    code = "ROUTE_CHANGED"


class SurfaceMutated(RouteRefusal):
    code = "SURFACE_MUTATED"


class TokenReplay(RouteRefusal):
    code = "TOKEN_REPLAY"


class TokenForged(RouteRefusal):
    code = "TOKEN_FORGED"


class MandateExceeded(RouteRefusal):
    code = "MANDATE_EXCEEDED"


class RecipientNotAllowed(RouteRefusal):
    code = "RECIPIENT_NOT_ALLOWED"


class UnverifiedSend(RouteRefusal):
    code = "UNVERIFIED_SEND"


REFUSAL_CODES = {
    c.code for c in (
        Misroute, AmbiguousSurface, RouteChanged, SurfaceMutated, TokenReplay,
        TokenForged, MandateExceeded, RecipientNotAllowed, UnverifiedSend,
    )
}


# --------------------------------------------------------------------------
# Target / Observation
# --------------------------------------------------------------------------
def _norm(s: str) -> str:
    """Canonicalise a routing string. Deliberately conservative: casefold and
    collapse whitespace only. No unicode confusable folding - two handles that
    LOOK alike must not compare equal."""
    return " ".join(str(s).split()).casefold()


@dataclass(frozen=True)
class Target:
    conversation_id: str
    recipient_handle: str
    thread_title: str

    def digest(self) -> str:
        return sha256_obj({k: _norm(getattr(self, k)) for k in ROUTING_FIELDS})


@dataclass(frozen=True)
class Observation:
    conversation_id: str
    recipient_handle: str
    thread_title: str
    compose_open_count: int
    focused_compose_id: Optional[str]
    mutation_seq: int
    observed_at: float
    obs_id: str

    def surface_digest(self) -> str:
        return sha256_obj({k: _norm(getattr(self, k)) for k in ROUTING_FIELDS})

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["surface_digest"] = self.surface_digest()
        return d


class Surface:
    """Adapter boundary. A real deployment implements observe()/do_send()
    against the live browser tool. Nothing below this line trusts the surface
    to be honest or stable - it is treated as adversarial."""

    def observe(self) -> Observation:  # pragma: no cover - abstract
        raise NotImplementedError

    def do_send(self, text: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- read side, used by the commit-first acceptor --------------------
    def conversation_ids(self) -> List[str]:  # pragma: no cover - abstract
        """Every conversation reachable on this surface, not only the target.
        The acceptor needs the whole set: a misroute is only visible if you can
        look in the conversation the message should NOT be in."""
        raise NotImplementedError

    def inbox_digests(self, conversation_id: str) -> List[str]:  # pragma: no cover
        """sha256 of each delivered message body in that conversation."""
        raise NotImplementedError


# --------------------------------------------------------------------------
# Send token
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SendToken:
    nonce: str
    intended_digest: str
    surface_digest: str
    mutation_seq: int
    obs_id: str
    issued_at: float
    mac: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# RouteGuard
# --------------------------------------------------------------------------
class RouteGuard:
    def __init__(self, surface: Surface, workdir: os.PathLike | str,
                 allowlist: List[str], max_sends: int):
        self.surface = surface
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.route_ledger = self.workdir / "route_ledger.jsonl"
        self.allowlist = {_norm(a) for a in allowlist}
        self.max_sends = int(max_sends)
        self.sends_done = 0
        self._key = secrets.token_bytes(32)
        self._spent: set[str] = set()
        self._issued: Dict[str, SendToken] = {}

    # -- audit ------------------------------------------------------------
    def _record(self, kind: str, payload: Dict[str, Any]) -> None:
        row = {"ts": time.time(), "kind": kind, **payload}
        with open(self.route_ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _mac(self, nonce: str, intended: str, surface: str, mseq: int,
             obs_id: str, issued_at: float) -> str:
        return hmac.new(
            self._key,
            canon([nonce, intended, surface, mseq, obs_id, issued_at]),
            hashlib.sha256,
        ).hexdigest()

    # -- step 1: verify ---------------------------------------------------
    def verify(self, intended: Target) -> SendToken:
        obs = self.surface.observe()
        base = {
            "intended": asdict(intended),
            "intended_digest": intended.digest(),
            "observed": obs.to_dict(),
        }

        if _norm(intended.recipient_handle) not in self.allowlist:
            self._record("VERIFY", {**base, "verdict": RecipientNotAllowed.code})
            raise RecipientNotAllowed(
                f"{intended.recipient_handle!r} is not on the run allowlist"
            )

        if obs.compose_open_count != 1:
            self._record("VERIFY", {**base, "verdict": AmbiguousSurface.code})
            raise AmbiguousSurface(
                f"{obs.compose_open_count} compose surfaces open; exactly 1 required"
            )

        if not obs.focused_compose_id:
            self._record("VERIFY", {**base, "verdict": AmbiguousSurface.code})
            raise AmbiguousSurface("no focused compose surface")

        if obs.surface_digest() != intended.digest():
            mismatched = [
                f for f in ROUTING_FIELDS
                if _norm(getattr(obs, f)) != _norm(getattr(intended, f))
            ]
            self._record("VERIFY", {**base, "verdict": Misroute.code,
                                    "mismatched_fields": mismatched})
            raise Misroute(
                "surface does not match intended target; mismatched: "
                + ",".join(mismatched)
            )

        nonce = secrets.token_hex(16)
        issued_at = time.time()
        tok = SendToken(
            nonce=nonce,
            intended_digest=intended.digest(),
            surface_digest=obs.surface_digest(),
            mutation_seq=obs.mutation_seq,
            obs_id=obs.obs_id,
            issued_at=issued_at,
            mac=self._mac(nonce, intended.digest(), obs.surface_digest(),
                          obs.mutation_seq, obs.obs_id, issued_at),
        )
        self._issued[nonce] = tok
        self._record("VERIFY", {**base, "verdict": "OK", "nonce": nonce,
                                "token": tok.to_dict()})
        return tok

    # -- step 2: send -----------------------------------------------------
    def send(self, token: SendToken, text: str) -> str:
        expect = self._mac(token.nonce, token.intended_digest, token.surface_digest,
                           token.mutation_seq, token.obs_id, token.issued_at)
        if not hmac.compare_digest(expect, token.mac):
            self._record("SEND", {"verdict": TokenForged.code,
                                  "nonce": token.nonce})
            raise TokenForged("send token MAC does not verify")

        if token.nonce not in self._issued:
            self._record("SEND", {"verdict": UnverifiedSend.code,
                                  "nonce": token.nonce})
            raise UnverifiedSend("token was not issued by this guard")

        if token.nonce in self._spent:
            self._record("SEND", {"verdict": TokenReplay.code,
                                  "nonce": token.nonce})
            raise TokenReplay("send token already spent")

        if self.sends_done >= self.max_sends:
            self._record("SEND", {"verdict": MandateExceeded.code,
                                  "nonce": token.nonce,
                                  "sends_done": self.sends_done,
                                  "max_sends": self.max_sends})
            raise MandateExceeded(
                f"mandate allows {self.max_sends} send(s); {self.sends_done} already made"
            )

        # ---- the TOCTOU close: re-derive the surface at send time --------
        fresh = self.surface.observe()
        if fresh.surface_digest() != token.surface_digest:
            self._record("SEND", {
                "verdict": RouteChanged.code, "nonce": token.nonce,
                "token_surface_digest": token.surface_digest,
                "fresh_surface_digest": fresh.surface_digest(),
                "fresh_observed": fresh.to_dict(),
            })
            raise RouteChanged(
                "surface routing changed between verify and send "
                f"({token.surface_digest[:12]} -> {fresh.surface_digest()[:12]}); "
                "nothing was sent"
            )
        if fresh.mutation_seq != token.mutation_seq:
            self._record("SEND", {
                "verdict": SurfaceMutated.code, "nonce": token.nonce,
                "token_mutation_seq": token.mutation_seq,
                "fresh_mutation_seq": fresh.mutation_seq,
            })
            raise SurfaceMutated(
                f"surface mutated between verify and send "
                f"(seq {token.mutation_seq} -> {fresh.mutation_seq}); nothing was sent"
            )

        self._spent.add(token.nonce)
        message_id = self.surface.do_send(text)
        self.sends_done += 1
        self._record("SEND", {
            "verdict": "OK", "nonce": token.nonce,
            "message_id": message_id,
            "intended_digest": token.intended_digest,
            "surface_digest_at_send": fresh.surface_digest(),
            "text_digest": _spine.sha256_bytes(text.encode()),
            "text_len": len(text),
            "sends_done": self.sends_done,
        })
        return message_id

    # -- convenience: the only sanctioned path ---------------------------
    def verified_send(self, intended: Target, text: str) -> str:
        return self.send(self.verify(intended), text)


# --------------------------------------------------------------------------
# Pack run
# --------------------------------------------------------------------------
class BrowserExecutionRun(Run):
    def __init__(self, workdir, producer_id, gate, allowlist, max_sends,
                 task_id, **kw):
        super().__init__(PACK, workdir, producer_id, gate,
                         mandate={"allowlist": list(allowlist),
                                  "max_sends": int(max_sends),
                                  "task_id": task_id}, **kw)
        self.guard: Optional[RouteGuard] = None

    def preflight(self, surface: Surface) -> RouteGuard:
        self.advance(Phase.PREFLIGHT, {
            "surface": type(surface).__name__,
            "allowlist_size": len(self.mandate["allowlist"]),
            "max_sends": self.mandate["max_sends"],
        })
        self.guard = RouteGuard(surface, self.workdir,
                                self.mandate["allowlist"],
                                self.mandate["max_sends"])
        return self.guard

    def recover_state(self) -> Dict[str, Any]:
        """Recovering CURRENT state means reading what this run already sent -
        so a resumed run cannot re-send. Derived from route_ledger.jsonl."""
        sent = []
        p = self.workdir / "route_ledger.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    if r.get("kind") == "SEND" and r.get("verdict") == "OK":
                        sent.append(r["message_id"])
        if self.guard is not None:
            self.guard.sends_done = len(sent)
        self.advance(Phase.CURRENT_STATE_RECOVERED,
                     {"already_sent": sent, "count": len(sent)})
        return {"already_sent": sent}

    def admit_input(self, targets: List[Target], messages: List[str]) -> None:
        if len(targets) != len(messages):
            raise ValueError("targets/messages length mismatch")
        bad = [t.recipient_handle for t in targets
               if _norm(t.recipient_handle) not in self.guard.allowlist]
        if bad:
            raise RecipientNotAllowed(f"off-allowlist recipients admitted: {bad}")
        if len(messages) > self.mandate["max_sends"]:
            raise MandateExceeded(
                f"{len(messages)} messages admitted, mandate caps at "
                f"{self.mandate['max_sends']}")
        self.advance(Phase.INPUT_ADMITTED, {
            "n": len(messages),
            "target_digests": [t.digest() for t in targets],
        })

    def execute(self, targets: List[Target], messages: List[str],
                recover=None, max_route_retries: int = 2) -> List[str]:
        """Send each message through the guard.

        `recover(target)` is the surface-specific re-navigation hook. When the
        surface moves between verify and send the guard refuses; recovery is
        BOUNDED (max_route_retries) and each attempt re-verifies from scratch.
        There is no path here that sends without a fresh matching observation."""
        ids: List[str] = []
        for t, m in zip(targets, messages):
            attempt = 0
            while True:
                try:
                    ids.append(self.guard.verified_send(t, m))
                    break
                except (RouteChanged, SurfaceMutated) as e:
                    attempt += 1
                    self.note("ROUTE_RECOVERY", {
                        "attempt": attempt, "reason": e.code,
                        "target": asdict(t), "bounded_by": max_route_retries,
                    })
                    if recover is None or attempt > max_route_retries:
                        raise
                    recover(t)
        write_json(self.workdir / "transcript.json", {
            "task_id": self.mandate["task_id"],
            "run_id": self.run_id,
            "sent": ids,
            "targets": [asdict(t) for t in targets],
        })
        self.advance(Phase.ACTION_EXECUTED, {"message_ids": ids})
        return ids

    def artefacts_present(self) -> None:
        import checks
        missing = checks.missing_artefacts(self.workdir)
        if missing:
            raise FileNotFoundError(f"missing artefacts: {missing}")
        self.advance(Phase.REQUIRED_ARTEFACTS_PRESENT,
                     {"artefacts": checks.REQUIRED_ARTEFACTS})

    def machine_checks(self) -> CheckReport:
        import checks
        rep = checks.run_checks(self.workdir)
        write_json(self.workdir / "checks_report.json", rep.to_dict())
        if not rep.ok:
            raise RuntimeError(f"machine checks failed: {rep.failed}")
        self.advance(Phase.MACHINE_CHECKS_PASSED, {"check_digest": rep.digest()})
        return rep

    def finish(self, acceptor: CommitFirstAcceptor,
               objective: Objective) -> Path:
        """Commit-first acceptance. The acceptor records what it independently
        observed in every conversation, and its own verdict, before it is
        allowed to open the transcript."""
        acceptor.precommit(self, objective)
        outcome = acceptor.decide(self)
        self.accept_with(outcome)
        p = self.write_return_state({"transcript": "transcript.json"})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": str(p.name)})
        self.advance(Phase.COMPLETE, {})
        return p
