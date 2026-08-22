# Independent clean-clone attack

Target: `cursor/po03-a3-portable-runtime-ed20` at immutable commit
`789991708ac49d5093fe6a452a91e4aba2cf1b40`, fetched into `FETCH_HEAD`.

The executable probe was:

```text
python3 -I workstreams/po03/review/luna/clean_clone_attack.py --ref FETCH_HEAD
```

Observed result:

```json
{
  "missing_required_objects": ["transcript"],
  "objects": {
    "runner": {"present": true},
    "tests": {"present": true},
    "transcript": {"present": false}
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
with `git cat-file`. It did not check out, merge, mutate, or write to the a3
branch.

The independent test command was:

```text
python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_a6_clean_clone_attack.py'
```

It ran one test and passed. The missing transcript and tracked bytecode are
defects against the a3-u01 acceptance artifact and the clean-clone claim. A
full remote clone execution was not scored because the required committed
transcript was absent at this immutable revision.
