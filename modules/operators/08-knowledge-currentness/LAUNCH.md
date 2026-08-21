# LAUNCH — pack 08 · knowledge-currentness

## Entry point

```bash
cd 08-knowledge-currentness
python3 test_pack.py
python3 checks.py <workdir>
```

```python
import checks, state_machine as sm
from _spine import AcceptanceGate, IndependentAcceptor

# pin once, deliberately, by a named principal
board = sm.Pinboard("/var/obzio/pins.json")
board.pin("schema", "/srv/app/schema.yaml", by="ahmed")

run = sm.KnowledgeCurrentnessRun(
    workdir="/var/obzio/currentness/<run_id>",
    producer_id="operator-08",
    gate=gate,
    pinboard_path="/var/obzio/pins.json",
    max_staleness_s=60.0,
)

run.preflight()        # PREFLIGHT
run.recover_state()    # CURRENT_STATE_RECOVERED - prior verdicts DISCARDED, on the record
run.admit_pins()       # INPUT_ADMITTED
run.audit()            # ACTION_EXECUTED - a fresh full-byte read per pin
report = run.publish() # REQUIRED_ARTEFACTS_PRESENT
run.machine_checks()   # MACHINE_CHECKS_PASSED  <-- producer stops here
# COMMIT-FIRST ACCEPTANCE
import acceptance
from _spine import CommitFirstAcceptor
objective = acceptance.objective_for("/var/obzio/pins.json", ["schema"], 60.0)
acc = CommitFirstAcceptor("acceptor-QA", gate,
                          derive=acceptance.derive_expectation,
                          compare=acceptance.compare_to_expectation)
run.finish(acc, objective)   # the acceptor reads the pinned paths itself, first

sys.exit(report["exit_code"])   # 0 only for CURRENT
```

## Read this before wiring it into a dashboard

**A run that finds drift is a successful run.** `machine_checks()` asserts the
*audit was performed honestly*, not that the world is healthy. Drift travels in
`report["status"]` and `report["exit_code"]`, not in the pass/fail of the run.

Wire your alerting to `exit_code`, and your "is this control alive?" monitoring
to `comparisons_performed` and `reads_performed`. A currentness control that
stops running looks identical to one that keeps saying MATCH — which is the
whole reason this pack exists.

| status | exit | meaning |
|---|---|---|
| `CURRENT` | 0 | every pin compared this run, every one matched, no evidence went stale |
| `DRIFT` | 1 | at least one pin changed or vanished |
| `DEGRADED` | 1 | a MATCH was demoted to UNKNOWN because its evidence aged past the ceiling before publication |
| `INCOMPLETE` | 1 | a pin on the board was never compared this run |

`UNKNOWN` is never an assertion of health. There are four verdicts and only
one of them means "fine".

## Mandate

Compare pinned expectations against live state and report, per pin, whether
they still agree — where "agree" is only sayable on the strength of bytes read
during this run.

## Maximum delegated authority

| | |
|---|---|
| Reads | the pinned paths, in full, every run |
| Writes | `workdir` only |
| May never | write to a pinned path; re-pin; reuse a prior run's verdict; report `CURRENT` on partial coverage |
| Re-pinning | a human act. `Pinboard.pin()` takes `by=` and is not called anywhere in the run lifecycle. |
| Phase reachable alone | `MACHINE_CHECKS_PASSED` |

Re-pinning is the dangerous operation in this domain: it makes drift disappear
by redefining the expectation. It is deliberately not reachable from any run
method. If drift is legitimate, a human re-pins and the next run goes green
with a new `pinned_at` and `pinned_by` on the record.

## Escalate, do not improvise

- `UnbackedVerdictRefused` — something tried to publish a verdict this run did
  not derive. Do not retry. Find out what produced it.
- A `mtime_shortcut_disagreements` entry — content changed while mtime was
  preserved. That is not normal file behaviour. Ask who wrote it.
- `DEGRADED` recurring — the gap between reading and publishing is too long;
  the pipeline is slow enough to make its own answers stale.
