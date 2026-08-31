# Independent PO-02 / PO-03 evaluation — 2026-08-22T09:32Z

Evaluator: `SCF-01/CGPT-01`, distinct from the producer branches. Read-only source
scope. No producer branch, PR #9, PO-01, merge or promotion was mutated.

## PO-02 candidate

Immutable source: PR #5 head
`9696c325f0897b7c9e7ff2cd9d57fc7c4bb19e27`, five-file work-unit contract.
The exact forced-interruption executable reported eight kill positions PASS,
tamper-evident ledger PASS and contract-seal PASS in a clean local process.

Disposition: `CANDIDATE / CORE_RECOVERY_TEST_PASS / NOT_ACCEPTED_AS_COMPLETE`.

Limits: the effect sink is an in-process reconstruction rather than a real external
side-effect adapter; only the work-unit contract module is present; the wider
PO-02 modules and raw provider denominator are missing. It is worth ingesting as a
candidate recovery primitive, not as completed PO-02.

## PO-03 outputs

Observed PR #9 head at evaluation start:
`4949d1a5ee8ea21177aa48740c08ef45ac63000e`, 78 commits, 443 files.
Five remotely visible top-level parent factories duplicate seven foundation paths
and use incompatible denominators/acceptance definitions. A full best-of-eight race
has no frozen common comparison and is not justified.

Artifact-level dispositions:

- `wave-a-022` recovery reproduction: seven executable tests PASS, including a
  deliberately losing stale-snapshot schedule and passing locked/atomic recovery.
  `CANDIDATE / REPRODUCTION_PASS / INTEGRATION_ACCEPTANCE_PENDING`.
- route-isolation evidence: two same-host fresh-clone canaries were independently
  accepted with limitations. It proves only that route at width two; result-ref
  fencing remains open and PO-03 remains unaccepted.
- parent outputs: retain immutable custody; deduplicate and route through the frozen
  cross-parent matrix before ingestion. Producer acceptance counts remain
  observations until replayed by a different parent.

Capacity is a route tuple, not one account number: current PR9 route safe width two;
the `6e19` runtime observed a three-new-VM admission ceiling; the `ed20` runtime
proved at least ten background subagents in exclusive worktrees. Account-global
quota and the effect of a second Cursor group are unknown until CUR-01 records its
own telemetry. CUR-01 must therefore harvest/qualify rather than create a ninth
factory and throttle its active parent width if the provider queues existing PO-03
parents.

Owned next evaluation work is constituted in ChatGPT lanes CGPT-03 and CGPT-04; it
is no longer a `NOT_YET` row.

