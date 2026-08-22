# Execution evidence

Test command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-008-warm-checkout-adversarial/test_warm_checkout_adversarial.py`

Exit code: `0`

Verbatim combined output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 1.294s

OK
```

Adversarial command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-008-warm-checkout-adversarial/warm_checkout_adversarial.py --fixture workstreams/po03/attempts/po03-wa-b2e7-008-warm-checkout-adversarial/warm_only_fixture.py --clean-runner workstreams/po03/attempts/po03-wa-b2e7-001-clean-clone-runner/clean_clone_runner.py --workspace workstreams/po03/attempts/po03-wa-b2e7-008-warm-checkout-adversarial/_adversarial-proof`

Exit code: `0`

Verbatim outcome fields:

```json
{
  "clean_runner_returncode": 3,
  "failed_tests": [
    "workstreams/po03/tests/test_warm_only.py"
  ],
  "fixture_commit": "f46d31337d66af9317307ec0d91fe14b5708224f",
  "warm_checkout_dependence_caught": true,
  "warm_marker_tracked": false,
  "warm_returncode": 0
}
```

The same committed test passed in the warm repository only because the
untracked marker existed. The real unit-001 runner cloned the fixture commit,
did not receive that marker, and returned `3` with the fixture in
`failed_tests`. A vacuous fake runner that returned green was rejected by the
adversarial harness.

Observed limitation: this is a synthetic marker dependency selected to make
the warm/cold distinction falsifiable; it demonstrates detector power but does
not enumerate every possible hidden-state channel.
