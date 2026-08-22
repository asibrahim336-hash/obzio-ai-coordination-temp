> **SUPERSEDED IN PART — 2026-08-22T23:05Z.** Read `FOUNDER-AUTHORITY-20260822T2225Z.json` first; it governs.
>
> - **OA-A is withdrawn.** A Cursor API key already exists in Supabase Edge Secrets. Verify and reuse it; do not mint a duplicate. A name census confirms `CURSOR_API_KEY` is absent from the Cloud Agent namespace, so the remaining work is to bridge the existing key across once the Supabase integration is authenticated.
> - **The tranche-02 stage gate is removed** as a blocking gate. Work not resting on an unverified assumption proceeds immediately.
> - **The per-wave founder touch-point budget (Q7) is withdrawn.** It conflated not overburdening the founder with not sending him routine relay work; those are different axes.
> - **One action was missing.** Authenticating MCP integrations is not the whole of the environment work. This environment is database-managed, established positively rather than inferred, so the applied `environment.json` is valid and inert until the environment record points at the repository file. That is a separate and prior action.
>
> Everything below is retained as written except where the notes above override it.

# Founder tranche 01 — unblock programmatic control

**Stage gate:** nothing beyond this tranche is prescribed until it is evaluated.
**Total founder effort:** two dashboard actions, one answer, one decision.
**Blocking:** none of it. Every lane continues in parallel regardless.
**Secrets:** never pasted into chat. Everything below stores them in a secret manager.

This is deliberately small. It is not the programme; it is the part of the programme whose assumptions are verified well enough to act on now. The rest is built and waiting behind these four items.

---

## Why these four, and why now

The single most consequential finding across the lanes is that the operation currently routes around missing credentials by putting a human in the loop. Two API surfaces are live and return `401` on every real route while nonexistent routes return a differently-shaped `404` — they are credential-blocked, not unsupported. Those two keys are the difference between an agent platform that dispatches and collects its own work, and one that asks you to carry results between systems.

The third item is a question that costs nothing to answer and that two separate routes branch on. The fourth is a policy statement that closes a silent inheritance, and it needs no integration work.

---

## OA-A — Issue a Cursor API key

**Purpose.** Unlock programmatic agent-run creation and follow-up submission. This is the strongest available lever against you acting as relay: with it, this orchestrator can launch, address and collect work itself instead of surfacing it for you to move.

**Surface.** `https://cursor.com/dashboard/api`, on any device.

**Prerequisites.** None.

**Action.** Create an API key. Then store it — do not paste it into chat — at Cursor Dashboard → Cloud Agents → Secrets, as a **repository-scoped** secret named exactly:

```
CURSOR_API_KEY
```

**Permissions and disclosure.** The key acts as your Cursor account for agent operations. It does not widen repository access; the agent already has that. Scope it to this repository only.

**Cost and renewal.** Agent runs created through the API bill as normal agent usage. No separate subscription. The key does not expire on its own; revoke it to end it.

**Expected result.** The secret name appears in the injected-secret list on the next agent run.

**Verification** — reveals nothing:

```bash
echo "$CLOUD_AGENT_ALL_SECRET_NAMES" | tr ',' '\n' | grep -x CURSOR_API_KEY
curl -s -o /dev/null -w '%{http_code}\n' https://api.cursor.com/v1/me \
  -H @<(printf 'Authorization: Bearer %s' "$CURSOR_API_KEY")
```

`200` replaces the `401` recorded before activation. Because the pre-activation state is fully characterised, a failure afterwards is unambiguous rather than a mystery.

**Recovery.** Delete the key at the same page. Nothing else depends on it; the qualified GitHub custody route is unaffected.

**Stop condition.** If `/v1/me` returns anything other than `200`, stop and report. Do not retry against other routes with a key of unknown validity.

---

## OA-B — Issue an OpenAI API key, spend limit first

**Purpose.** Unlock the Responses and Conversations routes so strategic research, challenge and independent-acceptance lanes can run against a second provider family without you moving anything between systems.

**Sequencing — this order matters.** Set the hard spend limit **before** the key exists. Limit enforcement is documented as not instantaneous, so containment precedes capability.

**Surface.** `https://platform.openai.com`.

**Action.**
1. Create an **isolated project** for this work, so its usage and blast radius are separable from anything else on the account.
2. In that project, set a hard monthly spend limit at a figure you are comfortable losing.
3. At `platform.openai.com/settings/organization/api-keys`, create a key **scoped to that project only**, with the minimum permissions: *List models — Read*, *Responses API — Read+Write*, *Model capabilities — Request*. Nothing else.
4. Store it at Cursor Dashboard → Cloud Agents → Secrets, repository-scoped, named exactly:

```
OPENAI_API_KEY
```

**Permissions and disclosure.** Content sent to `/v1/responses` is not retained. Content in `/v1/conversations` is retained **until explicitly deleted** and is not zero-data-retention eligible, and deleting a conversation does not delete its items. That is precisely why the repository stays canonical and the provider object never holds provenance — its metadata is capped far below what provenance requires. See OA-C-adjacent question Q2 below before any founder-intent material goes through Conversations.

**Cost and renewal.** Usage-based, bounded by the limit you set in step 2. No subscription.

**Expected result.** The secret name appears in the injected-secret list. The prepared canary then creates one conversation, runs one bounded response, and proves retrievability **by identifier on a separate request** — retrieval by ID, not text generation, is what qualifies a route as custody.

**Verification.** The canary script is already written and tested against a synthetic invalid key; its receipt contains zero credential-shaped strings. It feeds the auth header to `curl` on **stdin** so the key never enters an argument vector or a process list, and prints error type and code rather than the message body, which echoes a masked key fragment.

**Recovery.** Revoke the key in the same page; delete the project to remove its history. Both are immediate and local to the isolated project.

**Stop condition.** If the spend limit cannot be set before key creation, stop and report rather than proceeding in the other order.

---

## OA-C — Answer one question

**Which ChatGPT plan does the account hold?**

Free to answer, and load-bearing: both candidate routes for reaching UI-resident work branch on it, and one of them is plan-gated. Answering it prevents a lane from specifying an owner action against a contract that may not exist for you.

No action, no cost, no risk. Just the plan name.

---

## OA-D — State the MCP policy, connect nothing

**Purpose.** Close a silent inheritance. `disableAllMcpServers` and `mcpServerAllowlist` are both unset, so this repository inherits whatever upstream policy applies, and that inheritance is invisible from inside the repository.

**Decision, not an install.** Choose one:

- **(a) Allowlist** — only explicitly named MCP servers may be used. Recommended.
- **(b) Open** — accept upstream policy as-is, and record that as a deliberate choice.

**The one to think about.** A Slack or Linear connector is the highest-risk item on the horizon, and not for the usual reasons: it would create a **second place where "what is current" can be asserted**. Given that competing currentness claims are already the estate's most damaging defect, adding another source of truth deserves a decision rather than a default. Nothing here asks you to connect one; only to say whether they need naming first.

---

## What continues in parallel regardless

Currentness compilation against the live estate; the capability and topology evidence base; independent acceptance structure; the staged Cursor configuration, still unapplied and outside `.cursor/`; and integration controls now running in CI on every push.

---

## The gate before tranche 02

Tranche 02 is not written as prescriptions yet, deliberately. It becomes specifiable once these are known:

- whether `CURSOR_API_KEY` verifies, which decides whether agent-run creation is real here or only documented;
- the plan answer from OA-C, which decides which UI-reaching route is even available;
- your ruling on Q1 and Q2 below, which decide whether provider-side retention of founder-intent material is acceptable at all.

Until those are known, writing tranche 02 would mean prescribing against assumptions — the failure this correction was issued to stop.

---

## Questions that need your judgment, ranked

**Q1 — Is R2 qualified?** Your instruction records it as qualified and directs work that "the qualified R1/R2 routes already enable". The independent acceptance you asked me to constitute refused exactly that, and a second lane reached the same place independently. Either accept the narrower reading — proceed on R1 custody, stop claiming two independent routes — or commission R2 to be re-qualified properly. *Currently following the narrower reading; nothing is paused.*

**Q2 — Is indefinite provider-side retention of founder-intent material acceptable?** Durability and retention are the same property seen from two sides, and no configuration setting separates them. This governs how much of the intent corpus may ever transit Conversations.

**Q3 — Does the earlier model allocation still bind?** A directive locks a named model family, but live evidence shows its flagship is far too large for any laptop. Open weights and runnable-by-us are different properties. Model qualification cannot proceed without either re-opening a settled decision or ignoring one.

**Q4 — Which of PR #6 or PR #7 is correct?** Both are open against `main` and both rewrite the same pointer files with different bytes, so whichever merges first silently sets currentness for the other. Deliberately left unresolved: choosing is a founder-bound act.

**Q5 — May a connector hold repository write?** It is the most plausible non-founder return route for UI-resident work, and the alternative is you carrying results.

**Q6 — Is GitHub acceptable as the sole host of canonical state?** Everything currently depends on it. R1 is the one custody route that survived independent challenge, which is a strength and a concentration at the same time.

**Q7 — What is the per-wave founder touch-point budget?** Needed to size tranches, rather than guessing at your tolerance each time.
