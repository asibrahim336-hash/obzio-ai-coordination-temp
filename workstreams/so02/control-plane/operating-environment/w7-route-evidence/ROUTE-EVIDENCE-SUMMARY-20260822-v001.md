# Route evidence: what can travel between Ahmed's ChatGPT account and Cursor

**Lane:** OE-W7-CHATGPT-ROUTE-EVIDENCE · **Commission:** COM-CUR-ENV-01-20260822-v001
**State:** `READY_TO_COMMIT` · **Branch:** `cursor/oe-w7-route-evidence-696d`

Machine-readable companion: `ROUTE-EVIDENCE-TABLE-20260822-v001.json` — 27 routes,
72 excerpts cut out of bodies this lane fetched, 18 claims reused from OE-L5 with
their original hashes, 3 counted scans used for claims about absence.

This lane evidences routes. It opened none, authenticated to nothing, and holds no
credential of any name.

---

## The one finding that matters

**The decisive column is not "does a route exist" but "does a result come back
without Ahmed touching it".** Thirteen of the 27 routes return to a machine. Five
return only to a place a person must open. The five are where the founder-as-relay
pattern hides, and it hides best when a great deal of automation sits upstream of
the link a human still has to click.

The single sharpest fact in the table is an asymmetry between two agent platforms
answering the same architectural question in opposite ways:

| | OpenAI Workspace Agents | Cursor Cloud Agents |
|---|---|---|
| Start work from outside | yes, `202 Accepted` with a conversation URL | yes, `POST /v1/agents` |
| Retrieve what the agent said | **no** — "The agent's response cannot currently be retrieved through the API." | **yes** — the run stream's terminal `result` event carries `text`, "the final assistant reply" |
| Poll for progress | status enum only: `queued`, `in_progress`, `suspended`, `completed`, `failed` | assistant text deltas, thinking, tool calls with args and results |

Both statements are `DOCUMENTED`, quoted verbatim, from bodies whose sha256 is
recorded. The practical consequence is a design rule, not a complaint: **build any
loop to terminate on the Cursor side, where content is retrievable, never on the
ChatGPT side, where it is not.**

---

## What was asked about Workspace Agents, verified

The brief said this would be decisive if true. It is true, and it verifies against
live documentation rather than recall.

`POST https://api.chatgpt.com/v1/workspace_agents/{id}/trigger` genuinely starts
work inside the account and durably queues it. Then the documentation says, in one
sentence: *"The agent's response cannot currently be retrieved through the API."*
Beta run polling behind `OpenAI-Beta: workspace_agent_runs=v1` returns the five
status values above and no content.

So Cursor can start the work, and Cursor can learn that it finished, and Cursor
cannot learn one word of what it concluded. A workflow ending in "the founder opens
the conversation URL" is exactly the prohibited pattern; automating the noticing
while leaving the relaying to him automates the half that costs nothing.

This is not a reason to discard the route. Dispatch and scheduling are real value.
It is a reason never to draw it as a closed loop.

---

## Routes that return without Ahmed touching them

Thirteen, in three groups.

**Already ours, carrying no account content.** The Responses API (R01),
Conversations API (R02), API-side service connectors (R03), the Codex Analytics API
(R12), Cursor's own agent API (R23), Cursor's inbound `@cursor` triggers (R24),
Cursor webhooks (R25) and Cursor's MCP consumption (R27). Each returns to a machine.
None carries anything from his account, so none closes a loop that was open.

**The account reaching outward into GitHub — the group that actually answers the
brief's question.** Codex cloud with a connected repository (R14) works on a branch
and opens pull requests. Codex code review (R15) *"posts a review on the pull
request, just like a teammate would"*, will do it on every new PR with Automatic
reviews on, and *"can push a fix back to the branch when it has permission to do
so."* The Codex GitHub Action (R16) runs in CI and posts back.

The reason these close the loop is worth stating plainly, because it is the design
lesson: **they write where Cursor already reads.** No conversation API achieves
that; a commit does. This lane did not exercise any of them — its boundaries forbid
modifying any pull request — so they are `DOCUMENTED` and deliberately not
`DIRECTLY_REPRODUCED`.

**Workspace identity for automation.** Codex access tokens (R17) authenticate
non-interactive `codex exec` runs as a named ChatGPT workspace user, with runs
appearing in governance data. Service accounts (R18) give a non-human identity the
same roles and auditability as a person. Both are plan-gated and neither opens his
chats; they authorise code work under an attributable identity.

## Routes that do not

Five. `R07` Workspace Agents trigger and `R08` its beta polling, for the reason
above. `R13` the data export, below. `R20` the ChatGPT Chrome extension, which
reaches authenticated sessions nothing else can and for exactly that reason is the
most founder-coupled route here — output lands in a chat on his machine. `R21` the
built-in browser and desktop Computer Use, which is documented for macOS and Windows
only and therefore cannot run in this Linux runtime at all.

## Eight conditional, and the conditions are the whole story

A conditional route behaves as `NO` until its precondition holds. Naming the
precondition is the useful part:

| Route | Becomes YES when |
|---|---|
| R04 ChatGPT connectors | the connector writes into a system Cursor reads, rather than returning data into the chat |
| R05 Remote MCP app in ChatGPT | a reachable MCP endpoint exists — see R06 |
| R06 Secure MCP Tunnel | a durable host runs `tunnel-client`, plus tunnel RBAC and developer mode |
| R09 ChatGPT scheduled tasks (web) | the scheduled run's own action writes outward instead of into the Scheduled inbox |
| R10 Scheduled tasks (desktop, repo) | his machine is on, the app is running, and the task pushes |
| R11 Compliance API | plan eligibility is confirmed and the authenticated contract is read |
| R22 Cursor-side browser control | an authenticated `chatgpt.com` session exists |
| R26 OpenAI platform webhooks | a durable HTTPS endpoint exists |

---

## Two corrections to what this lane inherited

**The Cursor inbound API is real, and the predecessor's 404 was a wrong guess.**
OE-W6 recorded HTTP 404 for `cursor.com/docs/background-agent/api/overview.md` and
so could not establish the route. That path does not exist. Reading the published
docs sitemap instead of guessing again produced
`cursor.com/docs/cloud-agent/api/endpoints` and `.../api/webhooks`, both HTTP 200,
documenting agent creation, run streaming, artifacts, worker tokens and fleet
management. The route was never absent; the guess was wrong. This is the same lesson
OE-L5 recorded when guessed paths produced 24 404s out of 34, and it recurred.

**Secure MCP Tunnel removes the blocker OE-L5 identified.** That lane concluded
push-based return needed a durable public HTTPS endpoint this runtime lacks. Secure
MCP Tunnel — absent from the W6 harvest entirely, found by following a link out of
the connectors guide — *"lets you connect private MCP servers to supported OpenAI
products without opening inbound firewall ports"*, and the named callers include
ChatGPT. It is *"an outbound-only connection from a host inside your network"*: no
public ingress, no inbound port. The remaining requirement is a **durable host**,
which an ephemeral cloud-agent pod is not, but that is a materially easier thing to
obtain than public ingress. Connection is configured from ChatGPT Plugins by
creating a developer-mode app and choosing **Tunnel**.

Composed with scheduled tasks (R09), which run unattended and can use
`approval_policy = "never"`, this is the most plausible documented shape for a
return loop that carries chat-resident material into the repository without him.
The **composition is `HYPOTHESIS`**; each part is `DOCUMENTED`.

---

## What the API can and cannot see, stated flatly

The Responses and Conversations APIs **cannot read his ChatGPT UI content**. Prior
work asserted this; this lane tested it rather than repeating it. Every occurrence
of "chatgpt" was enumerated in both full references — the 832 KB Conversations
reference and the 474 KB Responses create reference. In Conversations, all resolve
to the image model id `chatgpt-image-latest` or to one sentence: *"Identifier for
service connectors, like those available in ChatGPT."* In Responses create, they
resolve to that model id, connector identifiers, and `utm_source=chatgpt.com` inside
example web-search citation URLs. **There is no ChatGPT-UI read path in either
reference.** An absence claim needs a search, not a quotation, which is why this one
is recorded as a counted scan.

Where his conversation content *is* documented to be reachable is the **Compliance
API** — and here this lane can say more than OE-L5 could, from a host that answers
rather than one that 403s. The admin FAQ states that for eligible workspaces *"the
Compliance API provides covered ChatGPT conversation records"*, that for eligible
Enterprise and Edu workspaces the Compliance Logs Platform *"provides Work user
prompts and agent responses"*, and that Library files are reachable through
Library-specific endpoints. It also states the limits: these records *"don't
establish a complete audit trail for every hosted file operation, shell command,
browser interaction, tool invocation, or approval"*, and the platform retains data
for 30 days. The routes and schemas remain published only behind authentication.

So the row moves from "plan-gated and unspecified" to "plan-gated, unspecified, and
documented to cover conversation records". Everything still branches on one fact
this lane does not have: **which plan the account is on.**

There is also no GitHub connector. The supported `connector_id` values are exactly
eight — Dropbox, Gmail, Google Calendar, Google Drive, Microsoft Teams, Outlook
Calendar, Outlook Email, SharePoint. The account's path to GitHub is Codex, not the
connector mechanism.

---

## What remains UNESTABLISHED

**One route: the owner's own data export (R13).** Not "undocumented" — unestablished,
and the distinction is the point.

All three sources answered 403 for OE-W6 and 403 again for this lane, once with
curl's default user agent, which rules out a block specific to an agent string. The
bodies are bot-challenge pages: `privacy.openai.com` returns a Cloudflare *"Just a
moment..."* interstitial and `help.openai.com` returns a refresh-and-retry page.
Their bytes differ between fetches because the challenge carries a per-request
nonce, which is why these three are the only sources this lane reports as CHANGED.
No attempt was made to defeat the challenge.

Then the step that turns "we could not read it" into a finding: the **published
`learn.chatgpt.com` index was searched for an account data-export page on a host
that does answer**. It has none. Its only export entries are a single-file Markdown
export of the documentation itself and a security-findings export. This lane looked
for a reachable description of the export route and there is not one.

Its viability, format, contents, scope and delivery mechanism are therefore all
unknown, and a lane may not assume the favourable reading of something it could not
read at all. Even granted, an export is an owner-initiated one-shot delivered to the
owner — not a route.

Three further things are bounded rather than established, and each branches on the
same missing fact:

- **Plan eligibility.** The Compliance API (R11), Codex access tokens (R17,
  Business/Enterprise) and service accounts (R18, pay-as-you-go only) all depend on
  which plan the workspace holds.
- **The Compliance API contract.** Routes, schemas and filters are published only at
  `chatgpt.com/admin/api-reference`, behind authentication this lane must not attempt.
  Anyone who writes you a concrete Compliance endpoint today is recalling, not reading.
- **Whether any GitHub-reaching connector exists in the ChatGPT plugin directory.**
  The directory is live and admin-gated; nothing this lane read enumerates it.

---

## Browser control: the constraint is the session, not the rendering

Confirmed against this runtime rather than assumed. Chrome 148.0.7778.96 is
installed, X.Org 21.1.11 is live on `DISPLAY=:1`, and Cursor's agent Browser tool is
documented with *"full access to console logs and network traffic"* and needs no
external tools. On the API side, the computer-use tool *"return[s] interface actions
for your code to execute"* — the caller supplies the browser, and this runtime has
one.

So driving `chatgpt.com` from here is blocked by exactly one thing: **an
authenticated session.** No ChatGPT credential of any name is present in this pod,
and acquiring one is an owner-identity act this lane is forbidden to attempt. That
makes R22 an authorisation question, not a technical one — and this lane raises it
without recommending it, because delegating a founder session carries a real
security cost that ought to be weighed against R06, which does not require one.

Both API hosts answer `401` from this pod, not `404` and not `000`: the routes exist
and are gated, and egress works.

---

## How much of the harvest was reused

The predecessor's harvest was treated as evidence to carry forward, not work to
redo — re-fetching everything is what exhausted it.

| | |
|---|---|
| W6 harvest reused | 79 sources, 75 at HTTP 200, built 2026-08-23T00:03:58Z, zero authenticated requests |
| What it lacked | it committed the log but **not the bodies**, so the text behind each recorded hash was unavailable |
| Fetched by this lane | 37 sources — only the bodies a route conclusion depends on. 33 at HTTP 200, 3 at 403, 1 at 404 |
| Verified byte-identical to W6 | **28 of 28** overlapping successful fetches |
| Genuinely new sources | 6 — the Cursor API pair, the docs sitemap, the Cursor browser tool, Secure MCP Tunnel, and one 404 |
| Sources cited by a claim | 28 |
| OE-L5 claims reused with original hashes | 18 |
| Authenticated requests | 0. No credential used, read, printed or stored. |

Every one of the 28 overlapping fetches matched the predecessor's sha256 exactly, so
W6's provenance carries forward rather than being restated. Separately, 26 URLs were
fetched independently by OE-L5 at 20:36Z and OE-W6 at 00:03Z and every hash agrees,
which is why L5's excerpts are reused rather than re-cut.

The 404 is recorded rather than quietly dropped:
`developers.openai.com/api/docs/guides/tools-remote-mcp.md` was attempted because
the connectors guide links to `tools-remote-mcp#connectors`, and the `.md`
convention that works elsewhere on that host does not resolve here — it returns a
404 HTML shell. **Nothing in the table cites it**, and the claims it was meant to
support were established instead from `api-secure-mcp-tunnels` and
`chatgpt-extend-mcp`, both HTTP 200. That is one more instance of the same lesson:
constructed documentation paths fail, published ones do not.

---

## Reading the JSON

Each of the 27 routes carries: `reaches`, `cannot_reach`, `credential_required`,
`credential_present_in_this_runtime`, `founder_action_required`,
`provenance_quality`, `returns_without_founder_touch` with its reason, `maturity`,
`status`, `confidence`, and an `evidence` array.

Every evidence item is labelled `DIRECTLY_REPRODUCED`, `DOCUMENTED` or `HYPOTHESIS`.
Every `DOCUMENTED` item carries the source URL, the sha256 of the whole body, the UTC
fetch time, the line the locator matched, whether those bytes are identical to the W6
harvest, and a verbatim excerpt. No capability claim rests on recall.

Excerpts are cut out of the fetched bodies **at build time** by literal locator. If a
locator stops matching, the build fails rather than emitting a quotation that no
longer exists at its source — the next wave learns the documentation moved on the day
it moved. That tripwire fired twice during this build, on two locators that spanned a
line break, and both were corrected against the source rather than loosened.

```bash
python3 tools/fetch_route_gaps.py --harvest W6LOG --out BODIES --log GAPLOG
bash    tools/capture_runtime_facts.sh
python3 tools/build_route_table.py --bodies BODIES --gap-log GAPLOG \
        --w6-log W6LOG --l5-evidence L5JSON --runtime-facts FACTS --out TABLE.json
```

## What this lane did not do

Did not authenticate to ChatGPT, acquire any credential, or sign up for anything. Did
not print or store any credential value; presence is reported by name only. Did not
open, comment on, merge or modify any pull request. Did not message or configure SW,
and did not touch PO-01, PO-03 or MANUS. Did not attempt to defeat the bot challenge
on the three 403 sources. Did not design a constitution, adjudicate a role, or write
a founder action — other lanes own those. Wrote only on its own branch, inside
`w7-route-evidence/**` and `receipts/so02/2026-08-22/oe-w7-route-evidence/**`.
