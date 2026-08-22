# Wave A 033 — lost provider callback: reproduction and recovery classification

**Task:** `wave-a-033-lost-callback-reproduction`
**Function:** controlled-reproduction
**Frozen hypothesis:** *A lost provider callback leaves the task recoverable from immutable input and ledger state.*
**Dispatch base:** `e63fbae079774b151fd24a4132e4a5e571f75298`
**Branch:** `po03/wave-a-033-lost-callback-reproduction`
**Disposition:** producer result staged. Independent acceptance is **pending**; this attempt does not self-accept and does not claim Obzio completion.

## Verdict

| Claim | Outcome |
| --- | --- |
| Recovery **classification** from immutable input plus ledger alone | `PASS` |
| Provider state kept **distinct** from Obzio state | `PASS` |
| **Zero false completion** across the deliberately incorrect path | `PASS` |
| Lost unit **returns to execution** after a controller decision | `PASS` |
| **Automatic, time-bounded escalation** for a permanently lost callback | `NOT_YET` — refuted, see F1 |
| `RESULT_COMMITTED` commit identifier verified against Git at transition time | `FAIL` — see F2 |
| Documented idempotency-key replay tolerance | `FAIL` — see F3 |

Nine of twelve frozen predictions were confirmed exactly, one was confirmed with a
qualification, one was partially refuted and one was refuted outright. The
refutations are the substantive yield of this attempt.

## Method

The controller under test is the live mechanism
`workstreams/po03/tools/transactional_factory.py`, consumed **byte-for-byte from
immutable Git object bytes** at the dispatch base (`git cat-file blob`), never
from a working tree and never patched or monkey-patched. Each scenario
materialises its own throwaway Git repository containing only the pinned
mechanism and its contracts, then imports the factory from that copy so the
factory's own import-time root resolution binds to the sandbox. Faults are
injected exclusively through the factory's public API, so a passing assertion
cannot be an artefact of a reimplemented controller.

Nothing durable is written outside
`workstreams/po03/attempts/wave-a/wave-a-033-lost-callback-reproduction/**`.
Sandboxes live in `mkdtemp` directories and are disposable.

Lease expiry is made deterministic rather than raced: the harness reads the
recorded `LEASED` event's `observed_at` and the capsule's frozen `lease_seconds`,
computes the exact deadline the factory will compare against, and waits past it.
Still-valid-lease behaviour is tested with a separate 1800-second reservation
that reproduces the real capsule window, so both sides of the boundary are
exercised without depending on scheduling luck.

Determinism was checked by running the full injection three times and comparing
every asserted claim. All 84 claims matched on every pair. Two capsule digests
are excluded from that comparison because they hash a creation timestamp and the
sandbox's own commit SHA, which vary by construction; ledger self-consistency is
still asserted separately through the factory's chain verification, which
reported zero errors in every scenario.

## Fault classes exercised

### S1 — pre-provider reservation loss

The controller leases a reservation (`provider_run_id` prefixed `reservation:`)
and the dispatch callback is then dropped. No worker ever runs.

The controller classified this from immutable state alone as Obzio `LEASED`,
provider `NOT_DISPATCHED`, recovery action
`AWAIT_PROVIDER_ADMISSION_OR_LEASE_EXPIRY`, with the unit visible in the
recovery scan. Critically, provider state is **not** collapsed into Obzio state:
`_has_provider_execution_evidence` returned false, so a reservation is
structurally distinguishable from a running provider.

Recovery correctly refused to preempt a still-valid lease
(`undispatched recovery cannot preempt a still-valid reservation lease`) and
wrote no events. Once the frozen lease expired, the same call scheduled a retry,
moving the unit to `RETRY_SCHEDULED` with recovery action `RERUN_OR_RECONCILE`
while provider state remained `NOT_DISPATCHED`. A duplicate recovery callback
returned `ALREADY_RETRY_SCHEDULED` and appended **zero** new events. After
re-leasing at fence 2, the original worker's attempt to act at fence 1 was
rejected with `stale fence token 1; current is 2`.

### S2 — genuinely running provider, callback lost

A worker emitted a real `RUNNING` event carrying both `provider_task_id` and
`worker_agent_id`, mirroring this attempt's own admission event, and its return
message was then lost.

The controller classified this as Obzio `RUNNING`, provider `RUNNING`, recovery
action `MONITOR`, with provider execution evidence present. The strongest safety
result: with the lease **already expired**, undispatched recovery was still
rejected with `cannot recover as undispatched after provider execution
evidence`. The guard keys on provider evidence rather than on elapsed lease
time, so a live worker cannot be preempted as though it were an unclaimed
reservation. That is the specific confusion a lost callback invites, and the
mechanism resists it.

When provider transport then reported completion with nothing committed, the
controller recorded `PROVIDER_COMPLETED_UNCOMMITTED` with provider state
`COMPLETED`, recovery action `RERUN_OR_RECONCILE` and `result_commit_id` null.
Provider completion never became Obzio completion. The unit returned to
execution through `RECOVERY_REQUIRED → RETRY_SCHEDULED → LEASED` at fence 2, and
provider evidence survived that transfer rather than being rewritten to hide
that a provider had run.

### S3 — deliberately incorrect / false-completion path

Every illegal shortcut was rejected: `RUNNING → COMPLETED`,
`RUNNING → PARENT_INGESTED`, `PROVIDER_COMPLETED_UNCOMMITTED → COMPLETED` and a
producer attempting to complete its own work. Staging evidence requirements held
(`RESULT_STAGED` without a well-formed manifest hash, and `RESULT_VERIFIED`
without `parent_remote_readback=PASS`, were both refused). A forged result commit
could not reach `PARENT_INGESTED` or `COMPLETED`.

**No false completion was reachable by any route attempted.** The unit stranded
on a forged commit remained recoverable rather than stuck, which matters: fail-closed
must not mean fail-stuck.

### S4 — duplicate callback replay

Replaying the identical event bytes was idempotent: zero new events, bytes
unchanged. A conflicting payload at the same sequence was rejected
(`immutable file differs`) and left the original bytes intact. Replaying capsule
creation was harmless.

### S5 — escalation probe

Deliberately designed so the weakest half of the hypothesis could be refuted. It
was.

## Findings

### F1 — no automatic time-bounded escalation for a lost callback from a running provider (refutation of P12)

For a genuinely running provider whose callback is permanently lost, lease expiry
changes **nothing**. Classification before and after expiry was byte-identical;
the unit sits at Obzio `RUNNING`, provider `RUNNING`, recovery action `MONITOR`
indefinitely. No exposed subcommand escalates it. An AST scan of the pinned
mechanism shows `lease_seconds` and the lease deadline are consulted only in
`recover_undispatched_task`, `task_capsule`, `_task_capsule_locked` and
`activate` — never in `_recovery_action`, so the dispatched path has no
time-bounded route at all. `heartbeat_at` is present in the schema and the
initial record but is never written to a non-null value anywhere in the
mechanism, so there is no liveness signal to escalate from either.

The hypothesis as literally written still holds: the unit **is** recoverable from
immutable input and ledger state, and S2 demonstrates the full route back to
execution. But recovery requires a controller decision. It is not automatic, so
a lost callback from a running provider depends on someone noticing. Against the
commission's requirement that lost callbacks must replay, this is `NOT_YET`
rather than `PASS`.

### F2 — `RESULT_COMMITTED` accepts an unverifiable commit identifier (partial refutation of P9)

`_validate_transition_evidence` checks only that `result_commit_id` matches the
*shape* of a Git object ID. A well-formed but nonexistent commit
(`0000000000000000000000000000000000000001`) was accepted into the immutable
ledger, and the recovery projection then surfaced it as the unit's
`result_commit_id`. A recovery scanner consumer reading that field would believe
a durable result exists.

Blast radius is bounded and this is **not** a false completion: `PARENT_INGESTED`
independently revalidates and refused, and `ingest_committed_result` — which does
resolve the commit in Git — rejected the unit because ingestion requires `RUNNING`
custody. So terminal completion fails closed. The defect is a misleading
intermediate record, not an escaped completion. The natural repair is to resolve
the commit in Git at transition time rather than only at ingestion.

### F3 — documented idempotency-key replay tolerance is not implemented

`_advance_task_locked` documents that "a callback replay with an already-recorded
idempotency key is harmless when it names the same target state and event
payload." An AST scan confirms the function never reads an idempotency key. A
redelivered `RUNNING` callback from the same worker is rejected as
`invalid transition: RUNNING -> RUNNING` rather than recognised as the same
logical callback.

This is safe — nothing is corrupted and the ledger is untouched — but a worker
retrying a lost callback receives a hard error rather than an idempotent
acknowledgement, so the docstring overstates the guarantee. Byte-identical event
replay *is* idempotent (S4), so the protection exists at the file layer; it is
the logical-callback layer that is missing.

### F4 — fence validation is ordered after transition validation (qualification of P10)

In S1 the stale worker was rejected specifically for its fence token. In S2 the
equivalent attempt was rejected earlier, for an illegal transition, so the fence
guard was never reached. Both are fail-closed, but the fence check is not the
first line of defence, and a test that only exercised the S2 shape would report
fence protection it never actually observed. S1 is the clean demonstration.

### F5 — capsule source-hash drift (custody disclosure)

Three of four declared capsule source hashes reproduce byte-exactly from
immutable Git bytes at the dispatch base. The fourth,
`transaction_schema_sha256`, does **not** match any blob at the dispatch base.
It matches the *original seed* revision of
`workstreams/po03/contracts/transactional-result.schema.json` at commit
`ad154348`, which has since been superseded **three** times; the dispatch base
carries `91fb63c1...` at 5,251 bytes. The capsule also names the schema at
`contracts/transactional-result.schema.json`, which does not exist at either
revision — the file lives under `workstreams/po03/contracts/`.

Separately, the capsule declares controller head
`1bb843b2a81fd8d73617caf2f1db81909266bb6e`, but its own `input.json` and
`acceptance.json` **did not yet exist** at that commit; they were committed
later, and both verify byte-exactly at the dispatch base, 49 commits further on.

**Additive hardening disclosure:** the current controller carries additive
hardening committed after the capsule's historical head, and the controller
branch tip has advanced beyond the dispatch base as well. No capsule byte was
rewritten and nothing was narrowed; the drift is that the capsule pins a stale
schema digest and a stale path, so a consumer verifying strictly against the
declared value would report a mismatch it cannot resolve.

## Limitations

Recorded in full in `limitations.json`. The material ones: this reproduces the
controller's classification logic in sandboxed repositories, not a live
multi-machine dispatch, so genuine network partition, provider-runtime loss and
concurrent controller restart are modelled through their ledger consequences
rather than induced physically. The "genuinely running provider" is genuine in
the sense the mechanism can detect — a real worker-emitted event carrying
provider execution evidence — but no second provider process was actually
spawned. Lease-expiry determinism depends on whole-second timestamp truncation in
the mechanism. F1's absence claim rests on exhausting the exposed subcommands
plus an AST scan of the pinned source, which is strong evidence of absence but
not a proof.

## Requested versus observed runtime

Requested `claude-opus-5` at high thinking. The parent cloud run reports
`originalModelName: gpt-5.6-sol-max-fast`, and no exposed API returns a subagent's
own model identifier, so the exact model that executed this attempt is
`NOT_SUPPORTED` as machine-observed evidence. Recorded verbatim in
`runtime-binding.json` without invented fields.
