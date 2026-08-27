# The write admission gate admits a declaration whose hashes are false

**Lane** SCP-SI-01 lane C
**Evidence label** `DIRECTLY_REPRODUCED` — observed without tampering, on this
lane's own real declaration, in this run
**Integration commit audited against** `f0fb3f51a25db67b33bdd558c73055f3d02ddb60`
**Subject** `workstreams/so02/control-plane/operating-environment/tools/write_admission.py`
and `.../tools/evidence_integrity.py`, both unmodified
**Raw output** `receipts/so02/2026-08-27/scp-c/raw/gate-blindness-observed.txt`

## Finding

A `MANIFEST_CLOSURE` evidence record can assert hashes for bytes that are not on
disk, and every gate passes with `EVIDENCE_RECOMPUTED`.

## How it was observed

Not constructed. It happened in the ordinary course of this lane's work.

1. `release.sh` step 6 generated the declaration, hashing 18 files from disk.
2. Step 7 confirmed the evidence was true of the disk, and step 8 recorded
   `WRITE_ADMITTED`.
3. Three files under `lane-c/` were then edited and one was added — the README
   gained a section, `verify_declaration_evidence.py` gained a parameter, and
   `reproduce_gate_blindness.py` was created.
4. The gate was re-run on the declaration, unmodified.

```
WRITE_ADMITTED  target='cursor/scp-c-authorship-sidecar-696d' operation='COMMIT_AND_PUSH'
  [pass] declaration    DECLARED_AND_REASONED
  [pass] concurrency    SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT
  [pass] reversibility  REVERSAL_RE_EXECUTED_AND_VERIFIED
  [pass] evidence       EVIDENCE_RECOMPUTED
```

Two of the eighteen recorded hashes were wrong at that moment, one by 2,450
bytes, and a fourth deliverable file was present and hashed by nothing. The
verdict was `EVIDENCE_RECOMPUTED`.

## Mechanism

`write_admission.check_evidence_gate` delegates to
`evidence_integrity.verify_manifest_closure`, which asks exactly two questions:

```python
covered = {entry.get("path") for entry in manifest.get("entries", [])}
for path in sorted(set(present_paths)):
    if path not in covered:
        errors.append(...)
recomputed = sha256_bytes(json.dumps(manifest.get("entries", []), ...))
if manifest.get("bundle_sha256") != recomputed:
    errors.append(...)
```

Is every `present_paths` entry covered, and does `bundle_sha256` bind the entry
list. Neither question opens a declared file. `present_paths` comes from the
declaration too, so a declaration supplies both the claim and the yardstick.

The word `recomputed` in the verdict is accurate about what it recomputes — the
bundle hash over the entry list — and is easy to read as something stronger.

## Why this is the estate's own recorded defect, one layer out

`write_admission`'s docstring names it:

> a wholly fabricated read-back record naming commit 000...0 passed the old
> verifier because the verifier checked the record's SHAPE and never its TRUTH.

That is this, applied to `MANIFEST_CLOSURE` instead of `READBACK`. The
correction was made for one evidence kind and the other kind kept the shape.

It is also the same error this lane was commissioned against, in a different
medium. A substring match was treated as proof of authorship because the check
that ran was cheap and adjacent to the check that was wanted. Internal closure
is being treated as proof that files exist for the same reason.

## What this is not

`HYPOTHESIS`-free scoping, because overstating this would be its own defect:

* **Not a reason to distrust the gate.** The other three gates do recompute
  against the world. The concurrency gate re-runs `git ls-remote` and would
  catch a writer the agent list cannot see; the reversibility gate re-executes
  the rollback against a real disposable remote and refuses if the tree does not
  come back. Both were observed passing on real evidence in this run.
* **Not an exploit.** It needs no adversary. A lane that edits a file after
  declaring is the whole mechanism, which is what makes it likely rather than
  exotic.
* **Not fixed here.** `write_admission.py` is not in lane C's write scope and
  this lane did not touch it. The finding is reported; the repair is somebody
  else's call.

## What this lane did about it

Added a check, in its own namespace, that asks the question the gate does not:

```bash
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/verify_declaration_evidence.py --repo-root .
```

It recomputes every recorded hash against disk, checks that the covered set is
exactly what is present, requires `present_paths` to be stated rather than
defaulted, and requires every gap between `target.paths` and the evidence to be
one of three declared exclusions. On the stale declaration above it produced
five findings and exited 1. It runs as step 7 of `release.sh`, before the gate,
so the lane cannot push on a declaration that is false about its own files.

`reproduce_gate_blindness.py` reproduces the same finding on demand, by putting
a deliberately false hash through the estate's live gate and through this check.
It exits 1 if the gate ever starts catching it — a finding that has been fixed
upstream should stop being reported, and a stale finding kept alive is its own
small version of this defect.

## Provenance of the constraint this adds

`EARNED`. The defect is named above, reproduced in this run, and its raw output
is committed. Per the standing rule the constraint is binding as mechanism and
the defect is cited rather than implied. It binds this lane's own release path
and proposes nothing for anyone else's.
