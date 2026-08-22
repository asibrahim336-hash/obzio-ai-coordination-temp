"""PO03-WA-053 — NOT_SUPPORTED survives aggregation instead of becoming zero.

Frozen hypothesis: unknown metric values remain NOT_SUPPORTED through aggregation.

The metric definitions fix `NOT_SUPPORTED` as the unknown value and the
commission forbids inventing unavailable values. The quiet failure mode is
arithmetic: an unknown coerced to `0` inflates a sum, deflates a mean, and turns
"we could not measure this" into "we measured zero". A rate whose denominator is
entirely unknown is not `0.0`; it is unknown.

Every aggregate here carries its own coverage, so a caller can never read a
number without also reading how much of the population it actually covers.

Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

NOT_SUPPORTED = "NOT_SUPPORTED"

# Sentinels that must be treated as unknown rather than silently coerced.
_UNKNOWN_SENTINELS = (None, NOT_SUPPORTED, "", "null", "NULL", "N/A", "n/a", "unknown")


class MetricCoercionError(TypeError):
    """Raised when an unknown value is pushed into arithmetic."""


def is_unknown(value) -> bool:
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, bool):
        return False
    for sentinel in _UNKNOWN_SENTINELS:
        if value is sentinel:
            return True
        if isinstance(value, str) and isinstance(sentinel, str) and value == sentinel:
            return True
    return False


def numeric(value):
    """Return a number, or refuse. Never returns 0 for an unknown."""
    if is_unknown(value):
        raise MetricCoercionError(
            f"{value!r} is unknown; NOT_SUPPORTED must not be coerced into arithmetic"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricCoercionError(f"{value!r} is not numeric")
    return value


@dataclass(frozen=True)
class Aggregate:
    """An aggregate that cannot be read without its coverage."""

    metric: str
    value: object
    known_count: int
    unknown_count: int
    population: int
    boundary: str = ""

    @property
    def supported(self) -> bool:
        return self.value != NOT_SUPPORTED

    @property
    def coverage(self):
        if self.population == 0:
            return NOT_SUPPORTED
        return self.known_count / self.population

    def as_row(self) -> dict:
        return {
            "metric": self.metric,
            "value": self.value,
            "known_count": self.known_count,
            "unknown_count": self.unknown_count,
            "population": self.population,
            "coverage": self.coverage,
            "observed_boundary": self.boundary,
        }


def _split(values):
    known, unknown = [], 0
    for value in values:
        if is_unknown(value):
            unknown += 1
        else:
            known.append(numeric(value))
    return known, unknown


def aggregate_sum(metric: str, values, boundary: str = "") -> Aggregate:
    values = list(values)
    known, unknown = _split(values)
    if not known:
        return Aggregate(metric, NOT_SUPPORTED, 0, unknown, len(values), boundary or "no known value")
    return Aggregate(metric, sum(known), len(known), unknown, len(values), boundary)


def aggregate_mean(metric: str, values, boundary: str = "") -> Aggregate:
    values = list(values)
    known, unknown = _split(values)
    if not known:
        return Aggregate(metric, NOT_SUPPORTED, 0, unknown, len(values), boundary or "no known value")
    return Aggregate(metric, sum(known) / len(known), len(known), unknown, len(values), boundary)


def aggregate_rate(metric: str, numerators, denominators, boundary: str = "") -> Aggregate:
    """A rate is unknown when either side has no known contribution."""
    numerators, denominators = list(numerators), list(denominators)
    if len(numerators) != len(denominators):
        raise ValueError("numerator and denominator populations must align")
    num_known, num_unknown = _split(numerators)
    den_known, den_unknown = _split(denominators)
    population = len(numerators)
    unknown = max(num_unknown, den_unknown)
    if not den_known or not num_known:
        return Aggregate(
            metric, NOT_SUPPORTED, min(len(num_known), len(den_known)), unknown, population,
            boundary or "denominator or numerator entirely unknown",
        )
    total_den = sum(den_known)
    if total_den == 0:
        return Aggregate(
            metric, NOT_SUPPORTED, len(den_known), unknown, population,
            boundary or "denominator sums to zero",
        )
    return Aggregate(
        metric, sum(num_known) / total_den, min(len(num_known), len(den_known)), unknown,
        population, boundary,
    )


def aggregate_percentile(metric: str, values, q: float, boundary: str = "") -> Aggregate:
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be within [0, 1]")
    values = list(values)
    known, unknown = _split(values)
    if not known:
        return Aggregate(metric, NOT_SUPPORTED, 0, unknown, len(values), boundary or "no known value")
    ordered = sorted(known)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return Aggregate(metric, ordered[idx], len(known), unknown, len(values), boundary)


def aggregate_count(metric: str, values, predicate=bool, boundary: str = "") -> Aggregate:
    """Counting is total: unknowns are counted as unknown, never as non-matches."""
    values = list(values)
    known, unknown = 0, 0
    matched = 0
    for value in values:
        if is_unknown(value):
            unknown += 1
            continue
        known += 1
        if predicate(value):
            matched += 1
    if known == 0:
        return Aggregate(metric, NOT_SUPPORTED, 0, unknown, len(values), boundary or "no known value")
    return Aggregate(metric, matched, known, unknown, len(values), boundary)


def roll_up(rows, spec) -> dict:
    """Aggregate a table of counted-unit rows. Unknowns propagate per metric."""
    rows = list(rows)
    out = {}
    for metric, how in spec.items():
        column = [row.get(metric, NOT_SUPPORTED) for row in rows]
        if how == "sum":
            out[metric] = aggregate_sum(metric, column).as_row()
        elif how == "mean":
            out[metric] = aggregate_mean(metric, column).as_row()
        elif how == "p95":
            out[metric] = aggregate_percentile(metric, column, 0.95).as_row()
        elif how == "count_true":
            out[metric] = aggregate_count(metric, column).as_row()
        else:
            raise ValueError(f"unknown aggregation {how!r}")
    return out
