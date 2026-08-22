# po03-wa-b2e7-031-clean-ci-suite-gate

Hypothesis: *The complete PO-03 suite runs in a clean GitHub Actions environment
with no repository-local state.*

**Verdict: NOT_YET.**

The hypothesis is a conjunction of two claims and only one of them can be
measured from here.

The half that is proved: the complete suite runs with no repository-local state.
All nine `run:` blocks of the staged workflow were executed inside a fresh `git
clone` of an immutable commit, in a temporary directory, with a scrubbed
environment and a temporary `HOME`, and all nine exited zero. The clone holds
committed bytes only, so nothing untracked in the producer's worktree can have
contributed. A deliberate refutation attempt is part of the test suite: a step
that reads an untracked file created in the producer's worktree fails inside the
clone, which is what makes the "no repository-local state" claim measured rather
than asserted.

The half that is not proved: nothing here observes GitHub Actions. The producer
has no authority over `.github/**`, so the workflow was never installed and no
run was ever triggered. A real Ubuntu runner, the genuine `actions/checkout` and
`actions/setup-python` implementations and GitHub's shell defaults are not
reproduced by a local clone. Calling this PASS would assert a provider capability
that was never exercised, so the verdict stays NOT_YET until a controller
installs the file and a real run is observed.

## Install path

```
.github/workflows/po03-suite.yml
```

The staged bytes are `po03-suite.yml` in this subtree and are intended to be
installed verbatim at that path. The path is inside the commissioned allowlist
glob `.github/workflows/po03-*.yml`, and this is checked rather than assumed:
`test_the_live_guard_admits_the_declared_install_path` feeds the path to the live
`workstreams/po03/tools/check_path_scope.py` and requires exit 0. It must be
installed on a ref that contains the c4 unit subtrees under
`workstreams/po03/attempts/`, because the workflow runs the guards and fixtures
those units built.

## What the gate actually runs

Beyond the three elements the capsule names (aggregate suite, path-scope guard,
rejection fixture), the workflow also exercises the other c4 mechanisms, so a
regression in any of them turns the gate red:

| Step | Result in the clean clone |
| --- | --- |
| Record the runtime | `Python 3.12.3`, `git version 2.43.0` |
| Legacy path boundary | `PO03_PATH_SCOPE_PASS changed_paths=337` |
| Hardened path boundary (unit 028) | `PO03_HARDENED_SCOPE_PASS images=337` |
| Dependency-free contract suite | `Ran 58 tests ... OK` |
| Every counted unit's own tests | 6 unit suites discovered, all OK |
| Rejection fixture (unit 027) | `scenarios=16 rejecting=14 passing=2` |
| Tamper harness (unit 030) | `cases=15 detected=9 clean=4 known_undetected=2` |
| Coverage audit (unit 029) | `slots_audited=6` |
| Provenance rooting (unit 026) | `slots_rooted=6` |

The baseline of 58 contract tests is unchanged, which is the intended outcome:
this unit adds a gate, it does not modify the mechanisms under it.

## The one emulated piece, disclosed

The workflow calls `python`, which exists on a runner only because
`actions/setup-python` puts it there. This host ships `python3` alone, so the
first execution attempt failed with exit 127 on all nine steps. That run is kept
verbatim in `clean_clone_execution_no_python_shim.txt` rather than discarded,
because it is the evidence that the local environment and a runner genuinely
differ.

The fix is a shim directory holding a `python` that execs the local 3.12
interpreter, prepended to `PATH`. It emulates exactly the one thing the pinned
action does that these steps depend on, it is off by default and passed
explicitly, and the interpreter it resolves to is printed in the report and
recorded as `python_shim_target` in `structural_report.json`. It is a
substitution in the evidence and is labelled as one.

## Deliberate design choices

*Every aggregate loop fails closed.* A `for` loop over an empty glob exits zero
and would report a green gate having verified nothing. Each of the three loops
therefore counts what it processed and exits 1 with `PO03_SUITE_ERROR` if the
count is zero, and a test asserts this for every loop it can find.

*Both guards judge the same range.* The hardened guard is pinned to the same base
commit that `check_path_scope.py` uses as its own `PINNED_BASE_SHA`, asserted by
a test that imports the legacy guard and looks its constant up rather than
hard-coding the hash a second time. Any disagreement between the two guards is
then a guard difference, not a range difference. `fetch-depth: 0` is what makes
that base reachable, and a test requires it.

*No GitHub expressions in `run:` blocks.* Expressions are used only in
`concurrency:`. A `run:` block containing one would not be locally executable, so
the execution evidence would cover something other than what the runner runs. The
structural checker reports any such block.

*The parser refuses what it cannot read.* This validator reads a small YAML
subset, not full YAML, and no third-party parser is available. A parser that
silently skipped a malformed step would let an unchecked step through, so
anything unrecognised inside the steps list raises `WorkflowError` and the tool
exits 2.

## Observed limitations

- **No GitHub Actions observation.** This is the operative limitation and the
  reason for the NOT_YET verdict. Local clean-clone execution is the strongest
  available local evidence, not evidence about the runner.
- **The YAML subset parser is not a YAML implementation.** It reads this file.
  GitHub could accept a document this parser rejects, or read a valid document
  differently than this parser does. Structural checks are therefore a check on
  the staged bytes, not a guarantee of GitHub's interpretation.
- **The base commit is pinned, not derived.** Pinning follows the existing guard's
  behaviour and keeps both guards aligned, but a pinned base cannot express a
  changed-path range for a branch that does not descend from it.
- **The gate inherits the known gaps it runs over.** The tamper harness reports
  two undetected cases, tail truncation and a forged append, and passes while
  reporting them. A green gate therefore means "the known gaps are still exactly
  these two", not "custody is untamperable".
- **`timeout-minutes: 30` is unvalidated against a runner.** The clean-clone
  execution took roughly 36 seconds here, but runner hardware and the cost of
  fetching full history are not measured.
