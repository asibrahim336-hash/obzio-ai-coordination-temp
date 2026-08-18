# OBZIO — FOUNDER INTENT REGISTRY AND OPERATOR-BUS PROPAGATION AUDIT

**Date:** 19/08/2026  
**Function acting:** Founder Intent & Authority  
**Status:** `CURRENT AUDIT — GITHUB PROPAGATED — REGISTRY AND DRIVE BUS INCOMPLETE`  
**Strategy snapshot:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`

## 1. FOUNDER-CONFIRMED

1. Founder Intent and strategy changes require durable propagation rather than remaining chat-only.
2. The current company direction is agent-first, capability-first and internal-first; Bid Readiness is not Obzio's identity.
3. Technically accessible internal capability is authorised by default, subject to action-specific founder-reserved exceptions.
4. Production database and security mutations remain founder-gated.
5. Ahmed is not the routine relay between durable operating nodes.

## 2. EMPIRICAL-CLAIM

Evidence labels: `OBSERVED` unless stated otherwise.

### Supabase registry

1. Supabase project `obzio-prod-eu` (`szxhcwvcmzpyxojgiiws`) is `ACTIVE_HEALTHY`.
2. Schema `obzio_registry` is readable through the current authorised route.
3. Active strategy snapshot `SNAP-2026-08-18-AGENT-FIRST` correctly states the agent-first capability platform, capability-first/internal-first sequence and Bid Readiness exclusion.
4. Contaminated snapshot `SNAP-2026-08-18-BID-READINESS-CONTAMINATED` is inactive and its identity claim is refuted.
5. Registry source and claim activity stops at `2026-08-18 14:04:42.810796+00`; strategy snapshots stop at `14:02:29.346119+00`; objects and learnings are older; receipts stop at `01:54:16.897291+00`.
6. `obzio_registry.strategy_bindings` contains zero rows.
7. The later enterprise, execution-profile, high-competence, reasoning-quality, strategic-bootstrap and full-operational-initiative founder deltas are not registered in the rows recovered by the exercised route.
8. The current v008 currentness correction, claim-type repair, SC repair requirement and operating-learning records are not registered.
9. The registry is therefore directionally correct at company-strategy level but incomplete and stale for current founder-intent, authority, dispatch and receipt state.

### Operator bus

10. The registry records the Drive bus capability and folder under principal `asibrahim336@gmail.com`, with the limitation that it does not see the `ahmed@obzio.com` Drive.
11. The currently connected Drive principal is Ahmed's Obzio work account, not the recorded personal-account bus principal.
12. Direct reads of the registered bus folder and receipt locators, plus the later reported directive-file locator, return `404 NOT_FOUND` under the current work-account principal.
13. The 404 results establish current principal-specific unavailability. They do not prove that the personal-account bus objects were deleted.

### Registry security posture

14. The Supabase table advisor reports six `obzio_registry` tables with RLS disabled: `lane_mandates`, `strategy_bindings`, `claim_uses`, `strategy_snapshots`, `strategy_events` and `strategy_holds`.
15. Evidence label: `PLATFORM-REPORTED`. The advisor classifies the finding as critical and warns against enabling RLS without policies because doing so would block all access.
16. Direct PostgreSQL privilege checks show that `anon` and `authenticated` currently lack `USAGE` on schema `obzio_registry` and lack effective `SELECT`, `INSERT`, `UPDATE` and `DELETE` privileges on all six tables.
17. Immediate exposure through those two standard roles was therefore not observed through the database privilege model.
18. The current Data API exposed-schema setting was not observable through `current_setting('pgrst.db_schemas', true)`; it returned null.
19. Missing RLS remains a defence-in-depth and future-change risk even though current standard-role grants do not expose the tables.

## 3. TECHNICAL-HYPOTHESIS

1. The Drive bus is likely still present under the personal Google principal and inaccessible because the available connector is bound to the work principal.
2. A later grant or Data API exposure change could make the six non-RLS tables reachable, so privilege checks alone do not retire the RLS risk.
3. Blindly enabling RLS without designed policies could break the current control plane.
4. GitHub is currently the strongest recovered durable propagation route, but it should not become the only registry by accidental default.

## 4. MODEL-RECOMMENDATION

1. Treat Supabase propagation as `INCOMPLETE`; do not represent the current Founder Intent chain as registered.
2. Prepare a proposition-level registry reconciliation for the later founder deltas and current v008 repair records, including sources, claims, learnings, objects, contradictions and receipts.
3. Do not execute that production write without the explicit production-database gate.
4. Route the six non-RLS tables to the existing production-security decision lane. Design access policies and verify intended Data API/schema exposure before any `ENABLE ROW LEVEL SECURITY` change.
5. Do not apply the advisor's bare RLS statements alone.
6. Recover the personal-account Drive bus through the correct principal or deliberately migrate the operator bus to an accessible durable route with read-back receipts and supersession treatment.
7. Until bus recovery, use the pinned GitHub correction and dispatch requirement as the active internal propagation route and keep the Drive defect open.
8. Add connector principal identity to every future capability and receipt record so a locator is never described as globally unavailable when it is only unavailable to one principal.

## 5. ADVERSARIAL-OUTPUT

1. A correct active strategy snapshot does not mean the registry is current; the empty `strategy_bindings` table and eight-hour freshness gap disprove that inference.
2. A prior confirmed Drive write does not prove present accessibility from a different authenticated principal.
3. A platform RLS warning should not be repeated as proven public exploitability when direct privilege evidence shows no current standard-role grants; it remains a serious latent control defect rather than a verified live exposure through those roles.

## 6. UNRESOLVED

1. Intended read/write policy for the six non-RLS control tables.
2. Current Supabase Data API exposed-schema configuration.
3. Whether another role or service path has unintended access to the six tables.
4. Exact recovery or migration route for the personal-account Drive bus.
5. The precise registry transaction and rollback plan for current Founder Intent propagation.

## 7. Current consequence

- GitHub propagation: `PASS — READ-BACK VERIFIED`.
- Supabase registry propagation: `INCOMPLETE — STALE AFTER 18/08 14:04 UTC`.
- Google Drive operator-bus propagation: `BLOCKED — PRINCIPAL MISMATCH / CURRENT ROUTE 404`.
- Production database mutation: `NOT EXECUTED — FOUNDER GATE PRESERVED`.
- Production security mutation: `NOT EXECUTED — POLICY DESIGN AND FOUNDER GATE REQUIRED`.

## 8. Founder state

**Founder decision required now:** `NONE for evidence recovery and repair design`.  
**Potential founder decision after preparation:** exact production registry/RLS change set and consequence review.  
**Useful founder participation:** reconnect or expose the personal Drive principal only if bus recovery remains worthwhile after route comparison.  
**Human Configuration Queue:** `CONDITIONAL — Google principal connection only if selected; production change decision after a complete repair package`.

## 9. Interlock metadata

**decision_changed[]:** registry propagation changes from assumed to incomplete; Drive bus absence is typed as principal-specific access failure; six non-RLS tables enter production-security review with immediate standard-role exposure not observed; no production mutation is executed.

**premises[]:** current Founder Intent sources and GitHub writes; authenticated Supabase project/table/row reads; direct PostgreSQL privilege checks; authenticated Drive profile and exact-locator failures; existing registry capability and receipt records.

**scope:** read-only registry/bus audit, propagation status and security-route recommendation. No production database, RLS, grant, Drive, DNS, deployment or external-message mutation.

**authority_basis[]:** Ahmed Sadek's current launch; constituted Founder Intent & Authority mandate; standing read-only internal recovery authority; explicit founder gate for production database and security changes.

**strategy_snapshot_id:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`.

# END AUDIT
