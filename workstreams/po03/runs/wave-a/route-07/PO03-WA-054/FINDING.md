# PO03-WA-054 — blind review ordering is enforced, not merely asserted

- Task: `PO03-WA-054`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Blind review ordering prevents producer conclusions from changing criteria.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`review_order_gate.py` makes review order a checked property of a hash-chained,
append-only access ledger rather than a claim in a narrative.

Every source a reviewer opens is classified as `CRITERIA`, `TARGET_ARTIFACT` or
`PRODUCER_CONCLUSION` by a declared path policy. In the `CRITERIA_INTAKE` phase
only criteria may be opened; an attempt to open a finding, a producer
`result.json`, a run log, an observed-result document or a route ingestion
receipt raises `ReviewOrderViolation` — **and is still appended to the ledger as
`OPEN_DENIED`**, so the attempt cannot be erased by handling the exception.

`freeze_rubric()` advances the phase once and records the rubric digest.
`amend_rubric()` allows a correction only while no producer conclusion has been
opened, and requires a justification; after producer contact it refuses, because
that is precisely the contamination the hypothesis is about. `audit()` reports
whether the blind order held, which producer reads preceded the freeze, and
whether any amendment followed a producer read.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 20 tests — OK
```

## Hidden and adversarial cases

Six tamper attacks are run against the ledger: rewriting an entry, deleting an
entry, reordering two entries, replacing the genesis marker, and clearing the
entry list to hide an early producer read. Each must raise `LedgerTampering`.
The ordering attacks cover reading a finding before freeze, reading target code
before freeze, double-freezing, freezing outcomes before the rubric, and amending
the rubric after producer contact.

## Defect found while building

`test_hiding_an_early_producer_read_by_truncation_is_detected` initially failed:
clearing `entries` left `verify_chain()` with nothing to iterate, so a wholesale
truncation verified clean. The chain-length invariant
(`len(chain) == len(entries) + 1`) was added to the component. This is a real
defect the adversarial case found, not a test adjustment.

## Limitations

- The path policy is pattern-based. A producer conclusion stored under an
  unrecognised filename would classify as `TARGET_ARTIFACT`, which is still gated
  behind the freeze but is a weaker classification than it deserves.
- The ledger is in-process. It detects mutation of its own structure; it does not
  by itself prove that the reviewer used the gate for every read. Pairing it with
  a committed freeze artifact — as this route did at commit `353a78d` — is what
  makes the claim externally checkable.
- The gate cannot distinguish reading a target artifact from *understanding* it;
  it constrains order, not comprehension.

## Disposition

**PASS** — producer conclusions cannot be opened before the freeze, a post-contact
amendment is refused, and every attempt to hide either event in the ledger is
detected.
