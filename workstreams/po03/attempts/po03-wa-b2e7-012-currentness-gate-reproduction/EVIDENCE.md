# Evidence — po03-wa-b2e7-012-currentness-gate-reproduction

## Falsifiable hypothesis

The repository currentness check is reproducible from an immutable commit
and its verdict is stable.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-012-currentness-gate-reproduction/test_reproduction_harness.py
```

Working directory: repository root of this worktree, commit base
`5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_fails_closed_on_unknown_commit
[PASS] test_run_taxonomy_check_reports_missing_script
[PASS] test_run_taxonomy_check_detects_synthetic_fail_setup
[PASS] test_run_taxonomy_check_detects_synthetic_fail
[PASS] test_reproduce_at_commit_never_touches_worktree
[PASS] test_reproduction_is_deterministic_for_same_commit
[PASS] test_real_pinned_commits_all_reproduce_pass_with_stable_hash
    pinned_base=5db7affeb7f0 verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
    main=37943ec2ff9f verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
    soo_currentness_repair=745f634ba76c verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
    soo_controlling_pointer=8c52ef6d8f0d verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
    agent_taxonomy_continuity_repair=ee0f74e55ac1 verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
    cohort_base=5ef49cb148f5 verdict=PASS exit_code=0 stdout_sha256=e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5 script_blob_sha=109689db047bbb0179d60b5e29fe4297eb463623
[PASS] test_real_pinned_commits_share_byte_identical_script

RESULT: all 7 tests passed
```

Exit code: `0`.

## Method (strictly read-only)

For each named commit, the harness runs `git archive <commit>` (read-only;
never touches the worktree index or files) and extracts the tree into a
throwaway `tempfile.mkdtemp()` directory, then invokes that commit's own
committed `scripts/check_operator_taxonomy.py` bytes with
`python3 -I` against that scratch snapshot, captures stdout/stderr/exit
code, hashes stdout, and deletes the scratch directory. This never writes
to `scripts/check_operator_taxonomy.py`, or to any file it checks, in the
real repository — confirmed by
`test_reproduce_at_commit_never_touches_worktree`, which hashes the real
worktree's own script bytes before and after a reproduction run.

## What was actually found (real, not fabricated)

All six named commits were reproduced:

| label | commit | verdict | exit code | stdout sha256 | script blob sha |
|---|---|---|---|---|---|
| pinned_base | `5db7affeb7f0...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |
| main | `37943ec2ff9f...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |
| soo/v003-currentness-repair-20260820 | `745f634ba76c...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |
| soo/v003-controlling-pointer-and-part-manifest-repair-20260820 | `8c52ef6d8f0d...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |
| agent/operator-function-taxonomy-continuity-repair | `ee0f74e55ac1...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |
| cohort_base (this cohort's frozen starting commit) | `5ef49cb148f5...` | PASS | 0 | `e08582bd5040...` | `109689db047b...` |

Every one of the six commits reproduces `OPERATOR TAXONOMY CHECK: PASS`,
exit code `0`, and the identical stdout SHA-256
`e08582bd50407feeba4d67ee06e073e7fadb373b1893374b12446e9da1a129b5`.

Also verified: `git diff --stat 5db7affe...5ef49cb -- state/ scripts/
operations/ instructions/ templates/` is empty — the tracked surfaces the
taxonomy script checks have not changed at all across this commit range,
and `scripts/check_operator_taxonomy.py` itself is the same blob
(`109689db047b...`) at every one of the six commits.

## Verdict rationale

**PASS**, with an explicit limitation. The hypothesis is confirmed on
real, immutable commits: the check is genuinely reproducible (re-running
against the same commit twice yields identical exit code and stdout hash
— `test_reproduction_is_deterministic_for_same_commit`) and its verdict
is stable across every named reference commit. The harness is not a
stub: `test_run_taxonomy_check_detects_synthetic_fail` proves it reports
`FAIL`/exit code `1` when a required file
(`state/operator-system/COMMISSION_REGISTER.jsonl`) is deleted from a
scratch snapshot, so the uniform "PASS" result on the six real commits is
a genuine measurement, not a hardcoded answer.

**Limitation, recorded precisely**: this reproducibility result is
observed across a commit range in which the checked script and the
checked `state/`/`operations/`/`instructions/`/`templates/` surfaces are
byte-identical at every point (confirmed by an empty `git diff --stat`).
The test therefore demonstrates deterministic, side-effect-free execution
and a stable verdict across six distinct commit objects, but it does not
by itself demonstrate resilience of the *verdict* across a commit range
where the checked content actually differs — none of the six pinned
reference commits happen to differ from each other in the checked paths.
