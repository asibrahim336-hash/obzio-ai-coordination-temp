"""Source claims, hypotheses and reproductions, held as separate states.

Four kinds of record live here and they are not interchangeable:

* a **source claim** is something this unit read, with the exact locator, the
  transport status, the byte count and the digest of what came back;
* a **hypothesis** is something this unit asserted in advance and then tested,
  with its prediction written before the result;
* a **reproduction** is an observation obtained by running something;
* a **mechanism disposition** is what this unit did about the outcome.

The identifier spaces are disjoint, and a hypothesis is not permitted to rest on
a source recorded as ``NOT_SUPPORTED``. A candidate claim under review (``EC-*``)
is never promoted into a source claim: it is the object of study, not evidence.

External fetching is confined to this module and never runs in the review path,
so the harness and its tests are hermetic and a network outage degrades the
source record rather than the result.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .canonical import digest_bytes

NOT_SUPPORTED = "NOT_SUPPORTED"

# Each entry declares the locator, the claim this unit wants to rest on, and a
# keyword whose presence in the retrieved body is required before the claim may be
# asserted. Without that requirement a 200 response would license any paraphrase.
EXTERNAL_SOURCES: tuple[dict[str, str], ...] = (
    {
        "claim": (
            "Blinding withholds information about the experiment from participants so that the "
            "information cannot influence them, and is used to reduce bias in the assessment of "
            "outcomes."
        ),
        "claim_id": "S1",
        "keyword": "blind",
        "url": "https://en.wikipedia.org/wiki/Blinded_experiment",
    },
    {
        "claim": (
            "Preregistration means specifying the research plan in advance of observing the outcomes, "
            "which separates prediction from postdiction and constrains analytic choices made after "
            "seeing the data."
        ),
        "claim_id": "S2",
        "keyword": "preregistration",
        "url": "https://www.cos.io/initiatives/prereg",
    },
    {
        "claim": (
            "Hypothesising after the results are known presents a hypothesis formed after inspecting "
            "the outcomes as though it had been stated in advance."
        ),
        "claim_id": "S3",
        "keyword": "HARKing",
        "url": "https://en.wikipedia.org/wiki/HARKing",
    },
    {
        "claim": (
            "An anonymity policy withholds author identity from reviewers for a defined period so that "
            "review is conducted without knowledge of who produced the submission."
        ),
        "claim_id": "S4",
        "keyword": "anonym",
        "url": "https://aclrollingreview.org/anonymity",
    },
    {
        "claim": (
            "Double-blind review conceals the identities of authors from reviewers, in contrast with "
            "single-blind review in which reviewers know who the authors are."
        ),
        "claim_id": "S5",
        "keyword": "double-blind",
        "url": "https://en.wikipedia.org/wiki/Peer_review",
    },
    {
        "claim": (
            "Confirmation bias is the tendency to search for, favour and recall information in a way "
            "that supports one's prior beliefs, and to give disproportionate weight to evidence that "
            "supports them."
        ),
        "claim_id": "S6",
        "keyword": "confirmation bias",
        "url": "https://en.wikipedia.org/wiki/Confirmation_bias",
    },
    {
        "claim": (
            "Preregistration of a study's hypotheses and analysis plan is intended to reduce the "
            "flexibility that allows a result to be selected after the data are seen."
        ),
        "claim_id": "S7",
        "keyword": "preregistration",
        "url": "https://en.wikipedia.org/wiki/Preregistration_(science)",
    },
    {
        "claim": (
            "Define steady state as a measurable output indicating normal behaviour, hypothesise it "
            "continues, introduce variables reflecting real-world events, and then try to disprove the "
            "hypothesis rather than confirm it."
        ),
        "claim_id": "S8",
        "keyword": "hypothes",
        "url": "https://principlesofchaos.org/",
    },
    {
        "claim": (
            "A measured comparison of single-blind and double-blind reviewing of the same submissions, "
            "which would give an effect size for identity bias in human reviewers."
        ),
        "claim_id": "S9",
        "keyword": "single-blind",
        "url": "https://www.pnas.org/doi/10.1073/pnas.1707323114",
    },
)


REPOSITORY_SOURCES: tuple[dict[str, str], ...] = (
    {
        "claim": "The frozen task input for this unit: its falsifiable hypothesis, attempt envelope, owned globs and required executable output.",
        "claim_id": "P1",
        "path": "workstreams/po03/control/inputs/wave-a/wa-020-a02.json",
    },
    {
        "claim": "The frozen producer-neutral acceptance contract: twelve required assertions, the required artifact list and the allowed outcomes.",
        "claim_id": "P2",
        "path": "workstreams/po03/control/acceptance/wave-a-material-v1.json",
    },
    {
        "claim": (
            "The commission's requirement that consequential decisions receive blind adversarial "
            "review with criteria frozen before producer conclusions are received, and its "
            "strongest-model policy, which assigns each configuration a standing role."
        ),
        "claim_id": "P3",
        "path": "workstreams/po03/COMMISSION.md",
    },
    {
        "claim": "The declared wire format for a transactional result, including the six-value result_transaction.state enumeration.",
        "claim_id": "P4",
        "path": "workstreams/po03/contracts/transactional-result.schema.json",
    },
    {
        "claim": "The dependency-free executable control that gates result custody; read-only to this unit and executed unmodified by every probe.",
        "claim_id": "P5",
        "path": "workstreams/po03/tools/validate_contracts.py",
    },
    {
        "claim": "The seeded control tests, run unmodified as a probe.",
        "claim_id": "P6",
        "path": "workstreams/po03/tests/test_validate_contracts.py",
    },
    {
        "claim": "The seeded workflow, whose test discovery root is confined to workstreams/po03/tests.",
        "claim_id": "P7",
        "path": ".github/workflows/po03-contracts.yml",
    },
    {
        "claim": (
            "A committed producer identity, complete: runner id, observed model slug and reasoning. "
            "Used as the one identity envelope in the pool that is a real identity rather than a real "
            "shape."
        ),
        "claim_id": "P8",
        "path": "workstreams/po03/wave-a/units/wa-016/result/result.json",
    },
    {
        "claim": (
            "The committed branch and result commit of that producer, and the prior finding this "
            "unit's fixture cites as prior art."
        ),
        "claim_id": "P9",
        "path": "workstreams/po03/wave-a/units/wa-016/result/ready-to-commit.json",
    },
)


_SENTENCE_PATTERN = re.compile(r"[^.!?]{40,400}[.!?]")
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _plain_text(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = _TAG_PATTERN.sub(" ", text)
    return _WHITESPACE_PATTERN.sub(" ", text)


def _excerpt(text: str, keyword: str) -> str | None:
    lowered = text.lower()
    position = lowered.find(keyword.lower())
    if position < 0:
        return None
    window = text[max(0, position - 300) : position + 400]
    matches = [match.group(0).strip() for match in _SENTENCE_PATTERN.finditer(window)]
    for match in matches:
        if keyword.lower() in match.lower():
            return match
    return window.strip()[:300] or None


def fetch_external_claims(timeout: int = 30) -> list[dict[str, Any]]:
    """Retrieve each declared external source and record what came back.

    A claim is asserted only when the transport succeeded and the retrieved body
    actually contains the declared keyword. Everything else is recorded as
    NOT_SUPPORTED with the observed boundary, and supports nothing.
    """
    records: list[dict[str, Any]] = []
    for source in EXTERNAL_SOURCES:
        record: dict[str, Any] = {
            "claim_id": source["claim_id"],
            "keyword_required": source["keyword"],
            "url": source["url"],
        }
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "-L",
                    "--max-time",
                    str(timeout),
                    "-w",
                    "\n%{http_code}",
                    source["url"],
                ],
                capture_output=True,
                timeout=timeout + 15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            record.update(
                {
                    "claim": NOT_SUPPORTED,
                    "http_status": None,
                    "limitation": f"retrieval failed in this runtime: {exc}",
                    "readable_in_runtime": False,
                }
            )
            records.append(record)
            continue

        raw = completed.stdout
        separator = raw.rfind(b"\n")
        body = raw[:separator] if separator > 0 else raw
        status_text = raw[separator + 1 :].decode("ascii", errors="replace").strip() if separator > 0 else ""
        status = int(status_text) if status_text.isdigit() else None
        record.update({"bytes": len(body), "http_status": status, "sha256": digest_bytes(body)})

        if status != 200 or not body:
            record.update(
                {
                    "claim": NOT_SUPPORTED,
                    "limitation": (
                        f"the locator returned HTTP {status} rather than a readable body, so no claim "
                        "is asserted from it and nothing in this unit rests on it"
                    ),
                    "readable_in_runtime": False,
                }
            )
            records.append(record)
            continue

        text = _plain_text(body)
        excerpt = _excerpt(text, source["keyword"])
        if not excerpt:
            record.update(
                {
                    "claim": NOT_SUPPORTED,
                    "limitation": (
                        f"the body was retrieved but does not contain the declared keyword "
                        f"{source['keyword']!r}, so the intended claim is not supported by what was read"
                    ),
                    "readable_in_runtime": False,
                }
            )
            records.append(record)
            continue

        record.update(
            {
                "claim": source["claim"],
                "readable_in_runtime": True,
                "supporting_excerpt": excerpt,
            }
        )
        records.append(record)
    return records


def repository_claims(root: Path) -> list[dict[str, Any]]:
    """Digest every repository file this unit read, at the checkout it read them from."""
    head = _git_head(root)
    records: list[dict[str, Any]] = []
    for source in REPOSITORY_SOURCES:
        path = root / source["path"]
        if not path.is_file():
            records.append(
                {
                    "claim": NOT_SUPPORTED,
                    "claim_id": source["claim_id"],
                    "limitation": "the path is absent from this checkout",
                    "path": source["path"],
                    "read_at_commit": head,
                }
            )
            continue
        payload = path.read_bytes()
        records.append(
            {
                "bytes": len(payload),
                "claim": source["claim"],
                "claim_id": source["claim_id"],
                "path": source["path"],
                "read_at_commit": head,
                "sha256": digest_bytes(payload),
            }
        )
    return records


def _git_head(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else NOT_SUPPORTED
    except (OSError, subprocess.SubprocessError):
        return NOT_SUPPORTED


# --------------------------------------------------------------------------
# Hypotheses. Statement and prediction are written before the run; only the
# outcome and evidence fields are filled from the result.
# --------------------------------------------------------------------------

HYPOTHESES: tuple[dict[str, Any], ...] = (
    {
        "evaluator": "identity_swing_under_blinding",
        "hypothesis_id": "CM-H1",
        "prediction": "Every blind cell reports a maximum identity swing of 0 and 0 rank inversions.",
        "source_claim_ids": ["S1", "S4", "S5", "P3"],
        "statement": (
            "If the scorer receives only a rendered payload redacted against a pool-wide identity "
            "vocabulary, then permuting which producer identity is attached to which submission leaves "
            "every score unchanged, including for a reviewer carrying an explicit standing bias."
        ),
    },
    {
        "evaluator": "identity_swing_when_unblinded",
        "hypothesis_id": "CM-H2",
        "prediction": "At least one unblinded cell reports a maximum identity swing above 0.",
        "source_claim_ids": ["S5", "S6"],
        "statement": (
            "The same reviewer with the same bias function moves at least one submission's score when "
            "identity is visible and nothing but the attached identity changes, so the null result "
            "under blinding is attributable to the blind rather than to an unbiased reviewer."
        ),
    },
    {
        "evaluator": "seeded_claim_catch_by_probe",
        "hypothesis_id": "CM-H3",
        "prediction": (
            "Every cell whose adjudicator runs the probe catches the seeded false claim in every "
            "permutation under blinding; no cell with a credulous adjudicator catches it at all."
        ),
        "source_claim_ids": ["S8", "P4", "P5"],
        "statement": (
            "A claim that is attractive on every surface a reader uses to judge quickly, and false "
            "only in what the executable control actually does, is caught when the control is executed "
            "and missed when the claim is read."
        ),
    },
    {
        "evaluator": "seeded_claim_survival_under_standing",
        "hypothesis_id": "CM-H4",
        "prediction": (
            "The unblinded standing-sensitive probing cell catches the claim in three of four "
            "permutations, missing exactly the permutation that attributes it to the highest tier."
        ),
        "source_claim_ids": ["S6", "P3"],
        "statement": (
            "Running the probe is not sufficient on its own: a reviewer who can see a high-standing "
            "producer discounts the refutation it has already obtained, so the false claim survives a "
            "review that did execute the control."
        ),
    },
    {
        "evaluator": "criteria_freeze_gate",
        "hypothesis_id": "CM-H5",
        "prediction": (
            "The gated session refuses a post-ingestion seal, and removing the gate yields a strictly "
            "positive weighted gain for the favoured submission."
        ),
        "source_claim_ids": ["S2", "S3", "S7", "P3"],
        "statement": (
            "Sealing the criteria before ingestion prevents outcome-directed selection of weights from "
            "a declared menu; with the gate removed, the same reviewer obtains a measurable gain for "
            "the submission it favours."
        ),
    },
    {
        "evaluator": "per_identity_vocabulary_channel",
        "hypothesis_id": "CM-H6",
        "prediction": (
            "The per-identity blinder renders one submission's content into more than one distinct "
            "byte string across identity permutations; the pool-vocabulary blinder renders exactly one."
        ),
        "source_claim_ids": ["S1", "P8", "P9"],
        "statement": (
            "Redacting each submission against its own identity vocabulary leaves an identity channel "
            "even when it removes every identity string, because a submission that legitimately cites a "
            "committed prior attempt loses the citation under one identity and keeps it under the others."
        ),
    },
    {
        "evaluator": "arrival_order_label_channel",
        "hypothesis_id": "CM-H7",
        "prediction": (
            "Arrival-order labels correlate perfectly with the withheld standing tier for a pool "
            "arranged in descending standing; content-derived labels do not."
        ),
        "source_claim_ids": ["S1", "S4"],
        "statement": (
            "Assigning pseudonyms in arrival order leaves an identity channel after complete "
            "redaction, because the label ranks the producers whenever arrival order carries standing."
        ),
    },
    {
        "evaluator": "freeze_not_subsumed_by_blinding",
        "hypothesis_id": "CM-H8",
        "prediction": (
            "Under blinding, removing the ordering gate still changes at least one ranking, so "
            "blinding does not make the freeze redundant."
        ),
        "source_claim_ids": ["S2", "S3", "S7"],
        "statement": (
            "Blinding and the ordering gate close different channels. Blinding removes who wrote a "
            "submission; the gate removes the reviewer's freedom to choose the weights after reading it. "
            "Neither substitutes for the other."
        ),
    },
    {
        "evaluator": "human_or_model_reviewer_transfer",
        "hypothesis_id": "CM-H9",
        "prediction": (
            "This hypothesis is expected to be unresolvable within this unit: no human or "
            "language-model reviewer is measured anywhere in it."
        ),
        "source_claim_ids": ["S5", "S6"],
        "statement": (
            "The identity-bias reduction measured here transfers to a human or language-model reviewer "
            "at a comparable magnitude."
        ),
    },
)


def state_separation(
    source_claim_ids: Sequence[str],
    hypothesis_ids: Sequence[str],
    reproduction_ids: Sequence[str],
    mechanism_ids: Sequence[str],
    candidate_claim_ids: Sequence[str],
) -> dict[str, Any]:
    """Check that the five identifier spaces are disjoint and report the result."""
    spaces = {
        "candidate_claims": set(candidate_claim_ids),
        "hypotheses": set(hypothesis_ids),
        "mechanisms": set(mechanism_ids),
        "reproductions": set(reproduction_ids),
        "source_claims": set(source_claim_ids),
    }
    collisions: list[dict[str, Any]] = []
    names = sorted(spaces)
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            shared = spaces[names[left]] & spaces[names[right]]
            if shared:
                collisions.append(
                    {"shared": sorted(shared), "spaces": [names[left], names[right]]}
                )
    return {
        "collisions": collisions,
        "disjoint": not collisions,
        "note": (
            "A candidate claim under review is the object of study and is never promoted into a source "
            "claim. A hypothesis is never permitted to rest on a source recorded as NOT_SUPPORTED."
        ),
        "sizes": {name: len(members) for name, members in sorted(spaces.items())},
    }


def unsupported_source_ids(external: Sequence[dict[str, Any]], repository: Sequence[dict[str, Any]]) -> list[str]:
    return sorted(
        record["claim_id"]
        for record in list(external) + list(repository)
        if record.get("claim") == NOT_SUPPORTED
    )


def hypotheses_resting_on_unsupported_sources(unsupported: Sequence[str]) -> list[dict[str, Any]]:
    """Every hypothesis whose only cited sources are unsupported.

    A hypothesis that cites an unsupported source alongside supported ones is not
    a violation, because it still rests on something that was read. A hypothesis
    with no supported source underneath it is.
    """
    blocked = set(unsupported)
    offenders: list[dict[str, Any]] = []
    for hypothesis in HYPOTHESES:
        cited = set(hypothesis["source_claim_ids"])
        if cited and cited <= blocked:
            offenders.append({"cited": sorted(cited), "hypothesis_id": hypothesis["hypothesis_id"]})
    return offenders
