# LAUNCH — pack 10 · economics-measurement

## Entry point

```bash
cd 10-economics-measurement
python3 test_pack.py
python3 checks.py <workdir>
```

```python
import checks, state_machine as sm
from _spine import AcceptanceGate, IndependentAcceptor

run = sm.EconomicsMeasurementRun(workdir, "operator-10", gate, campaign_id="CAMP-1")

run.preflight({"cfg-a": 660_000, "cfg-b": 440_000})   # declared spend, micro-USD
run.recover_state()
run.admit(cost_events, work_units)   # INPUT_ADMITTED - where bad data is refused
run.measure()                        # ACTION_EXECUTED
report = run.publish()               # REQUIRED_ARTEFACTS_PRESENT
run.machine_checks()                 # MACHINE_CHECKS_PASSED  <-- producer stops here
# COMMIT-FIRST ACCEPTANCE - REQUIRES AN INDEPENDENT METER
import acceptance
from _spine import AttestedAcceptance, CommitFirstAcceptor
objective = acceptance.objective_for("CAMP-1", declared_totals,
                                     meter_path="/var/obzio/billing.json")
acc = CommitFirstAcceptor("acceptor-QA", gate,
                          derive=acceptance.derive_expectation,
                          compare=acceptance.compare_to_expectation)
run.finish(acc, objective)

# NO METER? Then there is nothing to derive from, and the pack says so:
#   objective = acceptance.objective_for("CAMP-1", declared_totals)  # meter=None
#   run.finish(acc, objective)   -> NoIndependentExpectation
#   run.finish_attested(AttestedAcceptance("cfo-human", gate), objective,
#                       "reviewed the invoice by hand")
# which stamps acceptance_machine_enforced=false into the return state.
```

## What counts as what

Every cost event carries a `basis`. Each basis is in exactly one class, and the
sets are closed — an unrecognised basis raises rather than landing in "other".

| MODEL | HARNESS |
|---|---|
| `input_tokens` | `orchestration_tokens` |
| `output_tokens` | `scaffold_tokens` |
| `reasoning_tokens` | `tool_invocation` |
| `cache_read_tokens` | `retry_overhead` |
| `cache_write_tokens` | `verification_pass` |
| | `acceptance_review` |
| | `infra_seconds` |
| | `human_review_seconds` |

The line is: **would this cost exist if the model had got it right first
time?** Tokens in the work call are MODEL. Tokens the scaffold spends deciding
whether to call again are HARNESS. Reviewer time is HARNESS. Retries are
HARNESS, including the model tokens burned inside a retry loop if your
accounting can separate them — if it cannot, say so in `detail`, because that
ambiguity is the one that flatters weak models.

All amounts are integer micro-USD. Nothing accumulates in floating point.

## Reading the output

| Metric | What it tells you |
|---|---|
| `cost_per_accepted_micro` | the honest headline. `None` when nothing was accepted. |
| `model_per_accepted_micro` | the number on the invoice. **Never quote it alone.** |
| `harness_amplification` | harness ÷ model. High means the scaffold is doing the work. |
| `harness_share` | harness ÷ total. |
| `first_pass_yield` | accepted-on-first-attempt ÷ attempted. A money-free read on model strength. |
| `attempts_per_accepted` | how many tries a unit costs. |
| `comparisons[].verdict` | `NOT_COMPARABLE` means the two configs do not share a harness and raw cost/unit is not a fair fight. |
| `comparisons[].normalised_*` | both configs re-scored against a pooled reference harness cost per attempt. |
| `comparisons[].model_only_is_misleading` | `true` when the model-only ranking disagrees with the total-cost ranking. |

**`cost_per_accepted_micro` is `None`, not infinity, and not cost per attempt.**
A config that accepted nothing has no cost per accepted unit. Anything that
renders it must render "undefined".

## Mandate

Measure cost per accepted work unit across configurations, with model cost and
harness cost separated, and refuse comparisons that are not like-for-like.

## Maximum delegated authority

| | |
|---|---|
| May | classify a cost event against the declared basis sets; compute; refuse |
| May not | invent a basis; publish with unreconciled spend; divide by attempts when accepted is zero; count a self-accepted unit; rank configs whose amplification differs beyond threshold without also showing the equal-harness re-scoring |
| Phase reachable alone | `MACHINE_CHECKS_PASSED` |
| Procurement decisions | out of scope. This pack produces the number. It does not choose the vendor. |

## Escalate, do not improvise

- `UnattributedCost` — a basis nobody classified. Do **not** add it to a set to
  make the error go away without deciding which class it belongs to; that
  decision is the whole measurement.
- `UnreconciledSpend` — the events do not add up to what was spent. The gap is
  named in micro-USD. Find it before publishing anything.
- `NOT_COMPARABLE` recurring across a whole evaluation — you are comparing
  harnesses, not models. Re-run the weaker config in the stronger harness, or
  quote both components and no single ranking.
