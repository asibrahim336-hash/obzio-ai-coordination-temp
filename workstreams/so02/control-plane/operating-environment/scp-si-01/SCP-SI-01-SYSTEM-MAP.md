# SCP-SI-01 — system map

**Frozen at** `3b97d6ff5ed732c796adc0fd091f0125916079bd` on `cursor/operating-environment-return-20260822-v001`
**Read-only source** `so02/…-20260822-v001` @ `fe0a5952`
**Purpose of this file:** name what already exists so no lane rebuilds it. Every lane extends a row here or explains why it cannot.

## The single control plane — do not duplicate any row

| Function | Canonical artifact | State |
|---|---|---|
| Seed contracts + invariants | `workstreams/so02/control-plane/tools/scctl.py` | live, 55 tests |
| Hash-chained event log | `workstreams/so02/control-plane/state/events.jsonl` | 22 events, chain valid |
| Control-plane state | `workstreams/so02/control-plane/state/control-plane.json` | live; `prohibited_paths` voided, reason-gating in its place |
| Currentness compiler | `…/operating-environment/l4-currentness-recovery/tools/currentctl.py` | live, 71 tests, exits 1 by design |
| Admission ladder + workstream ledger | `…/l4-currentness-recovery/ledger/` | live |
| Lane integration guard | `…/operating-environment/tools/lane_guard.py` | live; protected-ref code retired |
| Evidence integrity | `…/operating-environment/tools/evidence_integrity.py` | live; read-back truth, allowlist capacity, manifest closure, artifact validity |
| Write admission | `…/operating-environment/tools/write_admission.py` | live; **enforcement voluntary, see below** |
| Write declarations | `…/operating-environment/write-declarations/` | 2 records |
| Provenance classifier | `…/w10-provenance/tools/provctl.py` | live, 86 constraints, 27 negative tests |
| Route evidence | `…/w7-route-evidence/ROUTE-EVIDENCE-TABLE-20260822-v001.json` | 27 routes |
| Platform roles + decision partition | `…/w4-platform-roles/` | `rolectl.py`, 14 invariants |
| ChatGPT constitution | `…/w8-chatgpt-constitution/` | `intentctl.py`, 16 injected failures |
| Operator launch guide | `…/operating-environment/AGENTIC-OFFICE-LAUNCH-GUIDE.md` | 890 lines — **RECONCILE, do not rebuild** |
| Founder standing authority | `.cursor/rules/00-founder-standing-authority.mdc`, `AGENTS.md` §0, `FOUNDER-STANDING-INSTRUCTION-20260822.md` | live, always-applied |

Living on the preserved CUR-01 evidence branch (`11a60dcf`), **not** here: `orchqual.py`, `INDEPENDENT-ACCEPTANCE-REQUEST-CUR-ORCH-QUAL-01.md`, `launch/OWNER-CREDENTIAL-ACTIONS-NOW.md`. `NOT_FOUND` on this ref is accurate and authorises nothing.

## The finding that governs how every lane must work

**Project hooks are NOT firing.** Directly reproduced: two commands that the guard refuses when run by hand both *executed* when sent through the agent shell tool, and the audit log gained no line. Cursor reads hooks from the project root `/workspace`; every lane works in a `/tmp` worktree.

Consequences, stated rather than softened:

1. `.cursor/write-scope.json` is **documentation**. Nothing in it refuses anything here.
2. `require_write_declaration: true` **cannot auto-refuse**. The coordinator told the founder on 23 August that enabling it would make every push require an admitted declaration. That was wrong, and this is the correction.
3. `write_admission.py` still refuses correctly **when invoked**. Enforcement is voluntary and lane-side.
4. Therefore every lane must run admission explicitly and attach the verdict. A lane that skips it will not be stopped by anything, and the coordinator will catch it only at integration.

This is the difference between a control and a description of one, and it is the same defect class as a rule written in prose and enforced by nothing — which this estate has now hit three times.

## What is genuinely open

- **CUR-ORCH-QUAL: REFUSED**, governing. `REQUESTED_NOT_GRANTED` on the CUR-01 branch is the earlier request state, frozen by design, and is not the current one. Two artifacts, one event each — not one event described twice.
- **868 tests / 19 failures and 117 portability findings** across the integrated tree. Fourteen of the 19 are whole-tree gates judged correct. Lane D owns triage; the suite is reported **failing** until it is not.
- **DEF-05/DEF-16** are halves of one thing: verify each artifact at its own commit, then compare to branch tip for supersession. Neither root alone is right.
- **DEF-21** was invisible to sequential fault injection. Any fencing or lease claim needs interleaving-aware testing. Chain validity does not imply fence uniqueness.
- **Portable memory** accepted only at schema 1.0 / index 159 / pointers 77 / hashes 5-5 / verifier 13-13. The later 1.1/123/126 receipt was refused as non-reproducible and is not state.

## Lane assignments, each extending a row above

| Lane | Extends | Must not create |
|---|---|---|
| A | CUR-ORCH-QUAL refusal record | a second acceptance track |
| B | `events.jsonl` + currentness projections | a competing ledger |
| C | authority index (928 items) | a replacement index |
| D | existing regression harness | a parallel test suite |
| E | `ROUTE-EVIDENCE-TABLE` | a new route registry |
| F | the authorship worker contract | a second adapter layer |
| G | cohort history | a ceremonial Cycle 0 |
| H | independent acceptance machinery | a producer-authored verdict |

## Provenance discipline

Every constraint any lane proposes states `FOUNDER_AUTHORED` (quote him), `EARNED` (name the defect), or `ASSISTANT_AUTHORED` (inert unless ratified). **An unclassified constraint is not in force**, including one inherited from this map. Git authorship is not founder authorship.

Three packet constraints are void by founder amendment: the credential prohibition, blanket append-only preservation, and the merge prohibition. Merge permission is full. Deletion is permitted with a snapshot and a reason. Credentials are handled as operationally useful, never echoed into a log, argv or committed artifact.
