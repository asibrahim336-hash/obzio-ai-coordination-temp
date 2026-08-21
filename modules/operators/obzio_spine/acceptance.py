"""Independent-acceptance gate.

THE PROBLEM
-----------
A producing operator must not be able to sign off on its own work. Writing
"the producer must not self-accept" in a policy document is not a control; it
is a wish. This module makes the control cost a SHA-256 preimage.

THE MECHANISM
-------------
Before any work happens (at PREFLIGHT), a reviewer that is NOT the producer
generates two independent random secrets and hands the producer only their
digests:

    C_accept = sha256("obzio.acceptance.v1|ACCEPT|" + s_accept)
    C_reject = sha256("obzio.acceptance.v1|REJECT|" + s_reject)

The producer stores the two commitments. It does not hold s_accept or
s_reject and cannot derive them: doing so requires inverting SHA-256.

To cross the gate the reviewer reveals the secret matching its verdict, plus
a token binding that secret to the exact run under review:

    T = sha256("obzio.acceptance.v1|BIND|" + s + "|" + run_digest + "|" + verdict)

The machine verifies BOTH:
  1. sha256(domain|verdict|s) == C_verdict     -> proves reviewer authorship
  2. recomputed T == submitted T               -> binds verdict to THIS run

Separate secrets per verdict are what stop the obvious downgrade attack. If a
single secret covered both verdicts, then the moment the reviewer revealed it
to say REJECT, the producer would hold everything needed to mint an ACCEPT.
With split secrets, learning s_reject tells the producer nothing about
s_accept.

WHAT THIS DOES NOT DEFEND AGAINST -- read this, it is the real boundary
----------------------------------------------------------------------
This is a protocol control, not a sandbox. A producer that can execute
arbitrary code IN THE SAME PYTHON PROCESS can monkeypatch this module,
mutate machine internals, or fabricate a Ticket object. Python has no
intra-process memory isolation and this file does not pretend otherwise.

The control is therefore enforceable against:
  * a producer calling the public API, however adversarially   -> MACHINE
  * a producer that forges/replays/downgrades tokens           -> MACHINE
  * a producer that self-declares as its own reviewer          -> MACHINE
  * a producer that rewrites this module in memory             -> NOT DEFENDED

To get the last one you need a process/OS boundary: run the reviewer as a
separate process or on separate hardware and pass only the reveal across.
The API here is deliberately shaped so that move is a deployment change, not
a rewrite -- Reveal is plain JSON-serialisable data.
"""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, asdict

DOMAIN = "obzio.acceptance.v1"

ACCEPT = "ACCEPT"
REJECT = "REJECT"
VERDICTS = (ACCEPT, REJECT)


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def commit(secret: str, verdict: str) -> str:
    """Public commitment to a verdict-specific secret."""
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    return _h(DOMAIN, "COMMIT", verdict, secret)


def bind(secret: str, run_digest: str, verdict: str) -> str:
    """Token binding a revealed secret to one specific run and verdict."""
    return _h(DOMAIN, "BIND", secret, run_digest, verdict)


@dataclass(frozen=True)
class ReviewerKeypair:
    """Held ONLY by the reviewer. Never crosses into producer memory."""
    reviewer_id: str
    s_accept: str
    s_reject: str

    @staticmethod
    def generate(reviewer_id: str) -> "ReviewerKeypair":
        return ReviewerKeypair(
            reviewer_id=reviewer_id,
            s_accept=secrets.token_hex(32),
            s_reject=secrets.token_hex(32),
        )

    def commitments(self) -> "AcceptanceCommitments":
        """The only thing the producer is ever given."""
        return AcceptanceCommitments(
            reviewer_id=self.reviewer_id,
            c_accept=commit(self.s_accept, ACCEPT),
            c_reject=commit(self.s_reject, REJECT),
        )

    def issue(self, run_digest: str, verdict: str) -> "Reveal":
        """No `note` parameter. An earlier version carried a free-text note
        back to the producer; that is a rubric leak. A producer that learns
        WHY it failed learns what to change to pass without becoming correct.
        Rejection detail goes to the acceptor's own sink instead."""
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}")
        s = self.s_accept if verdict == ACCEPT else self.s_reject
        return Reveal(
            reviewer_id=self.reviewer_id,
            verdict=verdict,
            run_digest=run_digest,
            secret=s,
            token=bind(s, run_digest, verdict),
        )


@dataclass(frozen=True)
class AcceptanceCommitments:
    """Producer-visible. Contains no secret material."""
    reviewer_id: str
    c_accept: str
    c_reject: str

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Reveal:
    """Crosses the boundary at acceptance time. Plain data, JSON-safe.

    Carries a VERDICT BIT and the material proving who issued it. It carries
    no explanation, by design -- see AcceptanceReturn in expectation.py."""
    reviewer_id: str
    verdict: str
    run_digest: str
    secret: str
    token: str

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "Reveal":
        return Reveal(
            reviewer_id=d["reviewer_id"],
            verdict=d["verdict"],
            run_digest=d["run_digest"],
            secret=d["secret"],
            token=d["token"],
        )


class AcceptanceError(RuntimeError):
    """Raised on any failed gate crossing. Never swallowed."""


class SelfAcceptanceError(AcceptanceError):
    """The producer tried to review itself."""


def verify(
    reveal: "Reveal",
    commitments: "AcceptanceCommitments",
    expected_run_digest: str,
    producer_id: str,
) -> str:
    """Return the verdict, or raise. There is no boolean return: a caller
    cannot accidentally treat a falsy result as success."""

    if reveal.verdict not in VERDICTS:
        raise AcceptanceError(f"unknown verdict {reveal.verdict!r}")

    # 1. Identity separation. Cheap, checked first, and independent of crypto.
    if reveal.reviewer_id == producer_id:
        raise SelfAcceptanceError(
            f"producer {producer_id!r} cannot be its own reviewer"
        )
    if reveal.reviewer_id != commitments.reviewer_id:
        raise AcceptanceError(
            f"reveal from {reveal.reviewer_id!r} but commitments were bound to "
            f"{commitments.reviewer_id!r}"
        )

    # 2. Run binding. Stops replay of a valid reveal onto a different run.
    if reveal.run_digest != expected_run_digest:
        raise AcceptanceError(
            "reveal is bound to a different run: "
            f"{reveal.run_digest[:16]}... != {expected_run_digest[:16]}..."
        )

    # 3. Preimage. This is the part that costs a SHA-256 inversion to forge.
    expected_commit = (
        commitments.c_accept if reveal.verdict == ACCEPT else commitments.c_reject
    )
    if not hmac.compare_digest(commit(reveal.secret, reveal.verdict), expected_commit):
        raise AcceptanceError(
            f"revealed secret does not open the {reveal.verdict} commitment"
        )

    # 4. Token binding. Stops verdict substitution using a known-good secret.
    if not hmac.compare_digest(
        bind(reveal.secret, reveal.run_digest, reveal.verdict), reveal.token
    ):
        raise AcceptanceError("binding token does not match revealed secret")

    return reveal.verdict
