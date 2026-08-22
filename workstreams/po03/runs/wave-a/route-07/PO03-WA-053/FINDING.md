# PO03-WA-053 — NOT_SUPPORTED survives aggregation instead of becoming zero

- Task: `PO03-WA-053`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Unknown metric values remain NOT_SUPPORTED through aggregation.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`metric_aggregator.py` implements sum, mean, rate, percentile, count and a table
roll-up over the counted-unit rows described by
`workstreams/po03/metrics/metric-definitions.json`, where the declared unknown
value is `NOT_SUPPORTED`.

Two rules carry the hypothesis:

1. **Unknowns never enter arithmetic.** `numeric()` raises
   `MetricCoercionError` on any sentinel (`None`, `NOT_SUPPORTED`, `""`,
   `"N/A"`, `NaN`, …) instead of returning `0`. Zero and `0.0` are known values
   and are never confused with unknown.
2. **Every aggregate carries its coverage.** `Aggregate` exposes
   `known_count`, `unknown_count`, `population` and `coverage`, so a caller
   cannot read a number without also reading how much of the population it
   covers. When nothing is known the value is `NOT_SUPPORTED` and an observed
   boundary string is recorded, satisfying the commission rule to report the
   boundary rather than invent a value.

A rate is `NOT_SUPPORTED` when either side is entirely unknown *or* when the
known denominator sums to zero — that second case is the one that most often
gets silently reported as `0.0`.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 26 tests — OK
```

## Hidden and adversarial cases

`test_mean_is_over_known_values_only` pins the specific arithmetic a
zero-coercing implementation would produce (`10` instead of `15`) and asserts the
wrong answer is *not* returned. Each aggregation is additionally driven with an
all-unknown column, a mixed column, an empty population and a missing column, and
`NaN` is asserted never to leak into a result.

## Limitations

- Percentile uses nearest-rank on the known values with no interpolation. It is
  adequate for the p95 latency rows in the metric register and is not a general
  statistics implementation.
- Coverage is computed over the supplied population. If rows are missing from the
  input entirely, coverage cannot detect that; completeness of the row set is the
  measurement lane's responsibility.
- The unknown sentinel list is fixed. A new unknown spelling introduced upstream
  would be treated as a known string and refused by `numeric()` as non-numeric,
  which fails closed but reports a type error rather than a coverage gap.

## Disposition

**PASS** — every aggregation preserves `NOT_SUPPORTED`, no unknown is coerced to
zero, and each result reports its own coverage and observed boundary.
