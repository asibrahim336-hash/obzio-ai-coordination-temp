# Reason-gated writes

**Lane:** OE-W9-REASON-GATED-WRITES · **Commission:** COM-CUR-ENV-01-20260822-v001
**Authority:** Ahmed Sadek, standing amendment 2026-08-23 — the "protected surface" category is VOID
**Verbatim record:** `../FOUNDER-STANDING-INSTRUCTION-20260822.md`

The write-scope guard used to ask *is this target on the forbidden list?* It now
asks *was this write declared and reasoned?* Those are different questions, and
only the second one was ever the founder's.

> "It is void as a category. Every surface in the Ahmed/Obzio-controlled estate
> is writable under my authority — main, every PR branch, every source branch,
> every PO lane, every repository, every project, every connected service. No
> surface is off-limits because of a name on a list."
>
> "You do not need my permission for any of it — you need a reason and a rollback."

**This is not a shorter denylist.** No module here holds a list of refs. Tests
assert that the same declaration is admitted against `main`, a `cursor/po03-*`
branch, an `so02/*` source branch and a scratch branch, and that the strings
`PROTECTED_REFS`, `PROTECTED_PREFIXES` and `protected_branch_globs` appear in no
executable code.

## What ships

| File | Role |
|---|---|
| `tools/write_declaration.py` | the schema and its pure validation |
| `tools/concurrency_observer.py` | gate 1, observed at a moment |
| `tools/reversal_rehearsal.py` | gate 2, constructed and executed |
| `tools/write_admission.py` | the composed guard; gate 3 delegates to `evidence_integrity.py` |
| `.cursor/hooks/guard_write_scope.py` | the client-side refusing hook, re-founded |
| `.cursor/write-scope.json` | its declarative source, with the protected keys deleted |
| `PROVENANCE-CLASSIFICATION.json` | every constraint kept, introduced or retired, with its class |
| `WRITE-DECLARATION-OE-W9.json` | this lane's own write, declared under its own schema |

191 tests: 138 in `tools/`, 16 in `.cursor/hooks/`, plus the pre-existing suites.

## The declaration

```json
{
  "declaration_version": "1.0",
  "declared_by": "...", "declared_at": "ISO-8601 UTC",
  "target":  { "ref": "...", "paths": ["..."], "operation": "COMMIT_AND_PUSH" },
  "reason":  { "code": "<closed vocabulary>", "statement": "...", "<required fields per code>": "..." },
  "reversal":{ "method": "<closed vocabulary>", "command": ["argv"], "<custody per method>": "..." },
  "evidence":{ "asserts_result": true, "kind": "READBACK|MANIFEST_CLOSURE", "record": { } },
  "concurrency": { "observed_at": "...", "ref_sha_at_observation": "...", "agents": [ ] }
}
```

**Reason** is a closed vocabulary: `INTEGRATE_RETURNED_LANE`,
`PUBLISH_LANE_DELIVERABLE`, `REPAIR_BROKEN_CONTRACT`, `RECORD_FOUNDER_INSTRUCTION`,
`RETIRE_SUPERSEDED_SURFACE`, `SNAPSHOT_CUSTODY`, `CORRECT_PUBLISHED_ERROR`.

A closed vocabulary by itself would only shorten the list of strings that always
pass, so two further things make a reason falsifiable:

1. **Each code carries required fields** that are false when the reason is not
   live. `INTEGRATE_RETURNED_LANE` without a `lane_head_sha` is not a reason.
   Each code also records `expires_when`, because the founder's gates expire.
2. **The statement must name its own target** — the ref or one of the declared
   paths. A statement true of every write in the estate distinguishes none of
   them. This is the same defect that mis-certified `FB-11`: the classifier read
   commit authorship, a signal identical for every commit here, and so decided
   on evidence carrying no per-item information.

**Operation** and **evidence kind** are closed too, because an open field admits
every value nobody enumerated — the failure that let `ERROR` and `FAILED` pass
`capacity_verdict` silently.

Whether a write asserts a result is decided by its **reason code**, not by the
declarer. Otherwise any write could self-certify that it asserts nothing and the
evidence gate would be optional.

## Gate 1 — concurrency, and what it cannot see

> "Do not corrupt work in flight. PO-03 has live top-level runs; a write that
> would disturb a running lane waits for that lane to finish — not forever. When
> it completes, the gate is gone."

Concurrency is a property of a target **at a moment**, not of its name. The
observer holds no branch list; the same ref is refused and admitted by the world
alone, and a test asserts exactly that.

**Signal 1 — the agent layer.** `cursor-cloud list-cloud-agents` is read-only and
reports each accessible run's `status` and `branchName`. Settled statuses are an
**allowlist** (`IDLE`, `ERROR`, `ARCHIVED`, `EXPIRED`, `COMPLETED`, `FINISHED`);
every other status, including ones this code has never heard of, counts as
possibly in flight. This matters concretely: in both captures no agent was
`RUNNING`, but the root controller was `WAITING_FOR_BACKGROUND_WORK` on
`cursor/so02-cur-orch-qual-01`. A denylist naming only `RUNNING` would have
admitted a write to a branch whose subagents were still working.

**The hole, reproduced twice.** At 03:40Z and again at 04:08Z this lane called
that tool while itself running against
`cursor/oe-w9-reason-gated-writes-696d`. Its own branch was absent from all 13
returned agents both times; sibling lanes running as subagents were likewise
absent, and only top-level runs carried a `branchName`. **A writer can be fully
live and completely invisible.** Absence from the list is not idleness.

**Signal 2 — remote ref movement.** An invisible writer still has to move the
remote ref to do damage. Comparing the ref now against
`ref_sha_at_observation` catches a writer signal 1 cannot see.

The admitting verdict is named `SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT` rather than
anything resembling "clear", and it carries the limit in its own payload.

**The residual hole, stated rather than glossed:** a writer that is live but has
not yet pushed is invisible to both signals. Closing it needs a claim or lease
protocol that writers take before writing — a design decision, not a defect fix.

## Gate 2 — reversibility, executed rather than described

> "Snapshot before an irreversible write: tag, archive, recorded SHA. That is
> custody, not protection."

A prior lane published a documented revert procedure that did not work when it
was executed. Prose cannot be run, so it was never tested until it was needed.
Here, `build_reversal` is the single source of the argv for both the rehearsal
and the declaration, and every reversal is executed against a real disposable
bare remote before it is offered. `origin` is never touched.

**The gate caught its own author.** The first `REVERT_COMMIT_RANGE` constructor
used `git revert --no-edit --no-commit`, which stages the revert without
committing it, so the follow-up push republished the unchanged post-write commit,
exited 0 and restored nothing. The rehearsal returned `REVERSAL_DID_NOT_RESTORE`.
The constructor was fixed and a test keeps it fixed.

Three things the verification does that a naive one would not:

- **Compares the tree, not the exit code.** `git revert` exits 0 on a
  conflict it auto-resolved wrongly, and `git push` exits 0 having done nothing.
- **Compares the tree, not the commit SHA.** A correct forward revert is a *new*
  commit with the *same* tree; comparing commit SHAs would fail every correct
  revert and would look strict while being wrong.
- **Requires the rehearsed write to have changed something.** A reversal passes
  trivially if there was nothing to reverse, so that reports
  `REHEARSAL_PROVED_NOTHING`.

Four sabotage modes (`noop`, `wrong_sha`, `unrelated_command`, `partial_restore`)
are tested to fail, because a rehearsal that cannot fail is not evidence.

**What the rehearsal does not prove,** and says so in its own receipt: that the
live remote will accept the push at rollback time. Server-side ref rules,
credentials and a concurrent writer are outside a local fixture's reach.

## Gate 3 — evidence, delegated not reimplemented

> "A write that asserts a result carries the evidence for that result. The
> problem was never the target of a write; it was unverified writes."

`write_admission` hands the record to `evidence_integrity.verify_readback_truth`
or `verify_manifest_closure`. Those corrections were earned by an independent
acceptor's refusal and re-deriving them here would fork them; a test asserts the
reimplementation is absent. An evidence kind with no recomputation route fails
closed, and a `READBACK` record with no remote to recompute against returns
`EVIDENCE_UNVERIFIABLE_HERE` rather than passing.

## Nothing the declaration says about itself is believed

| The declaration says | The guard does |
|---|---|
| "my reversal was rehearsed and it worked" | re-executes the rehearsal on a fresh remote |
| "here is the command that reverses it" | re-derives it from the constructor and compares |
| "the target was idle" | recomputes from the agent list and the live remote ref |
| "here is my evidence" | hands it to `evidence_integrity`, which recomputes it |

That inversion is the `verify_readback_truth` lesson: a wholly fabricated
read-back record naming commit `000...0` passed the old verifier because it
checked shape and never truth. Self-consistency is not custody.

## Provenance is enforced, not just declared

> "any lane proposing a constraint states its provenance class in the same
> breath. An unclassified constraint is not in force."

Every `Finding` carries a `provenance` class and a `basis` — his words verbatim
for `FOUNDER_AUTHORED`, the named defect for `EARNED`. `BLOCKING_PROVENANCE`
contains only those two, so an `ASSISTANT_AUTHORED` check is reported and
**never refuses**. Ratification is available and is an explicit act.

Two checks in this lane's own code are classified `ASSISTANT_AUTHORED` and are
therefore inert: the boilerplate phrase list and the minimum statement length.
They are preferences, and they are labelled as such rather than smuggled in.

**Git authorship is not founder authorship.** Assistant lanes commit under the
founder's git identity as a matter of course, so a commit header proves nothing.
Every classification in `PROVENANCE-CLASSIFICATION.json` is derived from a
quoted founder utterance or a named, reproduced defect.

## Rollout

`require_write_declaration` defaults to **false**. A guard that begins refusing
every push the moment it installs is the over-broad guard that blocks legitimate
work. The mechanism is built, tested and inert; enabling it is an operator act,
and it is listed in `PROVENANCE-CLASSIFICATION.json` under
`open_for_founder_judgement`.
