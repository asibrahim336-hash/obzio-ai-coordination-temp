# OpenAI API surface: what is actually there, as of 2026-08-22

**Lane:** OE-L5-CHATGPT-SCALE · **Commission:** COM-CUR-ENV-01-20260822-v001
**State:** READY_TO_COMMIT

Companion machine-readable artifact: `OPENAI-SURFACE-EVIDENCE-20260822-v001.json`
— 58 claims, each carrying the source URL, the sha256 of the exact body fetched,
the UTC fetch time, and a verbatim excerpt cut out of that body.

---

## 0. Method, and why it is worth reading before the findings

Endpoint shapes, parameter names and model identifiers change. Recalling them is
how a programme ends up confidently wrong. So nothing here is recalled.

Two scripts produce everything below, and re-running them re-derives it:

```bash
python3 scripts/harvest_openai_docs.py    --out DOCS --log LOG
python3 scripts/build_surface_evidence.py --docs DOCS --log LOG --out EVIDENCE.json
```

`harvest_openai_docs.py` fetched **59 official documentation URLs, all HTTP 200**,
on **2026-08-22**, recording sha256 for each
(`DIRECTLY_REPRODUCED`; receipt: `receipts/so02/2026-08-22/oe-l5-chatgpt-scale/raw/openai-doc-fetch-log.json`).

`build_surface_evidence.py` then cuts each excerpt **out of the fetched body at
build time** using a literal locator. If a locator stops matching, the build
fails rather than emitting a stale quotation. That is a deliberate tripwire: the
next wave learns that the documentation moved on the day it moved, not on the
day something breaks in production.

The route paths themselves were not guessed either. They were read out of the
published indexes — `developers.openai.com/llms.txt`,
`/api/reference/llms.txt`, `/api/docs/llms.txt`,
`/workspace-agents/llms.txt` and `learn.chatgpt.com/llms.txt` — which are
harvested alongside the pages they point to. This mattered: a first pass that
guessed plausible paths produced 24 404s out of 34, including
`.../conversations/methods/get.md`, which does not exist. The real method is
`retrieve`. Guessing would have put a wrong route into an activation programme.

**Evidence labels.** `DIRECTLY_REPRODUCED` — this lane fetched or ran it, with
URL/command and date. `DOCUMENTED` — official source, cited, but not the basis
of an endpoint-shape claim. `HYPOTHESIS` — untested inference, never used for an
API surface claim.

---

## 1. The route is credential-blocked, not unsupported

`DIRECTLY_REPRODUCED` — `bash scripts/probe_openai_routes.sh`, 2026-08-22T20:38:23Z,
receipt at `receipts/so02/2026-08-22/oe-l5-chatgpt-scale/raw/unauthenticated-route-probe.txt`.

| Route | Status | Body |
|---|---|---|
| `GET https://api.openai.com/v1/models` | 401 | `Missing bearer authentication in header` |
| `GET https://api.openai.com/v1/conversations/{id}` | 401 | `Missing bearer or basic authentication in header` |
| `GET https://api.openai.com/v1/responses/{id}` | 401 | `Missing bearer or basic authentication in header` |
| `GET https://api.openai.com/v1/batches` | 401 | `Missing bearer or basic authentication in header` |
| `GET https://api.chatgpt.com/v1/workspace_agents/{id}/runs/{run_id}` | 401 | `You didn't provide an access token… create an access token at https://chatgpt.com/admin/access-tokens` |

Every route answers. A 401 is the endpoint telling you it exists and is gated.
A 404 would mean the path is wrong; `000` would mean egress is broken. Neither
occurred. `OPENAI_API_KEY` is absent from this runtime, confirmed by the probe
script's own environment check, which reports presence as yes/no and never reads
the value.

The last row is the one worth pausing on. `api.chatgpt.com` is a **different
host with a different credential** and its 401 names a different provisioning
page. Two routes, two credentials, two capability sets. Treating "the OpenAI
API" as one thing is the first mistake available here.

---

## 2. Responses: the execution primitive

`POST /responses` creates a model response (`C-RESP-ROUTE`). The parameters that
matter to this operation, all `DIRECTLY_REPRODUCED` from
`.../resources/responses/methods/create.md`:

| Parameter | What it does | Why this operation cares |
|---|---|---|
| `background` | runs the response asynchronously (`C-RESP-BACKGROUND`) | long analytical work stops depending on a held connection |
| `conversation` | prepends that conversation's items; the response's input and output items are added back automatically (`C-RESP-CONVERSATION`) | durable, addressable thread without a client-side transcript |
| `previous_response_id` | multi-turn by chaining response ids — **cannot be combined with `conversation`** (`C-RESP-PREVID-EXCLUSIVE`) | two rival state mechanisms; pick one per function and record which |
| `store` | whether the response is retained for later retrieval (`C-RESP-STORE`) | governs whether a result is retrievable after the call returns |
| `metadata` | 16 pairs, keys ≤64 chars, values ≤512 chars (`C-RESP-METADATA-LIMIT`) | far too small for provenance; see §3 |

Retrieval is `GET /responses/{response_id}` (`C-RESP-RETRIEVE`). An in-flight
background response can be cancelled (`C-RESP-CANCEL`).

Background mode's own guide is explicit that you start work with `background:
true` and poll the response object, and that `queued` and `in_progress` are the
non-terminal states — leaving them means terminal (`C-BG-POLL`, `C-BG-TERMINAL`).

**The retention trap in background mode.** Two separate statements in the
background guide (`C-BG-ZDR-STORE`, `C-BG-RETENTION-TRAP`) establish that under
Zero Data Retention background requests run `store=false` and survive roughly
ten minutes; and under Modified Abuse Monitoring a background response is
retained past the polling window **only when `store=true` is passed explicitly**
— otherwise it is deleted after roughly ten minutes. So "I started it in the
background and I'll fetch it later" is a false assumption unless `store=true`
was set deliberately. Any function that dispatches background work and collects
it on a later cycle must set `store` explicitly and must reconcile within the
window, or it will lose results and call it a provider failure.

---

## 3. Conversations: addressable custody, with a cost

| Operation | Route | Claim |
|---|---|---|
| create | `POST /conversations` | `C-CONV-ROUTE` |
| retrieve | `GET /conversations/{conversation_id}` | `C-CONV-RETRIEVE` |
| update | `POST /conversations/{conversation_id}` | harvested |
| delete | `DELETE /conversations/{conversation_id}` | `C-CONV-DELETE-ORPHANS` |
| list items | `GET /conversations/{conversation_id}/items` | `C-CONV-ITEMS-LIST` |

Creation accepts initial items, up to 20 at a time (`C-CONV-ITEM-BATCH`).
Identifiers carry a `conv_` prefix (`C-CONV-ID-PREFIX`).

Three findings change design rather than just informing it.

**The conversation object is a container, not a record.** It returns exactly
`id`, `created_at`, `metadata`, `object` (`C-CONV-SHAPE`), and metadata is
capped at 16 pairs of ≤64-char keys and ≤512-char values (`C-CONV-METADATA-LIMIT`).
You cannot store a function identifier, a decision class, a lease token, an
acceptance verdict and a provenance chain in there. This is not a reason to
avoid conversations; it is the reason the repository stays canonical and the
conversation id is a *locator* pointing into it. The operating programme's rule
that durable state lives in the repository is not merely a governance
preference — the provider's own object cannot hold it.

**Deleting a conversation does not delete its items** (`C-CONV-DELETE-ORPHANS`,
verbatim: "Items in the conversation will not be deleted"). Deleting the
container is not deleting the content. Any remediation function that plans to
"clean up" by deleting conversations must know it is removing the index, not the
data.

**Conversations are the most retentive endpoint on the platform.** From the
retention table (`C-RET-RESPONSES`, `C-RET-CONVERSATIONS`):

| Endpoint | Abuse-monitoring retention | Application-state retention | ZDR eligible |
|---|---|---|---|
| `/v1/responses` | 30 days | None (with exceptions) | Yes |
| `/v1/conversations` | **Until deleted** | **Until deleted** | **No** |
| `/v1/conversations/items` | **Until deleted** | **Until deleted** | **No** |

Durability is what makes the endpoint useful and is simultaneously its privacy
cost. Default abuse-monitoring retention elsewhere is 30 days (`C-RET-ABUSE-DEFAULT`);
for conversations it is until deletion, and Zero Data Retention cannot be
applied. **A programme that routes founder-intent material through Conversations
is choosing indefinite provider-side retention of that material.** That is a
founder decision, not a lane decision. Retention controls, where approved, are
configured under Settings → Organization → Data controls (`C-RET-CONTROLS-LOCATION`).

---

## 4. Structured outputs and strict tools: the discipline enforcer

Structured Outputs constrains generation to a supplied JSON Schema so a required
key cannot be omitted and an enum value cannot be invented (`C-SO-GUARANTEE`).
Safety refusals become programmatically detectable rather than prose a parser
would mistake for content (`C-SO-REFUSAL`). It is enabled through
`text: { format: { type: "json_schema", "strict": true, "schema": … } }`
(`C-SO-ENABLE`) and is supported on both the Responses API and the Batch API
(`C-SO-SURFACES`).

This is the single most useful thing on the surface for this operation, and the
reason is specific. The diagnosed failure is conflated
proposed/launched/observed/completed/accepted states. A strict enum over exactly
those states, enforced at generation time, makes "the model wrote something
state-shaped" impossible. A function cannot report `accepted` unless `accepted`
is a legal value of a schema that the acceptance owner controls.

For tools, `strict: true` makes calls adhere to the declared schema instead of
being best effort, and the provider recommends always enabling it (`C-FC-STRICT`).
There is a trap: **if `strict` is omitted, Responses may normalise the schema
and silently fall back to non-strict best-effort calling** (`C-FC-STRICT-FALLBACK`).
Omission is not a neutral default. Anywhere conformance is being relied on,
`strict` must be set explicitly, and the fallback case must be treated as a
defect rather than a nicety.

---

## 5. Background plus webhooks: the mechanism that removes the human poller

Webhooks deliver real-time notification when a batch completes, a background
response is generated, or a fine-tuning job finishes (`C-WH-EVENTS`).
`response.completed` is a published event type (`C-WH-EVENT-NAME`); the
reference also publishes `response.failed`, `response.cancelled`,
`response.incomplete`, and the `batch.*` family
(harvested in `webhooks-overview`). Endpoints are registered in the OpenAI
dashboard and subscribed to specific events (`C-WH-DASHBOARD`). Delivery follows
the Standard Webhooks specification; payload authenticity is validated before
parsing (`C-WH-UNWRAP`) using a **separate secret** carried in
`OPENAI_WEBHOOK_SECRET`, distinct from the API key (`C-WH-SECRET-ENV`).

The founder-directive relevance is direct. "The founder must not become the
relay, retriever, comparer or merge layer" is, mechanically, a requirement that
*something other than a person notices that work finished*. Polling needs a
poller. Webhooks are the documented way to have completion announce itself. The
catch is equally concrete: a webhook needs a reachable HTTPS endpoint. A cloud
agent VM is not one. Until an endpoint exists that outlives an agent run, the
honest fallback is background plus scheduled polling from a durable runner, and
the founder-load ledger should carry that as a known deficiency rather than
pretending the push route is live.

---

## 6. Batch: the economics of a large sweep

50% lower cost, a separate higher rate-limit pool, and a 24-hour turnaround
(`C-BATCH-ECONOMICS`). Accepted endpoints are `/v1/responses`,
`/v1/chat/completions`, `/v1/embeddings` (`C-BATCH-ENDPOINTS`). A single batch
takes up to 50,000 requests and a 200 MB input file (`C-BATCH-LIMITS`).

Structured Outputs works inside Batch (`C-SO-SURFACES`), which is what makes
Batch usable for classification work rather than only for text generation.

The caveat that keeps this honest: batch is superb for **API-native** bulk work
and is *not* a route to the 121 sidebar chats, because those live in the ChatGPT
UI and no batch route can read them. See §8.

---

## 7. Access control, spend and the shape of a minimum credential

Permissions are per-area and several are custom-role eligible (`C-RBAC-RESPONSES-PERM`,
`C-RBAC-MODELS-PERM`). Relevant rows from the RBAC table:

| Area | What it allows | Custom-role eligible |
|---|---|---|
| List models | list models the organization can access | yes |
| Model capabilities | make requests to chat completions, audio, embeddings, images | yes |
| Responses API | create responses | yes |
| Webhooks | create and view webhooks in the project | yes |
| Batch | create and manage batch jobs | no |

Two operationally important details. A project API key's effective rights are
the **intersection** of the key's permissions and the owning user's project role
(`C-RBAC-DOUBLE-CHECK`) — so over-scoping a key does not by itself grant access,
and under-scoping the user silently breaks a correctly scoped key. And the
provider's own instruction is to start from least privilege (`C-RBAC-LEAST-PRIV`).

Note an absence rather than a presence: **the RBAC table publishes no row named
Conversations.** Whether conversation operations are governed by the Responses
API permission or by something else is not stated on the page fetched. This is
recorded as `HYPOTHESIS` — most plausibly they ride with Responses API rights —
and it is exactly what the canary in §10 settles empirically, at a cost of one
API call.

**Spend.** A spend alert only notifies; a hard spend limit stops traffic
(`C-SPEND-HARD-LIMIT`). At the limit, requests return HTTP 429 with
`organization_spend_limit_exceeded` or `project_spend_limit_exceeded`, and
enforcement is not instantaneous, so recorded spend can slightly exceed the cap
(`C-SPEND-429`). Organization limits are set at
`https://platform.openai.com/settings/organization/limits` (`C-SPEND-LOCATION`).

This is the control that makes activation reversible-by-arithmetic rather than
by trust, and it is why the activation programme sets the limit *before* the key
is issued rather than after.

---

## 8. What actually reaches the founder's ChatGPT UI — and what does not

This is the section the programme depends on, so it is stated flatly.

**The Responses and Conversations APIs do not read the founder's ChatGPT UI.**
They operate on `api.openai.com` platform objects. A `conv_…` conversation
created through the API is not a chat in the sidebar; the 11 projects, the 61
project chats and the 121 sidebar chats are not addressable through any route in
§2–§6. No amount of API activation changes that.

Two documented routes touch the ChatGPT surface. Neither is a substitute.

### 8.1 Workspace Agents — dispatch without return

`POST https://api.chatgpt.com/v1/workspace_agents/{id}/trigger` triggers a
published ChatGPT workspace agent from outside the UI (`C-WA-TRIGGER-ROUTE`). It
durably queues the event and returns `202 Accepted` with a `conversation_url`
(`C-WA-ACCEPTED`). Optional `conversation_key` continues the same agent
conversation across trigger events; an `Idempotency-Key` header makes retries
safe.

Then the decisive sentence, verbatim from the documentation
(`C-WA-NO-RETURN`):

> The agent's response cannot currently be retrieved through the API.

Beta run polling, behind `OpenAI-Beta: workspace_agent_runs=v1`, returns
`queued` / `in_progress` / `suspended` / `completed` / `failed` — **status
only, never content** (`C-WA-RUN-STATUS`).

So Workspace Agents is a real, documented, one-way route: it can start work
inside the account, and it can tell you the work finished, but the result comes
back only as a URL a human opens. For this operation that is precise and
damaging: **a route that ends in "the founder opens a link and reads it" is the
founder-as-relay pattern the directives prohibit**, arriving dressed as
automation. It is genuinely useful for dispatch and scheduling. It cannot close
a return loop on its own.

Provisioning: a workspace admin must enable Workspace agents and turn on
personal access tokens under Admin → Permissions & roles; the token is then
created in ChatGPT under **Admin → Access tokens** with the **Workspace Agents**
scope (`C-WA-TOKEN-LOCATION`), and is scoped to Workspace Agents operations only
— a different credential from `OPENAI_API_KEY` (`C-WA-TOKEN-SCOPE`). The live
401 in §1 independently names `https://chatgpt.com/admin/access-tokens` as the
creation page.

### 8.2 Compliance API — the only documented read route, and it is opaque

The Compliance API exists to export auditable ChatGPT records into an external
audit or investigation system (`C-COMPLIANCE-PURPOSE`). That is the closest
documented thing to "read what is in the account".

But the public page **deliberately does not publish routes, schemas, filters or
retention behaviour**; it states that the authenticated Admin API reference at
`chatgpt.com/admin/api-reference` is the source of truth (`C-COMPLIANCE-UNDOCUMENTED`).
And the linked platform guide is titled for **ChatGPT Enterprise, Edu and
ChatGPT for Teachers** (`C-COMPLIANCE-PLAN-GATE`).

Three consequences, stated as limits rather than smoothed over:

1. This lane **cannot** specify a Compliance API call. The contract is behind
   authentication this lane must not attempt. Anyone who writes you a concrete
   Compliance endpoint today is recalling, not reading.
2. It is plan-gated. Whether it exists for this account depends on a fact this
   lane does not have — which plan the account is on.
3. It is designed for export-to-SIEM, not for agent coordination. Even granted,
   it would give an auditable record trail, not a working return channel.

### 8.3 The honest summary of UI reach

| Want | Route | Reality |
|---|---|---|
| start work inside ChatGPT from outside | Workspace Agents trigger | works; admin-gated; separate token |
| get that work's result back automatically | — | **not available**; response not retrievable via API |
| read existing projects / chats | Compliance API | plan-gated, admin-gated, contract not public |
| bulk-export account content | Data Controls export (UI) | owner action, one-shot, not a route |
| a programmatic loop inside the UI | connector / MCP tool | exists as a surface; needs a decision, see below |

The connector/MCP surface (`guide-tools-connectors-mcp`,
`chatgpt-apps-connectors`, harvested) is the most plausible non-founder return
route for UI-resident work, because a connector runs *inside* the chat and can
reach an external system the repository also reaches. It is also a disclosure
and security decision, not merely a technical one, which is why the operating
programme raises it as a founder question rather than assuming it.

---

## 9. Which of this actually serves the operation

Matching surface to need, rather than listing capabilities:

| Operational need | Route | Verdict |
|---|---|---|
| durable, addressable unit of work with a stable locator | Conversations | **serves** — but the id is a pointer; the repo holds the record (§3) |
| stop conflating proposed/launched/observed/completed/accepted | Structured Outputs, strict enums | **serves, strongly** — makes an illegal state ungeneratable (§4) |
| long analytical work that outlives a connection | `background: true` | **serves** — with the explicit `store` discipline (§2) |
| completion noticed without a human | webhooks | **serves in principle**; needs a durable HTTPS endpoint this runtime lacks (§5) |
| bulk classification of API-native material | Batch | **serves** — 50%, 24h, 50k/batch (§6) |
| triage of the 121 sidebar chats | any API route | **does not serve** — not addressable (§8) |
| independent acceptance of API-produced work | separate key/role per actor | **serves** — RBAC is per-area and custom-role eligible (§7) |
| bounded, reversible activation | hard spend limit | **serves** — set before issuing the key (§7) |
| dispatch into the ChatGPT account | Workspace Agents | **partially** — dispatch yes, return no (§8.1) |
| read the account's existing content | Compliance API | **unknown** — plan-gated and not publicly specified (§8.2) |

---

## 10. Model identifiers: deliberately not bound

The harvested documentation names current model families, and the guides index
lists per-model pages including several `gpt-5.x` entries
(`index-guides`, harvested 2026-08-22). **This lane binds none of them.**

Two reasons, one procedural and one technical. Procedurally, binding a named
model is outside this lane's authority; the founder decides. Technically, model
identifiers are exactly the class of fact that goes stale between the writing of
a document and its execution — which is the whole reason this findings document
was built from live fetches.

The consequence for the canary in the activation programme is concrete: it
**discovers** an available model id from `GET /v1/models` at runtime and lets the
operator override it by environment variable. It does not hardcode one. A script
that hardcodes a model identifier is a script that starts failing on a date
nobody chose.

---

## 11. What this section does not claim

- No claim is made about which ChatGPT plan the account holds. Everything in
  §8.1 and §8.2 branches on that fact, and this lane does not have it.
- No Compliance API route, schema or filter is specified, because none is
  publicly published.
- No claim that conversation operations require a specific RBAC permission; the
  table publishes no Conversations row and the canary is designed to settle it.
- No authenticated call was made. Every status code above came from a request
  carrying no credential.
