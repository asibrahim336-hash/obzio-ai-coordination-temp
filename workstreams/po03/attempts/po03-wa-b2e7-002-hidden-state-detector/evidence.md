# Execution evidence

Command:

`python3 -I -B workstreams/po03/attempts/po03-wa-b2e7-002-hidden-state-detector/test_hidden_state_detector.py`

Exit code: `0`

Verbatim combined terminal output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 29.618s

OK
```

The adversarial test committed a probe, added an uncommitted `.warm-state`,
and observed `warm` in the working checkout versus `pristine` from the Git
archive. The detector returned its documented divergence exit code. The clean
control produced equal observations, and a mismatched commit was refused.

Observed limitation: behavioral comparison covers the supplied command's exit
code and byte output; hidden state that does not affect those observables is
outside this detector's claim.
