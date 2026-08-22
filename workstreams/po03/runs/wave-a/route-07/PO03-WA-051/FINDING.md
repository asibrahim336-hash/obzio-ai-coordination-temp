# PO03-WA-051 — hidden cases cover every legal transition and every prohibited skip

- Task: `PO03-WA-051`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Hidden cases cover every legal state transition and every prohibited skip.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`transition_oracle.py` is a **case oracle**, not another state machine. It takes
the custody lifecycle named by the commission
(`CREATED → LEASED → RUNNING → CHECKPOINTED* → RESULT_STAGING → RESULT_STAGED →
RESULT_VERIFIED → RESULT_COMMITTED → PARENT_INGESTED → COMPLETED`) plus the five
fault states, and classifies the **complete** 15 × 15 ordered product into
`LEGAL`, `SKIP`, `REVERSAL`, `SELF` and `UNREACHABLE`. Coverage is therefore a
checkable property: an omitted transition shows up as an unclassified pair, and
`classify_pair` raises rather than defaulting.

`falsify(fsm_accepts)` runs all 225 cases against any caller-supplied transition
predicate, so the oracle can falsify a custody implementation it did not write.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 19 tests — OK
```

## Hidden and adversarial cases

- Every ordered pair is asserted present exactly once and the legal/prohibited
  sets are asserted to partition the space.
- Every forward skip over the happy path is asserted prohibited, with the
  staging bypass (`RUNNING → RESULT_COMMITTED`) additionally required to name
  `RESULT_STAGED` and `RESULT_VERIFIED` in its reason.
- Three adversarial implementations are run through `falsify`: an
  always-accepting one (must report every prohibited case as a false accept), an
  always-refusing one, and a faithful one carrying exactly **one** smuggled skip
  — the oracle must isolate that single edge and no other.
- An implementation that raises is treated as refusing, so a crash can never be
  scored as acceptance.

## Defect found while building

The first prohibition test asserted that every backwards edge classifies as
`REVERSAL`. Nine subtests failed because edges leaving `COMPLETED` are
`UNREACHABLE` first — terminality dominates direction. The classifier was
correct and the test was wrong; it now asserts the prohibition and the specific
verdict that applies, which documents the precedence instead of hiding it.

## Limitations

- The graph is derived from the commission text and the contract enum. If the
  lifecycle is amended, the oracle must be re-derived; it does not read the
  schema at runtime.
- `enumerate_paths` is bounded (default length 4). It demonstrates that no legal
  path reaches `COMPLETED` within three steps, but it is not an unbounded model
  check.
- Recovery resumption points are a declared table. They encode the commission's
  "resume from immutable input" rule; a different recovery policy would need a
  different table, not a code change.

## Disposition

**PASS** — all 225 ordered pairs are classified exactly once, every skip and
reversal is prohibited, and the oracle isolates a single smuggled illegal edge.
