# po03-wa-b2e7-027-changed-path-rejection-fixture

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

The path-scope guard has real rejection power, demonstrated by a deliberate
out-of-allowlist mutation fixture.

## Executable component

`rejection_fixture.py` runs `workstreams/po03/tools/check_path_scope.py` as a
separate process across 16 scenarios and compares each real exit status and
output marker against a stated expectation. It is CI-callable as one command:

```
python -I workstreams/po03/attempts/po03-wa-b2e7-027-changed-path-rejection-fixture/rejection_fixture.py
```

Scenario groups:

- **Synthetic control** — all four commissioned prefixes passed together must
  exit 0 with `PO03_PATH_SCOPE_PASS`.
- **Synthetic rejections** — ten individually named protected surfaces
  (`state/`, `workstreams/po01/`, `.cursor/environment.json`, `packs/`,
  `modules/`, `_transport/`, `dispatch/`, `COMMISSION.md`, a lookalike
  workflow, `README.md`) must each exit 1 with a
  `PO03_PATH_SCOPE_VIOLATION` naming that path.
- **Taint** — one out-of-allowlist path among four legitimate ones must still
  exit 1.
- **Real `git diff` scenarios** — inside a throwaway repository the fixture
  commits an in-allowlist change (must exit 0), then a deliberate
  `state/PO03-SHOULD-NOT-WRITE.json` mutation (must exit 1), then deletes it
  again (must also exit 1, because removing a file outside the allowlist is
  itself an out-of-scope change).
- **Fail-closed on error** — an unresolvable base must exit 2 with
  `PO03_PATH_SCOPE_ERROR`, never 0.

`--include-repo-scope BASE` adds a seventeenth scenario asserting the branch
under test has itself changed only allowlisted paths.

## Nothing out of allowlist is ever committed to this branch

Rejections are produced either from synthetic `--path` arguments with no
repository involved, or from commits inside a throwaway git repository created
under a temporary directory and deleted in a `finally` block. Three tests
enforce this: the scratch repository is asserted to be a different repository
from the one under test, the real repository's `git status --porcelain` and
`HEAD` are asserted unchanged across a full fixture run, and the scratch
directory is asserted empty after a command-line run.

## Verdict

PASS. All 16 default scenarios behaved as expected against the live guard
(`PO03_FIXTURE_PASS scenarios=16 rejecting=14 passing=2`), and the optional
repository-scope scenario also passed for this branch since
`5ef49cb148f5186397acf1303f325f726bb58543`.

## The fixture is not vacuous

A fixture that cannot fail proves nothing, so two tests substitute deliberately
broken guards for the real one:

- A guard that always prints `PO03_PATH_SCOPE_PASS` and exits 0 produces at
  least ten deviations, including
  `scratch-repo-out-of-allowlist-mutation` — and still passes both controls,
  which is precisely why controls alone cannot detect a vacuous guard.
- A guard that always exits 1 makes the controls deviate instead.

## Observed limitations

1. The fixture asserts what the guard *reports* about a change set. It cannot
   assert that CI feeds the guard the right change set; that depends on the
   workflow's `--base`/`--head`, which is a separate surface (unit 031).
2. A full run takes about 46 seconds of test time, almost entirely `git` and
   interpreter process spawns. It is fast enough for a pull-request gate but is
   not a tight inner-loop test.
3. Rejection is proven only for the path spellings enumerated here. The guard's
   behaviour against traversal, symlink, unicode and case-variant spellings, and
   against change sets where `git diff --name-only` does not reveal the whole
   mutation, is unit 028's subject — and unit 028 found real gaps there.
