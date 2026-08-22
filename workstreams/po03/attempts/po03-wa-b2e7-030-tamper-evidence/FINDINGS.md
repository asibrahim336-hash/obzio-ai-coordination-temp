# po03-wa-b2e7-030-tamper-evidence

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

Mutating a committed artifact after the fact breaks the manifest and the event
hash chain.

## Verdict: PASS for mutation, with two tested gaps recorded

All 15 tamper cases behaved as predicted:
`PO03_TAMPER_PASS cases=15 detected=9 clean=4 known_undetected=2`, exit 0.
Nine mutations were caught, four pristine states verified clean, and two
specific tamper shapes were confirmed *not* to be caught.

## Executable component

`tamper_harness.py` exercises the live mechanisms, not models of them:
the manifests `emit_result.py` wrote, and `verify_chain` imported from
`workstreams/po03/tools/transactional_factory.py` with its module roots
repointed at a scratch tree. Nothing in the repository is modified: artifacts
are materialised into a scratch directory before corruption and event chains are
copied before tampering, which two tests assert by comparing
`git status --porcelain`, `HEAD` and the SHA-256 of the live event files before
and after a full run.

## Mutations that are caught

| case | mechanism | what it proves |
| --- | --- | --- |
| `materialised-artifact-single-byte-flipped` | manifest | one flipped byte changes the SHA-256 |
| `materialised-artifact-truncated` | manifest | truncation changes the byte count as well as the hash |
| `manifest-entry-rewritten-breaks-the-result-hash` | result document | rewriting an entry breaks `result_transaction.manifest_sha256` |
| `event-body-mutated` | `verify_chain` | `event hash mismatch` plus `previous hash mismatch` on the successor |
| `single-byte-flip-preserving-length` | `verify_chain` | detection does not depend on a size change (388 bytes before and after) |
| `middle-event-deleted` | `verify_chain` | `non-monotonic sequence` |
| `self-hash-overwritten` | `verify_chain` | an event cannot vouch for itself |
| `previous-link-rewritten-and-self-hash-recomputed` | `verify_chain` | recomputing the event's own hash cannot repair the link to its predecessor's *file* hash |
| `live-chain-copy-tampered:po03-canary-001` | `verify_chain` | a copy of a real committed chain verifies clean, then fails once one `actor` field is edited |

## Two gaps, confirmed by execution

1. **`tail-event-deleted` is undetected.** Deleting the last event leaves a
   chain that is internally consistent: sequences still start at 1 and every
   `previous_event_sha256` still matches. `verify_chain` returns `[]`. Nothing
   in the chain records its own expected head, so truncation is invisible to the
   verifier. Closing it needs an external anchor, for example the head event
   hash recorded in the result document or in a signed receipt.
2. **`forged-event-appended-with-correct-links` is undetected.** Appending a new
   event with `hash_chain_event` itself produces a chain that verifies. A hash
   chain constrains *order*, not *authorship*, so any actor able to write under
   `control/events/` can extend history. Closing it needs a signature or a
   write-authority boundary, neither of which a producer may install.

Both are asserted as gaps by tests that fail if the behaviour ever changes, so
the record cannot silently rot into a false claim of strength.

## Related finding: git makes "mutating a committed artifact" impossible in place

`committed-bytes-unchanged-by-working-copy-tampering` corrupts the working copy
and then re-reads the same blob with `git cat-file`, which returns the original
bytes and the original hash (`identical=True`). A committed artifact cannot be
edited in place at all; an attacker must either rewrite history, which produces
different object ids and therefore breaks every `git:<commit>:<path>` locator in
the manifest, or add a new commit, which leaves the manifest's locator pointing
at the original bytes. The manifest's strength here comes from git's content
addressing as much as from the recorded hash.

## Audit of live custody

`test_every_live_event_chain_verifies_under_the_real_verifier` copies all event
directories the repository holds into a scratch tree and runs the real
`verify_chain` against every one. Every chain verified with no errors. A second
test tampers with five of those copies and asserts each then fails.

Tests: 24, OK.

## Observed limitations

1. The harness must repoint the factory module's `REPO_ROOT`, `PO03_ROOT`,
   `CONTROL_ROOT` and `RECEIPT_ROOT` after import, because those are computed at
   module level from `__file__`. That is why the real verifier can be aimed at
   scratch bytes, but it also means the harness is coupled to those four names.
2. Detection of a manifest mutation is demonstrated by measurement, not by
   invoking a gate. Unit 029's `coverage_assert.py` is the gate that would refuse
   such a manifest in CI, and unit 025's verifier is the equivalent for
   `PO03-MANIFEST-v1` documents.
3. Only the first artifact of the chosen slot is corrupted, and the chosen slot
   is the first with a manifest. The tamper classes are properties of hashing
   rather than of a particular file, but a broader sweep would cost one `git
   cat-file` per artifact.
