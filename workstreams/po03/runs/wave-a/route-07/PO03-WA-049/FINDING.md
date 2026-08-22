# PO03-WA-049 — provider, Obzio and acceptance completion are three separate axes

- Task: `PO03-WA-049`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Frozen evaluators distinguish provider, Obzio, and acceptance completion.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`completion_semantics.py` models completion as three orthogonal lattices rather
than one status string:

- **provider** — an observation of the provider runtime (`QUEUED`…`UNKNOWN`);
- **Obzio custody** — the durable lifecycle state, valid only when a verified
  result commit backs it;
- **independent acceptance** — a decision belonging to a different producer.

`classify()` returns the state the *evidence* supports, not the state that was
asserted. `is_complete(triple, axis)` answers exactly one axis and refuses a
bare string selector. `provider_completion_implies_obzio_completion()` exists
only to raise `AxisConfusion`: the conflation it names is the one the commission
forbids, so the codebase carries an executable refusal rather than a comment.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 17 tests — OK
```

The full transcript is in `evidence/observed-output.txt`.

## Hidden and adversarial cases

`test_no_uncommitted_triple_can_reach_completed` sweeps the entire
6 × 15 provider-by-custody grid with no durable commit id and asserts that not a
single combination classifies as `COMPLETED` — 90 generated cases rather than a
handful of examples. The frozen lost PO-02 Code-2 fixture (provider `COMPLETED`,
nothing durable) is asserted separately to reclassify to
`PROVIDER_COMPLETED_UNCOMMITTED`.

## Defect found while building

The first version of the enum-hygiene test asserted that `COMPLETED` was the only
name shared between the provider and Obzio vocabularies. Running it showed the
contract also reuses `RUNNING` and `CANCELLED` on both axes. That overlap is the
actual hazard — a bare state string cannot identify which axis is being asserted
— so the component refuses string axis selectors and the test now pins the real
three-name collision instead of an assumed one.

## Limitations

- The lattices are in-memory value objects; durability is asserted through the
  supplied `durable_result_commit_id`, not by reading a git object. Verifying
  that the commit exists is route-01's custody concern, not this component's.
- Acceptance authority is checked structurally (reviewer distinct from producer).
  Alias-resistant identity resolution is `PO03-WA-050`, deliberately not
  duplicated here.
- `NOT_SUPPORTED` is not modelled on these axes; unknown metric handling is
  `PO03-WA-053`.

## Disposition

**PASS** — the three axes are separately addressable, no uncommitted triple can
reach `COMPLETED`, and the conflation path raises rather than returns.
