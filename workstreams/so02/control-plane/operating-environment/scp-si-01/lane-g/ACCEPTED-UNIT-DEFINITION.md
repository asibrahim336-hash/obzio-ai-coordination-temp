# Lane G — what counts as one accepted unit, and why

**Extends:** `receipts/so02/2026-08-22/oe-dispatch/CUR01-REFUSAL-INGESTION.json` (the one
independent-acceptance event this estate has ever produced) and
`workstreams/so02/control-plane/operating-environment/scp-si-01/SCP-SI-01-SYSTEM-MAP.md`
(row G: "cohort history", must-not-create: "a ceremonial Cycle 0"). This document does not
open a new ledger; it defines the unit the existing evidence chain is measured in.

## The definition

> **An accepted unit is one commissioned deliverable that has been judged by a
> structurally independent acceptor — distinct model family or distinct principal,
> criteria committed before the verdict, criteria commit a provable git ancestor of the
> verdict commit, namespace-contained — and whose verdict is ACCEPTED.**

Every other outcome for a commissioned deliverable is a real outcome and is recorded, but
it is **not** an accepted unit:

| State | What happened | Accepted unit? |
|---|---|---|
| `NOT_RETURNED` / `IN_FLIGHT_*` | lane has not delivered | No |
| `FAILED_INCOMPLETE` | lane timed out or was rejected before delivery | No |
| `READY_TO_COMMIT` / `CONFIRMED_PUBLISHED` | lane reports its own bundle complete | No — self-report |
| `VERIFIED_ADMISSIBLE` / `CUSTODY_SOUND` | **the same principal that dispatched the lane** recomputed custody (hashes, containment, read-back) from the remote and found it sound | No — custody is not acceptance |
| `INDEPENDENTLY_JUDGED_REFUSED` | a structurally independent acceptor evaluated the artifact against pre-committed criteria and refused it | No — judged, and the judgment was negative |
| `INDEPENDENTLY_JUDGED_ACCEPTED` | a structurally independent acceptor evaluated the artifact against pre-committed criteria and accepted it | **Yes** |

## Provenance of every constraint this definition rests on

Per the standing amendment: `FOUNDER_AUTHORED` (quoted), `EARNED` (defect named), or
`ASSISTANT_AUTHORED` (inert unless ratified). Unclassified is not in force.

1. **"Produced/pushed is not accepted; independent judgment is required."**
   `FOUNDER_AUTHORED`. Quoted from this lane's own launch instruction: *"An accepted unit
   is derived from independently accepted artifacts, not from produced ones... A unit
   that was produced, pushed and never independently judged is not an accepted unit."*
   Also structurally identical to the standing controls the founder named as his own, not
   an assistant imposition: *"independent acceptance where the producer cannot issue its
   own verdict"* (`.cursor/rules/00-founder-standing-authority.mdc`, "Controls that are
   Obzio's own").

2. **"Provider non-rejection is dispatch success and never quality acceptance."**
   `FOUNDER_AUTHORED`, quoted verbatim from the same launch instruction. This is the
   reason the ledger below does not count a lane's `READY_TO_COMMIT` self-report, or the
   PO-03 "zero provider rejection across ten cohorts" figure, as any form of acceptance.
   That PO-03 figure is used in this lane's comparison only as labelled external context,
   per instruction, and its own baseline status is `UNVERIFIED` (see
   `SCP-SI-01-BASELINE.yaml#numbers_re_verified_from_source.ten_cohorts_zero_provider_rejection`).

3. **The four independence properties (distinct principal, criteria-before-verdict,
   provable ancestry, namespace containment).** `EARNED`. These are exactly the
   properties `CUR01-REFUSAL-INGESTION.json#independence_controls_verified_by_root_controller`
   checked before trusting L3's refusal of CUR-ORCH-QUAL-01, and the same document
   records that a further OE-W8 lane found a real gap in reasoning about them (shared
   dispatch and shared rule files can undercut model-family diversity — see
   `DEVICE-GATING-CORRECTION-20260823T0132Z.json#what_the_lane_got_right`, which is itself
   folded into why namespace/lineage independence is listed as a separate property here
   rather than assumed to follow from model family alone).

4. **"Custody verification is not claim verification, and neither is acceptance."**
   `EARNED`. Named defect: the root controller's own admission report for OE-L1 states
   this exactly — *"Custody and containment hold... not: ACCEPTED... Independent
   acceptance is a separate act by a separate party and cannot be issued by the run that
   produced this bundle"* (`LANE-ADMISSION-L1-20260822T2046Z.json#state_transition`,
   `#what_this_establishes` in `oe-l1-cursor-baseline/MANIFEST.json`). And a second,
   independent instance of the same lesson: `CORRECTIONS-20260822T2330Z.json#COR-01`
   records that this same root controller verified OE-W3's custody rigorously and then
   accepted one of its *substantive claims* on trust, which a later lane falsified. Two
   different failure instances of conflating verification classes, caught twice, is why
   this definition keeps the classes separate rather than collapsing them.

5. **"Do not treat raw counts as success."** `FOUNDER_AUTHORED`, quoted from
   `.cursor/rules/00-founder-standing-authority.mdc` Non-negotiable 3. This is why the
   ledger below reports a produced-count and an accepted-count as two different numbers
   and never nets them into one "lanes delivered" figure presented as quality.

6. **Model-family diversity alone does not establish independence; namespace/lineage
   independence is a separate, necessary property.** `EARNED`. Named defect: OE-W8's own
   adjudication record found that "the six independence properties are properties of the
   verdict process, not of the criteria's origin, so shared rule files and a shared
   dispatch mean model-family diversity does not break shared lineage"
   (`DEVICE-GATING-CORRECTION-20260823T0132Z.json`). Folded into property (3) above as an
   explicit, separate check rather than inferred from model family alone.

## What this definition deliberately excludes, and why

- **Token counts, dollar costs, or a cost-per-unit table.** Nothing available inside a
  Cloud Agent pod in this run exposed model token consumption or billing (`NOT_MEASURABLE`,
  see the comparison document). Inventing a plausible-looking number would be worse than
  omitting it, per instruction. Where a cost figure is unavoidable context (e.g. citing
  PO-03's own figures) it is labelled `HYPOTHESIS` or `UNVERIFIED_EXTERNAL_CONTEXT` and
  never presented as this lane's own measurement.
- **A ceremonial restart.** The unit ledger begins at `CUR-ORCH-QUAL-01`, the earliest
  artifact in this repository's history that was ever placed in front of a structurally
  independent acceptor, and continues through the 14-lane operating-environment programme
  into this cohort. SCP-SI-01 is the newest entries in one continuous series, not a new
  Cycle 0.
- **A new acceptance mechanism.** This lane does not build a second acceptance track,
  ledger, or metrics store. It reuses the vocabulary and the one existing acceptance event
  on record, and extends the same evidence chain with a unit-economics view over it. Lane
  H, not Lane G, is commissioned to run acceptance itself.

## Worked consequence, stated plainly before the numbers

Given this definition, the operating-environment programme's own closure figures —
*"lanes_dispatched: 8, lanes_delivered: 8"*, *"14 lanes dispatched across 4 waves, 13
delivered"* — describe **produced units**, not accepted ones. Applying the definition
above to the full available history (next document) yields an accepted-unit count that is
computed, not assumed, and it is small. That is the finding, not a defect in this
document's method.
