# Execution evidence

Test command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-007-network-independence/test_network_denied_runner.py`

Exit code: `0`

Verbatim combined output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 3.667s

OK
```

Full-suite command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-007-network-independence/network_denied_runner.py --source . --commit 7dca56c6abcc29e96df85adeb67d460613176d34 --workspace workstreams/po03/attempts/po03-wa-b2e7-007-network-independence/_network-proof`

Exit code: `0`

Verbatim outcome fields:

```json
{
  "clean_after_run": true,
  "commit": "7dca56c6abcc29e96df85adeb67d460613176d34",
  "network_dependency_failures": [],
  "network_namespace_preflight": "SUPPORTED",
  "sandbox": "linux-user-and-network-namespace",
  "test_file_count": 10,
  "unrelated_failures": []
}
```

All ten recursively discovered test files passed inside separate unprivileged
Linux network namespaces with no external interface. The adversarial fixture
attempted a socket connection to a documentation-only address and was
classified as genuine network dependence; a separate assertion failure was
classified as unrelated.

Observed limitation: the executable depends on Linux `unshare` with enabled
unprivileged user and network namespaces. It fails as unsupported where the
host kernel or policy denies that facility.
