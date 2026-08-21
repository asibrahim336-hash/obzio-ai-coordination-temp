# LAUNCH — pack 06 · browser-execution

## Entry point

```bash
cd 06-browser-execution
python3 test_pack.py                  # prove the pack before trusting it
python3 checks.py <workdir>           # audit any run directory, exit 0/1
```

Programmatic entry — this is the whole sanctioned lifecycle:

```python
import checks, state_machine as sm
from _spine import AcceptanceGate, IndependentAcceptor

gate = AcceptanceGate.from_keyfile("/etc/obzio/acceptance.key")   # acceptor-owned
run  = sm.BrowserExecutionRun(
    workdir="/var/obzio/runs/<run_id>",
    producer_id="operator-06",
    gate=gate,
    allowlist=["@ops-alpha"],        # every permitted recipient, explicitly
    max_sends=1,                     # hard cap on delivered messages
    task_id="T-1",
)

guard = run.preflight(LiveSurface())     # PREFLIGHT
run.recover_state()                      # CURRENT_STATE_RECOVERED (replay-safe)
run.admit_input(targets, messages)       # INPUT_ADMITTED
run.execute(targets, messages,           # ACTION_EXECUTED
            recover=lambda t: surface.navigate(t.conversation_id))
run.artefacts_present()                  # REQUIRED_ARTEFACTS_PRESENT
run.machine_checks()                     # MACHINE_CHECKS_PASSED  <-- producer stops here
# COMMIT-FIRST ACCEPTANCE
import acceptance
from _spine import CommitFirstAcceptor
objective = acceptance.objective_for(targets, messages, allowlist, 1, "T-1")
acc = CommitFirstAcceptor(
    "acceptor-QA", gate,
    derive=lambda obj: acceptance.derive_expectation(obj, surface),
    compare=acceptance.compare_to_expectation)
run.finish(acc, objective)   # precommit -> window -> one-bit decision
```

`LiveSurface` is the only thing you write. It implements two methods against
whatever browser tool you actually have:

```python
class LiveSurface(sm.Surface):
    def observe(self) -> sm.Observation:   # read conversation_id, recipient
                                           # handle, thread title, compose count,
                                           # focused compose id, mutation counter
    def do_send(self, text) -> str:        # click send, return a message id
```

Everything below `observe()` treats the surface as **adversarial and unstable**.
Do not "clean up" values inside `observe()` — report what the DOM says, including
when it says something unexpected. Normalising a wrong conversation id into the
expected one inside the adapter defeats every control in this pack.

## Mandate

Drive a browser surface to complete one delivery task, and deliver **only** into
the conversation named in the intended `Target`.

## Maximum delegated authority

| | |
|---|---|
| Sends per run | `max_sends`, hard-capped at construction; refusal code `MANDATE_EXCEEDED` |
| Recipients | only handles in `allowlist`; refusal code `RECIPIENT_NOT_ALLOWED` |
| Route-recovery retries | `max_route_retries` (default 2), each one a full re-verify |
| Content | the exact strings passed to `admit_input`; the pack never composes text |
| Phase reachable alone | `MACHINE_CHECKS_PASSED` and no further |
| Never delegated | changing `allowlist` or `max_sends` mid-run; accepting its own work; deleting or editing `route_ledger.jsonl` |

The producing process cannot raise its own ceiling. `max_sends` and `allowlist`
are read into `run.mandate` at construction and written into the PREFLIGHT ledger
entry; `checks.py` re-reads the cap from that entry and fails the run if the
delivered count exceeds it, so a mid-run mutation of the in-memory value is
caught by the audit even if it were attempted.

## Escalate to a human, do not improvise

- `Misroute` on a target you believe is correct — the pinned target may be stale.
- `AmbiguousSurface` that persists — more than one compose surface open means the
  operator's mental model of the page is wrong.
- Route recovery exhausting `max_route_retries` — something is actively moving
  the surface. Stop. Do not raise the retry count.
