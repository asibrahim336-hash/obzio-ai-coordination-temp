# Execution evidence

Test command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-004-process-boundary-isolation/test_process_boundary_harness.py`

Exit code: `0`

Verbatim combined output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.554s

OK
```

Mechanism command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-004-process-boundary-isolation/process_boundary_harness.py --repo-root . --spec workstreams/po03/attempts/po03-wa-b2e7-004-process-boundary-isolation/mechanisms.json`

Exit code: `0`

Verbatim outcome fields:

```json
{
  "all_process_boundaries_equivalent": true,
  "mechanism_count": 3,
  "mismatches": []
}
```

The full command output recorded equal return code, stdout and stderr for both
fresh `python -I -B` processes for contract validation, changed-path scope and
transaction-custody verification. The adversarial PID fixture produced unequal
output and the harness returned its mismatch exit code.

Observed limitation: three read-only PO-03 command mechanisms were exercised;
state-mutating controller commands were excluded because this producer has no
authority to write their shared control paths.
