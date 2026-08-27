# Lane G — comparison, founder-attention ledger, and what could not be measured

## 1. Founder-attention: a count, not a duration

**`NOT_MEASURABLE`, stated plainly:** wall-clock founder-attention *time* — how
many minutes Ahmed actually spent reading or replying — is not recoverable
from this repository. Nothing here timestamps when he opened a message, and
the receipts below record only when the coordinator *sent* or *corrected*
something, never when he read or acted on it. Inventing a minutes-spent figure
from send timestamps alone would be exactly the kind of unsupported precision
this lane's instruction forbids.

What **is** measurable, and is the number this document reports: a count of
distinct founder-facing action or guidance events found in the evidence
available to Lane G, each classified by whether it rested on a verified fact
at the time it was sent and whether it was later withdrawn or corrected. This
is the operationalisation the launch instruction itself specifies —
*"Count it honestly: how many actions actually required him, how many were
later withdrawn as mis-specified, and how many were sent resting on an
unverified fact"* — a count, not a clock.

### The ledger (SO-02 → operating-environment episode, `DOCUMENTED`)

| ID | Event | Rested on unverified/false fact? | Withdrawn or corrected? | Class |
|---|---|---|---|---|
| FA-1 | Direct founder relay: submit the CUR-ENV-01 commission packet to Cursor via his authenticated session (`founder-operating-environment-role-correction-20260822T173520Z.json`) | No | First attempt `NOT_DELIVERED` (Cloudflare verification loop); required a second attempt | Necessary owner act, with one wasted sub-attempt |
| FA-2 | Direct guidance given **twice** (`22:31Z`, `23:05Z`, `2026-08-22`): authenticate the Supabase MCP integration because it holds the `CURSOR_API_KEY` route | **Yes** — Supabase MCP has no Edge-secrets tool in its published surface; authenticating it would not have reached the key at all | **Yes** — `CORRECTIONS-20260822T2330Z.json#COR-02`, marked "FALSE AND ACTED-ON-ADVICE" | Negative value |
| FA-3 | A false "two distinct GitHub credentials" claim recorded in `LANE-ADMISSION-L1` **and repeated in the PR body** — a founder-visible reporting surface | **Yes** — falsified by `OE-W3`: one token, two transports, not two credentials | **Yes** — `CORRECTIONS-20260822T2330Z.json#COR-01` | Negative value (reporting-accuracy attention cost) |
| FA-4 | A direct question asked **twice** (`23:59Z` `2026-08-22`, `00:40Z` `2026-08-23`): "Do you already have a GitHub connector enabled in your ChatGPT account?" | **Yes** — `OE-W7` established from live documentation that ChatGPT's supported connector list contains no GitHub connector; the thing asked about does not exist | **Yes** — withdrawn and replaced `01:25Z`, `QUESTION-CORRECTION-20260823T0125Z.json` | Negative value — one of the estate's own named "two founder actions in two hours" instances |
| FA-5 | `FA-W8-01` nominated as the constitution's *highest-leverage* founder action: attach a local repository clone as a ChatGPT desktop-app project folder | **Yes** — requires macOS/Windows; the founder's current device is a Chromebook (`DEVICE-GATING-CORRECTION-20260823T0132Z.json`) | Re-ranked to `DEFERRED_MACBOOK_GATED` (rank 6 of 6) before the corrected list was finalised | Negative value — the other named "two founder actions in two hours" instance |
| FA-6 | Guidance given: "MCP integrations are authenticated in the Cursor desktop IDE" | Partly — incomplete rather than false; a web callback (`cursor.com/agents/mcp/oauth/callback`) also exists | Yes — `COR-03`, lowers required founder effort | Negative value (minor: overstated a device requirement) |
| FA-7 | The corrected, ranked founder-action list itself (mirror `CURSOR_API_KEY`; confirm Codex↔GitHub; retire 4 dead `AUREA_E2E_*` secrets; point the environment at the repo file; state the ChatGPT plan; `FA-W8-01` deferred) | No — issued after FA-2 through FA-6 were corrected | N/A — this is the corrected artifact | Legitimate, required |

**Totals:** 7 distinct founder-facing events identified in the evidence Lane G
read. **5 of 7 (71%)** rested on an unverified or false fact at the time they
were first stated or acted on. **All 5** of those were later withdrawn or
corrected — a 100% correction rate on the flawed subset, which is a real
mitigating control, and a 71% first-pass flaw rate on founder-facing material,
which is the cost the instruction asks to be counted honestly rather than
netted away by the correction rate.

### A tension in the source records, stated rather than resolved

`DEVICE-GATING-CORRECTION-20260823T0132Z.json` asserts *"Both were caught
before reaching him"* about FA-4 and FA-5. But `QUESTION-CORRECTION-20260823T0125Z.json`'s
own `asked_at` field lists **two** send timestamps for FA-4
(`23:59Z`, `00:40Z`) before its `01:25Z` withdrawal, which reads as the
question having been sent, not intercepted pre-send. Lane G does not have an
instrument that shows whether Ahmed actually read either message before the
correction landed, so this is recorded as an unreconciled tension in the
estate's own evidence rather than silently resolved in either direction. If
FA-4 truly never reached him, the honest count is 4 of 7 rested-on-unverified
(57%); if it did, the figure above (5 of 7, 71%) stands. Both readings keep
FA-5's status as `DOCUMENTED` "caught before the corrected list was
finalised," which is a narrower and better-supported claim than "never
reached him" in either case.

### The current cohort's founder-attention count so far

`SCP-SI-01-BASELINE.yaml#decision_changed: []`. No founder-facing action or
guidance event has been recorded against this cohort as of this snapshot.
**This is `NOT_MEASURABLE` as a final figure**, not a verified zero: Lane G
cannot see whether lanes A–F or H have generated (or will generate) a
founder-facing ask that simply has not been written to a receipt Lane G can
read yet. Reporting "0" as though the cohort had closed would repeat exactly
the mistake this ledger exists to catch elsewhere — a produced-so-far count
mistaken for a final one.

## 2. What is `NOT_MEASURABLE`, and why, without a fabricated substitute

| Item | Status | Reason |
|---|---|---|
| Model token consumption, per unit or in aggregate | `NOT_MEASURABLE` | Nothing available inside a Cloud Agent pod in this run exposes token counts. No API, log, or file observed in this repository or this run's tool surface reports it. |
| Dollar cost, per unit or in aggregate | `NOT_MEASURABLE` | Derived entirely from token counts and per-model pricing, neither of which is available; a cost table built on assumed token counts is explicitly excluded by this lane's instruction. |
| Compute/runtime seconds (CPU/GPU time actually consumed) | `NOT_MEASURABLE` | Wall time (elapsed time between commits) is recoverable from git history and is reported per unit; it is a lower-bound proxy, not a compute measurement, and is reported as such. |
| Model identity for locally-dispatched (subagent, `source: internal`) lanes | `NOT_MEASURABLE` as a confirmed fact | `list-cloud-agents` and `run-info` report `originalModelName: null` for every `internal`-source entry Lane G observed, including Lane G's own run. The model named at dispatch time (e.g. wave 1's `DISPATCH-RECORD`) is `DOCUMENTED` as what was requested, not independently confirmed by any instrument available here. |
| Founder-attention wall-clock time | `NOT_MEASURABLE` | No timestamp for when Ahmed read or replied to anything exists in this repository. A count of distinct action/guidance events is reported instead (Section 1). |
| Whether sibling SCP-SI-01 lanes share this pod's physical filesystem with Lane G | `NOT_MEASURABLE` | Lane G can observe that dedicated worktrees exist and are mutually isolated; it has no instrument that reports another `bcId`'s process/filesystem co-residency. |
| SCP-SI-01 lanes E, F, H — dispatched, in progress, content | `NOT_MEASURABLE` | Not visible in Lane G's `list-cloud-agents` snapshot (E) or not visible at all (F, H); no worktree for any of the three exists on this pod. Recorded as `NOT_OBSERVED`, never as absent or as zero. |
| Retry counts for OE lanes other than `L1` and `W4` | `NOT_MEASURABLE` | No retry evidence was found in the read receipts for those lanes' own production. Absence of a recorded retry is not proof none occurred, so the ledger records `NOT_MEASURABLE`, not `0`. |

## 3. Is the current cohort commensurable with history?

**Partially — the method transfers; the founder-attention and acceptance
figures do not, yet, and this is stated rather than forced.**

**Commensurable now, using the same instruments both times:**
- **Unit definition and verdict taxonomy.** `VERIFIED_ADMISSIBLE` vs.
  `INDEPENDENTLY_JUDGED_*` vs. `IN_FLIGHT_*` applies unchanged to both the OE
  programme and SCP-SI-01; this ledger uses one taxonomy across all 24 rows.
- **Wall-time computation.** The same git-recomputation method
  (`extract_wall_time.py`) produced figures for both `SCP-A` and `SCP-C` and
  every OE lane; the numbers sit in the same units and were derived the same
  way.
- **The mechanism fix for `SHARED_WORKTREE_COLLISION`.** Directly comparable:
  wave 1 reproduced it live within two minutes; this cohort shows dedicated,
  isolated worktrees in place from the start (Section "current cohort's
  mechanism check" in `HISTORICAL-EXTRACTION.md`).
- **Model-attribution uncertainty.** Identically `NOT_MEASURABLE` in both
  eras, for the same underlying reason (`originalModelName: null` for
  internal-source runs). This is a genuine like-for-like null result, not a
  gap unique to either period.

**Not commensurable yet, and forcing it would manufacture a false number:**
- **Accepted-unit rate.** History's rate is `0 accepted / 1 judged` — a real
  refusal, on real evidence, with a real verdict. SCP-SI-01's rate so far is
  `0 accepted / 0 judged`, because Lane H (the cohort's own acceptance
  mechanism) has not yet produced a verdict on anything, by this snapshot.
  **These are not the same zero.** One is a negative result; the other is an
  absence of a result. Reporting them on the same scale would imply the
  current cohort has already failed a judgment it has not yet undergone.
- **Founder-attention count.** History's count (Section 1) is a closed
  episode's total. The current cohort's count is a snapshot of an open
  episode and will change as lanes still running deliver. A ratio or
  before/after comparison built from an open count would be comparing a
  finished number to an unfinished one.
- **Produced-unit throughput.** History's 13/14 (OE programme) and 8/8
  (waves 1–2) describe closed dispatch batches. SCP-SI-01's produced count
  (Section "the full unit roster" in `HISTORICAL-EXTRACTION.md`: 2 of 6
  observed lanes A–D plus G have delivered something as of this snapshot) is
  mid-batch and will move.

**Where the baseline instead of a comparison is the honest output:** for
accepted-unit rate and founder-attention count, this document establishes
the historical figures as a transparent first baseline (`0/1` judged-accepted;
`5–7 of 7` founder-facing events unverified-at-send) rather than forcing a
ratio against an unfinished cohort. A future lane closing SCP-SI-01 — after
Lane H has run and every dispatched lane has either delivered or been
recorded as failed — can compare against this baseline honestly, because by
then both sides of the comparison will be closed numbers.

## 4. External context, explicitly labelled and not restated as established

PO-03's own figures — 74 units vs. 64 required, 10 cohorts, 10 canary round
trips, "zero provider rejection across ten cohorts" — are `UNVERIFIED` per
`SCP-SI-01-BASELINE.yaml#numbers_re_verified_from_source` and are **not**
measurable from this branch; Lane G did not attempt to verify them and does
not restate them as established. They are noted here only because the launch
instruction names them as context: if used at all, they should be read as an
**external, unverified** data point that a different programme (PO-03, not
the operating-environment programme this ledger extends) reports "zero
provider rejection" across ten cohorts — and, per the same instruction and per
Section 1's own finding here, provider non-rejection is dispatch success and
is never quality acceptance, so even if that PO-03 figure were verified it
would not change this document's accepted-unit count of zero.

## 5. Bottom line

- **Produced (this ledger, both eras combined): 19 of 24 recorded units are
  `produced: true`** (18 OE/SCP lanes plus `CUR-ORCH-QUAL-01`'s own
  production); the remainder are `FAILED_INCOMPLETE` (1), genuinely in-flight
  with no delta yet (2), or not observable from this pod (3).
- **Independently judged: 1** (`CUR-ORCH-QUAL-01`, by `OE-L3-INDEPENDENT-ACCEPTANCE`).
- **Accepted units in this estate's full recorded history: 0.**
- **Accepted units in the current cohort so far: not yet measured (0 judged, distinct from 0 accepted).**
