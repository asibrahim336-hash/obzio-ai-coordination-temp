# PO03-WA-040 — A shared-path write without controller identity fails before commit

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** A shared-path write without controller identity fails before commit.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-040/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-040-1` / `1`
- **Acceptance contract SHA-256:** `077bf8cebb18595bb491ee0748f239e7da30060838d240ed949cb57f9edb4a28`
- **Immutable input capsule SHA-256:** `8b52266365e906e50b8fbd1a37bf165cdb0d7a7c37fc2379784f10f78a68e72a`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A two-phase staging gate implementing the PO-03 shared-path rule. `stage` records
an intended write and touches nothing, `precommit_check` returns a decision over
the whole staged set, and only `commit` applies it. Shared paths - the control
ledgers, metrics, evidence, successor state, receipts and the `po03-*` workflow
files - admit only the controller identity, and identity is presented as
`(actor_id, fence_token)` so a writer claiming the controller's id without its
current fence token is still refused. Route workers are confined to their own
subtree, and anything outside the PO-03 allowlist entirely gets its own verdict.

## Adversarial case

The temporal claim is what is tested: for every refusal the test asserts the
target file does not exist on disk afterwards. Three fail-closed paths are
exercised. Calling `commit` without a check raises `GateNotCheckedError`; a
staged set containing one violation refuses the whole batch, leaving even the
legitimate write unapplied; and a time-of-check/time-of-use attack that swaps the
staged set behind the API after a passing check is caught by the staged-set
digest and raises `StagedSetChangedError`.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-040/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/shared_path_controller_gate.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

23 unit tests pass. A worker staging `control/leases/route-05.json` is refused
with `REJECTED_NOT_CONTROLLER` and the file is absent afterwards; the controller
id with a stale fence token is refused with `REJECTED_STALE_FENCE`; a sibling
route gives `REJECTED_OUTSIDE_OWNED_SUBTREE` and `docs/roadmap.md` gives
`REJECTED_OUTSIDE_ALLOWLIST`. After `precommit_check` and before `commit` the
root directory is still empty. The controller with the current fence token
writes the shared path successfully, and the worker writes its own slot
successfully.

## Limitations

The gate enforces identity as presented to it; it does not authenticate the
caller, so it is a control on an honest-but-careless producer and on ordering
mistakes, not a defence against a hostile process that can call the API with
arbitrary arguments. Fence-token currency is supplied by the caller rather than
read from a lease authority. The TOCTOU digest closes the window between check
and commit, not between commit and any later external mutation of the files.

## Disposition

**PASS** — the hypothesis holds: the refusal is observable before commit, with the target absent from disk after every rejected attempt.

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
