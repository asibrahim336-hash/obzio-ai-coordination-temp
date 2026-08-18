# OBZIO — FOUNDER INTENT REGISTRY PROPAGATION AND RLS REVIEW REQUIREMENT

**Date:** 19/08/2026  
**Originating function:** Founder Intent & Authority  
**Destinations:** Strategic Control / Registry Stewardship / Production Security Review  
**Status:** `CURRENT INTERNAL REQUIREMENT — DESIGN AND EVIDENCE ONLY — NO PRODUCTION MUTATION`  
**Strategy snapshot:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`

## 1. Read and verify

1. Registry and operator-bus propagation audit  
   Path: `state/FOUNDER_INTENT_REGISTRY_AND_OPERATOR_BUS_PROPAGATION_AUDIT_20260819_v001.md`  
   Blob: `cf4bf32d25881943f102d4384fcff8d51a5e5e54`

2. Current v008 currentness and dispatch correction  
   Path: `state/FOUNDER_INTENT_SC_CIEG_V008_CURRENTNESS_AND_DISPATCH_CORRECTION_20260819_v001.md`  
   Blob: `342817214d95deea620e8fee294f83a8ca08b6ab`

3. Current full-operational-initiative founder delta  
   Path: `state/FOUNDER_INTENT_FULL_OPERATIONAL_INITIATIVE_AND_ACTIVE_STARTUP_DELTA_20260818_v001.md`  
   Blob: `1452d43a7e00c1ef5a5058edea0c80b9a45c16a3`

## 2. Typed standing

### FOUNDER-CONFIRMED

- Durable founder-intent and strategy changes require real propagation.
- Production database and security mutations are founder-gated.
- Evidence recovery, technical design, route comparison and complete change-package preparation are delegated.
- Ahmed is not the routine registry merge layer or Drive relay.

### EMPIRICAL-CLAIM

- The registry's company-direction snapshot is correct.
- Current registry rows stop before the later Founder Intent deltas and current dispatch corrections; `strategy_bindings` is empty.
- Six control tables have RLS disabled.
- Direct checks show no current `anon` or `authenticated` schema usage or CRUD privileges on those tables.
- The Drive bus records target the personal Google principal; the technically accessible connector is bound to the work principal and returns 404 for the recorded locators.

### MODEL-RECOMMENDATION

- Prepare one proposition-level registry catch-up transaction and one separately reviewable RLS/access-policy change package.
- Keep production execution held until founder review of the exact consequence package.
- Recover or deliberately migrate the Drive bus rather than treating principal mismatch as global deletion.

### UNRESOLVED

- Intended control-table access model and policies.
- Data API exposed-schema configuration.
- Access by roles other than `anon` and `authenticated`.
- Correct Drive-bus principal or replacement route.
- Exact production transaction, rollback and acceptance plan.

## 3. Required work

### A. Registry reconciliation design

Prepare a transactionally coherent, idempotent registry catch-up package for:

- current founder sources and exact identities;
- current typed claims and supersessions;
- founder bindings where actually bound;
- v008 dispatch hold and repair requirement;
- current operating learnings;
- GitHub write/read-back receipts;
- Drive principal-specific access defect;
- current objects, contradictions, holds and claim uses.

The design must preserve the mandated seven-value authority taxonomy and must not convert model recommendations into founder intent.

Return row-level before/after effects, conflict handling, rollback, validation queries and re-run behaviour.

### B. Production RLS and access review

For each of the six non-RLS tables:

- recover intended reader/writer roles and actual call paths;
- verify schema/Data API exposure and effective grants for all relevant roles;
- define least-privilege RLS policies, service-role behaviour and migration order;
- model the access breakage caused by enabling RLS without policies;
- provide rollback and post-change verification;
- reconcile with the wider production `SECURITY DEFINER` / function-execute remediation lane; and
- state whether the finding is immediate exploitable exposure, latent exposure risk or defence-in-depth only.

Do not use the advisor's bare `ENABLE ROW LEVEL SECURITY` statements as the complete remediation.

### C. Operator-bus route repair

Compare:

1. reconnecting the personal Google principal;
2. deliberately migrating the bus to the work Drive;
3. using the private coordination repository as the primary bus with Drive as mirror; and
4. using the registry as index/receipt plane rather than payload store.

Choose the strongest route based on access, currentness, read-back, conflict handling, founder burden and recovery.

Prepare any owner action only after the surrounding work is complete.

## 4. Required return

Return:

`FOUNDER INTENT REGISTRY / RLS / BUS REPAIR PACKAGE — FOUNDER-GATED EXECUTION`

Include:

- exact source identities;
- typed proposition and row mapping;
- SQL migration/transaction candidate;
- access-policy model;
- rollback and acceptance tests;
- Drive principal/route result;
- interaction with CG-2 production-security standing;
- risks of action and inaction;
- internal work already completed;
- exact founder decision, only if production execution is ready;
- human execution queue; and
- durable write/read-back receipt for the design package.

## 5. Boundaries

No production SQL, RLS, grants, functions, security settings, Drive mutation, deletion, downstream external message, new spend or permanent architecture activation under this requirement.

Do not ask Ahmed to choose SQL, policy mechanics, route topology or ordinary sequencing.

## 6. Interlock metadata

**decision_changed[]:** registry catch-up, RLS remediation and bus-principal repair become explicit prepared work; production execution remains held; security posture is calibrated by both advisor and privilege evidence.

**premises[]:** current registry/bus audit; current Founder Intent correction; current full-operational-initiative delta; production security founder gate.

**scope:** internal design, evidence recovery, route comparison and founder-gated change-package preparation only.

**authority_basis[]:** Ahmed Sadek's current launch and standing internal delegation; constituted Founder Intent & Authority mandate; explicit founder gate for production database and security mutations.

**strategy_snapshot_id:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`.

# END REQUIREMENT
