# Owner credential actions — two dashboard actions, nothing else

Route qualification `CUR-ORCH-QUAL-01` passed on two independent routes without
either of these credentials. Nothing is blocked. These two actions each unblock
one further route and are listed because an agent cannot issue a credential on
the founder's behalf.

Neither action requires you to retrieve, compare, monitor or merge anything.
The orchestrator does all of that itself and writes the evidence to the
repository.

## OA-CURORCH-01 — OpenAI API key

**Why it is non-delegable:** the key is issued against your account.

**Exact action:** Cursor Dashboard → Cloud Agents → Secrets → add a
repository-scoped secret named `OPENAI_API_KEY` holding an authorised key for
the Obzio OpenAI API project.

**What it unblocks:** route `R4-OPENAI-RESPONSES-CONVERSATIONS`. Network egress
from the orchestrator is unrestricted and the endpoint already answers, so the
credential is the only blocker. Verified by an unauthenticated probe on
2026-08-22T13:37:38Z returning HTTP 401 `Missing bearer or basic authentication
in header`.

**What the orchestrator then does unaided:** creates one bounded conversation,
retrieves the result by conversation ID, records the ID as a stable locator with
no credential material, reconciles it into the hash-bound bundle and reads it
back from the remote by immutable SHA.

## OA-CURORCH-02 — Cursor API key

**Why it is non-delegable:** the key is issued against your Cursor account.

**Exact action:** issue a Cursor API key from the Cursor dashboard and add it as
a Cloud Agent secret named `CURSOR_API_KEY`.

**What it unblocks:** route `R4A-CURSOR-AGENT-REST-API`. Route `R2` already
qualifies agent-run observation, result and artifact retrieval over the MCP
surface. This key adds the missing half — programmatic run creation and
follow-up submission — which is what lets one persistent orchestrator dispatch
and collect work without a second Multiple Agents group. Verified by an
unauthenticated probe on 2026-08-22T13:37:38Z returning HTTP 401
`Invalid User API Key`.

**What the orchestrator then does unaided:** creates one bounded canary run,
retrieves its result by run ID, reconciles and reads it back remotely, and
measures the concurrency ceiling against the recorded PO-03 baseline before any
scale-up.

## What these actions explicitly do not authorise

Attaching either credential does not admit a second Cursor Multiple Agents
group, does not promote or merge anything, does not create exclusive dependence
on any provider and does not bind strategy. Each new route must still pass the
same seven-part end-to-end evidence test before it counts.
