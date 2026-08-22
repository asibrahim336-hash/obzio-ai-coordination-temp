# OE-L4 — currentness recovery

**Parent:** `OE-L4-CURRENTNESS-RECOVERY` under `COM-CUR-ENV-01-20260822-v001`
**Immutable start:** `fe0a595206e5986de7eaac6cabc619215a1eb81b`
**Terminal state:** `READY_TO_COMMIT`
**decision_changed:** `[]`

This lane owns one problem: scaled work in this estate cannot resolve its own
currentness, differentiation, admission state or provenance, so the founder ends
up being the correction mechanism. The instruction was explicit that the answer
is not to shrink the estate.

The lane ships a diagnosis and a mechanism. The mechanism is the point. A
markdown analysis would reproduce the exact failure it describes — a lesson
documented without changing anything that runs.

## Layout

```
tools/currentctl.py        the compiler and fail-closed gate
tools/build_diagnosis.py   derives the diagnosis from the projection
tests/test_currentctl.py   68 probes, mostly old-behaviour injections
ledger/                    the contracts and the transcribed repository claims
projection/                the addressable machine-readable current-state output
diagnosis/                 the generated diagnosis, JSON and Markdown
```

## Running it

Standard library only. No packages, no network beyond the git remote already
configured, no provider access.

```
python3 -I .../tools/currentctl.py validate     # fail-closed gate, exits 1 on any ERROR
python3 -I .../tools/currentctl.py compile --out .../projection/CURRENT-STATE-PROJECTION-20260822-v001.json
python3 -I .../tools/currentctl.py project      # the projection on stdout
python3 -I .../tools/currentctl.py resolve --scope pointer.operator-system
python3 -I .../tools/currentctl.py reproduce    # re-runs every REPRODUCIBLE_COMMAND
python3 -I .../tests/test_currentctl.py
```

`validate` currently exits 1 against this repository. That is the correct
result, not a defect to fix.

## What the mechanism actually enforces

**Currentness is compiled, not declared.** The ref graph is built from
`git for-each-ref` and a containment DAG over `git rev-list --topo-order --all
--parents`. A branch is `ACTIVE` because a pull request or the group manifest
addresses it, `SUPERSEDED` because another head already contains it, `ORPHANED`
because it shares no ancestry with the trunk. Never because of its name or its
date.

**Competing claims fail closed.** A currentness *scope* is a logical pointer
identity realised by one or more paths. `resolve` reads the blob for that scope
on every live branch. If two live branches hold different bytes and no
supersession edge is declared, it refuses and exits 1. It does not take the
newest, the nearest or the majority — seven branches agreeing against one is
still unresolved, because agreement by copying is not authority. Declaring which
side lost is a founder-bound or independently-evaluated act, and the tool accepts
the answer the moment someone records it in `ledger/currentness-scopes.json`.

**Admission is evidence-gated and monotonic.** `PROPOSED → LAUNCHED → OBSERVED →
DURABLE → INDEPENDENTLY_VALIDATED → ACCEPTED`. Each rung names the evidence
classes it requires. Eleven classes are recorded but can never lift a subject
above `PROPOSED`: an open pull request, a branch existing, a ZIP, a file count, an
agent existing, a prompt sent, an acknowledgement, a provider `completed` status,
a receipt count, a documented mechanism and a documented lesson. Evidence for a
later stage does not backfill an earlier one, so a launch with no commission
behind it is held and named rather than silently downgraded.

**Evidence must be reachable now.** A `COMMITTED_ARTIFACT_HASH` must name a path
that exists and hashes to the claimed value. A `REPRODUCIBLE_COMMAND` must carry
an argv, and `reproduce` re-runs it. A locator must be stable — a display or
session alias such as `current_project_conversation` is rejected, because an alias
resolves to whatever the reader happens to be looking at. A `REMOTE_READBACK_HASH`
pinned to a commit the ref has since moved past is reported as stale.

**A producer cannot accept its own work.** `INDEPENDENT_EVALUATION` requires an
evaluator identity distinct from the producer identity.

**Commissions must differentiate.** Two active commissions may not both assert
whole-operation authority over an overlapping namespace without a supersession
edge. One identifier naming two documents is an addressability failure. An active
commission absent from `state/operator-system/COMMISSION_REGISTER.jsonl` cannot
resolve the five things `AGENTS.md` rule 8 requires.

**Everything is addressable and carries provenance.** Every assertion in the
projection has a `urn:obzio:l4:<kind>:<name>` address and a provenance record
labelled `DIRECTLY_REPRODUCED`, `DOCUMENTED` or `HYPOTHESIS`.

**The projection hash is a pure function of repository state.** No wall clock
enters it, so two runs over the same refs produce the same
`projection_sha256` and a change in the hash means the estate moved.

## Extending it

Adding a workstream, a commission or a currentness scope is a ledger edit, not a
code change. Adding a new evidence class requires editing
`ledger/admission-ladder.json`; an unregistered class raises
`EVIDENCE_CLASS_UNKNOWN` rather than being trusted by default.

## Boundaries

This lane writes only inside its own namespace and
`receipts/so02/2026-08-22/oe-l4-currentness-recovery/**`. It reads every other
branch and every pull request and modifies none of them. It deletes nothing:
superseded refs and files stay as evidence, and
`diagnosis/DIAGNOSIS-L4-20260822-v001.json` proposes explicit disposition instead.
It binds no strategy.
