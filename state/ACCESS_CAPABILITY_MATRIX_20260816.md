# OBZIO — ACCESS & CAPABILITY MATRIX v1 (16 Aug 2026, ~23:45 Irish)
TEMPORARY — NON-CANONICAL — REPLACEABLE — NO SECRETS
Evidence basis: exercised this session unless marked (reported). Browser-side rows await the successor operator (queue item 5).

| Surface | Auth/route | Read | Write | Action types evidenced | Limitation | Owner act needed | What access unlocks |
|---|---|---|---|---|---|---|---|
| ChatGPT web estate (projects, chats, Work mode) | Browser extension only | YES (UI + backend-api GET, exercised) | YES (project/chat creation, sends, rename PATCH, exercised) | create project (memory-scope select), seed chats, send, rename | Extension bridge unstable today (2 drops); >5KB composer inserts freeze tabs; file-attach only via owner or synthetic paste | Reconnect side panel / new session | Full internal ChatGPT operation without founder relay |
| ChatGPT (OpenAI) API | Zapier connector (27 actions) | YES | YES | (reported — not exercised this session) | API estate ≠ chatgpt.com account; cannot post into web chats | none | Deterministic processing lanes, batch generation |
| Claude Cowork cloud | native session | YES | YES | files, shell, connectors, scheduled tasks, memory | no browser view of ChatGPT/Metamate | none | Unattended recurring work, artifact production |
| Claude-in-Chrome | extension session | — | — | demonstrated: full chatgpt.com operate; drive/gmail via connectors | DOWN in this session (verified); claude.ai excluded by platform | reopen panel / restart Chrome | Authenticated cross-surface browser execution |
| Claude memory (cross-surface) | native | YES | YES | read/append/edit (exercised) | size-capped files | none | Continuity across sessions incl. successor boot |
| Scheduled tasks | claude-code-remote | YES | YES | daily 08:30 + weekly Sun 17:00 live (trig_01SATZ…, trig_01GLX9…) | fresh sessions each fire | none | Unattended briefing/review cadence |
| Gmail — personal (asibrahim336@gmail.com) | connector | YES (search/read, exercised prior cycle) | Partial | labels, drafts; SENDS HELD by standing rule | external sends founder-gated | none for triage | Email triage, CRO watch, priority-queue movement |
| Email — ahmed@obzio.com mailbox | none | NO | NO | — | not connected; CRO correspondence likely there | connect mailbox or open signed-in tab | Closes the CRO/company-admin blind spot |
| Google Calendar | connector — ahmed@obzio.com account | YES (exercised: list_calendars) | YES (reported) | list/create/update events | connected to OBZIO account, not personal gmail | none (verify personal-cal need) | Briefing calendar section; scheduling |
| Google Drive — personal | connector | YES | YES | search/read/create (exercised; 4 docs filed) | sharing changes HELD; .004 ZIP custody NOT here (verified absent) | none | Interim handoff bus (Obzio Ops) |
| GitHub (asibrahim336-hash) | Zapier connector | YES | YES | repo create (custom action, exercised), file CRUD (exercised), branches/PRs/issues/gists (reported) | tokens expiring ≈18 + ≈21 Aug (rotation founder-only) | rotate 2 tokens | Coordination repo; RadarLedger CI diagnosis; release PR work |
| Metamate / SW | none from Claude | NO | NO | — | requires signed-in tab (SSO/VPN) in operator window | open Metamate tab when bootstrap delivery wanted | Native high-scale agent estate (bootstrap commission ready) |
| LinkedIn | Zapier connector (4 actions) | YES (reported) | limited | — | — | none | Monitoring items only |
| Anthropic API | Zapier connector (6 actions) | YES (reported) | YES (reported) | — | billing card issue open | update card | Programmatic Claude lanes if needed |
| Supabase / Vercel / Cloudflare / Notion / HubSpot / Resend / higgsfield | connectors in Cowork | YES | YES | (reported; exercised in prior cycles per package) | production/DNS/deploy changes HELD | none | Obzio platform work under release gate |
| Browser estate (history, extensions, site permissions, account switcher) | extension only | — | — | — | successor to inspect; prefer settings/integrations pages over history scraping | none | Discovery per Addendum 02 |

## Materially useful missing capabilities (ranked)
1. Stable extension bridge (crashes are the top operational risk; mitigation rules in handoff runbook).
2. ahmed@obzio.com mailbox route (CRO blind spot).
3. Metamate tab availability at delivery time (blocks bootstrap commission delivery only).
4. ChatGPT file-attach from operator (owner drag or synthetic-paste; platform file-picker is OS-gated).
5. GitHub token rotations before ≈18/≈21 Aug expiries (founder-only).

## v2 DELTA — 17 Aug 2026, ~01:20 Irish (successor Claude-in-Chrome session; exercised unless marked)

- Claude-in-Chrome: UP (successor session live). Re-demonstrated full chatgpt.com operate: project-chat sends, Work-surface new-chat creation outside projects, model/effort picker set to Ultra, conversation rename via backend-api PATCH (200), verbatim message extraction via backend-api GET, paste-attachment delivery at 35,690 B and 65,419 B (synthetic ClipboardEvent → pasted-text attachment; no composer freeze at these sizes).
- New failure mode + standing mitigation: SPA navigation race — the home/new-chat composer can silently rebind to the most recent conversation between tool calls (caused one misrouted seed 6b3372c1…, voided by in-lane correction). Mitigation now standard: one JS call performing route-check → paste → chip-check → route-recheck → send. Also: coordinate clicks unreliable under window resize; element-ref/DOM clicks required.
- ChatGPT account facts (API-level): asibrahim336@gmail.com, plan pro; Work-surface effort tiers Light/Medium/High/Extra High/Max/Ultra; observed model slug gpt-5.6-sol-wm.
- ChatGPT connected apps (partial): Google Drive connected as Work source (observed in E&I Sources panel); Slack and Linear NOT connected (Connect buttons on Work home); 2 plugins enabled on Work composer (identity not yet inventoried); full settings-dialog inventory deferred to next queue.
- Metamate: extension tool injection FAILS on metamate.meta.com (all extension tools error on that origin — site access not granted or unsupported). Bootstrap delivery blocked from the operator. Owner routes: (a) grant the Claude extension site access to metamate.meta.com and provide a signed-in tab, or (b) paste the paste-ready commission directly (~1 min) from commissions/METAMATE_BOOTSTRAP_COMMISSION_DRAFT_20260816.md.
- chrome:// pages (extensions, site permissions, settings): CONFIRMED unreachable — navigation coerces chrome:// to https and tools cannot attach. Method substitution per Addendum 02: provider-native settings/API surfaces + connected-tool registries are the discovery routes; history scraping remains excluded.
- GitHub browser route: signed-in session CONFIRMED (private repo readable in-tab; raw.githubusercontent token-redirect fetch works).
- Zapier estate verified live this session: Gmail (12 actions), LinkedIn (4), GitHub (30, connection asibrahim336-hash), Anthropic (6), ChatGPT/OpenAI API (27).
- Claude scheduled tasks verified live via claude-code-remote: trig_01SATZsoQttGX6SUGC4yRKrW daily 07:30Z (next 2026-08-17T07:31Z), trig_01GLX97waErKzNWgrsVrncd1 weekly Sun 16:00Z (next 2026-08-23T16:03Z), push on, both enabled.
- Drive fallback pointer verified readable via Claude Drive connector (doc 1SzDA5Q47gOX0f5ysBuRCSiOF8X_tlwQoWTHOKGYCYKA).
