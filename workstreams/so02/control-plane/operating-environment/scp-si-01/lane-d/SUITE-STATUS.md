# Suite status — the so02 control-plane canonical harness this lane extends

`DIRECTLY_REPRODUCED`, this session, on this lane's own branch (`cursor/scp-d-failure-to-
learning-696d`), against the integration commit this lane audited and merged:
`379712b369616cffdb2dcf444c2dece163ebb173` on
`cursor/operating-environment-return-20260822-v001`, re-fetched mid-run per the setup
instructions (this lane's original base was `f0fb3f51`; the branch advanced three commits
in between — see `DEFECTS.md`'s reconciliation notes). Recorded again in `MANIFEST.json`.

This is **not** the "868 tests / 19 failures / 117 portability findings" figure from the
commission — that is `po03`'s integrated tree, which is not present anywhere in this
branch's ancestry (§0 of `triage/PORTABILITY-117-TRIAGE.md` shows the direct check). This
is the `so02/control-plane` canonical harness: every test file this lane's four defects
extend, plus every other test file already living under `workstreams/so02/control-plane`.

## Totals

Measured after merging the integration branch's mid-run advance
(`f0fb3f51` -> `379712b3`; see `DEFECTS.md`'s reconciliation notes on Defects 2 and 4).

| Harness | Command | Result |
|---|---|---|
| `pytest`-collectible `test_*.py` files (13 files under `workstreams/so02/control-plane`, includes this lane's `test_def05_def16_supersession.py`, this lane's additions to `test_write_admission.py` and `test_currentctl.py`, and the coordinator's new `test_evidence_integrity.py`) | `python3 -m pytest workstreams/so02/control-plane -q` | **290 passed**, 0 failed |
| `negative_tests_provctl.py` (unittest-based, but named outside pytest's default `test_*.py` glob, so it does not appear in the row above and is run explicitly; includes this lane's `Defect1EmbeddedDisclaimedAttributionTests`) | `python3 -m pytest workstreams/so02/control-plane/operating-environment/w10-provenance/tools/negative_tests_provctl.py -q` | **30 passed**, 0 failed |
| `negative_tests_canary.py` (custom PASS/FAIL harness, not unittest, not pytest-collectible) | `python3 -I .../l5-chatgpt-scale/scripts/negative_tests_canary.py` | **10 passed**, 0 failed |
| `negative_tests_register.py` (same style) | `python3 -I .../l5-chatgpt-scale/scripts/negative_tests_register.py` | **6 passed**, 0 failed |
| `negative_tests_intentctl.py` (same style) | `python3 -I .../w8-chatgpt-constitution/tools/negative_tests_intentctl.py` | **16 passed**, 0 failed |
| `verify_hooks.py` (custom hook-test harness; includes this lane's Defect 3 and Defect 4 / PROJECTION_WORDS cases) | `python3 -I .../l1-cursor-baseline/proposed-cursor-config/dot-cursor/hooks/verify_hooks.py` | **72 passed, 5 failed** |

**Combined: 429 cases run, 424 passed, 5 failed.**

## The five failures

All five are in `guard_write_scope.py`'s `beforeShellExecution` section of `verify_hooks.py`
(`allows push to own lane branch`, `denies commit while HEAD is protected`,
`allows --force-with-lease`, `allows pushing a genuinely divergent branch`, `allows pushing
a branch that does not exist locally yet`). `DIRECTLY_REPRODUCED`: confirmed
`git diff --stat HEAD -- '*guard_write_scope*'` is empty on this branch (this lane changed
nothing in that file or its test section), and the file's last three commits
(`bf5a5864`, `5f7ac053`, `064361be`) all predate this lane's `HEAD`. These are reported
here rather than hidden, per evidence discipline, but they are pre-existing,
environment/git-version-dependent, and outside this lane's write boundary
(`.cursor/hooks/**` write access for the *mechanism* is not excluded by the hard
boundary's namespace rule, but fixing an unrelated, undiagnosed defect in another lane's
already-shipped hook is exactly the "do not write another lane's ... concern" spirit the
commission's lane table protects — Lane D's row extends "the existing regression harness",
not every hook in it. Named, not fixed, not hidden.)

## Verdict

**FAILING** is the correct word for the estate as a whole for two independent reasons this
lane will not conflate:

1. The `po03` portability gate reports 6 genuine, unfixed findings, routed in
   `triage/ROUTED-FINDINGS.json` — outside this lane's write access.
2. This lane's own harness area (`so02/control-plane`) is **414/419 passing**; the 5
   failures are pre-existing, named, and outside this lane's defects.

Neither number is papered over into the other.
