"""The submission pool: repository-native strategy proposals under blind review.

Every submission proposes a change to the custody controls this repository
already runs, and every load-bearing claim it makes is a prediction about what
happens when one of those controls is executed. Nothing here describes an
imagined system.

The identity envelopes are harvested from result documents already committed at
the source base, so the strings the blind has to remove are strings that really
occur in this repository: real runner-id shapes, real observed model slugs, real
branch names and real commit identifiers. The standing tier attached to each
envelope comes from the commission's own strongest-model policy, not from any
ranking invented here.

Sanitisation: the fixtures carry no credential, no owner identity, no third-party
content and no path outside this unit's own subtree except the read-only control
paths the claims are about.

One submission carries a seeded false claim. It is written to compete: it cites a
real path, quotes the real digest of the real control, reproduces the control's
own error style, enumerates the schema's real transaction states correctly,
hedges nothing, and reaches a conclusion that would save the reader work. It is
false in exactly one respect, and only an executed probe reveals which.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .blinding import IdentityEnvelope
from .canonical import digest

# The commission's strongest-model policy assigns each configuration a role. The
# tier below is that role ordering and nothing else; the quotation that fixes it
# is recorded as a source claim and carried on every envelope.
STANDING_POLICY: tuple[tuple[str, int, str], ...] = (
    ("claude-opus-5", 4, "lead/integrator default"),
    ("gpt-5.6-sol", 3, "independent chief challenger and parallel engineering default"),
    ("gemini-3.1-pro", 2, "independent long-context and alternative-generation default"),
    ("composer-2.5", 1, "restricted; never a routine cheaper substitute"),
)

STANDING_SOURCE = (
    "workstreams/po03/COMMISSION.md, section 'Strongest-model policy': the commission names a "
    "lead/integrator default, an independent chief challenger default, an alternative-generation "
    "default, and one family admitted only under a frozen paired evaluation."
)


def standing_for(model_slug: str) -> tuple[int, str]:
    """Map an observed model slug to the standing its family carries in the commission."""
    for family, tier, role in STANDING_POLICY:
        if model_slug.startswith(family):
            return tier, role
    return 0, "no standing declared in the commission's strongest-model policy"


def harvest_identity_envelopes(repository_root: Path) -> list[dict[str, Any]]:
    """Read observed producer identity shapes from result documents at the source base.

    Read-only. Records what each document actually contained, including where a
    field was absent, so the pool is an observation rather than an invention.
    """
    units_dir = repository_root / "workstreams/po03/wave-a/units"
    observations: list[dict[str, Any]] = []
    if not units_dir.is_dir():
        return observations
    for unit in sorted(path for path in units_dir.iterdir() if path.is_dir()):
        for relative in ("result/result.json", "result.json"):
            document = unit / relative
            if not document.is_file():
                continue
            try:
                payload = json.loads(document.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            model = payload.get("model_observed")
            if isinstance(model, dict):
                model = model.get("requested_model_slug") or model.get("provider_run_original_model_name")
            reasoning = payload.get("reasoning_observed")
            if isinstance(reasoning, dict):
                reasoning = reasoning.get("requested") or "NOT_SUPPORTED"
            observations.append(
                {
                    "attempt_id": _first_string(payload, ("attempt", "attempt_id")) or "",
                    "model_slug": model if isinstance(model, str) else "",
                    "observed_in": f"workstreams/po03/wave-a/units/{unit.name}/{relative}",
                    "reasoning": reasoning if isinstance(reasoning, str) else "",
                    "runner_id": payload.get("runner_id") or "",
                    "task_id": payload.get("task_id") or "",
                }
            )
            break
    return observations


def _first_string(payload: dict[str, Any], path: Sequence[str]) -> str | None:
    cursor: Any = payload
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor if isinstance(cursor, str) else None


def observed_prior_producer(repository_root: Path) -> dict[str, Any] | None:
    """Read one real producer identity, complete, from committed result documents.

    The pool needs at least one envelope that is not merely shaped like a real
    identity but *is* one, because the prior-art channel only exists when a
    submission can legitimately cite work whose producer is in the pool. Every
    field below is read from bytes already committed at the source base.
    """
    for unit in ("wa-016", "wa-024", "wa-023"):
        result = repository_root / f"workstreams/po03/wave-a/units/{unit}/result/result.json"
        ready = repository_root / f"workstreams/po03/wave-a/units/{unit}/result/ready-to-commit.json"
        if not result.is_file():
            continue
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runner = payload.get("runner_id")
        model = payload.get("model_observed")
        if not isinstance(runner, str) or not isinstance(model, str):
            continue
        branch = ""
        commit = ""
        if ready.is_file():
            try:
                return_document = json.loads(ready.read_text(encoding="utf-8"))
                branch = return_document.get("remote_branch") or ""
                commit = return_document.get("result_commit_id") or ""
            except (OSError, ValueError):
                pass
        attempt = _first_string(payload, ("attempt", "attempt_id")) or ""
        return {
            "attempt_id": attempt,
            "branch": branch,
            "model_slug": model,
            "observed_in": (
                f"workstreams/po03/wave-a/units/{unit}/result/result.json and "
                f"workstreams/po03/wave-a/units/{unit}/result/ready-to-commit.json"
            ),
            "reasoning": payload.get("reasoning_observed") if isinstance(payload.get("reasoning_observed"), str) else "",
            "result_commit_id": commit if len(commit) == 40 else "",
            "runner_id": runner,
            "task_id": payload.get("task_id") or "",
            "unit": unit,
        }
    return None


def prior_art_citation(prior: dict[str, Any] | None) -> str:
    """A legitimate citation of committed prior work.

    Proposals in this repository cite earlier units, and earlier units have
    producers. That is what makes a per-candidate redaction vocabulary unsafe: the
    citation is content, not identity, but it names a string that is one pool
    member's identity and nobody else's, so redacting each submission against its
    own identity removes the citation for exactly one reviewer and leaves it in
    place for the others.
    """
    if not prior or not prior["attempt_id"]:
        return (
            "No committed prior attempt was resolvable in this checkout, so this proposal cites no "
            "prior art."
        )
    commit = prior["result_commit_id"] or "an immutable commit"
    branch = prior["branch"] or "its dispatch branch"
    return (
        f"Prior art: attempt {prior['attempt_id']} recorded that damage landing between verification "
        "and publication is published under the earlier manifest, and that the spent idempotency key "
        f"then blocks the repair. That result was committed at {commit} on branch {branch}. This "
        "proposal generalises that finding from one transition to the whole staging path."
    )


def identity_pool(repository_root: Path) -> tuple[IdentityEnvelope, ...]:
    """Four identity envelopes, one per standing tier, shaped from observed data.

    The runner-id and branch forms are the forms this repository actually uses.
    The tiers are the commission's role ordering. Producing one envelope per tier
    is what makes the permutation experiment able to separate a standing effect
    from noise.
    """
    observed = harvest_identity_envelopes(repository_root)
    observed_slugs = [item["model_slug"] for item in observed if item["model_slug"]]
    observed_runners = [item["runner_id"] for item in observed if item["runner_id"]]
    runner_form = observed_runners[0] if observed_runners else "best-of-n-runner-bc-b1956656-wa-000-a01"
    prior = observed_prior_producer(repository_root)

    def slug_for(family: str, fallback: str) -> tuple[str, str]:
        for slug in observed_slugs:
            if slug.startswith(family):
                return slug, "observed in a committed result document at the source base"
        return fallback, "declared in the commission's strongest-model policy; not observed in a committed result"

    envelopes: list[IdentityEnvelope] = []
    fallbacks = {
        "claude-opus-5": "claude-opus-5-thinking-high",
        "gpt-5.6-sol": "gpt-5.6-sol",
        "gemini-3.1-pro": "gemini-3.1-pro",
        "composer-2.5": "composer-2.5",
    }
    for index, (family, tier, role) in enumerate(STANDING_POLICY):
        slug, provenance = slug_for(family, fallbacks[family])
        short = family.split("-")[0]
        use_observed = prior is not None and prior["model_slug"].startswith(family) and tier == 4
        if use_observed:
            # One envelope is a complete real producer identity rather than a real
            # shape, so a submission can cite its committed work as prior art.
            envelopes.append(
                IdentityEnvelope(
                    envelope_id=f"IDENT-T{tier}",
                    producer_id=prior["runner_id"],
                    runner_id=prior["runner_id"],
                    attempt_id=prior["attempt_id"],
                    model_slug=prior["model_slug"],
                    reasoning=prior["reasoning"] or "high",
                    branch=prior["branch"],
                    result_commit_id=prior["result_commit_id"],
                    standing_tier=tier,
                    standing_role=role,
                    standing_source=f"{STANDING_SOURCE} Slug provenance: observed in a committed result document.",
                    observed_in=prior["observed_in"],
                )
            )
            continue
        envelopes.append(
            IdentityEnvelope(
                envelope_id=f"IDENT-T{tier}",
                producer_id=f"obzio.producer.po03-wave-a-{short}-t{tier}",
                runner_id=_reshape_runner(runner_form, short, tier),
                attempt_id=f"PO03-WA-020-FIXTURE-{short.upper()}-A0{index + 1}",
                model_slug=slug,
                reasoning="high",
                branch=f"cursor/po03-wave-a-fixture-{short}-t{tier}-1a9f",
                result_commit_id=digest(f"wa-020-fixture-commit-{family}")[:40],
                standing_tier=tier,
                standing_role=role,
                standing_source=f"{STANDING_SOURCE} Slug provenance: {provenance}.",
                observed_in=", ".join(
                    item["observed_in"] for item in observed if item["model_slug"] == slug
                )
                or "not observed; slug taken from the commission's policy text",
            )
        )
    return tuple(envelopes)


def _reshape_runner(observed_form: str, short: str, tier: int) -> str:
    """Reuse an observed runner-id shape with a fixture-specific body."""
    if observed_form.startswith("best-of-n-runner-"):
        return f"best-of-n-runner-bc-b1956656-wa-020-fixture-{short}-t{tier}"
    return f"obzio.worker.po03-wa-020-fixture-{short}-t{tier}"


# --------------------------------------------------------------------------
# Submissions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Submission:
    """One strategy proposal, with its identity envelope attached but separable."""

    submission_id: str
    identity: IdentityEnvelope
    title: str
    proposal: str
    method: str
    executable_component: str
    limitations: str
    novelty_assertion: str
    claim_ids: tuple[str, ...]
    self_reference: str = ""
    prior_art: str = ""

    def reviewable_content(self) -> dict[str, Any]:
        """The content a reviewer is entitled to see, before blinding.

        Identity is not included as a field here: the envelope is held alongside
        rather than inside. The prose, however, is the producer's own writing and
        does refer to the producer's branch and earlier attempts, which is why a
        field-level redactor is not enough.
        """
        return {
            "claim_ids": list(self.claim_ids),
            "executable_component": self.executable_component,
            "limitations": self.limitations,
            "method": self.method,
            "novelty_assertion": self.novelty_assertion,
            "prior_art": self.prior_art,
            "proposal": self.proposal,
            "self_reference": self.self_reference,
            "title": self.title,
        }

    def unblinded_content(self) -> dict[str, Any]:
        """Everything, including identity: what the unblinded arm receives."""
        content = self.reviewable_content()
        content["identity"] = self.identity.as_record()
        return content


@dataclass
class SubmissionPool:
    submissions: list[Submission] = field(default_factory=list)

    @property
    def identities(self) -> tuple[IdentityEnvelope, ...]:
        return tuple(submission.identity for submission in self.submissions)

    def by_id(self, submission_id: str) -> Submission:
        for submission in self.submissions:
            if submission.submission_id == submission_id:
                return submission
        raise KeyError(submission_id)

    def with_identities(self, assignment: dict[str, IdentityEnvelope]) -> "SubmissionPool":
        """Return the same content under a different identity assignment."""
        return SubmissionPool(
            submissions=[
                Submission(
                    submission_id=submission.submission_id,
                    identity=assignment[submission.submission_id],
                    title=submission.title,
                    proposal=submission.proposal,
                    method=submission.method,
                    executable_component=submission.executable_component,
                    limitations=submission.limitations,
                    novelty_assertion=submission.novelty_assertion,
                    claim_ids=submission.claim_ids,
                    self_reference=_reference_for(assignment[submission.submission_id]),
                    prior_art=submission.prior_art,
                )
                for submission in self.submissions
            ]
        )


def _reference_for(identity: IdentityEnvelope) -> str:
    """The producer's own prose reference to its earlier work.

    This is the sentence a field-level redactor never looks at, and the reason the
    leak scanner reads the rendered bytes instead of the object graph.
    """
    return (
        f"This extends the approach taken by attempt {identity.attempt_id} on branch "
        f"{identity.branch}, whose result was committed at {identity.result_commit_id}; the "
        f"reviewer may consult that result for the prior evidence. Produced by "
        f"{identity.producer_id} running {identity.model_slug}."
    )


SUBMISSION_SPECIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "submission_id": "SUB-1",
        "title": "Reconcile declared byte accounting before publishing a result",
        "proposal": (
            "Add a pre-publication step that re-reads the staged artifact bytes and refuses to "
            "publish when the declared total disagrees with what is on disk."
        ),
        "method": (
            "The seeded control already compares the declared total against the sum of the "
            "per-artifact byte counts inside one document. It cannot compare either number against "
            "the bytes actually staged, because it never opens the artifacts. The proposal closes "
            "that second gap with a reconciliation step in the producer, keeping the control "
            "unmodified."
        ),
        "executable_component": (
            "A reconciliation function plus a focused test that damages one staged artifact between "
            "verification and publication and asserts the refusal."
        ),
        "limitations": (
            "The step reconciles bytes, not meaning: an artifact can be internally wrong and still "
            "reconcile. It does not detect damage that lands after publication."
        ),
        "novelty_assertion": "A modest addition to an existing control path; no novelty is claimed.",
        "claim_ids": ("EC-01", "EC-02"),
        "cites_prior_art": True,
    },
    {
        "submission_id": "SUB-2",
        "title": "Rely on the seeded control for transaction-state enumeration",
        "proposal": (
            "Drop the transaction-state enumeration check that units have been adding to their own "
            "subtrees and rely on the seeded control, which already enforces it."
        ),
        "method": (
            "The wire format for a transactional result is declared in "
            "workstreams/po03/contracts/transactional-result.schema.json and enforced by "
            "workstreams/po03/tools/validate_contracts.py, which every unit already runs. Auditing "
            "both against each other shows the enumeration is covered centrally, so per-unit "
            "duplication costs maintenance and buys nothing."
        ),
        "executable_component": (
            "A removal patch against the per-unit checks, plus a test asserting the central control "
            "still rejects an undeclared state."
        ),
        "limitations": "Removing a check requires the central control to stay in place; that is a governance dependency.",
        "novelty_assertion": (
            "This is a strategically significant simplification: it removes duplicated custody logic "
            "from every unit subtree in the wave at once."
        ),
        "claim_ids": ("EC-03", "EC-FALSE-01", "EC-04"),
    },
    {
        "submission_id": "SUB-3",
        "title": "Enforce logical-name uniqueness in the artifact list",
        "proposal": (
            "Add a uniqueness check over artifact logical names and content locations, so a single "
            "file cannot be counted twice toward a manifest."
        ),
        "method": (
            "The control enforces uniqueness of artifact_id and nothing else, so two entries may "
            "describe one path under two identifiers and inflate both the count and the byte total. "
            "The check is three lines and has a direct adversarial case."
        ),
        "executable_component": "A uniqueness predicate over the artifact list and an adversarial document that trips it.",
        "limitations": (
            "Uniqueness of a name is not identity of content; two entries may still describe the same "
            "bytes under different names. The check does not attempt content deduplication."
        ),
        "novelty_assertion": "No novelty is claimed; this is a missing constraint rather than a new idea.",
        "claim_ids": ("EC-05", "EC-06"),
    },
    {
        "submission_id": "SUB-4",
        "title": "Require a manifest digest whenever a manifest is located",
        "proposal": (
            "Refuse any result that names a manifest location without also carrying the manifest "
            "digest, at every lifecycle state rather than only after commit."
        ),
        "method": (
            "A located but undigested manifest is worse than an absent one: it reads as evidence and "
            "cannot be reconciled. The proposal moves the digest requirement forward to the moment a "
            "location is first claimed."
        ),
        "executable_component": "A predicate over the transaction record plus its adversarial document.",
        "limitations": (
            "The claim about the hosted runner's behaviour below is not probed in this proposal and "
            "may not hold; it is recorded as unverified rather than relied upon."
        ),
        "novelty_assertion": "No novelty is claimed.",
        "claim_ids": ("EC-07", "EC-08"),
    },
    {
        "submission_id": "SUB-5",
        "title": "Adopt a stronger custody posture across the wave",
        "proposal": (
            "Adopt a comprehensive custody posture that strengthens result integrity end to end "
            "across every unit in the wave."
        ),
        "method": (
            "The current controls are directionally right but insufficiently rigorous. A unified "
            "posture, applied consistently, will raise integrity substantially and reduce the "
            "variance between units."
        ),
        "executable_component": "A posture document to be implemented by each unit in its own subtree.",
        "limitations": "None identified.",
        "novelty_assertion": (
            "This is a fundamentally novel and strategically decisive reframing of custody for the "
            "whole programme."
        ),
        "claim_ids": ("EC-09", "EC-10"),
    },
)


def build_pool(
    identities: Sequence[IdentityEnvelope], prior: dict[str, Any] | None = None
) -> SubmissionPool:
    """Assemble the pool, assigning identities in descending standing order.

    Descending order is deliberate: it is the arrangement under which an
    arrival-order pseudonym scheme leaks the standing ranking perfectly, which is
    what makes ``ArrivalOrderBlinder`` a meaningful control rather than a
    formality. Where there are more submissions than identities the shortfall
    repeats the lowest-standing envelope, so the arrangement stays monotonically
    descending and the control keeps its full leak.
    """
    ordered = sorted(identities, key=lambda envelope: -envelope.standing_tier)
    shortfall = len(SUBMISSION_SPECIFICATIONS) - len(ordered)
    if shortfall > 0:
        ordered = list(ordered) + [ordered[-1]] * shortfall
    citation = prior_art_citation(prior)
    submissions: list[Submission] = []
    for specification, identity in zip(SUBMISSION_SPECIFICATIONS, ordered):
        submissions.append(
            Submission(
                submission_id=specification["submission_id"],
                identity=identity,
                title=specification["title"],
                proposal=specification["proposal"],
                method=specification["method"],
                executable_component=specification["executable_component"],
                limitations=specification["limitations"],
                novelty_assertion=specification["novelty_assertion"],
                claim_ids=tuple(specification["claim_ids"]),
                self_reference=_reference_for(identity),
                prior_art=citation if specification.get("cites_prior_art") else "",
            )
        )
    return SubmissionPool(submissions=submissions)
