# Fencing-pattern research

## Frozen hypothesis

`Fencing tokens have known edge cases that should appear in fault fixtures.`

The source claim is supported with boundaries. Strictly increasing ownership
tokens and target-side enforcement address stale-owner writes, but a token
allocator alone does not protect a write. Validation placement, atomicity,
target participation, token high-water durability, idempotency and ledger
ordering all matter.

## Sources read

1. Martin Kleppmann, “How to do distributed locking,” 8 February 2016,
   <https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html>
   (retrieved 2026-08-22).
   - The worked example assigns token 33, transfers ownership with token 34,
     processes 34 at the storage service, and then rejects 33.
   - The article explicitly requires the storage service to participate by
     remembering a higher token and rejecting a token that goes backwards.
   - It also requires the token source to be strictly monotonic.

2. Hazelcast, “Distributed Locks are Dead; Long Live Distributed Locks!”,
   <https://hazelcast.com/blog/long-live-distributed-locks/> (retrieved
   2026-08-22).
   - The article states that external services must participate in the
     fencing-token protocol before side effects.
   - It adds a stronger condition: the participating services need guaranteed
     linearizability for the combined invariant.
   - It reports testing both ownership behavior and fencing-token monotonicity.

3. Mike Burrows, “The Chubby lock service for loosely-coupled distributed
   systems,” OSDI 2006,
   <https://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf>
   (retrieved 2026-08-22; 117,687 bytes; SHA-256
   `0747c84a49d32744a2744e2f2951b05fb7a0829ce44afb0b700833eb2bb3ecdd`).
   - Section 2.4 describes lock sequencers that include a lock generation
     number and are passed to another server for validity checking.
   - This is evidence for checking a current ownership generation at the
     side-effect boundary, not treating successful acquisition as sufficient.

These sources establish the external pattern. The exact snapshot-versus-ledger
separation and observation-gap fixture below are deductions tested by this
attempt, not claims attributed to the sources.

## Concrete edge cases translated into fixtures

| Edge case | Deterministic fixture | Observation |
|---|---|---|
| Check and write are separate operations | `split-validation-stale-write` | The old snapshot validates before transfer; a later sequence-only append accepts the stale owner. The atomic current-snapshot path rejects it. |
| A ledger position is mistaken for ownership | `ledger-sequence-not-fence` | The old owner supplies the exact next sequence and is still rejected. |
| Ownership is mistaken for append ordering | `snapshot-not-ledger-sequence` | The current owner supplies an already-used sequence and is rejected independently. |
| Fence high-water rolls back or is reused | `monotonic-transfer` | Equal and lower transfer tokens are rejected; a greater non-contiguous token is valid. |
| A sink only remembers tokens it has seen | `highest-seen-observation-gap` | After authority transfers but before token 2 reaches the sink, a distinct token-1 write is accepted. Token 1 is rejected only after token 2 is observed. |
| Strict greater-than rejects legitimate retries, while equal accepts too much | `idempotent-replay-after-transfer` plus the observation-gap case | Equality is safe only when it is an exact idempotent replay or current ownership is also established. |

## Snapshot validation is not ledger-sequence validation

An ownership snapshot is a tuple such as `(owner-b, fence=2)`. It answers:
“Does this writer still own the right to create a new effect now?” Safe
validation compares that tuple with authoritative current state at the same
atomic boundary as the write.

A ledger sequence is an append position such as `2`. It answers: “Is this the
next append, rather than a duplicate, overwrite or gap?” It says nothing about
which owner is current. Conversely, a current owner can still propose a stale
ledger position.

The safe fixture therefore performs both checks under one local critical
section and emits different errors:

- `StaleOwnership` for current-snapshot failure;
- `LedgerSequenceMismatch` for append-order failure.

This separation matters operationally because retry and recovery code can then
react to the actual failed invariant rather than treating every mismatch as
lease expiry.

## Negative and refuting outcomes

- The broad claim “a sink that tracks the highest token rejects every stale
  write immediately after transfer” is refuted. It rejects lower tokens only
  after it has observed a higher token. The source worked example sends token
  34 before delayed token 33; the fixture makes the opposite ordering explicit.
- Requiring `token > highest_seen` for every write is not a general repair:
  multiple legitimate writes and exact retries can share one ownership token.
- A fence token does not protect any target that does not validate it.
- A pre-write snapshot check does not protect a later non-atomic write.
- A monotonic token in volatile memory is not enough after rollback or restore;
  the high-water must not regress.

No networked system was probed. Research was read-only, and the reproduction is
a local deterministic reference model.
