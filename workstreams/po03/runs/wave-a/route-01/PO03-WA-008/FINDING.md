# PO03-WA-008 — a recovery scan deterministically resumes every nonterminal task

- **Task:** `PO03-WA-008`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-008-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** A recovery scan deterministically resumes every nonterminal task.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`recovery_scan.py` folds an append-only event ledger into a per-task position
and emits a resume plan. The hypothesis contains two independent claims, and the
component addresses each structurally rather than by convention.

**Completeness** is obtained by construction: the plan is built by iterating the
**task roster**, not the events. A task with no events at all is still planned,
as `CREATED → DISPATCH`. An event referencing a task outside the roster is
reported as an orphan rather than quietly planned. A position with no declared
resume action raises `UnknownPosition` instead of being skipped, so the action
map is total over nonterminal states.

**Determinism** is obtained by total ordering on `(event_seq, task_id)`,
collapsing duplicate events by content digest, and emitting the plan sorted by
task id under canonical serialisation with no timestamps. Nondeterminism is the
more insidious of the two failure modes — a scan that is merely usually right
looks fine until the run that matters.

`verify_plan` re-derives the coverage invariant independently of how the plan
was produced, and the suite shows it can fail: a dropped entry, a mislabelled
action and a reordered list are each detected.

## Commands and observed results

```
$ python3 recovery_scan.py --demo            # exit 0
$ python3 -m unittest -v test_recovery_scan  # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 17 tests, **17 passed, 0 failed**, exit 0. All passed on first execution.
- Synthetic wave of 24 tasks: 21 resumed, 3 terminal, coverage exactly the
  roster with no duplicates, `coverage_problems = []`.
- 25 shuffled permutations of one ledger produced **1 distinct plan hash**
  (`59970acf21e375d7af0b00d153d3c25578d22df620ff6c5ebb3cfe559fa2f8dd`) with no
  mismatched permutations. Determinism held across 10 further seeds.
- Tripling every event left the plan hash unchanged, so an at-least-once ledger
  writer cannot alter the outcome.
- Determinism is not achieved by ignoring the input: appending one event changes
  the plan hash.
- Every one of the 12 nonterminal positions yields exactly one resume action;
  resume always advances the fence (`fence 4 → next_fence_token 5`).
- Orphan event `PO03-WA-999` was reported and not planned.
- False completion — `COMPLETED` with no durable locator — is detected
  separately from legitimate terminal states.

### Negative control

An order-sensitive fold, the naive "last line wins" scan, was driven through the
identical 40 shuffles and produced **more than one** result for the same task,
confirming the shuffle genuinely exposes nondeterminism. The guarded fold
returned `RESULT_STAGED` on all 40, the highest `event_seq` winning every time.

## Limitations

- Determinism is over ledger *ordering*, duplication and permutation. It is not
  a claim about determinism across ledger *content* changes, which correctly
  produce different plans.
- The scan plans resume actions; it does not execute them. Whether each action
  is itself safe to re-run is the subject of `PO03-WA-006`.
- Event validity is assumed. A ledger with a corrupted or reused `event_seq`
  across genuinely different events would fold incorrectly, and this component
  does not authenticate the ledger.
- The synthetic wave is seeded and reproducible but is a fixture, not observed
  production traffic.
- `decision_changed: []`.
