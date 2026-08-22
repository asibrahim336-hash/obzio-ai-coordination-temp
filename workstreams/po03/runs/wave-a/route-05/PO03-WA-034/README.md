# PO03-WA-034 — Symlink indirection cannot bypass the write allowlist

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Symlink indirection cannot bypass the PO-03 write allowlist.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-034/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-034-1` / `1`
- **Acceptance contract SHA-256:** `f831e6aeffb977996303511653bfd1cc127e6a0214c48f5fed5367d468fb705a`
- **Immutable input capsule SHA-256:** `651ff45d3970ebf25154e67077fbe7d096e3b4f5924e356ce26fd3424acc8f1c`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A filesystem-aware write guard for an owned subtree. It gates lexically first,
then walks every path component beneath the owned root looking for symlinks,
resolves the deepest existing ancestor with `realpath`, and requires the result
to stay inside the physically resolved root. The owned root itself is resolved
once so a guard rooted on a symlinked directory still compares like with like.
Link chains are followed one hop at a time so a cycle surfaces as its own
verdict, and a dangling final component is rejected because containment of a
non-existent target cannot be asserted. The write path uses `O_NOFOLLOW` so the
residual window on the final component is closed at the syscall.

## Adversarial case

Six bypass shapes are exercised against a fixture containing an `owned` tree and
an `outside` tree holding a victim file: final-component symlink to the victim,
directory symlink as an ancestor, a deeper nested ancestor symlink, a two-hop
symlink chain, a relative `../outside` symlink, a dangling symlink and a symlink
loop. A control test performs the same write without the guard and shows the
victim file being corrupted, so the guard's refusal is not vacuous.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-034/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/symlink_resolution_guard.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

18 unit tests pass. Every bypass shape is rejected with a distinguishing verdict
(`REJECTED_SYMLINK_ESCAPE`, `REJECTED_ANCESTOR_SYMLINK_ESCAPE`,
`REJECTED_DANGLING_SYMLINK`, `REJECTED_SYMLINK_LOOP`). After each refused write
the victim file still reads `ORIGINAL` and the outside directory listing is
unchanged, while the unguarded control writes `CORRUPTED` through the same
symlink. A symlink pointing back inside the owned root is admitted.

## Limitations

Resolution and the subsequent write are separate syscalls, so a sufficiently
fast adversary with write access to the intermediate directories retains a
narrow TOCTOU window; `O_NOFOLLOW` closes it for the final component only. Full
closure needs `openat2(RESOLVE_BENEATH)`, which is Linux-specific and not
exposed by the standard library. Hard links are out of scope: they are
indistinguishable from the original file by path resolution alone.

## Disposition

**PASS** — the hypothesis holds for symlink indirection; the TOCTOU and hard-link residuals are recorded above rather than claimed as covered.

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
