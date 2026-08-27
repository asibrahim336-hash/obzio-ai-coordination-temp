# Lane G — historical extraction: what this estate has actually produced vs. accepted

**Ledger:** `SCP-SI-01-ACCEPTED-UNIT.jsonl` in this directory, built by
`tools/build_ledger.py` from `tools/extract_wall_time.py`'s git-derived facts
(`receipts/so02/2026-08-27/scp-g/raw/oe-lane-wall-time*.jsonl`) plus the cited
receipts named in each record's `sources` field. Every number below is either
recomputed in this run or transcribed from a named file; none is estimated.

## The full unit roster (24 records)

| # | unit_id | produced | independently judged | is_accepted_unit | verdict |
|---|---|---|---|---|---|
| 1 | `CUR-ORCH-QUAL-01` | yes | **yes** | **no** | `INDEPENDENTLY_JUDGED_REFUSED` |
| 2–6 | `OE-L1..L5` (wave 1) | yes (5/5) | no | no | `VERIFIED_ADMISSIBLE` |
| 7–9 | `OE-W2..W4` (wave 2) | yes (3/3) | no | no | `VERIFIED_ADMISSIBLE` |
| 10 | `OE-W5` (wave 3) | yes | no | no | `VERIFIED_ADMISSIBLE` |
| 11 | `OE-W6` (wave 3) | **no** | no | no | `FAILED_INCOMPLETE` |
| 12–13 | `OE-W7, OE-W8` (wave 3 recovery) | yes (2/2) | no | no | `VERIFIED_ADMISSIBLE` |
| 14–15 | `OE-W9, OE-W10` (wave 4) | yes (2/2) | no | no | `VERIFIED_ADMISSIBLE` |
| 16 | `SCP-SI-01-BASELINE` (this cohort) | yes | no | no | `VERIFIED_ADMISSIBLE` |
| 17 | `SCP-A-REFUSAL-REPAIR` | yes (published) | no | no | `IN_FLIGHT_PUBLISHED_NOT_YET_ADMITTED` |
| 18 | `SCP-B-IMPROVEMENT-CHAIN` | no | no | no | `IN_FLIGHT_NO_CONTENT_YET` |
| 19 | `SCP-C-AUTHORSHIP-SIDECAR` | yes (unpublished) | no | no | `IN_FLIGHT_COMMITTED_NOT_YET_PUBLISHED` |
| 20 | `SCP-D-FAILURE-TO-LEARNING` | no | no | no | `IN_FLIGHT_NO_CONTENT_YET` |
| 21 | `SCP-E-HELD-OUT-ROUTE-QUALIFICATION` | unknown | no | no | `NOT_OBSERVABLE_FROM_THIS_POD` |
| 22–23 | `SCP-F`, `SCP-H` | unknown | no | no | `NOT_OBSERVED_IN_THIS_SNAPSHOT` |
| 24 | `SCP-G-ACCEPTED-UNIT-ECONOMICS` (this lane) | yes (self-reported) | no | no | `READY_TO_COMMIT` |

**Totals:** 24 units on record. 18 have a `produced: true` (something exists,
custody-checkable, on a branch). Of those 18 (plus the pre-programme artifact,
19 produced total including `CUR-ORCH-QUAL-01`), exactly **1** has ever been
placed in front of a structurally independent acceptor
(`CUR-ORCH-QUAL-01`, judged by `OE-L3-INDEPENDENT-ACCEPTANCE`), and that
judgment's verdict was **REFUSED**.

**Accepted units in this estate's full recorded history: 0.**

This is not a defect in the counting method; it is what the evidence shows when
"produced" and "accepted" are kept as separate questions, which is exactly what
the unit definition in the previous document requires and what this estate's own
`VERIFIED_ADMISSIBLE`/`not: ACCEPTED` vocabulary already distinguishes
(`LANE-ADMISSION-L1-20260822T2046Z.json#state_transition`).

## Reading the operating-environment programme's own closure language correctly

The programme's own records state, accurately and for a narrower question than
this ledger asks:

- `CORRECTIONS-20260822T2330Z.json#group_closure`: *"lanes_dispatched: 8,
  lanes_delivered: 8, lanes_rejected: 0"* — true, for wave 1 (5) + wave 2 (3) =
  8, all custody-verified by the dispatching root controller.
- The baseline's own reconciliation: *"14 lanes dispatched across 4 waves, 13
  delivered, one, OE-W6, timed out"* — true, across all 4 waves plus the
  wave-3 recovery pair (`5 + 3 + 4 + 2 = 14` dispatched, `5 + 3 + 3 + 2 = 13`
  delivered; recomputed independently in this run, see `git log --all
  --format` timestamps in the ledger).

Both statements are about **delivery**, i.e. `produced: true` in this ledger's
terms. Neither statement is, or claims to be, about acceptance. Reading either
figure as evidence of quality is exactly the substitution this lane's
instruction warns against: *"ten dispatched cohorts with zero provider
rejection, and provider non-rejection is dispatch success and never quality
acceptance."* The 13/14 and 8/8 figures are the operating-environment
programme's own version of that same distinction, and this ledger keeps it.

## The one judged unit, in full

`CUR-ORCH-QUAL-01` production: 3 commits, `04001dba` → `11a60dcf`, wall time
**9 minutes** (`13:41:09Z` → `13:50:10Z`, `2026-08-22`; `DIRECTLY_REPRODUCED`
from `git log`). Judgment (`OE-L3-INDEPENDENT-ACCEPTANCE`): 3 commits,
criteria commit `9a390df3` (`20:14:33Z`) → verdict commit `541eff44`
(`20:23:55Z`), wall time **9.4 minutes**. Total elapsed from production start
to verdict: 6h 43m, of which ~18.4 minutes were the two artifacts' own active
wall time and the remainder was the gap between the production run ending and
the acceptance lane being dispatched — a gap this evidence chain has no record
of the reason for, so it is left unexplained rather than filled with a guess.

The independence controls the root controller checked before trusting this
verdict (`CUR01-REFUSAL-INGESTION.json#independence_controls_verified_by_root_controller`):
distinct model family (`gpt-5.6-sol-xhigh` vs. `claude-opus-5-thinking-max-fast`),
criteria committed before the verdict, criteria commit a provable git ancestor
of the verdict commit, criteria commit touched only the criteria file, and
namespace containment via `lane_guard.py`. All five held. The verdict found two
real defects (`DEF-01`, `DEF-02`, named in the definition document) and refused
the producer's own two-independent-routes claim, while explicitly upholding the
parts of the producer's evidence that survived challenge (R1 custody, the
92-test gate, the 22-event hash chain). This is a working acceptance mechanism
that returned a negative verdict on real evidence — not a broken mechanism, and
not evidence that anything since has passed it, because nothing since has been
put in front of it.

## Wave-by-wave wall time (own-lane commits only; `DIRECTLY_REPRODUCED`)

| Wave | Units | Own-commit wall time (min) | Notes |
|---|---|---|---|
| 1 (`L1–L5`) | 5 | `L1` 19.6, `L2` 9.8, `L3` 9.4, `L4` 13.3, `L5` 20.6 | Concurrent; shared-worktree collision reproduced live within 2 minutes of dispatch |
| 2 (`W2–W4`) | 3 | `W2` 18.6, `W3` 23.1, `W4` 11.6 | Dispatched into isolated per-lane worktrees (the wave-1 postmortem's fix) |
| 3 (`W5, W6`) | 2 | `W5` 28.7; `W6` single harvest commit, then timed out before any further own commit | `W6` timed out during analysis, not collection |
| 3-recovery (`W7, W8`) | 2 | `W7` 21.1, `W8` 20.4 | Re-dispatched, reused `W6`'s harvest (28/28 byte-identical overlap) |
| 4 (`W9, W10`) | 2 | `W9` 28.0, `W10` 28.8 | Built the write-admission gate this lane itself invokes |

Exact minute figures and the git commit ranges they were computed from are in
`SCP-SI-01-ACCEPTED-UNIT.jsonl`'s `wall_time_minutes_first_to_last_own_commit`
and `own_commit_count` fields per unit, and in
`receipts/so02/2026-08-27/scp-g/raw/oe-lane-wall-time.jsonl` (the raw
recomputation).

## What "wall time" does and does not mean here

Wall time above is elapsed time between a lane's first and last own commit on
its branch. It is `DIRECTLY_REPRODUCED` (recomputed from `git log`, not
transcribed from a lane's own claim), but it is a proxy, not a compute
measurement, and it is biased **short**: it excludes whatever time the agent
spent before its first commit (reading, planning, tool calls that produced no
commit) and any gap before delivery is recorded. It is the best available
lower bound on lane duration, not an estimate of effort or cost. See the
comparison document for why runtime/compute time is `NOT_MEASURABLE` rather
than estimated.

## Retries, lease conflicts and ingestion failures found in the historical record

- **Lease conflicts:** exactly one class of event, `DIRECTLY_REPRODUCED` and
  named `SHARED_WORKTREE_COLLISION` in
  `receipts/so02/2026-08-22/oe-dispatch/SHARED-WORKTREE-COLLISION-LIVE-REPRODUCTION.json`.
  Five local subagents dispatched from one parent shared one filesystem and
  therefore one git `HEAD`; the collision reproduced **within two minutes** of
  dispatch, unprompted, even though the exact same defect was already
  documented against PO-03. `OE-L4` was the one lane reported structurally
  immune, because it independently created its own worktree before writing.
  The required fix — a dedicated worktree per lane — was applied from wave 2
  onward; no further collision is reported in waves 2–4, which is evidence by
  absence and is labelled that way in the ledger, not as a direct
  reproduction.
- **Retries:** two documented self-corrections before commit (`OE-L1`'s
  cherry-pick recovery from the shared collision; `OE-W4`'s re-run of its own
  model-configuration inventory after a first pass returned an inconsistent
  count). No other lane's own production records a retry. Retry counts for
  everything else are `NOT_MEASURABLE`, not zero — absence of a recorded retry
  is not proof none occurred, and the ledger says so per unit rather than
  defaulting silently to 0.
- **Ingestion failures:** exactly one, `OE-W6`. Its manifest was absent at the
  point of failure, which the root controller's own rule states plainly:
  *"A lane that did not deliver is never assumed successful."* Every other
  delivered lane's admission record shows `digest_mismatches: 0`,
  `uncovered: 0`, `outside_scope: 0` at first check — zero further ingestion
  failures, `DOCUMENTED` from each lane's own admission/correction record.

## The current cohort's mechanism check

Lane G directly observed, on its own pod's local disk, dedicated git worktrees
for lanes A–D (`/tmp/lane-a` … `/tmp/lane-d`) already isolated from one
another before creating its own at `/tmp/lane-g`, exactly as its own launch
instruction required. `list-cloud-agents` shows those same names as separate,
concurrently `RUNNING` top-level entries at the moment of this snapshot. This
is the wave-1 postmortem's mandated fix (`worktree_path` per lane, dispatch
forbidding `git checkout`/`git add -A` in a shared root) applied to a new
cohort, and it is `DIRECTLY_REPRODUCED` rather than assumed: Lane G checked
for the collision precondition (a shared, contended `HEAD`) and did not find
one. What Lane G cannot determine from inside its own pod is whether every
sibling lane's process is co-resident on the same physical filesystem as its
own worktree-listing sees, or on separate infrastructure entirely; either way
the mitigating control (isolated worktree per lane) is the thing that matters
and it was observed in place.
