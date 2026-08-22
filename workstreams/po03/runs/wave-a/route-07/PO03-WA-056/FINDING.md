# PO03-WA-056 — a corrupted manifest never produces a false PASS

- Task: `PO03-WA-056`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Adversarial corrupt manifests never produce a false PASS.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`manifest_verifier.py` pairs a strict verifier with an adversarial corruption
generator.

`verify()` reconciles a manifest against a tree: version, entry shape, declared
count, per-entry digest and byte count, path safety, and — critically — the
reverse direction, that no file present in the tree is absent from the manifest.
Path safety rejects absolute paths, backslashes, `..` traversal, non-canonical
`./` and empty segments, symlinks and anything resolving outside the root, and
rejects two entries that alias one another under Unicode NFC plus case folding.

`corruptions()` mutates a known-good manifest in **24** distinct ways: truncated
entry list, zeroed digest, swapped digests between two entries, uppercased
digest, non-hex digest, short digest, absent digest, inflated byte count,
negative byte count, stringified byte count, duplicate entry, path traversal,
absolute path, backslash path, `./` prefix, double slash, leading space,
case-fold path alias, missing artifact, empty artifact list, inflated count,
inflated total bytes, forged version, non-object entry and absent path.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 18 tests — OK
```

Every generated corruption is asserted to fail, to fail with its expected
diagnostic code, and to carry a non-empty actionable detail.

## Hidden and adversarial cases

Beyond the manifest mutations, seven on-disk tampering cases run against an
*honest* manifest: editing an artifact, a same-length edit that only the hash can
catch, deleting an artifact, adding an unmanifested file, replacing an artifact
with a symlink to an identical file outside the tree, adding a symlinked
directory containing a hidden file, and truncating an artifact to zero bytes.

## Defect found while building

The `./component.py` corruption produced a **false PASS** on the first run.
`pathlib` silently folds `.` segments away, so the traversal guard never saw
them and the entry reconciled against the real file. The verifier now compares
the raw path string against its canonical segmentation before pathlib touches
it, and reports `PATH_NOT_CANONICAL`. A `sub//name` case was added to cover the
empty-segment variant of the same class. The symlink check was also moved ahead
of resolution so that a symlinked artifact is diagnosed as `PATH_SYMLINK` rather
than as the downstream `PATH_ESCAPES_ROOT`.

This is the single most important result in the slot: the hypothesis was
falsified on first execution and the component was repaired, rather than the
case being weakened.

## Limitations

- The verifier reads the tree with `os.walk(followlinks=False)`. A symlinked
  *directory* is therefore not descended, so a file hidden behind one is neither
  verified nor reported as unlisted. The test pins this behaviour explicitly:
  nothing outside the root is ever admitted as a verified artifact, but the
  verifier does not enumerate what lies beyond the link.
- Hash comparison assumes SHA-256 as fixed by the contract; no algorithm agility.
- Case-fold aliasing is detected between two manifest entries. On a
  case-insensitive filesystem a single entry could still resolve to a
  differently-cased file on disk; that boundary is filesystem-dependent and is
  not asserted here.

## Disposition

**PASS** — all 24 generated corruptions and all seven on-disk tampering cases are
rejected with specific diagnostics, after one real false-PASS defect was found
and repaired.
