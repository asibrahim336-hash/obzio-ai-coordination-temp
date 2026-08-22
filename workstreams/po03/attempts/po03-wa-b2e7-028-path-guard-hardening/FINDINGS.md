# po03-wa-b2e7-028-path-guard-hardening

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

The path-scope guard resists traversal, symlink, unicode and case-variation
evasion.

## Verdict: FAIL — refuted on the symlink clause

Three of the four clauses hold for the live guard
`workstreams/po03/tools/check_path_scope.py`. The symlink clause does not.

| clause | live guard | evidence |
| --- | --- | --- |
| traversal | resisted | `..`, `../x`, `workstreams/po03/../state/x`, `./` and `//` spellings all refused |
| unicode | resisted | Cyrillic `о` and fullwidth `ｗ` confusable prefixes refused |
| case variation | resisted | `WORKSTREAMS/PO03/x` and `.github/workflows/PO03-a.yml` refused |
| **symlink** | **not resisted** | an in-allowlist name added as mode 120000 pointing at `../../state` passes with `PO03_PATH_SCOPE_PASS` |

The refutation is recorded as a refutation. No hole was invented: where the
existing guard already refuses, the matrix and the tests say `REFUSES` for it.

## Real gaps found, each reproduced against the live guard

1. **`RENAME_SOURCE_OUT_OF_SCOPE` — the highest-severity finding.**
   `git diff --name-only` reports only the post-image of a rename. So
   `git mv state/PROTECTED.json workstreams/po03/attempts/scratch/i.json`
   deletes a file outside the allowlist while the guard sees exactly one
   in-allowlist path and exits 0. A plain `git rm state/PROTECTED.json` *is*
   caught, so rename detection is precisely what hides the mutation. The guard
   is therefore weaker against a disguised deletion than against an obvious one.
2. **`SYMLINK_TARGET_OUT_OF_SCOPE`.** The guard inspects names, never modes or
   blob bodies. `workstreams/po03/.../link -> ../../../../state` is admitted,
   which installs a durable traversal handle out of the allowlist under an
   in-allowlist name. The same applies to an absolute target (`/etc/passwd`) and
   to a type change that replaces an existing in-allowlist regular file with an
   escaping symlink, both admitted.
3. **`GITLINK_NOT_ALLOWED`.** A mode 160000 entry at
   `workstreams/po03/.../sub` is admitted, importing a pointer to an entire
   foreign repository under an allowlisted name.
4. **`WORKFLOW_GLOB_MISMATCH`.** The commissioned allowlist is the glob
   `.github/workflows/po03-*.yml`, but the guard implements it as
   `startswith(".github/workflows/po03-") and endswith(".yml")`, which also
   admits `.github/workflows/po03-a/b.yml`. The guard is wider than the
   allowlist it is supposed to enforce. `.github/workflows/po03-.yml` is *not* a
   gap: an empty `*` expansion does match the glob, so admitting it is correct.

## Two deliberate narrowings, labelled as narrowings and not as escapes

These are admitted by the live guard and refused by the hardened guard, but they
are inside the allowlist and are therefore not scope escapes:

- Trailing dot or space components (`workstreams/po03/x.`,
  `workstreams/po03/x `) collide with `workstreams/po03/x` on Windows.
- Non-ASCII names, including bidi overrides such as
  `workstreams/po03/\u202egnp.txt`, make review display a name other than the
  real one, and NFC/NFD spellings collide on case-insensitive filesystems.

## Structural finding: the NUL class cannot be delivered at all

A NUL byte cannot cross an `execve` boundary, so `--path` can never carry one;
`ValueError: embedded null byte` is raised by the harness before any guard runs.
`git diff -z` uses NUL as its own field separator, and git forbids NUL in path
names, so no real change set can deliver it either. Both guards refuse the path
when called in process, and the matrix records that row's channel as
`in-process (argv cannot carry a NUL byte)` rather than pretending an argv test
happened.

## Executable components

- `hardened_path_scope.py` — the hardened guard. Judges both images of a rename
  from `git diff --raw -z --no-abbrev -M`, resolves and judges symlink targets,
  refuses gitlinks and unexpected modes, matches the workflow allowlist as a
  segment-aware glob, and refuses control, bidi, non-ASCII, trailing-dot and
  trailing-space spellings. A copy (`C`) does not have its source judged,
  because copying readable bytes into the allowlist mutates nothing outside it.
  Markers: `PO03_HARDENED_SCOPE_PASS`, `PO03_HARDENED_SCOPE_VIOLATION`,
  `PO03_HARDENED_SCOPE_ERROR`. Exit 0/1/2.
- `evasion_matrix.py` — runs both guards over one corpus of 37 cases, 28 by name
  and 9 through real `git diff` in throwaway repositories, and prints what each
  guard really did next to what the allowlist requires.

## Measured result

`python3 -I evasion_matrix.py`: `cases=37 legacy_unsatisfied=10
hardened_unsatisfied=0`, exit 0, ending `PO03_MATRIX_PASS`. The ten legacy gaps
are the five real escapes above (rename, symlink-relative, symlink-absolute,
typechange-to-symlink, gitlink), the nested-workflow glob divergence, and the
four deliberate narrowings.

Tests: 43, OK.

## Observed limitations

1. The hardened guard is shipped in this unit's own subtree. It does not replace
   `workstreams/po03/tools/check_path_scope.py`, which this producer must not
   modify. Until a controller installs it, the gaps above remain open in the
   live gate.
2. Symlink judgement needs the blob body, so the guard must be able to run
   `git cat-file`. When a target cannot be read the entry is refused as
   `SYMLINK_UNVERIFIABLE` rather than cleared, which is fail-closed but will
   reject a change set handed to the guard without repository access.
3. Refusing all non-ASCII paths is a policy narrowing, not a security necessity.
   If PO-03 ever needs a non-ASCII artifact name, this rule has to be replaced
   with something narrower, such as requiring NFC and refusing only
   script-mixing within a path component.
4. The guard judges a change set between two commits. It says nothing about
   what a workflow chooses as `--base`, so a gate that computes the wrong base
   can still be fed a change set that hides a mutation.
