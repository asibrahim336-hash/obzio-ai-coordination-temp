"""PO-03 transactional custody engine.

Cohort a1 owns the mechanisms that make false completion structurally
impossible rather than merely discouraged.  Every module here is
dependency-free standard-library Python so it runs identically in Cursor, in a
clean GitHub Actions runner and in a fresh clone with no warm cache, no
provider memory and no ``/tmp`` state.

The engine closes the causal defects recorded in
``workstreams/po03/evidence/so02-operating-correction.json``:

``ledger``          worker self-report can no longer represent completion; the
                    hash-chained append-only log plus a sealed head anchor is
                    the only source of truth.
``outbox``          at-least-once delivery becomes exactly-once effect, so a
                    lost or duplicated return message cannot create or destroy
                    an effect.
``lease``           leases, monotonic fence tokens, heartbeat renewal and
                    monotonic checkpoints; an evicted holder cannot commit and
                    an interrupted holder resumes instead of restarting.
``projection``      the work-unit registry is a pure projection, so losing it
                    loses no state.
``staging``         two-phase result staging makes a partial write
                    unobservable; there is no committed state with incomplete
                    bytes.
``artifact_store``  content addressing turns silent corruption into a loud,
                    named diagnostic.
``completion``      the Obzio state machine that structurally reserves
                    ``COMPLETED`` for the coordinator after verified ingestion.
"""

__all__ = [
    "artifact_store",
    "canonical",
    "completion",
    "ledger",
    "lease",
    "outbox",
    "projection",
    "staging",
]
