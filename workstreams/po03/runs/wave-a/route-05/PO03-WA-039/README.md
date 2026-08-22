# PO03-WA-039 — Concurrent writers with disjoint ownership cannot collide silently

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Concurrent writers with disjoint ownership cannot collide silently.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-039/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-039-1` / `1`
- **Acceptance contract SHA-256:** `0a073bb2edcffda1b5a0d67237fffd1d4d293379b56fdc07e922d89a6886c59b`
- **Immutable input capsule SHA-256:** `52ffd7986b0a42370f6342ac40e1960e323f2faf0fc10fddfb807e4694967291`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

An ownership arbiter that tests the disjointness claim at both moments that
matter. Statically, `detect_claim_overlaps` compares declared prefix claims
pairwise and treats nesting as overlap, so a claim on a route and a claim on a
task inside that route are correctly reported as non-disjoint. Dynamically,
`ArbitratedWriter.write` refuses any target outside the writer's own claim and
creates the target by staging to a sibling temporary file and linking it into
place, so exclusive creation and content commit are the same event. The loser of
a race gets `COLLISION_DETECTED` rather than silently overwriting the winner.

## Adversarial case

Concurrency is real, not simulated: eight threads are released simultaneously by
a `threading.Barrier` and the contested case is repeated 25 times so a single
lucky interleaving cannot produce a green result. A control test runs the same
eight-way race using ordinary `write_bytes`, where every writer believes it
succeeded and only one payload survives - the silent collision this component
exists to prevent.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-039/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/disjoint_writer_arbiter.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

22 unit tests pass. Across 25 repetitions of the eight-way contested race there
is always exactly one `WRITTEN` and seven `COLLISION_DETECTED`, and the file on
disk always holds the winner's payload. Eight disjoint writers all succeed
concurrently with each file holding its own writer's bytes. The eight real Wave A
route claims are reported disjoint; adding a task-level claim nested inside
route-05 reports `NESTED_CLAIM`, and a duplicate route claim reports
`IDENTICAL_CLAIM`. No staging temporaries are left behind after a collision.

## Limitations

`os.link` gives exclusive creation semantics on POSIX filesystems; on filesystems
without hard-link support, or across NFS clients with attribute caching, that
guarantee weakens. The arbiter protects file creation, not concurrent
modification of an existing file, and it protects paths, not git index or ref
updates, which have their own locking. Claim overlap detection is prefix-based
and does not interpret glob wildcards beyond a trailing `/**`.

## Disposition

**PASS** — the hypothesis holds under repeated real concurrency, and the control case establishes that the default behaviour it replaces is genuinely silent.

## Artifacts

`manifest.json` lists every file in this slot with its SHA-256 and byte count.
`result.json` is the transactional result record for this attempt and conforms
to `workstreams/po03/contracts/transactional-result.schema.json`.

## Transactional state

| Field | Value |
| --- | --- |
| Provider state | `RUNNING` (provider state is tracked separately from Obzio state) |
| Obzio state | `RESULT_STAGED` |
| Producer terminal report | `READY_TO_COMMIT` — the producer ceiling for this lease |
| Completion actor | `null` — only the coordinator may record completion |
| Independent acceptance | `NOT_TESTED` — the producer does not self-accept |
| `decision_changed` | `[]` |

This attempt is not COMPLETED and not ACCEPTED. Independent assurance and
coordinator ingestion are separate acts performed outside this result slot.
