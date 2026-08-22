# PO03-WA-052 — function, appointment, runtime and provider stay orthogonal

- Task: `PO03-WA-052`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Ontology checks separate function, appointment, runtime, and provider identity.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`ontology_guard.py` turns the repository-wide operator rules into an executable
resolver over four axes. Two of them bear authority (`function`, `appointment`)
and two are execution evidence only (`runtime`, `provider`). `resolve()` refuses
a record whose axes leak into one another; `authority_source()` refuses to read
authority from a runtime or provider binding at all.

Two continuity operations encode the rules that a runtime never grants authority
and a rename never removes standing permission:

- `rebind_runtime()` moves the runtime/provider binding and keeps the
  appointment, function and authority envelope, filing the old runtime as
  provenance;
- `rename_function()` is additive — the previous function name becomes
  provenance and the authority envelope survives.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 21 tests — OK
```

## Hidden and adversarial cases

Six cross-axis leaks are each asserted to raise: a runtime label on the function
axis, a provider model on the function axis, a provider model on the appointment
axis, a function identifier on the runtime axis, a runtime label on the provider
axis, and a rename into a runtime label. Every legacy alias in the register is
swept as a function value and must be refused, then the same aliases are asserted
to survive intact in the alias field — the rule constrains routing without
deleting historical evidence.

## Limitations

- Axis inference for runtime and provider values works from an explicit
  vocabulary. An unrecognised runtime name is classified as unknown and passes
  the leak check, so the guard is sound against the named surfaces rather than
  against every possible label.
- The function and appointment patterns are `obzio.*` shaped. A future namespace
  would need the patterns extended; the guard fails closed by refusing the record
  rather than silently accepting it.
- Alias resolution to a single principal is `PO03-WA-050`. This component checks
  the *shape* of an actor record and deliberately does not duplicate that work.

## Disposition

**PASS** — the four axes resolve independently, authority is unreadable from a
runtime or provider binding, and both rebinding and renaming preserve the
appointment and the authority envelope.
