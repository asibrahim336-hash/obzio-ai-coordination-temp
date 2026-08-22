"""PO03-WA-020 blind strategy review harness.

An executable review procedure that seals its criteria before any candidate is
admitted, withholds producer identity from the scorer, and adjudicates every
load-bearing candidate claim by running a read-only repository control rather
than by trusting the claim.

The package is standard-library only and deterministic: the review path uses a
logical clock, never wall-clock time, so a run replays byte for byte.
"""

__all__ = [
    "adjudicator",
    "bias_experiment",
    "blinding",
    "candidates",
    "canonical",
    "claims",
    "criteria",
    "emit_result",
    "logical_clock",
    "probes",
    "research",
    "review",
    "reviewers",
    "run_harness",
]
