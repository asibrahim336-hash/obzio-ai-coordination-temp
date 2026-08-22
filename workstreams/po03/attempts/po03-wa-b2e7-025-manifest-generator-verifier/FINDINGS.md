# po03-wa-b2e7-025-manifest-generator-verifier

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

Every committed PO-03 artifact is covered by a manifest entry with a matching
hash and byte count, and any gap fails closed.

## Executable component

`manifest_tool.py` — a generator/verifier pair over `PO03-MANIFEST-v1`:

```
PO03-MANIFEST-v1
SOURCE <kind> <locator>
<sha256>  <bytes>  <path>
TOTAL <count> <bytes>
```

Two sources are supported and the manifest records which one produced it:

- `--dir` enumerates the working tree, so it sees files a producer forgot to stage.
- `--git-commit`/`--git-prefix` enumerates committed bytes at an immutable
  commit through `git ls-tree`/`git cat-file`, so it is authoritative for what
  was actually durably recorded.

`verify` re-enumerates the source and reports every divergence rather than the
first one. Exit status is 0 verified, 1 verification failed, 2 usage or I/O
error.

Failure classes that fail closed: `UNCOVERED_FILE`, `MISSING_FILE`,
`HASH_MISMATCH`, `BYTE_MISMATCH`, `DUPLICATE_ENTRY`, `MALFORMED_LINE`,
`BAD_HEADER`, `MISSING_TRAILER`, `TRAILER_COUNT_MISMATCH`,
`TRAILER_BYTES_MISMATCH`, `UNSAFE_PATH`, `EMPTY_MANIFEST`.

## Verdict

PASS for the hypothesis as stated, with two observed limitations recorded below
rather than smoothed over.

Evidence: `python3 -I -m unittest discover` over this subtree, captured
verbatim in `evidence/`.

## Observed limitations

1. Coverage is only ever relative to a declared source. A git-source manifest
   cannot see an unstaged file, and
   `test_unstaged_file_is_invisible_to_a_git_source_but_caught_by_a_directory_source`
   asserts exactly that asymmetry instead of assuming it. A producer that never
   stages a file produces a manifest that is complete against the commit and
   incomplete against the working tree. Detecting that class requires the
   directory source, so a gate that only runs the git source cannot catch it.
2. The line-oriented format cannot represent a path containing a newline, a
   carriage return, a NUL or the two-space field separator. Such paths are
   refused at generation time (`UNSAFE_PATH`) rather than silently mangled,
   which is fail-closed but means those artifacts cannot be counted at all.
3. `TOTAL` is checked against the manifest's own entries, so a forged trailer
   that is internally consistent with a truncated entry list still fails,
   because the source enumeration and not the trailer is authoritative. This is
   asserted by `test_uncovered_file_fails_even_when_trailer_is_forged_consistent`.
