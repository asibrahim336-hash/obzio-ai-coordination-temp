# Evidence — po03-wa-b2e7-015-disposition-completeness

## What was executed

1. Unit tests:

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -I test_disposition_completeness.py
```

Real captured output is in `test_output.txt` (26 tests, all `ok`, `OK` overall
exit). The `FAILED_CLOSED` JSON block at the end of that file is the *actual
printed stdout* of `TestMainFailsClosedOnMissingRepo`, which calls
`disposition_completeness.main()` directly against a synthetic temp repo that
has no `operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md` — this is
expected fail-closed output from that one test case, not a failure of the
suite. `python -I` runs isolated (no user site-packages, no `PYTHONPATH`);
only the standard library (`unittest`, `json`, `re`, `tempfile`, `pathlib`,
`argparse`, `sys`) is used.

2. Real-repository run of the checker itself:

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -I disposition_completeness.py --repo-root .
```

Full real output captured in `real_repo_run.json` (exit code `1`, because
`open_defect_count > 0` — a truthful, non-zero-but-informative exit, mirroring
the pattern used by the sibling launch-surface-classifier unit).

## Real finding (falsification of the naive expectation)

The hypothesis under test is: *"Every superseded file either carries an
explicit disposition or is reported as an open defect."* The checker satisfies
this literally — every one of the 58 superseded files it discovers is placed
into exactly one of two buckets (`dispositioned` or `open_defects`), and
nothing is silently dropped. But the *substantive* finding is that the
repository's actual disposition coverage is incomplete:

- `files_scanned`: 386 (every `.json`/`.jsonl` file under the repo root)
- `superseded_file_count`: 58 (files named as the *older* side of some
  `*supersed*`-keyed relation)
- `dispositioned_count`: 24 — each via an inline `"standing"` field
  co-located with the path/objects list that named the file
- `open_defect_count`: 34 — no inline `standing`, no row in
  `operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md` (that table
  names only 1 explicit backtick path in this repository), and no verified
  `high_risk_markers` entry in `scripts/check_operator_taxonomy.py` (that
  dict names only 5 paths, all `.md` files disjoint from the 34 defects)

So 34 of 58 superseded files (59%) currently have **no** explicit disposition
from any of the three structured sources this checker recognises. That is
recorded as a precise, named, open-defect list (see `open_defects` in
`real_repo_run.json`), not as an invented clean pass.

## Non-mutation

The checker only opens files with `Path.read_text` / `Path.is_file`; it never
writes, deletes, or truncates any scanned path. `TestComputeCompletenessSynthetic.test_no_scanned_file_is_mutated`
and `TestRealRepository.test_real_repo_no_file_is_mutated_by_running_the_checker`
byte-compare files before/after running the checker (synthetic fixture repo
and `state/ACTIVE_CONTROL_POINTER_CURRENT.json` in the real repo,
respectively) and assert equality.

## Boundary / limitation

- The three disposition sources are exactly: inline `"standing"` field,
  `operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md` table rows,
  and verified `high_risk_markers` entries from
  `scripts/check_operator_taxonomy.py`. A file could plausibly carry an
  informal disposition through some other narrative field (e.g. a
  `"migration_ref"` or free-text sentence) that this checker does not
  recognise as a structured disposition; those are correctly reported as
  open defects rather than silently credited, per the fail-closed design in
  the task prompt ("never silently deletes or rewrites the underlying
  evidence" — this is read further as "never silently manufactures a
  disposition that isn't structurally present").
- This is a snapshot at the pinned working commit `5ef49cb` plus the six
  unit-009-through-015 commits on top of it; if committed content changes,
  the counts (58 / 24 / 34) will change and the real-repo tests would need
  their expectations updated to match the new true state — that is by
  design, since these are grounding tests against live content, not fixed
  constants.
