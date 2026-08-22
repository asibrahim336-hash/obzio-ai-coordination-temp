# Execution evidence

Test command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-005-deterministic-rerun-equivalence/test_double_clone_runner.py`

Exit code: `0`

Verbatim combined output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.718s

OK
```

Full-suite command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-005-deterministic-rerun-equivalence/double_clone_runner.py --source . --commit 6497c14c49a2f6ddb75c056bb1ee1e4a8196ebe1 --workspace workstreams/po03/attempts/po03-wa-b2e7-005-deterministic-rerun-equivalence/_double-clone-proof`

Exit code: `0`

Verbatim outcome fields:

```json
{
  "byte_equivalent": true,
  "clean_after_run": [
    true,
    true
  ],
  "commit": "6497c14c49a2f6ddb75c056bb1ee1e4a8196ebe1",
  "failed_tests": [],
  "normalized_fields": {
    "clone_a": {
      "unittest_elapsed_seconds": 8
    },
    "clone_b": {
      "unittest_elapsed_seconds": 8
    }
  },
  "test_file_count": 8
}
```

Both independent clones ran the same eight recursively discovered test files.
Every return code, stdout byte and normalized stderr byte matched. The only
observed non-deterministic field was the unittest elapsed duration, with eight
occurrences in each clone. Both working trees remained clean.

Observed limitation: equality is asserted after explicitly reported
normalization of ISO-8601 timestamps, unittest elapsed durations and clone-root
paths; an inappropriate normalization rule could conceal a defect, so the
normalization inventory is part of the output.
