# Independent acceptance request — CUR-ORCH-QUAL-01

**Requested by:** `SCF-01/CUR-01`, run `bc-c6f63d58-9611-495a-96f6-2f2dcbef696d`
**State:** `REQUESTED_NOT_GRANTED`
**Producer self-acceptance:** prohibited and not performed
**decision_changed:** `[]`

The producing run cannot accept its own work. This sheet exists so an
independent actor can accept or refuse the route qualification without asking
the producer for anything and without asking the founder to retrieve or compare
results.

## Who may accept

Any actor that did not produce this evidence: a different runtime, a different
model family, or a human reviewer. The Cursor account already runs Claude and
GPT families concurrently, so a cross-family evaluator is available.

The acceptor must not be run `bc-c6f63d58-9611-495a-96f6-2f2dcbef696d`. The
validator rejects a register whose acceptor equals the producing run.

## What to run

Everything below is replayable from a clean clone at the immutable commit, with
no provider access, no credentials and no network.

```bash
git clone https://github.com/asibrahim336-hash/obzio-ai-coordination-temp
cd obzio-ai-coordination-temp
git checkout cursor/so02-cur-orch-qual-01

python -I workstreams/so02/control-plane/tools/scctl.py validate
python -I workstreams/so02/control-plane/tools/orchqual.py verify
python -I -m unittest discover -s workstreams/so02/control-plane/tests -p "test_*.py" -v
```

To re-perform the live custody check rather than trusting the recorded one:

```bash
python -I workstreams/so02/control-plane/tools/orchqual.py readback \
  --commit 04001dba1c689c90041ea383f3092213756c7ead
```

That command clones the repository again into a throwaway directory, fetches the
immutable commit off the wire and compares every manifested byte over two
independent transports.

## Independent criteria

Accept only if all of the following hold on your own re-run, not on this
document's say-so.

1. At least two routes are marked `QUALIFIED`, they do not share a transport,
   and each carries all seven evidence flags.
2. Every qualified route's remote read-back reports zero mismatches over at
   least two transports.
3. The evidence manifest covers every bundle file, and altering or omitting any
   one of them changes `bundle_sha256`.
4. The PO-03 capacity observation contains at least three snapshots and the
   recomputed verdict is `ZERO_PO03_CAPACITY_INTERFERENCE`.
5. At least one unavailable-route or failure fallback failed closed without
   fabricating a result.
6. Every blocked route carries an exact owner action rather than a vague
   blocker.
7. No write left the SO-02 allowlist and no protected branch was touched.
8. `decision_changed` is empty everywhere and no strategy was bound.
9. The register admits exactly one persistent orchestrator and does not admit a
   second Cursor group, an unproved route, exclusive provider dependence, merge,
   promotion or cutover.

## Known limits the acceptor should weigh

- Capacity non-interference was measured at the visible top-level run layer in
  one account scope. It is not a proof of account-wide quota isolation and does
  not license a second Multiple Agents group.
- Nested PO-03 work units are not visible at that layer, so a within-run
  slowdown could not have been detected.
- Route `R2` qualifies observation, result and artifact retrieval. Programmatic
  run creation over the Cursor REST API remains credential-blocked and is
  recorded as `OWNER_REQUIRED`, not as qualified.
- The ChatGPT Projects browser route is unsupported in this runtime. Per the
  commission this is explicitly not a promotion gate, and the acceptor should
  refuse any argument that treats its absence as a failure.

## Refusal is a valid outcome

If any criterion fails on re-run, record `FAIL` or `NOT_YET` with the exact
failing check. A refusal is more useful than an accommodating acceptance, and
nothing in the current execution depends on this record being granted.
