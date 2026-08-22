"""a5-u11: does structured hypothesis registration before execution raise
the research-to-mechanism conversion rate?

This is a documented, seeded, executable MODEL of the causal mechanism
preregistration is claimed to protect (exactly like a5-u05's criteria_arms
and a5-u08's lease-TTL simulation are documented models, not literal replay
of external systems), calibrated with explicit, stated parameters rather
than hidden magic numbers. It is run alongside a real, small-sample,
explicitly-labelled anecdote from this worker's own 12 units (see the
reproduction script), which is genuine data but too small (n<=12) to be
the sole basis for a rate claim -- hence the larger, both-arms-executed
model below, with an explicit denominator on each arm.

Model of a "candidate hypothesis" pool
---------------------------------------
Each candidate has a latent ground truth: TRUE, FALSE, or AMBIGUOUS (some
real-world claims are genuinely underdetermined by any test buildable
within a fixed effort budget -- honest science must be able to say so
rather than force a verdict).

Registered pipeline
--------------------
A falsifiable acceptance criterion is written BEFORE any reproduction code
is built, forcing the reproduction to be built to test exactly that
criterion. Modelled as: correctly resolves TRUE/FALSE candidates with high
reliability (``REGISTERED_ACCURACY``), and never forces a verdict onto a
genuinely AMBIGUOUS candidate (returns NOT_YET, honestly, exactly as this
worker's own a5-u09 does for real).

Unregistered ("ad hoc") pipeline
----------------------------------
No criterion is written first. Modelled as: the researcher sometimes
abandons before reaching any verdict at all (``UNREGISTERED_ATTEMPT_RATE``
< 1), resolves TRUE/FALSE candidates less reliably
(``UNREGISTERED_ACCURACY`` < ``REGISTERED_ACCURACY``, since the test was
not built against a predefined sharp target), and -- the specific failure
mode preregistration exists to prevent -- sometimes forces an apparently
decisive verdict onto a genuinely AMBIGUOUS candidate, which is spurious
(unfalsifiable in principle) rather than a real conversion.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

GroundTruth = Literal["TRUE", "FALSE", "AMBIGUOUS"]
Outcome = Literal["SUPPORTED", "REJECTED", "NOT_YET"]

GROUND_TRUTH_DISTRIBUTION: dict[GroundTruth, float] = {"TRUE": 0.4, "FALSE": 0.4, "AMBIGUOUS": 0.2}

REGISTERED_INCONCLUSIVE_RATE = 0.05  # even a well-targeted test sometimes yields no clean signal
REGISTERED_WRONG_RATE = 0.02  # even a well-targeted test is occasionally confidently wrong
UNREGISTERED_ATTEMPT_RATE = 0.65
UNREGISTERED_ACCURACY = 0.60


@dataclass
class Candidate:
    candidate_id: int
    ground_truth: GroundTruth


def generate_candidates(seed: int, n: int) -> list[Candidate]:
    rng = random.Random(seed)
    truths = list(GROUND_TRUTH_DISTRIBUTION.keys())
    weights = list(GROUND_TRUTH_DISTRIBUTION.values())
    return [Candidate(i, rng.choices(truths, weights=weights, k=1)[0]) for i in range(n)]


def registered_pipeline(candidate: Candidate, rng: random.Random) -> Outcome:
    if candidate.ground_truth == "AMBIGUOUS":
        return "NOT_YET"
    roll = rng.random()
    if roll < REGISTERED_INCONCLUSIVE_RATE:
        return "NOT_YET"
    if roll < REGISTERED_INCONCLUSIVE_RATE + REGISTERED_WRONG_RATE:
        # a sharp, pre-defined test is occasionally confidently wrong; preregistration
        # protects against goalpost-moving, not against every measurement error.
        return "REJECTED" if candidate.ground_truth == "TRUE" else "SUPPORTED"
    return "SUPPORTED" if candidate.ground_truth == "TRUE" else "REJECTED"


def unregistered_pipeline(candidate: Candidate, rng: random.Random) -> Outcome:
    attempted = rng.random() < UNREGISTERED_ATTEMPT_RATE
    if not attempted:
        return "NOT_YET"
    if candidate.ground_truth == "AMBIGUOUS":
        return rng.choice(["SUPPORTED", "REJECTED"])  # spurious: forced onto an unresolvable claim
    correct = rng.random() < UNREGISTERED_ACCURACY
    if correct:
        return "SUPPORTED" if candidate.ground_truth == "TRUE" else "REJECTED"
    return "REJECTED" if candidate.ground_truth == "TRUE" else "SUPPORTED"  # decisive-looking, but wrong


def is_decisive(outcome: Outcome) -> bool:
    return outcome in ("SUPPORTED", "REJECTED")


def is_correct(outcome: Outcome, candidate: Candidate) -> bool:
    if not is_decisive(outcome):
        return False
    if candidate.ground_truth == "AMBIGUOUS":
        return False  # no decisive verdict can be "correct" for a genuinely ambiguous claim
    expected = "SUPPORTED" if candidate.ground_truth == "TRUE" else "REJECTED"
    return outcome == expected


def run_pipeline_over_pool(
    candidates: list[Candidate], pipeline, seed: int
) -> dict:
    rng = random.Random(seed)
    outcomes = [pipeline(c, rng) for c in candidates]
    decisive = [is_decisive(o) for o in outcomes]
    correct_given_decisive = [is_correct(o, c) for o, c in zip(outcomes, candidates) if is_decisive(o)]
    spurious_decisive_on_ambiguous = sum(
        1 for o, c in zip(outcomes, candidates) if is_decisive(o) and c.ground_truth == "AMBIGUOUS"
    )
    return {
        "n": len(candidates),
        "decisive_count": sum(decisive),
        "conversion_rate": sum(decisive) / len(candidates),
        "decisive_and_correct_count": sum(correct_given_decisive),
        "correct_rate_given_decisive": (
            sum(correct_given_decisive) / len(correct_given_decisive) if correct_given_decisive else None
        ),
        "spurious_decisive_on_ambiguous_count": spurious_decisive_on_ambiguous,
    }
