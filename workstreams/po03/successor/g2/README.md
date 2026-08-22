# G2 — NOT_YET

G2 does not exist. This file records why, so that the gap is visible rather than implied.

## Why not

The commission defines G2 as "a successor compiled from G1 failures and accepted lessons".
Neither input exists yet:

- **No G1 field failures.** G1's CI gates had not executed a single time on GitHub when this was
  written, because the branch had not been pushed. G1 has no run history, so it has produced no
  failures to learn from.
- **No accepted lessons.** Wave A's lessons are producer-recorded and producer-tested. No
  independent reviewer has accepted any of them; every unit is `NOT_TESTED` or `PENDING`.

Compiling a G2 now would mean inventing the failures it was supposed to have learned from. That
is the fabrication the commission's own anti-invention rule forbids, and it would also defeat
the point of the three-generation test, which is to measure whether learning from real failure
produces real lift.

## What would make G2 legitimate

1. At least one real CI run of G1 in a clean clone, with its outcome recorded.
2. An independent acceptance decision on Wave A, from a reviewer who did not produce it.
3. Real observed failures from either of the above, or from live use of the G1 controls.
4. A holdout set written by someone other than the producer, so that G0/G1/G2 can be scored on
   cases none of them was built against.

Until then the three-generation comparison in `../../metrics/generation-comparison.json` records
G0 and G1 as measured and G2 as `NOT_YET`, and the compounding claim stays `NOT_YET`.

## Known candidates for G2, recorded but not implemented

These come from residual weaknesses Wave A found in itself and disclosed rather than repaired.
They are candidates, not a plan, and none has been validated as worth doing:

- The changed-path guard passes vacuously on an empty changed-path set, so a silently wrong diff
  base yields `PASS` instead of `FAIL`. A successor could make an empty diff fail closed on
  events where a change is known to exist.
- Lease ids and fence tokens are structurally validated but never enforced by a live sink,
  because Wave A had one writer and no queue.
- Artifact read-back is performed by the process that wrote the record. An independent second
  reader, ideally on another machine, would make the provenance claim stronger.
- Supersession classification is textual, so 136 of 184 governance files are `UNCLASSIFIED`
  rather than proven current, and six pointer-reachable files trip the bare `SUPERSEDED` marker.
  A successor could resolve transitive references instead of the single hop Wave A performs.
