# SCP-SI-01 Lane I — making `INSTALLED_NOT_EFFECTIVE` detectable by construction

**Lane:** SCP-SI-01 Lane I (added mid-cohort)
**Branch:** `cursor/scp-i-effective-controls-696d`
**Worktree:** `/tmp/lane-i` (deliberately not `/workspace` — see Part 1)
**Integration commit audited against:** `379712b369616cffdb2dcf444c2dece163ebb173`
(`cursor/operating-environment-return-20260822-v001`, re-fetched
2026-08-27T06:31Z; lane branch point `f0fb3f51a25db67b33bdd558c73055f3d02ddb60`
— see "Integration drift observed" below)

One coherent deliverable in two parts, plus the regression the founder
asked for as a third.

---

## The defect class, and where it came from

> Three defects in this estate turned out to be one class: a control passed
> its own check while measuring or guarding the wrong thing. The founder
> named the class `INSTALLED_NOT_EFFECTIVE`.

**Provenance:** `FOUNDER_AUTHORED` — quoted directly from this lane's own
dispatch brief, attributed there to the founder in writing on 2026-08-27.
This lane treats that sentence as governing and does not restate,
soften, or reinterpret it.

The brief names three prior instances (git authorship mistaken for founder
authorship; manifest closure mistaken for parse validity; hooks installed
mistaken for hooks firing). This lane's mandate is the third instance and
the general mechanism behind all three: **stop certifying "installed" as a
proxy for "effective," and build the tooling that makes the gap visible
every time, not just this once.**

---

## Part 1 — the explicit push-path wrapper

**File:** `workstreams/so02/control-plane/operating-environment/tools/push_with_admission.py`
**Tests:** `workstreams/so02/control-plane/operating-environment/tools/test_push_with_admission.py` (9 tests, stdlib `unittest`, `python3 -I`)

### The problem, `DIRECTLY_REPRODUCED`

`require_write_declaration: true` is set in `.cursor/write-scope.json`. The
`beforeShellExecution` ambient hook that is supposed to enforce it
(`.cursor/hooks/guard_write_scope.py`, wired through `.cursor/hooks.json`)
never fires in this lane's own worktree. This was proved by hand, not
assumed: see `lane-i/AMBIENT-HOOK-PROBE-INPUT-20260827.json` and the sweep
below. Cursor loads `.cursor/hooks.json` from a project root fixed at run
start; every lane's `git worktree` lives under `/tmp`, so the hook that
would call `write_admission.py` is correct and unreached there.

### The wrong fix, named and rejected

Moving lanes into `/workspace` so the ambient hook's project root lines up
with the working directory would trade `INSTALLED_NOT_EFFECTIVE` for
`SHARED_WORKTREE_COLLISION` — `DIRECTLY_REPRODUCED`, live, within two
minutes of a prior dispatch, per this lane's own brief. Worktree isolation
is `EARNED` mechanism (it caught a real collision) and stays. The correct
fix is to stop depending on the ambient hook at all.

### What the wrapper does

A lane invokes `push_with_admission.py` explicitly, in its own push step,
instead of running `git push` directly. It runs the exact same
`write_admission.admit()` gates the ambient hook was supposed to trigger
and refuses the push when admission refuses.

### Why "works from any cwd" is load-bearing, not decorative

Every path the wrapper needs is resolved from **the script's own on-disk
location** and from **git**, never from `os.getcwd()`:

- `write_admission.py` loads from `Path(__file__).resolve().parent`
  (`importlib.util.spec_from_file_location` against an absolute path) — not
  a path built by assuming a project root.
- The repository root resolves via `git rev-parse --show-toplevel` with
  `cwd` pinned to that same script directory (or an explicit `--repo`
  override, itself resolved through the same git call) — never the
  caller's cwd. Because `git worktree` gives each lane its own root, this
  is also what keeps the wrapper inside its own lane rather than reaching
  into another one: worktree isolation is preserved, not routed around.
- The actual `git push` runs with `cwd` pinned to that resolved repository
  root, never the caller's cwd.
- The one input taken from the caller's cwd is the `--declaration PATH`
  itself, exactly like naming any other file on a command line — and even
  there, admission recomputes everything the declaration claims rather
  than trusting it.

### Proof it works from an arbitrary cwd, `DIRECTLY_REPRODUCED`

Automated (`test_push_with_admission.py`, `ResolvesRepoRootIndependentOfCwdTests`
+ `EndToEndFromArbitraryCwdTests`, 9/9 passing):

```
test_a_missing_declaration_file_refuses_without_reaching_admission ... ok
test_a_missing_write_admission_module_is_a_setup_error_not_a_silent_allow ... ok
test_a_push_argv_naming_a_different_ref_than_the_declaration_is_rejected ... ok
test_a_refused_declaration_never_touches_the_remote_regardless_of_cwd ... ok
test_an_admitted_declaration_actually_pushes_regardless_of_cwd ... ok
test_dry_run_admits_but_never_pushes ... ok
test_an_explicit_repo_override_is_independent_of_cwd_too ... ok
test_default_resolution_is_stable_across_unrelated_working_directories ... ok
test_write_admission_module_loads_from_script_location_not_cwd ... ok

Ran 9 tests in 2.112s
OK
```

Manual, live, run from a directory four levels below `/tmp` with no
relationship to this repository:

```
$ mkdir -p /tmp/arbitrary-cwd-demo/deep/nested/dir && cd /tmp/arbitrary-cwd-demo/deep/nested/dir && pwd
/tmp/arbitrary-cwd-demo/deep/nested/dir

$ python3 /tmp/lane-i/workstreams/so02/control-plane/operating-environment/tools/push_with_admission.py \
    --declaration /tmp/lane-i/workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-I.json \
    --dry-run
WRITE_ADMITTED  target='cursor/scp-i-effective-controls-696d' operation='COMMIT_AND_PUSH'
  [pass] declaration    DECLARED_AND_REASONED
  [pass] concurrency    SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT
  [pass] reversibility  REVERSAL_RE_EXECUTED_AND_VERIFIED
  [pass] evidence       NO_RESULT_ASSERTED

ADMITTED (dry run, not executed): git push -u origin HEAD:refs/heads/cursor/scp-i-effective-controls-696d
EXIT: 0
```

No `--repo` was supplied — resolution ran entirely from the script's own
location via `git rev-parse --show-toplevel`, not from the deep,
unrelated cwd it was invoked from. A refusal case from `/` with a bad
declaration path, to show it does not silently allow when it cannot even
find its input:

```
$ cd / && python3 /tmp/lane-i/.../push_with_admission.py --declaration /dev/null --dry-run
REFUSED: no declaration file at /dev/null
EXIT: 1
```

### What this wrapper honestly is and is not

- It is **not dispatch-time enforcement**. A lane that never calls this
  script is exactly as unstopped as one that never went through the
  ambient hook. Nothing registers it in `.cursor/hooks.json`; nothing here
  fires on its own.
- It **is** voluntary-but-explicit, and that is a real improvement over
  ambient-and-absent: a lane that reads its own push-path documentation
  will hit this call, and once it does, the call cannot be satisfied by
  standing in the wrong place or by a declaration that doesn't match what
  actually gets pushed.
- It is **not a replacement for `lane_guard.py`**. This lane's own brief
  states, and this report repeats without softening: the only thing in
  this estate that is genuinely enforcing is `lane_guard.py` at
  integration time, because it reads remote bytes and the coordinator runs
  it regardless of what any lane chooses to do. This wrapper narrows the
  gap on the lane side; it does not close it.

**Constraint labels:** the wrapper's cwd-independence requirement is
`FOUNDER_AUTHORED` ("it must be impossible to satisfy by being in the wrong
directory" — this lane's brief, Part 1). Its refusal to overstate itself as
dispatch-time enforcement is also `FOUNDER_AUTHORED` (the brief's explicit
"do not overstate the wrapper" instruction). The `--repo` override
mechanism and the push-argv/declared-ref cross-check are `ASSISTANT_AUTHORED`
— inert unless ratified — added to close a gap the brief did not
anticipate (a caller could otherwise construct a push naming a ref the
admitted declaration never covered).

---

## Part 2 — the generalised effectiveness prober

**File:** `workstreams/so02/control-plane/operating-environment/tools/effectiveness_prober.py`
**Tests:** `workstreams/so02/control-plane/operating-environment/tools/test_effectiveness_prober.py`
**Sweep output:** `workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/EFFECTIVENESS-SWEEP-20260827-v001.json`
**Ambient-hook probe input:** `workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/AMBIENT-HOOK-PROBE-INPUT-20260827.json`

### Design

`.cursor/hooks/probe_hook_firing.py` was the correct template: arm, send
inert commands through the real execution path, check whether the control
actually observed them. `effectiveness_prober.py` generalises that pattern
into four possible verdicts:

- `EFFECTIVE` — installed, a probe ran, and the probe observed the control
  fire.
- `INSTALLED_NOT_EFFECTIVE` — installed, a probe ran, and the control did
  **not** observe what should have fired it. This is the class the founder
  named.
- `UNPROBEABLE` — installed, but no inert probe exists for this control's
  topology. **A control that cannot be probed is not a control** —
  `UNPROBEABLE` is a first-class verdict, never a silent pass.
- `NOT_INSTALLED` — the control is not even installed.

Two hard requirements, enforced in code, not just in prose:

1. **A probe must be inert.** No programmatic probe in this module performs
   the destructive act the control it tests exists to prevent (there is
   even a static self-check for this,
   `test_no_probe_ever_writes_to_the_real_origin_remote`, which greps the
   prober's own source for a real push and fails if one is found). Every
   programmatic probe runs against a disposable `tempfile` fixture — a
   scratch bare git remote and a throwaway checkout — never this
   repository's own history or its real `origin`, except for read-only
   `git ls-remote`/`git rev-parse` calls that touch nothing.
2. **`classify()` never certifies `EFFECTIVE` without a probe result
   showing the control fired.** `installed=True` with no probe (or a probe
   that ran but returned no verdict either way) is `UNPROBEABLE`, not a
   default pass. This is enforced by
   `ClassifyNeverCertifiesWithoutAProbeTests` and is exactly the shortcut
   this module exists to close.

### Per-control effectiveness table

All results below are `DIRECTLY_REPRODUCED` — every probe listed was
actually run in this lane's own environment on 2026-08-27, and its output
is shown, not asserted.

| # | Control | Verdict | Probe method | Key evidence |
|---|---------|---------|---------------|---------------|
| 1 | Write-scope ambient hook (`.cursor/hooks/guard_write_scope.py` via `beforeShellExecution`) | **`INSTALLED_NOT_EFFECTIVE`** | `probe_hook_firing.py --arm`, three inert commands sent through the agent's real Shell tool, then `--check` comparing the guard's append-only audit log line count before/after | Audit log `3 -> 3` lines across 3 commands (`git status --porcelain`, `git rebase --abort`, `gh workflow list`); guard passed at arm time by hand but recorded nothing when the same commands ran through the real tool path |
| 2 | Write-admission gate (`write_admission.py`) | `EFFECTIVE` | `admit({})` expected to refuse; `admit(well-formed declaration)` expected to admit, against a scratch ref addressing no real remote branch | `bad_declaration_verdict=WRITE_REFUSED`; `good_declaration_verdict=WRITE_ADMITTED` through all four gates (declaration, concurrency, reversibility, evidence) |
| 3 | Evidence-integrity validity check (`evidence_integrity.verify_artifact_validity`) | `EFFECTIVE` | Well-formed JSON (expect no findings) vs. a byte-truncated file (expect a validity finding), both hash-bindable, in a disposable temp dir | `errors_on_valid=[]`; `errors_on_truncated=["validity: truncated.json is hash-bound but does not parse as JSON ..."]` |
| 4 | Evidence-integrity read-back check (`evidence_integrity.verify_readback_truth`) | `EFFECTIVE` | Genuine record (git-clone-recomputed hash match) vs. a forged record naming commit `0`×40, both against a disposable local bare remote | `errors_on_genuine=[]`; `errors_on_forged=["readback: commit 000...0 is not retrievable from the remote; the claim is unfounded"]` |
| 5 | `lane_guard.py` | `EFFECTIVE` | Namespace containment / path-collision detection against synthetic fixtures, plus `verify_reported_head` against a deliberately absent branch name and a live read-only `git ls-remote --heads origin` | `containment_fires=True`, `collision_fires=True`, `absence_detection_fires=True`, `live_remote_read=True` |
| 6 | Currentness compiler (`currentctl.py`) | `EFFECTIVE` | `compile()` against this repository's own real git refs and ledger, read-only | `trunk_head=37943ec2...`, `ref_count=186`, `fail_closed=True`, 17 distinct finding types populated (not an empty report standing in for a healthy one) |

**Sweep totals:** 6 controls probed, **5 `EFFECTIVE`, 1
`INSTALLED_NOT_EFFECTIVE`, 0 `UNPROBEABLE`, 0 `NOT_INSTALLED`.**

Full machine-readable output, including per-control `method`/`detail`/
`evidence` blocks, is in `EFFECTIVENESS-SWEEP-20260827-v001.json`. That
file explicitly declares itself `"not_a_control_registry"`: it is the
output of one sweep run on one date against one commit, not a persisted
registry, and it does not replace `control-plane.json` or
`write-scope.json`.

**A note on `lane_guard.py`'s verdict.** The prober's probe attests to the
*mechanism* — that the script correctly detects namespace violations, path
collisions, and absent branches when invoked, and that it can read real
remote bytes via `git ls-remote`. Whether the coordinator *actually invokes
it* at every integration is a process guarantee this lane cannot probe from
inside its own worktree; that half is `DOCUMENTED`, deferring to this
lane's own brief's statement that "the only thing in this estate that is
genuinely enforcing is `lane_guard.py` at integration time, because it
reads remote bytes and the coordinator runs it" — `FOUNDER_AUTHORED`,
carried forward rather than independently re-verified.

**How many controls came back `INSTALLED_NOT_EFFECTIVE`: one** — the
write-scope ambient hook. That is the finding this lane's brief predicted
("Expect some to come back `INSTALLED_NOT_EFFECTIVE` — that is a finding,
not a failure of your work"), and it is exactly the finding Part 1's
wrapper exists to work around on the lane side.

---

## Part 3 — the regression

**File:** `workstreams/so02/control-plane/operating-environment/tools/test_effectiveness_prober.py`,
class `RegressionAssertedEnforcingWhileUnreachableTests` (3 tests)
**Harness:** the existing per-module convention already used by
`test_write_admission.py`, `test_lane_guard.py`, and this lane's own
`test_push_with_admission.py` — stdlib `unittest`, one `test_*.py` beside
each module, run individually under `python3 -I`. There is no single
aggregating runner in this codebase to add to; this is not a new or
competing suite, it is the test file for the module (`effectiveness_prober.py`)
whose `classify()`/`assert_effective()` the regression is about.

### The failing-before state, `DIRECTLY_REPRODUCED`

`test_before_any_explicit_gate_a_bare_push_is_not_stopped_by_config_alone`
builds a disposable git fixture (a scratch bare "origin" and a throwaway
checkout — never this repository's own remote), writes a
`.cursor/write-scope.json` into it with `require_write_declaration: true`
and **no declaration on disk anywhere**, then runs a bare `git push` with
**nothing in the path invoking any guard at all** — exactly the topology
of the real ambient hook that never fires in this lane's own worktree.

Result: the push succeeds (`returncode == 0`) and the remote head equals
local `HEAD`. Config asserting enforcement enforced nothing. This is the
failing-before state named literally: before any explicit gate is wired
in, a control that is merely configured to be "on" does not stop anything,
which is the entire reason Part 1 exists.

### The classifier must refuse to certify it, `DIRECTLY_REPRODUCED`

`test_the_live_probed_ambient_hook_result_fails_assert_effective` feeds
this lane's own real probe numbers (the same ones in
`AMBIENT-HOOK-PROBE-INPUT-20260827.json`: audit log `3 -> 3` across 3 inert
commands) into `assert_effective()` and requires it to raise
`ControlNotEffectiveError` naming both `INSTALLED_NOT_EFFECTIVE` and the
control. If a future change to `classify()` ever let this pass silently,
that change would have reintroduced the exact defect this lane exists to
make detectable.

A third test,
`test_a_regression_guard_a_naive_classifier_that_trusts_config_alone_would_pass_wrongly`,
names the specific wrong shortcut this regression guards against — trusting
`require_write_declaration: true` in config as a proxy for effectiveness,
which this lane's own brief records as the belief the coordinator itself
held and reported on 2026-08-23 — runs it side by side with the correct
`classify()` output, and asserts the two diverge, so nobody re-derives that
shortcut under a different name later and calls it fixed.

```
$ python3 -I workstreams/so02/control-plane/operating-environment/tools/test_effectiveness_prober.py -v
...
test_a_regression_guard_a_naive_classifier_that_trusts_config_alone_would_pass_wrongly ... ok
test_before_any_explicit_gate_a_bare_push_is_not_stopped_by_config_alone ... ok
test_the_live_probed_ambient_hook_result_fails_assert_effective ... ok
...
Ran 25 tests in 4.6s
OK
```

**Constraint label:** "a control asserted as enforcing while unreachable
must fail a test" is `FOUNDER_AUTHORED` (this lane's brief, Part 3, verbatim).

---

## Integration drift observed, `DIRECTLY_REPRODUCED`, informational

This lane's branch point is `f0fb3f51a25db67b33bdd558c73055f3d02ddb60`. A
mid-run re-fetch of `cursor/operating-environment-return-20260822-v001`
found it had moved to `379712b369616cffdb2dcf444c2dece163ebb173`, which
includes a shared-tooling change to `write_admission.py` by another lane
(concurrency gate ICH-08: an absent `ref_sha_at_observation` used to be
*skipped* rather than *refused* — itself another `INSTALLED_NOT_EFFECTIVE`
instance, found and fixed by that lane) and to the evidence gate
(`MANIFEST_CLOSURE` now also runs `verify_manifest_truth` and
`verify_artifact_validity`, not closure shape alone).

This lane did **not** merge, rebase onto, or otherwise pull that change
into its own branch — per this lane's hard boundary against writing
another lane's namespace, and because `tools/write_admission.py` was not a
file this lane needed to modify. This lane's own `write_admission.py`
therefore remains, deliberately, at the version present at its branch
point. All `WRITE_ADMITTED` verdicts reported in this document were
produced against that version, invoked from this lane's own worktree —
consistent, reproducible, and unambiguous about which version produced
them, but readers integrating this branch should be aware a newer
`write_admission.py` exists upstream with a stricter concurrency check.
This lane's own write declaration (below) was checked against both: it
passes the version in this lane's tree, and its `concurrency` block
carries an `observed_at` and a `note` explaining the Signal-1 limit, but
does **not** carry a `ref_sha_at_observation`, so it would need that field
added before it could pass the newer gate's stricter ICH-08 check if ever
re-run against it. Recorded here rather than silently left for the
coordinator to discover.

---

## Write declaration and admission verdict

**Declaration:** `workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-I.json`
**Reason code:** `PUBLISH_LANE_DELIVERABLE` (`asserts_result: false` —
this declaration does not assert a result; the delivered claims are
independently checkable in `receipts/so02/2026-08-27/scp-i/MANIFEST.json`)
**Reversal method:** `DELETE_CREATED_REF` (`git push origin --delete
cursor/scp-i-effective-controls-696d`)

Re-admitted before every push in this lane, most recently before the final
push described below:

```
WRITE_ADMITTED  target='cursor/scp-i-effective-controls-696d' operation='COMMIT_AND_PUSH'
  [pass] declaration    DECLARED_AND_REASONED
  [pass] concurrency    SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT
  [pass] reversibility  REVERSAL_RE_EXECUTED_AND_VERIFIED
  [pass] evidence       NO_RESULT_ASSERTED
```

---

## Files added, and why

All within the hard boundaries stated in this lane's brief:

- `workstreams/so02/control-plane/operating-environment/tools/push_with_admission.py`
  + `test_push_with_admission.py` — Part 1, shared tooling addition (new
  files, nothing existing modified).
- `workstreams/so02/control-plane/operating-environment/tools/effectiveness_prober.py`
  + `test_effectiveness_prober.py` — Part 2 + Part 3, shared tooling
  addition (new files, nothing existing modified).
- `workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-I.json`
  — this lane's one declaration, as instructed.
- `workstreams/so02/control-plane/operating-environment/scp-si-01/lane-i/**`
  — this lane's own namespace: the ambient-hook probe input, the
  effectiveness sweep output, and this report.
- `receipts/so02/2026-08-27/scp-i/**` — manifest and closure evidence (see
  `MANIFEST.json` in this same delivery).

No file belonging to Lane B, C, or D was read for the purpose of writing
to it, and none was written to. The one place this lane's work intersects
shared ground is `tools/write_admission.py` itself, which this lane reads
and calls but does not modify — see "Integration drift observed" above.

---

## Honest summary

Six controls were probed; five came back `EFFECTIVE` with probe output
shown, one came back `INSTALLED_NOT_EFFECTIVE` with probe output showing
exactly why. A regression now fails if any future change lets a control
be certified `EFFECTIVE` on the strength of its configuration alone,
reproducing, in a disposable fixture, the exact failing-before state that
made the ambient hook's defect real. A wrapper exists that any lane can
call to get the enforcement the ambient hook cannot currently provide,
proven to work from an arbitrary cwd — and this report says plainly, twice
now, that calling it is still voluntary, and that `lane_guard.py` at
integration time remains the only thing in this estate that enforces
regardless of what a lane chooses to do.
