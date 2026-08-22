# po03-wa-b2e7-026-provenance-chain

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

Every counted result traces back to its immutable task input and acceptance
contract by hash.

## Executable component

`provenance_walker.py` walks every slot under
`workstreams/po03/attempts/<task_id>/`, either in the working tree or at an
immutable commit, and roots each result against
`workstreams/po03/control/tasks/<task_id>/`.

Rooting is a measurement, not a restatement. The walker hashes `input.json` and
`acceptance.json` itself and compares against the result's claims. Unrooted
classes reported: `ORPHAN_SLOT`, `EMPTY_SLOT`, `NO_TASK_ID`, `SLOT_MISMATCH`,
`CAPSULE_MISSING`, `ACCEPTANCE_MISSING`, `INPUT_HASH_MISMATCH`,
`ACCEPTANCE_HASH_MISMATCH`, `CAPSULE_SELF_INCONSISTENT`,
`CAPSULE_TASK_ID_MISMATCH`, `COMMISSION_MISMATCH`, `OWNERSHIP_SLOT_MISMATCH`,
`ATTEMPT_BINDING_MISMATCH`, `EVENT_CHAIN_MISSING`, `MANIFEST_MISSING`,
`MANIFEST_TASK_ID_MISMATCH`, `ARTIFACT_UNROOTED`, `ARTIFACT_UNCOVERED`,
`PRODUCER_CLAIMED_COMPLETION`, `SELF_ACCEPTANCE`, `NO_SUCH_SLOT`,
`NO_SLOTS_FOUND`.

Exit status is 0 only when every walked slot is rooted with no findings.

## Verdict

PASS. Walking commit `8791ceae84b9687b8601b45cfd09ec3e1271ed73` roots the one
committed result present at that time,
`po03-wa-b2e7-025-manifest-generator-verifier`, with measured input hash
`ad71ccbd4d660c0f17f0a4abc785953f16e59b28c9b76bb075b5cf51d5968e91` and measured
acceptance hash
`cb35f44be1607bd5dd19b59fe19db9b03b5d81451bd666519fb052e48ed25fd8`, and exits 0.

## Findings worth recording

1. **The emitter copies the acceptance hash; it never measures it.**
   `workstreams/po03/tools/emit_result.py` sets
   `acceptance_contract_sha256` from `capsule["source_hashes"]`, so a result can
   carry an acceptance hash that no process ever compared against
   `acceptance.json`. The walker measures the acceptance bytes directly and also
   cross-checks the capsule's self-declared value, which is what
   `CAPSULE_SELF_INCONSISTENT` exists to catch.
2. **Measured across all 65 frozen capsules in the repository, that declared
   hash is currently correct.**
   `test_live_capsules_declare_the_acceptance_hash_their_bytes_actually_have`
   asserts it for every capsule rather than for this cohort's eight, so the
   check is a regression guard and not an anecdote.
3. **An in-flight slot is correctly reported as unrooted.** A working-tree walk
   during this unit's own execution reported
   `ORPHAN_SLOT slot=workstreams/po03/attempts/po03-wa-b2e7-026-provenance-chain artifacts=2 result=absent`
   and exited 1, while the same walk at the immutable commit exited 0. The two
   answers differ because a working tree is not a commit, which is the property
   the guard should have.

## Observed limitations

1. Rooting is relative to the capsule bytes present at walk time. If a capsule
   and every result that cites it were rewritten together, the walk would still
   report ROOTED. Detecting that requires an anchor outside the pair, of which
   the repository holds two: the capsule's `controller_head_sha` and the
   hash-chained event files under `control/events/<task_id>/`. This walker
   checks only that the event chain is non-empty; verifying the chain itself is
   unit 030's subject.
2. `ARTIFACT_UNCOVERED` compares the manifest against files in the walked
   source. The generated `manifest.json` and `result.json` are excluded by
   name, matching the emitter's own exclusion, so a payload file named
   `manifest.json` anywhere in a slot would not be counted here either. That
   exclusion-by-basename is exercised adversarially in unit 032.
3. The walker cannot tell a legitimately in-flight slot from an abandoned one.
   Both appear as `ORPHAN_SLOT`. Distinguishing them needs lease state from
   `control/`, which is the controller's to read, not a producer's to write.
