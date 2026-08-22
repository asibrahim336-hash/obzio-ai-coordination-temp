# Execution evidence

Command:

`python3 -I workstreams/po03/attempts/po03-wa-b2e7-001-clean-clone-runner/test_clean_clone_runner.py`

Exit code: `0`

Verbatim combined terminal output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.979s

OK
```

The tests exercised recursive committed-file discovery, rejection of `HEAD` in
place of an immutable object ID, and fail-closed detection of a test-created
untracked file. The runner uses a caller-local runtime directory rather than
`/tmp`.

Clean-clone reproduction command:

`python3 -I workstreams/po03/attempts/po03-wa-b2e7-001-clean-clone-runner/clean_clone_runner.py --source . --commit 5ef49cb148f5186397acf1303f325f726bb58543 --destination workstreams/po03/attempts/po03-wa-b2e7-001-clean-clone-runner/_clean-clone-proof`

Exit code: `0`

Verbatim JSON output:

```json
{
  "commit": "5ef49cb148f5186397acf1303f325f726bb58543",
  "dirty_after_run": false,
  "failed_tests": [],
  "results": [
    {
      "path": "workstreams/po03/tests/test_check_path_scope.py",
      "returncode": 0,
      "stderr": ".......\n----------------------------------------------------------------------\nRan 7 tests in 0.000s\n\nOK\n",
      "stdout": ""
    },
    {
      "path": "workstreams/po03/tests/test_factory_custody.py",
      "returncode": 0,
      "stderr": ".....................\n----------------------------------------------------------------------\nRan 21 tests in 0.307s\n\nOK\n",
      "stdout": ""
    },
    {
      "path": "workstreams/po03/tests/test_transactional_factory.py",
      "returncode": 0,
      "stderr": ".......\n----------------------------------------------------------------------\nRan 7 tests in 0.023s\n\nOK\n",
      "stdout": ""
    },
    {
      "path": "workstreams/po03/tests/test_validate_contracts.py",
      "returncode": 0,
      "stderr": ".......................\n----------------------------------------------------------------------\nRan 23 tests in 0.001s\n\nOK\n",
      "stdout": ""
    }
  ],
  "test_count": 4
}
```

Observed limitation: local clone transport was exercised; remote clone
authentication and remote availability were not tested.
