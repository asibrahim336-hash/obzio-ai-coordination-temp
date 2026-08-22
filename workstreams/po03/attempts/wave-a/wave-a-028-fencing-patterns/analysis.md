# Attempt analysis

## Outcome

`SUPPORTED_WITH_BOUNDARIES`

The frozen hypothesis is supported: concrete fencing-token edge cases belong in
fault fixtures, and six such cases are executable in this result slot. The
strongest finding is that “monotonic token” is necessary but underspecified.
Correctness also depends on where and when the token is validated.

## Mechanism result

`fencing_model.py` provides:

- `FencedLedger`, a safe reference model that atomically validates current
  ownership and next ledger sequence;
- an explicitly unsafe split-validation append used only to reproduce a
  stale-owner write;
- `HighestSeenFenceSink`, a common max-observed-token rule used to expose its
  ordering boundary;
- exact idempotent replay handling that produces no second write;
- strict monotonic transfer checks that reject token equality and rollback.

`fixtures/fencing-edge-cases.json` freezes expected observations.
`run_fixtures.py` executes all cases with standard-library Python and returns
nonzero if any observation differs. `tests/test_fencing_model.py` independently
asserts the model invariants.

## Findings

1. A stale owner can write when ownership is checked before a transfer and the
   eventual append checks only ledger sequence.
2. Supplying the correct next ledger sequence does not prove current ownership.
3. Supplying the current owner and fence does not prove a ledger position is
   valid.
4. Fence equality or decrease at transfer is an ABA/rollback hazard and must be
   rejected. Strict increase need not mean contiguous increase.
5. A max-observed-token sink has an observation gap: before a newer token
   arrives, a distinct write carrying the old equal token is accepted.
6. Treating all equal-token calls as stale breaks legitimate repeated writes
   under one ownership period. Idempotency identity and payload agreement are
   needed to make an exact replay harmless.

## Recommended fault-fixture assertions

Retain the six frozen cases and require all of these independent assertions:

- transfer token is greater than durable prior high-water;
- new side effects validate current owner and exact fence at their commit
  boundary;
- ledger append validates exact next sequence separately;
- external targets participate in token validation;
- an exact operation replay returns its original receipt without a new effect;
- changed content under a reused operation identifier is rejected.

Where a target can only track its locally observed token high-water, add a
fixture in which the stale write arrives before the first new-owner write. Do
not infer immediate fencing from a test that orders the new token first.

## Disposition

The fixtures and reference model are retained as an isolated PO-03 candidate.
No shared controller, production system, workflow or strategy was changed.
Independent acceptance remains pending.
