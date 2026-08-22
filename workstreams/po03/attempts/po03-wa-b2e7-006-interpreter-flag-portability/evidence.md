# Execution evidence

Test command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-006-interpreter-flag-portability/test_interpreter_matrix.py`

Exit code: `0`

Verbatim combined output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 17.646s

OK
```

Full-suite matrix command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-006-interpreter-flag-portability/interpreter_matrix.py --source . --commit 4f47d80576ba29c05f2ee4e421bcd026994f0306 --workspace workstreams/po03/attempts/po03-wa-b2e7-006-interpreter-flag-portability/_matrix-proof`

Exit code: `0`

Verbatim outcome fields:

```json
{
  "clean_after_run": true,
  "commit": "4f47d80576ba29c05f2ee4e421bcd026994f0306",
  "failed_cases": [],
  "imports_escaping_standard_environment": [],
  "matrices": [
    [
      "-I"
    ],
    [
      "-I",
      "-S"
    ]
  ],
  "matrix_case_count": 18,
  "test_file_count": 9
}
```

All nine recursively discovered files passed under both isolated matrices, for
18 passing cases. The clean clone remained clean. The adversarial unit fixture
also proved that a missing external import is captured by module name.

Observed limitation: `-S` excludes automatic `site` initialization and `-I`
isolates user/environment paths, but an executable could still explicitly load
vendored code by absolute file path; this result establishes suite behavior
under the flags, not a static proof over every possible dynamic load.
