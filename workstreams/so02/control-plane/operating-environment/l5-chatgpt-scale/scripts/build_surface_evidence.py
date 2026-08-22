#!/usr/bin/env python3
"""Build the OpenAI API surface evidence register from harvested documentation.

Each claim names a source id and a locator (a literal substring). The excerpt is
cut out of the *fetched body* at build time rather than typed by hand, so an
excerpt cannot drift from the document it cites. If a locator stops matching,
the build fails loudly: that means the documentation changed and the claim needs
re-reading, which is exactly the signal this lane wants.

Pipeline:
    harvest_openai_docs.py --out DOCS --log LOG
    build_surface_evidence.py --docs DOCS --log LOG --out EVIDENCE.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

# (claim_id, source_id, locator substring, lines_before, lines_after, claim text)
CLAIMS: list[tuple[str, str, str, int, int, str]] = [
    # ---------------- Responses API ----------------
    ("C-RESP-ROUTE", "responses-create", "**post** `/responses`", 0, 2,
     "A model response is created by POST /responses."),
    ("C-RESP-BACKGROUND", "responses-create", "- `background: optional boolean", 0, 3,
     "POST /responses accepts a boolean `background` parameter that runs the "
     "response asynchronously."),
    ("C-RESP-CONVERSATION", "responses-create", "- `conversation: optional string", 0, 4,
     "POST /responses accepts a `conversation` parameter; items from that "
     "conversation are prepended to the request and the input and output items "
     "of the response are added back to the conversation automatically."),
    ("C-RESP-PREVID-EXCLUSIVE", "responses-create", "- `previous_response_id: optional", 0, 5,
     "`previous_response_id` and `conversation` are mutually exclusive: two "
     "different mechanisms for carrying state, not one."),
    ("C-RESP-STORE", "responses-create", "- `store: optional boolean", 0, 3,
     "`store` controls whether the generated response is retained for later "
     "retrieval via API."),
    ("C-RESP-METADATA-LIMIT", "responses-create", "- `metadata: optional Metadata", 0, 8,
     "Response metadata is capped at 16 key-value pairs, keys at 64 characters "
     "and values at 512 characters."),
    ("C-RESP-RETRIEVE", "responses-retrieve", "**get** `/responses/{response_id}`", 0, 2,
     "A stored response is addressable by identifier through "
     "GET /responses/{response_id}."),
    ("C-RESP-CANCEL", "guide-background", "responses/resp_123/cancel", -2, 2,
     "An in-flight background response can be cancelled by POST to the cancel "
     "route."),
    # ---------------- Conversations API ----------------
    ("C-CONV-ROUTE", "conversations-create", "**post** `/conversations`", 0, 2,
     "A conversation is created by POST /conversations."),
    ("C-CONV-ITEM-BATCH", "conversations-create", "You may add up to 20 items at a time", -1, 0,
     "Conversation creation accepts initial items, up to 20 at a time."),
    ("C-CONV-RETRIEVE", "conversations-retrieve", "**get** `/conversations/{conversation_id}`", 0, 2,
     "A conversation is addressable by identifier through "
     "GET /conversations/{conversation_id}."),
    ("C-CONV-SHAPE", "conversations-retrieve", "Conversation object { id, created_at", 0, 1,
     "The conversation object carries exactly id, created_at, metadata and "
     "object: it is an addressable container, not a provenance record."),
    ("C-CONV-ID-PREFIX", "conversations-retrieve", '"id": "conv_123"', -2, 3,
     "Conversation identifiers use a conv_ prefix and are returned in the "
     "creation and retrieval payloads."),
    ("C-CONV-METADATA-LIMIT", "conversations-retrieve", "Set of 16 key-value pairs", 0, 2,
     "Conversation metadata is capped at 16 key-value pairs, keys at 64 "
     "characters and values at 512 characters."),
    ("C-CONV-DELETE-ORPHANS", "conversations-delete", "Items in the conversation will not be deleted", -2, 0,
     "Deleting a conversation does not delete its items: deletion of the "
     "container is not deletion of the content."),
    ("C-CONV-ITEMS-LIST", "conversation-items-list", "/conversations/{conversation_id}/items", 0, 2,
     "The items of a conversation are listable by conversation identifier."),
    # ---------------- background mode ----------------
    ("C-BG-POLL", "guide-background", "Background mode kicks off these tasks asynchronously", 0, 0,
     "Background mode executes long-running work asynchronously and exposes "
     "status by polling the response object."),
    ("C-BG-TERMINAL", "guide-background", "Keep polling while the request is in the queued", -1, 1,
     "queued and in_progress are the non-terminal states; leaving them means a "
     "terminal state has been reached."),
    ("C-BG-ZDR-STORE", "guide-background", "Background requests from Zero Data Retention", 0, 2,
     "Under Zero Data Retention, background requests run with store=false and "
     "are held only about ten minutes for polling."),
    ("C-BG-RETENTION-TRAP", "guide-background", "retained after the polling period only when", -3, 2,
     "Under Modified Abuse Monitoring a background response is retained past "
     "the polling window only if store=true was passed explicitly; otherwise it "
     "is deleted after roughly ten minutes."),
    # ---------------- webhooks ----------------
    ("C-WH-EVENTS", "guide-webhooks", "allow you to receive real-time notifications about events", 0, 0,
     "Webhooks deliver real-time notification when a batch completes, a "
     "background response is generated or a fine-tuning job finishes. This is "
     "the push route that removes polling and, with it, the human poller."),
    ("C-WH-EVENT-NAME", "webhooks-overview", "## response.completed", 0, 1,
     "response.completed is a published webhook event type in the reference."),
    ("C-WH-SECRET-ENV", "guide-webhooks", 'OPENAI_WEBHOOK_SECRET="', -1, 0,
     "Webhook signature verification uses a separate secret carried in "
     "OPENAI_WEBHOOK_SECRET, distinct from the API key."),
    ("C-WH-DASHBOARD", "guide-webhooks", "set up a webhook endpoint in the OpenAI dashboard", 0, 0,
     "Webhook endpoints are registered in the OpenAI dashboard and subscribed "
     "to specific event types."),
    ("C-WH-UNWRAP", "webhooks-unwrap", "Validates that the given payload was sent by OpenAI", 0, 0,
     "The SDK exposes an unwrap operation that validates payload authenticity "
     "before parsing."),
    # ---------------- batch ----------------
    ("C-BATCH-ECONOMICS", "guide-batch", "50% lower costs", 0, 0,
     "The Batch API offers 50% lower cost, a separate higher rate-limit pool "
     "and a 24-hour turnaround."),
    ("C-BATCH-ENDPOINTS", "guide-batch", "For now, the available endpoints are:", 0, 5,
     "Batch accepts /v1/responses, /v1/chat/completions and /v1/embeddings."),
    ("C-BATCH-LIMITS", "guide-batch", "A single batch may include up to 50,000 requests", -1, 0,
     "A single batch admits up to 50,000 requests and a 200 MB input file."),
    # ---------------- structured outputs and tools ----------------
    ("C-SO-GUARANTEE", "guide-structured-outputs", "always generate responses that adhere to your supplied", -1, 0,
     "Structured Outputs constrains generation to a supplied JSON Schema so "
     "required keys cannot be omitted and enum values cannot be invented."),
    ("C-SO-REFUSAL", "guide-structured-outputs", "Explicit refusals:", 0, 0,
     "Safety refusals are programmatically detectable rather than returned as "
     "prose that a parser would mistake for content."),
    ("C-SO-SURFACES", "guide-structured-outputs", "Both Structured Outputs and JSON mode are supported in", -1, 0,
     "Structured Outputs is available on the Responses API and the Batch API, "
     "so the same schema discipline covers interactive and bulk work."),
    ("C-SO-ENABLE", "guide-structured-outputs", "json_schema\", \"strict\": true", 0, 0,
     "Strict schema adherence is enabled through the text.format configuration "
     "with type json_schema and strict true."),
    ("C-FC-STRICT", "guide-function-calling", "will ensure function calls reliably adhere to the function schema", -1, 1,
     "Setting strict true makes function calls adhere to the declared schema "
     "rather than being best effort; the provider recommends always enabling "
     "it."),
    ("C-FC-STRICT-FALLBACK", "guide-function-calling", "attempt to normalize your schema into strict mode", -2, 4,
     "If strict is omitted, Responses may silently fall back to non-strict "
     "best-effort calling. Omission is therefore not a neutral default and "
     "must be set explicitly wherever conformance is being relied on."),
    # ---------------- retention ----------------
    ("C-RET-ABUSE-DEFAULT", "guide-your-data", "retained for up to 30 days", -1, 0,
     "Abuse-monitoring logs are generated for all API usage and retained up to "
     "30 days by default."),
    ("C-RET-RESPONSES", "guide-your-data", "| `/v1/responses`", 0, 0,
     "/v1/responses is Zero Data Retention eligible and holds no application "
     "state by default."),
    ("C-RET-CONVERSATIONS", "guide-your-data", "| `/v1/conversations`", 0, 1,
     "/v1/conversations and /v1/conversations/items retain application state "
     "UNTIL DELETED and are NOT Zero Data Retention eligible. Durability is the "
     "point of the endpoint, and it is also its privacy cost."),
    ("C-RET-CONTROLS-LOCATION", "guide-your-data", "Settings → Organization → Data controls", -1, 0,
     "Data retention controls, once approved, are configured under Settings, "
     "Organization, Data controls."),
    # ---------------- access control ----------------
    ("C-RBAC-RESPONSES-PERM", "guide-rbac", "| Responses API", 0, 0,
     "Responses API access is a distinct permission that is custom-role "
     "eligible."),
    ("C-RBAC-MODELS-PERM", "guide-rbac", "| List models", 0, 0,
     "Listing models is a distinct, custom-role-eligible permission: the "
     "cheapest possible probe needs no generation right."),
    ("C-RBAC-DOUBLE-CHECK", "guide-rbac", "we take the permissions assigned to the API key", -1, 1,
     "A project API key's effective rights are the intersection of the key's "
     "permissions and the owning user's project role."),
    ("C-RBAC-LEAST-PRIV", "guide-rbac", "Use the principle of least privilege", 0, 1,
     "The provider's own guidance is to start from minimum permissions."),
    # ---------------- spend ----------------
    ("C-SPEND-HARD-LIMIT", "guide-spend-limits", "enforce a hard spend limit", -1, 0,
     "A hard spend limit stops traffic at a configured monthly amount; a spend "
     "alert only notifies."),
    ("C-SPEND-429", "guide-spend-limits", "organization_spend_limit_exceeded", -2, 2,
     "Exceeding a hard limit returns HTTP 429 with a spend-limit code, and "
     "enforcement is not instantaneous."),
    ("C-SPEND-LOCATION", "guide-spend-limits", "platform.openai.com/settings/organization/limits", -1, 3,
     "Organization spend limits are configured at Organization limits in "
     "platform settings."),
    # ---------------- workspace agents ----------------
    ("C-WA-TRIGGER-ROUTE", "wa-trigger-runs", "POST https://api.chatgpt.com/v1/workspace_agents/{id}/trigger", 0, 1,
     "A published ChatGPT workspace agent can be triggered from outside the UI "
     "on api.chatgpt.com."),
    ("C-WA-ACCEPTED", "wa-trigger-runs", "returns `202 Accepted` with a link", -1, 0,
     "The trigger route durably queues the event and returns 202 with a "
     "conversation URL."),
    ("C-WA-NO-RETURN", "wa-trigger-runs", "The agent's response cannot currently be retrieved through the API", 0, 0,
     "THE DECISIVE LIMIT: the agent's response cannot currently be retrieved "
     "through the API. Workspace Agents is a dispatch route with no return "
     "channel."),
    ("C-WA-RUN-STATUS", "wa-trigger-runs", "The agent run completed successfully", -4, 2,
     "Beta run polling returns status only - queued, in_progress, suspended, "
     "completed, failed - never content."),
    ("C-WA-TOKEN-LOCATION", "wa-authentication", "In ChatGPT, open Admin > Access tokens", -3, 3,
     "Workspace Agent access tokens are provisioned in ChatGPT under Admin, "
     "Access tokens, with the Workspace Agents scope, and a workspace admin "
     "must first enable the feature."),
    ("C-WA-TOKEN-SCOPE", "wa-authentication", "scoped to Workspace Agents API operations", -1, 1,
     "The Workspace Agent access token is scoped to Workspace Agents "
     "operations only and is a different credential from OPENAI_API_KEY."),
    # ---------------- compliance API ----------------
    ("C-COMPLIANCE-PURPOSE", "chatgpt-compliance-api", "Export supported records into an audit", -2, 3,
     "The Compliance API exists to export auditable ChatGPT records into an "
     "external system."),
    ("C-COMPLIANCE-UNDOCUMENTED", "chatgpt-compliance-api", "is the source of truth for current access requirements", -1, 2,
     "The public page deliberately does not publish routes or schemas; the "
     "authenticated Admin API reference is the source of truth. The contract "
     "cannot be read without admin access."),
    ("C-COMPLIANCE-PLAN-GATE", "chatgpt-compliance-api", "compliance-api-for-chatgpt-enterprise-edu", -2, 1,
     "The Compliance Platform guide is titled for Enterprise, Edu and ChatGPT "
     "for Teachers, indicating a plan gate."),
    # ---------------- ChatGPT product surface ----------------
    ("C-CHATGPT-MEMORY-NOT-CANONICAL", "chatgpt-memories", "not as the only source for rules that must", -2, 1,
     "The provider's own guidance is to keep binding rules in checked-in "
     "documentation and treat memory as a recall layer. Repository-canonical "
     "state agrees with the vendor, it does not fight it."),
    ("C-CHATGPT-SCHEDULED", "chatgpt-automations", "When scheduled tasks are enabled for your workspace", 0, 3,
     "Scheduled tasks run recurring work in the background and are managed in "
     "the Scheduled interface, when enabled for the workspace."),
    ("C-CHATGPT-PROJECT-CONTEXT", "chatgpt-projects", "Project instructions apply", -2, 1,
     "A ChatGPT project is a shared-context container: chats, files, sources "
     "and instructions that apply across its chats."),
    ("C-CHATGPT-PROJECT-PURPOSE", "chatgpt-projects", "Create a project when work will continue over time", 0, 2,
     "The product's own criterion for a project is continuing work with shared "
     "sources, not a unit of authority."),
]


def load(docs: pathlib.Path, sid: str) -> list[str]:
    p = docs / f"{sid}.md"
    if not p.exists():
        raise SystemExit(f"missing harvested source: {p}")
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def excerpt(lines: list[str], needle: str, before: int, after: int) -> tuple[str, int]:
    for i, line in enumerate(lines):
        if needle in line:
            lo = max(0, i + min(0, before))
            hi = min(len(lines), i + max(0, after) + 1)
            return "\n".join(lines[lo:hi]).strip(), i + 1
    raise SystemExit(
        f"locator no longer matches; the documentation moved: {needle!r}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="/tmp/openai-docs2")
    ap.add_argument("--log", default="/tmp/openai-fetch-log.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    docs = pathlib.Path(args.docs)
    harvest = json.loads(pathlib.Path(args.log).read_text(encoding="utf-8"))
    by_id = {r["source_id"]: r for r in harvest["records"]}

    sources = {}
    for sid, rec in sorted(by_id.items()):
        sources[sid] = {
            "url": rec["url"],
            "http_status": rec["http_status"],
            "fetched_at_utc": rec["fetched_at_utc"],
            "bytes": rec["bytes"],
            "sha256": rec["sha256"],
            "relied_on_for": rec["relied_on_for"],
        }

    claims = []
    used: set[str] = set()
    for cid, sid, needle, before, after, text in CLAIMS:
        if sid not in by_id:
            raise SystemExit(f"claim {cid} cites unharvested source {sid}")
        lines = load(docs, sid)
        snippet, lineno = excerpt(lines, needle, before, after)
        used.add(sid)
        claims.append({
            "claim_id": cid,
            "evidence_label": "DIRECTLY_REPRODUCED",
            "claim": text,
            "source_id": sid,
            "source_url": by_id[sid]["url"],
            "source_sha256": by_id[sid]["sha256"],
            "fetched_at_utc": by_id[sid]["fetched_at_utc"],
            "matched_at_line": lineno,
            "verbatim_excerpt": snippet,
        })

    out = {
        "artifact_id": "OE-L5-OPENAI-SURFACE-EVIDENCE-20260822-v001",
        "lane": "OE-L5-CHATGPT-SCALE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "how_to_reproduce": [
            "python3 scripts/harvest_openai_docs.py --out DOCS --log LOG",
            "python3 scripts/build_surface_evidence.py --docs DOCS --log LOG --out THIS_FILE",
        ],
        "evidence_label_meaning": {
            "DIRECTLY_REPRODUCED": "fetched or executed by this lane; url, sha256 and fetch time recorded",
            "DOCUMENTED": "official source cited but not the basis of an endpoint-shape claim",
            "HYPOTHESIS": "untested inference; never used for an API surface claim",
        },
        "credential_used": None,
        "harvest": {
            "harvested_at_utc": harvest["harvested_at_utc"],
            "source_count": harvest["source_count"],
            "http_200_count": harvest["http_200_count"],
        },
        "source_count": len(sources),
        "sources_cited_by_a_claim": sorted(used),
        "claim_count": len(claims),
        "sources": sources,
        "claims": claims,
    }
    pathlib.Path(args.out).write_text(
        json.dumps(out, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"{len(claims)} claims across {len(used)} cited sources "
          f"({len(sources)} harvested)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
