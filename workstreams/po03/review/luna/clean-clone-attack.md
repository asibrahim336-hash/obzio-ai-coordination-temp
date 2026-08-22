# Independent clean-clone attack

Target: `cursor/po03-a3-portable-runtime-ed20` at immutable commit
`7e11ee5c77aed0549be83e1444aa12d041a413f9`, read from the remote-tracking
ref without checkout.

The executable probe was:

```text
python3 -I workstreams/po03/review/luna/clean_clone_attack.py --ref origin/cursor/po03-a3-portable-runtime-ed20
```

Observed result:

```json
{
  "missing_required_objects": [],
  "objects": {
    "runner": {"present": true},
    "tests": {"present": true},
    "transcript": {"present": true}
  },
  "runner_checks": {
    "runner_clones_remote": true,
    "runner_object_read": true,
    "runner_rejects_inside_repo_scratch": true,
    "runner_shell_syntax": true,
    "runner_strips_environment": true,
    "runner_uses_external_default_scratch": true
  },
  "status": "ESCAPE_FOUND",
  "tracked_generated_files": [
    "workstreams/po03/tests/__pycache__/test_validate_contracts.cpython-312.pyc",
    "workstreams/po03/tools/__pycache__/validate_contracts.cpython-312.pyc"
  ]
}
```

The probe executed `sh -n` against the runner bytes read directly from the
immutable commit and checked the required runner, test, and transcript objects
with `git cat-file`. It also enumerated tracked generated files. It did not
check out, merge, mutate, or write to the a3 branch.

The independent test command was:

```text
python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_a6_clean_clone_attack.py'
```

It ran one test and passed. The tracked bytecode is an escape against the
clean-clone claim: a fresh clone contains generated interpreter artifacts, so
the claim is not a clean source-only reproduction. The runner, transcript and
test objects were present at this later revision; the earlier probe’s missing
transcript finding was superseded by this new immutable snapshot.
