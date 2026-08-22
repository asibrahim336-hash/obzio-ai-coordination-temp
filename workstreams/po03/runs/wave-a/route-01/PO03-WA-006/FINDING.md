# PO03-WA-006 — post-commit loss recovers without rerunning external effects

- **Task:** `PO03-WA-006`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-006-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** Post-commit process loss is recovered without rerunning external effects.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`effect_journal.py` wraps every external effect in a three-phase write-ahead
protocol: journal `INTENT` with a deterministic effect key, perform the effect,
journal `APPLIED`. The dangerous window is the gap between performing the effect
and recording it — a process that dies there returns believing the effect is
still outstanding, and naive resumption performs it twice.

For a key with `INTENT` and no `APPLIED` the outcome is genuinely unknown, and
both guesses are wrong: assume it failed and you double-spend, assume it
succeeded and you lose the work. Recovery therefore **probes the external system
by effect key** and reconciles from observed truth rather than inference.

## Measured at the effect, not at a status field

`ExternalSystem` counts real executions per key. Every assertion is made against
that counter, so a component that merely updates its own state field cannot pass
this suite. Each recovery runs in a **fresh workflow object** over the same
durable directory, so nothing held in the crashed object's memory can help.

## Commands and observed results

```
$ python3 effect_journal.py --demo             # exit 0
$ python3 -m unittest -v test_effect_journal   # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 14 tests, **14 passed, 0 failed**, exit 0. All passed on first execution.
- Crash matrix over all five protocol points:
  `max_executions_for_any_key = 1`. No crash point produced a duplicate effect.

| Crash point | Recovery action | Executions |
| --- | --- | --- |
| `before_commit` | `RESTART_FROM_SCRATCH` | 0 |
| `after_commit_before_intent` | `EFFECT_APPLIED_FIRST_TIME` | 1 |
| `after_intent_before_effect` | `PROBE_SHOWED_NOT_APPLIED_SO_APPLIED` | 1 |
| `after_effect_before_applied` | `CONFIRMED_BY_PROBE_JOURNAL_REPAIRED` | 1 |
| `after_applied` | `ALREADY_COMPLETE_NO_ACTION` | 1 |

- The hazard case in detail: after a crash between the effect and its record,
  the effect had genuinely executed once and the journal showed only `INTENT`.
  Recovery probed once, repaired the journal to `APPLIED`, and left the
  execution count at 1.
- Recovery is idempotent: running it four more times at every crash point never
  raised any key above one execution.
- A completed effect needs no probe (`probes = 0`), so reconciliation costs
  nothing on the common path.
- **Unprobeable external system:** where the effect key cannot be observed
  externally, recovery returns `RECONCILIATION_NOT_SUPPORTED` and
  `obzio_state = RECOVERY_REQUIRED` rather than guessing. The execution count
  stays at 1. This is the honest answer, and the blind matrix still never
  duplicates an effect.

## Limitations

- At-most-once across a crash **requires an externally observable effect key**.
  Where the target cannot be probed the component reports `NOT_SUPPORTED`; it
  does not manufacture a guarantee the target cannot provide.
- Process loss is raised in-process rather than by `SIGKILL`. It exercises the
  protocol's state transitions, not the operating system's write-back behaviour.
- The probe is assumed truthful and immediately consistent. A target with a
  read-after-write delay could return a false negative and cause a genuine
  duplicate; that risk is real and is not mitigated here.
- One effect per task is modelled. Multi-effect workflows would need per-effect
  keys and an ordering rule, which is not implemented.
- `decision_changed: []`.
