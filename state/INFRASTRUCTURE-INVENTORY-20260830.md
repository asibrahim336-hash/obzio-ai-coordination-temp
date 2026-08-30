# Live infrastructure inventory — 2026-08-30

Captured because the pointers to both of these live only inside ChatGPT project instructions that
Ahmed is about to delete (OBZIO-OPERATOR.md, OPEN WORK item 8). This file is the durable pointer.

Instrument: Supabase MCP (`list_projects`, `execute_sql` against `pg_class`/`pg_namespace`) and
Google Drive MCP (`search_files` by `parentId`). Row counts below are **exact** — `count(*)`, not
planner estimates — except where marked. Snapshot instant 2026-08-30 ~15:2x UTC.

---

## 1. Supabase — `obzio-prod-eu`

| field | value |
|---|---|
| project ref / id | `szxhcwvcmzpyxojgiiws` |
| region | eu-west-1 |
| status | ACTIVE_HEALTHY |
| Postgres | 17.6.1.147 (engine 17, ga) |
| host | `db.szxhcwvcmzpyxojgiiws.supabase.co` |
| created | 2026-07-22T11:27:04Z |
| organization | `rjwurqthumosbqlgmwce` |

**RLS is enabled on every base table in all four schemas** (verified via `pg_class.relrowsecurity`).
Views report `false` because RLS does not apply to views.

### schema `obzio_registry` — the operating registry (20 tables, 18 detection views)

Exact counts: `claims` 87 · `objects` 93 · `learnings` 35 · `sources` 33 · `receipts` 22 ·
`capabilities` 14 · `contradictions` 13 · `strategy_surfaces` 13 · `agent_events` 10 (est) ·
`lane_mandates` 7 (est) · `agent_runs` 6 (est) · `strategy_bindings` 5 · `claim_uses` 3 (est) ·
`strategy_events` 3 (est) · `strategy_snapshots` 2 · `claim_disputes` 1 (est) ·
`strategy_holds` 1 (est) · `perturbation_results` 0.

Views (all `v_*`): capability_claimed_unchecked, capability_drift, expired_claims,
illegal_lifecycle_jump, **integrity_dashboard**, lane_mandate_exceeded, monodirectional_evidence,
open_contradictions, same_family_review, strategy_interlock_breach, strategy_surface_coverage,
superseded_but_active, unbound_enumerations, unequipped_runs, unoperationalised_learnings,
unreceipted_delivery, unrestated_runs.

Entry point: `select * from obzio_registry.v_integrity_dashboard;`

### schema `obzio_mena_archive` — the corpus that survived (6 tables)

`evidence_events` **3,951** · `master_supplier_companies` **3,086** ·
`qualified_target_accounts` **450** · `buyer_supplier_edges` **238** ·
`public_professional_contacts` 12 (est) · `ingestion_runs` 1 (est).

Largest objects in the project: `master_supplier_companies` 7,016 kB, `evidence_events` 5,552 kB.

### schema `mena_product` — the product tables (18 tables, 8 views)

`record_evidence_links` **447** · `evidence` **195** · `source_crosswalks` 178 (est) ·
`accounts` **30** · `event_impacts` 29 (est) · `requirements` 38 (est) ·
`requirement_matches` 38 (est) · `relationships` 14 (est) · `opportunities` 9 (est) ·
`contracts` 8 (est) · `stakeholders` 4 (est) · `competitors` 2 (est) · `renewal_signals` 2 (est) ·
`checkpoints` 2 (est) · `workspaces` 1 (est) · `import_runs` 1 (est) ·
`workspace_members` 0 · `internal_next_actions` 0 · `saved_views` 0.

### schema `public` — effectively empty

13 tables, all 0 rows except `accounts` = 1 (est). RLS on all.

---

## 2. Supabase — a SECOND project, not named in OPEN WORK item 8

Item 8 names only `obzio-prod-eu`. There is another live project on the same organization:

| field | value |
|---|---|
| project ref / id | `wsnyawtbhspbkwuckpam` |
| name | `ahmed@obzio.com's Project` |
| region | eu-west-3 |
| status | ACTIVE_HEALTHY |
| created | 2026-07-17T14:30:15Z (five days *before* obzio-prod-eu) |

Its `public` schema holds 17 tables, RLS on all. Almost everything is empty, but three are not:

- **`research_artifact_checksums` — 347 rows.** Table comment, verbatim: *"Private SHA-256
  registration record for research artefacts preserved in the Fivetran-Intel repository."*
- `profiles` 4 · `accounts` 3 · `account_members` 3.

**Why this matters:** OPEN WORK item 3 asks whether Agentforce-Intel and Fivetran-Intel are
disposable job-application repos or the product prototype. This table is 347 hash-registered
research artefacts pointing at Fivetran-Intel — evidence bearing directly on that question, sitting
in a project the inventory task did not name. Worth reading before any decision to discard those
repos.

---

## 3. Google Drive — folder "Obzio Ops"

Folder id `1l3Bz5sLc9_OZbyAeboF2txFWToWIp8gS` (created 2026-08-16T18:14Z, owner
asibrahim336@gmail.com, parent = My Drive root).
https://drive.google.com/drive/folders/1l3Bz5sLc9_OZbyAeboF2txFWToWIp8gS

**20 files + 6 subfolders.** Newest content 2026-08-22; the folder has been static since.

Operator bus / state files (the cross-operator coordination channel):
`BUS_OPERATOR_B_STATE.md` (4,534 B) · `BUS_OPERATOR_B_STATE_02.md` (3,857 B) ·
`BUS_OPERATOR_C_DIRECTIVES.md` (15,257 B) ·
`BUS_OPERATOR_C_DIRECTIVES_02_STRATEGIC_CORRECTION.md` (15,348 B) ·
`BUS_OPERATOR_C_DIRECTIVES_v1_SUPERSEDED_20260818.md` (7,876 B) ·
`BUS_OPERATOR_C_HANDOFF_TO_D.md` (20,937 B) · `BUS_OPERATOR_D_STATE.md` (9,339 B) ·
`BUS_OPERATOR_D_STATE_02.md` (4,291 B) · `BUS_OPERATOR_D_STATE_03.md` (4,187 B).

Receipts and rulings:
`RECEIPTS_FULL_SCALE_CHATGPT_OPERATION_20260819.md` (8,278 B) ·
`RECEIPTS_COVERAGE_WAVE_AND_FOUNDER_BINDING_20260819.md` (9,284 B) ·
`RECEIPTS_OPERATOR_D_EXECUTION_20260818.md` (9,003 B) ·
`V009_ADMISSION_AND_OPERATING_FITNESS_RECEIPT_20260819.md` (7,411 B) ·
`OPERATOR_CORRECTION_20260819.md` (1,738 B) ·
`RETRACTED_ROUTE_VERIFICATION_SOO_20260819.md` (2,951 B) ·
`PRINCIPAL_OPERATOR_LEDGER_CURRENT.md` (6,414 B, newest file, 2026-08-22).

Google Docs (native, not markdown):
`OBZIO_ACTIVATION_PACKAGE_2026-08-16` · `OBZIO_HANDOFF_PROTOCOL_INTERIM_2026-08-16` ·
`OBZIO_SETUP_PROCUREMENT_EVIDENCE_BACKLOG_2026-08-16` · `OBZIO_EXTENSION_HANDOFF_2026-08-16` ·
`OBZIO_OPERATOR_A_WAVE001_STATE_20260817`.

Subfolders — **note the duplication**:
- `Founder Operating Method Recovery 2026-08-20` (`1KNJegoYvvA1S-9qsF6YvTv47Ai556Qz_`)
- `Operator Packs v1` (`1T9CYHubJxPTwj0K_w90_E8Mvtgqh6ocO`, 2026-08-21 05:11)
- `Operator Packs v1 2026-08-20` (`1Mtz81e12olK-whVPhVP5vsz62_84RYzD`, 2026-08-21 10:04)
- `Operator Packs v1 2026-08-20` (`1ZymPOBoP2B2B8VOE48v_iektGAuW8Lw2`, 2026-08-22 05:26)
- `Operator Packs v1 2026-08-20` (`1B0K0PFbf3F-7so8Jdf4V7CiE6uZnWmk8`, 2026-08-22 07:59)

**Four near-identical "Operator Packs v1" folders created across ~27 hours.** This is the
signature of a retried upload that partially succeeded each time, not four distinct deliveries.
Contents were not compared in this pass — that is an open item, and a candidate for the
supersede-by-pointer treatment rather than deletion (deletion is recorded as broken across every
route; see OBZIO-OPERATOR.md ALREADY TRIED).

---

## Open items this inventory raises

1. The four duplicate `Operator Packs v1` folders need a contents diff and a controlling pointer.
2. `research_artifact_checksums` (347 rows, second Supabase project) is evidence for OPEN WORK
   item 3 and should be read before Agentforce-Intel / Fivetran-Intel are judged disposable.
3. Item 8 named one Supabase project; there are two. Any future "inventory the estate" task should
   enumerate projects rather than accept a named one as the full set.
