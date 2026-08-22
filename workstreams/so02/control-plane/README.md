# SCF-01 — Obzio Strategic Coordination Function

`SCF-01` is the provider-independent strategic coordination function for Obzio. `OCP-INT-01` is its interim control-plane implementation. This directory seeds operation across Cursor, SW and ChatGPT while preserving a later cutover to an Obzio-controlled open-source runtime.

This is a continuation of the active programme. It does not restart `PO-01`, `PO-02`, `PO-03`, Manus or the company strategy.

## Current authority and state

- `SO-02` remains the active strategic operator until the cutover gates in `state/control-plane.json` are independently passed.
- `SCF-01/CUR-01` is the primary machine-orchestration candidate and candidate coordination-kernel principal. It is not promoted until a route-agnostic live qualification proves the strongest practical combination; native ChatGPT Projects visibility is optional.
- `SCF-01/SW-01` is the parallel SW strategy-discovery, coworker/workspace, HTML/presentation and capability-synthesis specialist. It is not the required central coordinator.
- `SCF-01/CGPT-01` is the active ChatGPT founder-interface, strategy-interlock, independent-synthesis and continuity principal.
- `SCF-01/OSS-01` is the future Obzio-controlled open-source successor binding; it is not yet qualified.
- Founder strategy decisions remain founder-bound. `decision_changed: []`.

Provider identity is a runtime binding, not a role identity. Replacing a provider must not replace the strategic function, its ledger or its evidence.

Stable runtime locations are tracked in `state/runtime-surface-locators.json`. Display
names and provider memory are not locators. New provider surfaces record exact URLs
or provider IDs, immutable resume checkpoints and return paths; unavailable IDs are
reported as `NOT_EXPOSED`, never fabricated.

Stable institutional IDs use object classes rather than provider names: `SS` strategy snapshot, `FN` function, `APT` appointment, `RTI` runtime instance, `OP` operation, `WV` wave, `WU` work unit, `ATT` attempt, `EVT` event, `CLM` claim, `HYP` hypothesis, `REP` reproduction, `MCH` mechanism change, `CAP` capability, `EVAL` evaluation, `PRP` proposal, `DEC` founder decision, `FACT` founder action, `ART` artifact, `RCPT` receipt and `SUC` successor. Provider project, space, agent, run and thread IDs are locators attached to those objects.

## Canonical operating rule

The repository and its immutable commits are the durable coordination source. Provider chats, memories, task statuses and callbacks are observations until committed, read back and reconciled here.

The operation has two simultaneous planes:

1. current-plan execution;
2. continuous discovery of superior strategies, methods, opportunities, capabilities, models, tools, topologies and successors.

Neither plane may silently suspend the other.

## State model

`DRAFT → COMMISSIONED → EXECUTING → OUTPUT_OBSERVED → DURABLE → INDEPENDENTLY_VALIDATED → ACCEPTED → SUPERSEDED | RETIRED`

Provider `completed` is never an Obzio lifecycle state. A mechanism described in a document is not operational. A launch instruction is not execution. A producer test is not independent acceptance.

Mechanism maturity is separately tracked as `DESCRIBED → SPECIFIED → IMPLEMENTED → UNIT_TESTED → INTEGRATION_TESTED → LIVE_CANARY → OPERATIONAL → INDEPENDENTLY_ACCEPTED → SUPERSEDED`. Nothing below `LIVE_CANARY` may be called active.

## Required compounding loop

`operate → observe → measure → challenge → research → discover → reproduce → learn → change live mechanism → independently test → retain/delete/supersede → launch stronger successor → repeat`

Every wave must leave a task result and a measured change to the system that generates the next wave. Activity volume, worker count, receipts or a successor document are insufficient.

## Start here

1. Run `python -I workstreams/so02/control-plane/tools/scctl.py validate`.
2. Read `state/control-plane.json` and `state/events.jsonl`.
3. Read `state/runtime-surface-locators.json`, resolve a stable surface locator and verify the immutable resume checkpoint.
4. Execute the relevant commission in `commissions/`.
5. Record runtime identity and every state transition before claiming execution.
6. Use `launch/` for the exact founder-side provider actions.
