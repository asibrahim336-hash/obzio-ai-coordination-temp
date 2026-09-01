# Work-unit contract and append-only run ledger

Activation module 1 of the transfer queue. Implemented, not specified.

## Provenance

| Field | Value |
|---|---|
| Implements | W18 Professional AI-Operator Intelligence and Method-Transfer Lab, activation module 1 of 3 |
| Source lane | `OBJ-LANE-W18`, ChatGPT Capability Factory project, conversation `6a8550e0-0e6c-83eb-afc3-b4679abaf66a` |
| Source model | 5.6 Sol, High effort. Worked 10m 49s. Frozen before the MetaMate return was admitted, so it is an independent comparator rather than an echo |
| Source artefact | `W18_PROFESSIONAL_AI_OPERATOR_INTELLIGENCE_FROZEN_2026-08-19.md`, report SHA-256 `8ae66de855f1b8078932d66a2acdc0e415461fdc75b1ee5294d5113c4f18a508` (attachment held in the source conversation; not yet migrated to a durable destination) |
| Built by | `obzio.appointment.strategic-operations-orchestration.20260819.001` |
| Built on | Operator sandbox, Python 3.11.15, stdlib only, no third-party dependency |
| Registered | `obzio_registry.objects` / `obzio_registry.claims` |

## The finding this implements

W18 sampled how strong practitioners actually run agentic operations, including durable methods predating current tooling, under an explicit constraint against generic advice. Its principal finding:

> Obzio does not primarily lack models, projects, prompts, or parallel operators. It lacks a portable work-unit contract, append-only execution state, receiver-verified handoffs, and trace-linked acceptance receipts. Increasing agent count before those controls exist should be rejected.

Its evidence base was structured handoffs, constrained agent interfaces, fixed workflows and provenance-controlled memory — I-PASS, SWE-agent, Agentless, and the memory-poisoning study — not generic agent best practice.

This module is the first two of those four controls, plus the test W18 named as the proof obligation.

## What is here

| File | What it is |
|---|---|
| `contract.py` | The portable work unit. Content-addressed seal, so a contract cannot be edited after results exist without its identity changing. Carries acceptance criteria, authority scope and an explicit forbidden list. |
| `ledger.py` | Append-only, hash-chained run ledger. Each event carries the previous event's hash, so any edit, reorder or deletion breaks every hash after it. Appends only — never re-reads whole state to write. |
| `runner.py` | A cold runner. Rebuilds execution state from the ledger alone: no conversation, no chat history, no in-memory carry-over. Write-ahead idempotency, so the intent is committed before the effect is applied. |
| `test_forced_interruption.py` | The proof. |

## Why the ledger appends rather than re-reads

This is not a style preference. The predecessor mechanism in this estate ran as a single turn over whole state against a provider ceiling sized per request, so its cost grew monotonically with the estate until it could no longer complete — 5m31s when state was small, then multi-hour hangs and infrastructure failures. A mechanism whose per-run cost scales with total state has that failure latent in it. Registered as `CLM-M02B-ROOT-CAUSE-20260819`.

## Running it

```
cd modules/work_unit_contract
python3 test_forced_interruption.py
```

Observed result, run three times consecutively, identical each time:

```
forced interruption, 8 kill positions: PASS
tamper-evident ledger:       PASS
contract seal enforced:      PASS
```

The interruption test kills the process before and after every step — eight positions, not one convenient position — and after each kill starts a genuinely cold runner that rebuilds the outside world from the ledger. It asserts on every position that resume completes, that acceptance passes against the sealed criteria, that no side effect is duplicated, that the effect set is exactly right, and that the hash chain still verifies.

## Honest residue

- **The tamper test was initially vacuous.** It edited a line that did not contain the target string, so nothing was altered and the reported FAIL was a defect in the test rather than the ledger. It now locates a real event and asserts the edit actually applied before drawing any conclusion. Worth stating because a test that cannot fail is worse than no test.
- **Two of W18's four controls are not built here.** Receiver-verified handoffs and trace-linked acceptance receipts are module 2. This module does not claim them.
- **The effects sink is in-process.** It stands in for the outside world. Binding it to a real side-effecting surface is the next step and will surface failure modes this test cannot reach.
- **Not independently reviewed.** Built by the producing operator. Adversarial review by a different model family is running in a separate lane and has not returned.

## Why this is an unmerged PR

Producer execution stays separate from acceptance. This branch is evidence that the module exists and passes its own test. It is not a claim that it should govern anything.
