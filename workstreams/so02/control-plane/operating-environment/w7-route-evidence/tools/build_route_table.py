#!/usr/bin/env python3
"""Build the route evidence table, cutting every excerpt out of a fetched body.

Nothing in the output is recalled. Each evidence item names a source and a
literal locator; the builder finds that locator in the body fetched for this
lane and records the line it matched, the sha256 of the whole body, and the URL
and fetch time. If a locator stops matching, the build fails rather than
emitting a quotation that no longer exists at its source. That is deliberate:
the next wave learns the documentation moved on the day it moved.

Three evidence kinds:

  source  -- a literal locator cut out of a body this lane fetched.
  l5      -- a claim already evidenced by the OE-L5 lane, carried forward with
             its own sha256 and fetch time rather than re-cut. Reuse is
             recorded as reuse, not restated as new work.
  scan    -- a counted search over a whole body, used for negative evidence.
             "This 832 KB reference mentions ChatGpt eight times and every one
             is a connector identifier" is a claim about absence, and absence
             cannot be evidenced by quoting one line.

    python3 build_route_table.py --bodies DIR --gap-log LOG --w6-log LOG \
        --l5-evidence JSON --out TABLE.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

LABEL_MEANING = {
    "DIRECTLY_REPRODUCED": (
        "This lane ran the command or fetched the URL in this run. Command or "
        "URL, output and UTC time recorded."
    ),
    "DOCUMENTED": (
        "Official source, fetched and hashed, quoted verbatim from the body "
        "this lane holds. Model recall is never a source."
    ),
    "HYPOTHESIS": (
        "Inference this lane did not test, including compositions of separately "
        "documented parts. Never used to assert a capability."
    ),
}

DECISIVE_COLUMN = {
    "field": "returns_without_founder_touch",
    "question": (
        "Does a result travel from the ChatGPT account into a surface Cursor "
        "reads, with no act by Ahmed at the moment of return?"
    ),
    "values": {
        "YES": "A machine reads the result. No founder act at return time.",
        "NO": (
            "The result exists only where a person must open it. This is the "
            "founder-as-relay pattern the standing instruction forbids, and it "
            "does not stop being that pattern because a machine started the work."
        ),
        "CONDITIONAL": (
            "Returns without a founder act only once a stated precondition "
            "holds. The precondition is named in the row, and until it holds "
            "the row behaves as NO."
        ),
        "NOT_APPLICABLE": "The route carries no result in this direction.",
    },
    "note": (
        "One-time setup by the founder does not make a route NO. A route is NO "
        "when he must act on every result. Setup cost is carried in "
        "founder_action_required instead, so the two are never conflated."
    ),
}

# --------------------------------------------------------------------------
# Routes. Ordered so the platform/UI boundary comes first, because most of the
# false hope in this estate lives in mistaking one for the other.
# --------------------------------------------------------------------------

ROUTES: list[dict] = [
    {
        "route_id": "R01",
        "name": "OpenAI Responses API",
        "endpoint": "POST/GET https://api.openai.com/v1/responses",
        "direction": "cursor_to_openai_platform",
        "surface": "API Platform (api.openai.com). Not the ChatGPT account.",
        "reaches": [
            "Model execution against inputs Cursor supplies.",
            "Retrieval of a response Cursor itself created, by response id.",
            "Asynchronous execution via background:true, so work outlives a held connection.",
        ],
        "cannot_reach": [
            "Ahmed's ChatGPT projects, project chats or sidebar chats. Nothing in the "
            "reference addresses ChatGPT UI content.",
            "Any conversation the founder had in the ChatGPT UI.",
        ],
        "credential_required": ["OPENAI_API_KEY"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Issue a Platform API key with least-privilege scopes.",
            "Set a hard spend limit before the key is issued, so activation is "
            "reversible by arithmetic rather than by trust.",
        ],
        "provenance_quality": (
            "High for what it covers. Response ids are addressable and retrievable, "
            "and retention is published. But provenance is only ever of Cursor's own "
            "calls: this route can prove what Cursor asked and what the model "
            "answered, and can say nothing about what the founder discussed."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Cursor makes the call and reads the result. No founder act at return "
            "time. This is not, however, a return route from the ChatGPT account, "
            "because nothing from that account is in it."
        ),
        "maturity": "General availability. Stable, versioned, widely used.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "l5", "claim_id": "C-RESP-CONVERSATION"},
            {"kind": "l5", "claim_id": "C-RESP-STORE"},
            {"kind": "runtime", "note": "api.openai.com/v1/models answers 401 from this pod: gated, not missing."},
            {"kind": "scan", "source": "api-responses-create", "pattern": r"(?i)chatgpt",
             "interpretation": (
                 "Every occurrence of 'chatgpt' in the 474 KB Responses create "
                 "reference is either the image model id chatgpt-image-latest, a "
                 "service-connector identifier, or a utm_source=chatgpt.com query "
                 "string inside an example web-search citation. None is a route to "
                 "ChatGPT UI content."
             )},
        ],
    },
    {
        "route_id": "R02",
        "name": "OpenAI Conversations API",
        "endpoint": "POST/GET/DELETE https://api.openai.com/v1/conversations[/{id}/items]",
        "direction": "cursor_to_openai_platform",
        "surface": "API Platform (api.openai.com). Not the ChatGPT account.",
        "reaches": [
            "Durable, addressable containers for API-native turns, with conv_ prefixed ids.",
            "Item lists for conversations this route created.",
        ],
        "cannot_reach": [
            "Ahmed's ChatGPT projects, project chats or sidebar chats.",
            "A conv_… object is not a chat in the founder's sidebar, and no route "
            "here converts one into the other.",
        ],
        "credential_required": ["OPENAI_API_KEY"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Issue a Platform API key.",
            "Decide, as a founder decision rather than a lane decision, that "
            "material may sit under indefinite provider-side retention: "
            "/v1/conversations retains until deleted and is not Zero Data "
            "Retention eligible.",
        ],
        "provenance_quality": (
            "Addressable but thin. The conversation object carries only id, "
            "created_at, metadata and object, and metadata is capped at 16 pairs "
            "with 512-character values. It cannot hold a provenance chain, so the "
            "id is a locator into the repository and the repository stays canonical."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Cursor reads it directly. Again, nothing from the founder's account "
            "is in it, so this closes no loop that was open."
        ),
        "maturity": "General availability. The most retentive endpoint on the platform.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "l5", "claim_id": "C-CONV-SHAPE"},
            {"kind": "l5", "claim_id": "C-CONV-METADATA-LIMIT"},
            {"kind": "l5", "claim_id": "C-CONV-DELETE-ORPHANS"},
            {"kind": "l5", "claim_id": "C-RET-CONVERSATIONS"},
            {"kind": "source", "source": "api-conversations-overview",
             "locator": "Identifier for service connectors, like those available in ChatGPT",
             "note": (
                 "The only substantive mention of ChatGPT anywhere in the 832 KB "
                 "Conversations reference is this connector-identifier note. The "
                 "reference does not describe reading ChatGPT UI content because it "
                 "cannot."
             )},
            {"kind": "scan", "source": "api-conversations-overview", "pattern": r"(?i)chatgpt",
             "interpretation": (
                 "All occurrences resolve to the image model id chatgpt-image-latest "
                 "or the service-connector sentence quoted above. There is no "
                 "ChatGPT-UI read path in this reference."
             )},
        ],
    },
    {
        "route_id": "R03",
        "name": "API-side service connectors (connector_id)",
        "endpoint": "connector_id parameter on Responses/Conversations MCP tool calls",
        "direction": "openai_platform_to_third_party",
        "surface": "API Platform, calling OpenAI-hosted connectors",
        "reaches": [
            "Exactly eight named services: Dropbox, Gmail, Google Calendar, Google "
            "Drive, Microsoft Teams, Outlook Calendar, Outlook Email, SharePoint.",
        ],
        "cannot_reach": [
            "GitHub. There is no GitHub connector in the supported connector_id list, "
            "so this route does not reach this repository at all.",
            "The founder's ChatGPT chats. These connectors reach third-party "
            "services, not ChatGPT content.",
        ],
        "credential_required": ["OPENAI_API_KEY", "per-connector service authorization"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Authorize each connector against the target service, as himself or as "
            "an identity he designates.",
        ],
        "provenance_quality": (
            "Whatever the connected service returns, bounded by the authenticated "
            "identity's permissions there."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Cursor makes the call and reads the result. Irrelevant to this "
            "lane's question, though, because the enumerated list contains no "
            "GitHub and no ChatGPT content."
        ),
        "maturity": "General availability, with an explicitly enumerated and therefore checkable list.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "api-conversations-overview",
             "locator": "Currently supported `connector_id` values are:",
             "window": 12,
             "note": "The enumerated list. Its completeness is the finding: no GitHub."},
        ],
    },
    {
        "route_id": "R04",
        "name": "ChatGPT plugins, apps and connectors (UI-side)",
        "endpoint": "chatgpt.com/apps, chatgpt.com/admin/ca, chatgpt.com/admin/plugins",
        "direction": "chatgpt_ui_to_third_party",
        "surface": "The founder's ChatGPT account, inside a chat",
        "reaches": [
            "External systems a plugin's connectors are configured for: connectors "
            "can search, retrieve, sync or act on them.",
            "Write actions, where the connector supports Action control and an admin "
            "has enabled them.",
        ],
        "cannot_reach": [
            "Anything beyond the authenticated identity's own permissions in the "
            "connected service. Making a plugin available grants nothing by itself.",
            "This repository, unless a connector for it exists and is admitted. No "
            "GitHub connector is evidenced in the material this lane holds.",
            "The IDE extension surface.",
        ],
        "credential_required": [
            "The founder's ChatGPT session",
            "Per-service authorization held by the connector",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Admin admission across a six-layer capability chain: availability, "
            "included skills, app access, actions and permissions, service "
            "authorization, runtime permissions.",
            "Explicitly enable write actions, which the documentation gates behind "
            "naming an owner, reviewing scopes and documenting a recovery path.",
        ],
        "provenance_quality": (
            "Results land in the chat as tool output. Conversations that use apps "
            "remain available through the Compliance API, so there is an audit path "
            "in principle, on eligible plans."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "Precondition: the connector must write into a system Cursor already "
            "reads. A connector that only returns data into the chat leaves the "
            "result where a person must read it, which is NO. A connector holding "
            "write to a Cursor-visible system turns the same mechanism into YES. "
            "The direction of the write, not the existence of the connector, is "
            "what decides this row."
        ),
        "maturity": "General availability. Admin-gated, plan-sensitive, directory contents change.",
        "status": "ESTABLISHED_MECHANISM_UNESTABLISHED_FOR_THIS_REPOSITORY",
        "confidence": "high for the mechanism, none for a GitHub connector",
        "evidence": [
            {"kind": "source", "source": "chatgpt-apps-connectors",
             "locator": "Plugins in ChatGPT and Codex can include connectors that search, retrieve, sync,"},
            {"kind": "source", "source": "chatgpt-apps-connectors",
             "locator": "Whatever the initial set, start with read actions. Before enabling write",
             "window": 3,
             "note": "Write actions exist and are gated. This is the sentence that makes R04 conditional rather than impossible."},
            {"kind": "source", "source": "chatgpt-apps-connectors",
             "locator": "Making an app or plugin available in ChatGPT doesn't grant access to files,",
             "window": 2},
            {"kind": "source", "source": "chatgpt-apps-connectors",
             "locator": "normal chat-retention controls. ChatGPT conversations that use apps remain",
             "window": 2},
        ],
    },
    {
        "route_id": "R05",
        "name": "Remote MCP connector in ChatGPT (developer-mode app)",
        "endpoint": "chatgpt.com/plugins → developer-mode app → Streamable HTTP MCP server",
        "direction": "chatgpt_ui_to_our_system",
        "surface": "The founder's ChatGPT account calling out to a server we control",
        "reaches": [
            "Any tool our own MCP server exposes, called from inside a chat.",
            "Therefore, in principle, the repository: the server is our code.",
        ],
        "cannot_reach": [
            "Local Codex configuration. ChatGPT web does not read local config files "
            "or expose local MCP servers.",
        ],
        "credential_required": [
            "The founder's ChatGPT session",
            "ChatGPT developer-mode access (a separate workspace permission)",
            "Bearer or OAuth credentials on the MCP server, our side",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Obtain developer-mode access: for Enterprise/Edu a workspace admin "
            "grants it, then the user enables it in Settings → Security and login.",
            "Create the developer-mode app in ChatGPT Plugins.",
        ],
        "provenance_quality": (
            "Excellent, and this is the reason to care about this route. Our own "
            "server sees the exact tool arguments, so the material arrives as "
            "structured input we hash and record on receipt rather than as prose "
            "someone pasted."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "Precondition: a publicly reachable HTTPS MCP endpoint, or the tunnel "
            "in R06. Once reachable, ChatGPT calls our server and our server writes "
            "the repository, with no founder act at return time. The remaining "
            "founder-shaped dependency is the trigger, not the return: some "
            "ChatGPT-side turn must invoke the app, which R09 can schedule."
        ),
        "maturity": "Beta. Developer mode is explicitly a beta workspace permission.",
        "status": "ESTABLISHED_MECHANISM_NOT_ACTIVATED",
        "confidence": "high for the mechanism",
        "evidence": [
            {"kind": "source", "source": "chatgpt-extend-mcp",
             "locator": "ChatGPT web can use remote MCP-backed tools supplied by plugins."},
            {"kind": "source", "source": "chatgpt-extend-mcp",
             "locator": "ChatGPT web doesn't read local Codex configuration files"},
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "Go to [ChatGPT Plugins](https://chatgpt.com/plugins), select the plus button to create a developer-mode app"},
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "ChatGPT developer mode is a separate workspace permission."},
        ],
    },
    {
        "route_id": "R06",
        "name": "Secure MCP Tunnel",
        "endpoint": "tunnel-client → OpenAI-hosted MCP tunnel endpoint (outbound HTTPS only)",
        "direction": "chatgpt_ui_to_our_private_network",
        "surface": "A private MCP server inside our own boundary, reachable by ChatGPT",
        "reaches": [
            "A private MCP server with no public listener and no inbound firewall port.",
            "Named callers: ChatGPT, Codex, the Responses API, or another supported "
            "OpenAI surface.",
            "Narrowly scoped private HTTP endpoints, via the embedded Harpoon server, "
            "limited to targets and methods we configure.",
        ],
        "cannot_reach": [
            "Public plugin submission or distribution. That still needs a stable, "
            "publicly reachable HTTPS endpoint.",
            "Anything if tunnel-client is not running. It long-polls; it is not a "
            "listener that survives its host.",
        ],
        "credential_required": [
            "OPENAI_API_KEY (a runtime key for tunnel-client)",
            "A tunnel_id from Platform tunnel settings",
            "Tunnels RBAC: Read + Manage to create, Read + Use to run",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Create the tunnel in Platform tunnel settings and grant the Tunnels role.",
            "Associate the tunnel with the target ChatGPT workspace, not only with "
            "the Platform organization, or it will not appear in ChatGPT.",
            "Provide a durable host for tunnel-client. An ephemeral cloud-agent pod "
            "is not one.",
        ],
        "provenance_quality": (
            "Strong on the app path, with a stated gap. App-level compliance logging "
            "still applies, including app invocation and APP_AUTH_LOG events, and "
            "tunnel metadata changes appear in Platform audit logs as tunnel.created, "
            "tunnel.updated and tunnel.deleted. But tunnel transport traffic itself is "
            "explicitly not emitted as Compliance Platform app events, so the "
            "transport leg is not independently auditable from the ChatGPT side."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "This is the finding that most changes the picture, because it removes "
            "the blocker the prior lane identified. OE-L5 concluded that push-based "
            "return needed a durable public HTTPS endpoint this runtime lacks. A "
            "tunnel is outbound-only, so no public endpoint is needed at all. "
            "Precondition becomes a durable host plus the credentials above, which "
            "is a materially easier thing to obtain than public ingress."
        ),
        "maturity": (
            "Documented, versioned client, enterprise networking features. Paired "
            "with ChatGPT developer mode, which is beta."
        ),
        "status": "ESTABLISHED_MECHANISM_NOT_ACTIVATED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "Secure MCP Tunnel lets you connect private MCP servers to supported OpenAI products without opening inbound firewall ports"},
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "An MCP tunnel is an outbound-only connection from a host inside your network"},
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "It does not support public plugin submission or distribution."},
            {"kind": "source", "source": "api-secure-mcp-tunnels",
             "locator": "Tunnel control-plane auth, long-poll / response traffic, and individual tunnel transport requests are not emitted"},
            {"kind": "source", "source": "api-tools-connectors-mcp",
             "locator": "If your MCP server is private, on-premises, or behind a firewall, use"},
        ],
    },
    {
        "route_id": "R07",
        "name": "ChatGPT Workspace Agents — trigger",
        "endpoint": "POST https://api.chatgpt.com/v1/workspace_agents/{id}/trigger",
        "direction": "cursor_to_chatgpt_account",
        "surface": "The founder's ChatGPT workspace, entered from outside the UI",
        "reaches": [
            "A published workspace agent inside the account, started from outside.",
            "Durable queueing: the trigger returns 202 Accepted with a conversation link.",
            "Continuation of one agent conversation across triggers, via conversation_key.",
        ],
        "cannot_reach": [
            "The agent's own answer. This is the decisive limit and it is stated "
            "flatly in the documentation.",
            "Existing projects or chats. This starts new work; it reads nothing.",
        ],
        "credential_required": ["A Workspace Agent access token, scoped to Workspace Agents operations only"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "A workspace admin enables Workspace agents and turns on personal access "
            "tokens under Admin → Permissions & roles.",
            "Create the token under Admin → Access tokens with the Workspace Agents scope.",
        ],
        "provenance_quality": (
            "Good for dispatch, nil for content. You can prove you triggered it and "
            "that it finished. You cannot obtain what it said."
        ),
        "returns_without_founder_touch": "NO",
        "returns_without_founder_touch_reason": (
            "The result comes back as a conversation URL. A workflow that ends in "
            "'the founder opens the link and reads it' is founder-as-relay wearing "
            "the costume of automation, and it is prohibited however much machinery "
            "sits upstream of the link."
        ),
        "maturity": "Available, with the return path documented as absent rather than merely unspecified.",
        "status": "ESTABLISHED_DISPATCH_ONLY",
        "confidence": "high",
        "evidence": [
            {"kind": "l5", "claim_id": "C-WA-TRIGGER-ROUTE"},
            {"kind": "l5", "claim_id": "C-WA-ACCEPTED"},
            {"kind": "l5", "claim_id": "C-WA-NO-RETURN"},
            {"kind": "l5", "claim_id": "C-WA-TOKEN-LOCATION"},
            {"kind": "l5", "claim_id": "C-WA-TOKEN-SCOPE"},
            {"kind": "source", "source": "chatgpt-access-tokens",
             "locator": "they do not authenticate workspace agent trigger calls",
             "note": "Independent confirmation that this is a third, separate credential."},
            {"kind": "runtime", "note": "api.chatgpt.com/v1/workspace_agents/x/runs/y answers 401 from this pod: the route exists and is gated."},
        ],
    },
    {
        "route_id": "R08",
        "name": "ChatGPT Workspace Agents — beta run polling",
        "endpoint": "GET https://api.chatgpt.com/v1/workspace_agents/{id}/runs/{run_id} (OpenAI-Beta: workspace_agent_runs=v1)",
        "direction": "chatgpt_account_to_cursor",
        "surface": "The same workspace agent, polled for progress",
        "reaches": [
            "Run status, one of queued, in_progress, suspended, completed, failed.",
            "A failure category in error.code.",
        ],
        "cannot_reach": [
            "Any content the agent produced. Status only, never the response.",
        ],
        "credential_required": ["A Workspace Agent access token"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["As R07."],
        "provenance_quality": (
            "A verifiable completion signal and nothing else. Enough to prove work "
            "finished, never enough to know what it concluded."
        ),
        "returns_without_founder_touch": "NO",
        "returns_without_founder_touch_reason": (
            "This lane was asked to verify this against live documentation because it "
            "is decisive, and it verifies. Polling returns a status enum. Cursor can "
            "learn that the agent finished and still cannot learn one word of what it "
            "said, so the content still requires a person to fetch it. A status-only "
            "channel automates the noticing and leaves the relaying to Ahmed, which "
            "is the half that matters."
        ),
        "maturity": "Beta, behind an explicit beta header.",
        "status": "ESTABLISHED_STATUS_ONLY",
        "confidence": "high",
        "evidence": [
            {"kind": "l5", "claim_id": "C-WA-RUN-STATUS"},
            {"kind": "l5", "claim_id": "C-WA-NO-RETURN"},
        ],
    },
    {
        "route_id": "R09",
        "name": "ChatGPT scheduled tasks (Tasks / automations) — web",
        "endpoint": "ChatGPT Scheduled view; RFC 5545 RRULE schedules",
        "direction": "internal_to_chatgpt_account",
        "surface": "The founder's ChatGPT account, running on a schedule",
        "reaches": [
            "Unattended runs on a schedule, using the uploaded files, connected "
            "tools, skills and plugins available to that chat.",
            "Polling of connected sources such as Slack or GitHub, where a connector exists.",
            "approval_policy = \"never\", where organization policy allows it.",
        ],
        "cannot_reach": [
            "A local folder or worktree. Web scheduled tasks keep none between runs.",
            "Any machine-readable outbox. Findings land in the Scheduled view, which "
            "the documentation calls an inbox.",
        ],
        "credential_required": ["The founder's ChatGPT session; his account's own entitlements"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Create the scheduled task once, and set the sandbox mode it runs under.",
        ],
        "provenance_quality": (
            "Each run is a chat with a timestamp, which is real provenance but only "
            "inside the account."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "By default NO: findings arrive in an inbox and the notification channels "
            "are push, email and SMS, all of which terminate at a person. It becomes "
            "YES only when the scheduled run's own action writes outward — through a "
            "connector (R04) or an MCP app on a tunnel (R05/R06). This is the most "
            "useful row in the table, because scheduling is the piece that removes "
            "the founder from the trigger, and it is worthless for return until it is "
            "pointed at an outward-writing tool."
        ),
        "maturity": "General availability. Model pinning inside a task expires: gpt-5.4 and gpt-5.4-mini retire 2026-08-31.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "Scheduled tasks run unattended with your default sandbox settings."},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "The **Scheduled** view acts as your inbox."},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "polling Slack, GitHub, or another connected source when the results should"},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "Scheduled tasks use `approval_policy = \"never\"` when your organization policy"},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "They don't keep a local folder or"},
            {"kind": "source", "source": "chatgpt-notifications",
             "locator": "channels can include push, email, or SMS",
             "note": "Every delivery channel terminates at a person."},
        ],
    },
    {
        "route_id": "R10",
        "name": "ChatGPT scheduled tasks — desktop app, project-scoped, with repository write",
        "endpoint": "ChatGPT desktop app, project bound to a Git working copy or worktree",
        "direction": "chatgpt_account_to_local_repository",
        "surface": "The founder's own machine, driven by his ChatGPT account",
        "reaches": [
            "Files in the selected project on disk, in the local checkout or a dedicated worktree.",
            "Commands and network, subject to sandbox mode; under full access, changes "
            "without asking.",
        ],
        "cannot_reach": [
            "Anything at all unless the machine is powered on and the desktop app is "
            "running, with the project still present on disk.",
            "Files outside the workspace, under workspace-write mode.",
        ],
        "credential_required": ["The founder's ChatGPT session on his own machine"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Keep the machine powered on and the desktop app running for the schedule to fire.",
            "Choose the sandbox mode, and accept that full access lets background "
            "tasks change files and run commands without asking.",
        ],
        "provenance_quality": (
            "Good if it reaches a commit: Git records author, time and diff. The risk "
            "is the opposite of missing provenance — local mode can modify files the "
            "founder is actively editing, so changes can arrive entangled with "
            "unfinished work."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "Precondition: his machine is on, the app is running, and the task pushes "
            "rather than only editing locally. Then commits reach the remote and "
            "Cursor reads them with no founder act. But the precondition makes the "
            "route depend on the founder's hardware being awake, which is a weaker "
            "guarantee than a server-side route and should not be presented as "
            "equivalent to one."
        ),
        "maturity": "General availability. Depends on desktop-app behaviour and local state.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "For project-scoped scheduled tasks, keep the machine powered on and the ChatGPT",
             "window": 3},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "In Git repositories, you can choose whether a scheduled task runs in your local",
             "window": 5},
            {"kind": "source", "source": "chatgpt-automations",
             "locator": "background scheduled tasks carry",
             "window": 3},
        ],
    },
    {
        "route_id": "R11",
        "name": "ChatGPT Compliance API",
        "endpoint": "Contract published only at chatgpt.com/admin/api-reference (authenticated)",
        "direction": "chatgpt_account_to_external_system",
        "surface": "The founder's ChatGPT workspace, read as auditable records",
        "reaches": [
            "Covered ChatGPT conversation records, on eligible workspaces, including "
            "supported cloud Work activity.",
            "Work user prompts and agent responses, for eligible Enterprise and Edu workspaces.",
            "Active Library files, through Library-specific endpoints.",
            "Connected app calls, logged separately.",
        ],
        "cannot_reach": [
            "A complete audit trail. The documentation states plainly that these "
            "records do not establish one for every hosted file operation, shell "
            "command, browser interaction, tool invocation or approval.",
            "Anything on an ineligible plan. Coverage depends on product, surface, "
            "permissions, available endpoint and documented event schema.",
            "History older than the retention window: the Compliance Logs Platform "
            "retains data for 30 days.",
        ],
        "credential_required": ["ChatGPT workspace admin access; credential type not publicly specified"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Confirm which plan the workspace is on. Every claim in this row branches "
            "on that single fact, and this lane does not have it.",
            "Read the authenticated Admin API reference, which is the only published "
            "source of routes and schemas.",
        ],
        "provenance_quality": (
            "The best available in principle: auditable records of prompts and "
            "responses, designed for legal hold and investigation. Its weakness is "
            "purpose rather than fidelity — it is built to export to a SIEM, not to "
            "hand a working answer to a coordinating agent."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "If eligible and credentialed, a machine reads it continuously and no "
            "founder act is needed per result — the documentation's own advice is to "
            "export records continuously to a downstream system. Until plan "
            "eligibility is confirmed and the authenticated contract is read, this "
            "row cannot be built against, so it behaves as NO today."
        ),
        "maturity": (
            "Available on eligible plans. Public documentation deliberately omits "
            "routes, schemas, filters and retention behaviour."
        ),
        "status": "PARTIALLY_ESTABLISHED",
        "confidence": (
            "high on coverage and limits, none on contract. This lane can say what "
            "it covers and cannot say how to call it."
        ),
        "evidence": [
            {"kind": "l5", "claim_id": "C-COMPLIANCE-PURPOSE"},
            {"kind": "l5", "claim_id": "C-COMPLIANCE-UNDOCUMENTED"},
            {"kind": "l5", "claim_id": "C-COMPLIANCE-PLAN-GATE"},
            {"kind": "source", "source": "chatgpt-work-admin-faq",
             "locator": "the Compliance API provides covered ChatGPT conversation records",
             "window": 3,
             "note": (
                 "New relative to OE-L5, and reached on a host that answers rather "
                 "than one that 403s. It upgrades the row from 'plan-gated and "
                 "unspecified' to 'plan-gated, unspecified, and documented to cover "
                 "conversation records'."
             )},
            {"kind": "source", "source": "chatgpt-work-admin-faq",
             "locator": "provides Work user prompts and agent responses"},
            {"kind": "source", "source": "chatgpt-work-admin-faq",
             "locator": "These records don't establish a complete audit trail for every hosted file",
             "window": 2},
            {"kind": "source", "source": "chatgpt-work-admin-faq",
             "locator": "The Compliance Logs Platform retains data for 30 days."},
        ],
    },
    {
        "route_id": "R12",
        "name": "Codex Analytics API",
        "endpoint": "Contract published only at chatgpt.com/codex/cloud/settings/apireference (authenticated)",
        "direction": "chatgpt_account_to_external_system",
        "surface": "Aggregated workspace metrics",
        "reaches": ["Aggregated Codex usage and activity metrics, scoped to a ChatGPT workspace."],
        "cannot_reach": [
            "Raw records. The documentation says outright that it is not a raw "
            "audit-log interface and points to the Compliance API instead.",
            "Any conversation content.",
        ],
        "credential_required": [
            "A Platform organization API key whose organization matches the workspace's",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["Issue the org-scoped key; confirm the org/workspace pairing."],
        "provenance_quality": "Aggregates only. Useful for detecting that something happened, never for what.",
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "A machine reads it. Worth recording precisely so it is not mistaken for "
            "a content route during a hunt for one: it returns counts, and counts are "
            "not context."
        ),
        "maturity": "Available. Contract behind authentication.",
        "status": "ESTABLISHED_METRICS_ONLY",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-analytics-api",
             "locator": "It's not a raw audit-log interface."},
            {"kind": "source", "source": "chatgpt-analytics-api",
             "locator": "authenticate with a Platform organization API key. The key's organization must",
             "window": 2},
        ],
    },
    {
        "route_id": "R13",
        "name": "Owner's own ChatGPT data export",
        "endpoint": "ChatGPT Settings → Data controls → Export (route not confirmable from here)",
        "direction": "chatgpt_account_to_founder",
        "surface": "The founder's account, exporting itself",
        "reaches": ["UNESTABLISHED. This lane could not read the documentation that would say."],
        "cannot_reach": ["UNESTABLISHED."],
        "credential_required": ["The founder's own account credentials (owner-identity act)"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "UNESTABLISHED. Even the shape of the action cannot be stated from "
            "documentation this lane was able to read.",
        ],
        "provenance_quality": "UNESTABLISHED.",
        "returns_without_founder_touch": "NO",
        "returns_without_founder_touch_reason": (
            "An export is initiated by the account owner and delivered to him. Even "
            "on the most favourable reading it is a one-shot owner act, not a route, "
            "and a lane may not assume the favourable reading of something it could "
            "not read at all."
        ),
        "maturity": "UNESTABLISHED.",
        "status": "UNESTABLISHED",
        "confidence": (
            "none on viability; high on the fact of the block, which was reproduced "
            "twice by two lanes"
        ),
        "evidence": [
            {"kind": "fetch_failure", "sources": ["openai-export-data", "openai-data-controls-faq", "openai-privacy-portal"],
             "note": (
                 "All three answered 403 for OE-W6 at 00:03Z and 403 again for this "
                 "lane, once with curl's default user agent, which rules out an "
                 "agent-string-specific block. The bodies are bot-challenge pages: "
                 "privacy.openai.com returns a Cloudflare 'Just a moment...' "
                 "interstitial and help.openai.com returns a refresh-and-retry page. "
                 "Their bytes differ between fetches because the challenge carries a "
                 "per-request nonce, which is why they are the only three sources "
                 "this lane reports as CHANGED. No attempt was made to defeat the "
                 "challenge."
             )},
            {"kind": "index_absence", "source": "index-chatgpt", "pattern": r"(?i)export",
             "interpretation": (
                 "The published learn.chatgpt.com index was searched for an account "
                 "data-export page on a host that does answer. It has none: the only "
                 "export entries are a single-file Markdown export of the docs "
                 "themselves and a security-findings export. So the export route is "
                 "unestablished rather than merely undocumented — this lane looked "
                 "for a reachable description of it and there is not one."
             )},
        ],
    },
    {
        "route_id": "R14",
        "name": "Codex cloud with a connected GitHub repository",
        "endpoint": "chatgpt.com/codex, chatgpt.com/codex/settings/environments",
        "direction": "chatgpt_account_to_github",
        "surface": "The founder's ChatGPT account, signed in to Codex, holding repository access",
        "reaches": [
            "Repositories he selects when connecting GitHub or GitLab.",
            "Isolated cloud environments with configured dependencies, variables and secrets.",
            "Branch work and pull requests: agents work on a branch and a PR can be opened when ready.",
            "Work started from GitHub, GitLab, Linear or Slack, not only from the web UI.",
        ],
        "cannot_reach": [
            "Repositories not selected during the GitHub connection step.",
            "The founder's own chats and projects. This surface reaches code, not "
            "conversation history.",
        ],
        "credential_required": [
            "The founder's ChatGPT sign-in to Codex",
            "A GitHub connection scoped to chosen repositories",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Sign in to Codex and connect GitHub, choosing which repositories Codex "
            "may access. This is a new external OAuth grant and therefore an owner act.",
            "Create an environment for the repository.",
        ],
        "provenance_quality": (
            "The strongest of any route here. Output arrives as commits, branches and "
            "pull requests, which are content-addressed, attributable and reviewable "
            "by the same machinery this repository already uses."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Once connected, work lands in GitHub, and Cursor reads GitHub directly. "
            "No founder act at return time. This is the answer to the question the "
            "brief poses: the account-resident surface that closes the loop is Codex, "
            "not any conversation API, because Codex writes where Cursor already reads."
        ),
        "maturity": "General availability for GitHub. GitLab is marked Beta.",
        "status": "ESTABLISHED_MECHANISM_NOT_ACTIVATED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "codex-cloud",
             "locator": "Connect GitHub or GitLab (Beta) when prompted. For GitHub, choose the repositories Codex can access"},
            {"kind": "source", "source": "codex-cloud",
             "locator": "Run tasks in isolated cloud environments, work in parallel, and start work from the web, GitHub, GitLab, Linear, or Slack."},
            {"kind": "source", "source": "codex-cloud",
             "locator": "Review the summary and diff. Ask Codex to make follow-up changes, or open a pull request when the work is ready."},
        ],
    },
    {
        "route_id": "R15",
        "name": "Codex code review on a pull request",
        "endpoint": "@codex review / @codex on a GitHub PR; automatic reviews",
        "direction": "chatgpt_account_to_github",
        "surface": "The account's Codex integration acting inside GitHub",
        "reaches": [
            "Pull request reviews posted as a GitHub review, like a teammate would.",
            "Pushes back to the branch, when it has permission to do so.",
            "Every new pull request automatically, with Automatic reviews on and no "
            "comment needed to trigger it.",
            "Repository guidance in AGENTS.md, including Code Review Rules.",
        ],
        "cannot_reach": [
            "Anything outside a repository with Codex cloud set up.",
            "A substitute for tests, branch protections or required approvals — the "
            "documentation says review rules do not replace them.",
        ],
        "credential_required": [
            "The GitHub connection from R14",
            "GitHub push or admin permission to configure it",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Turn on Code review for the repository in Codex settings, and Automatic "
            "reviews if the trigger should not need a comment.",
        ],
        "provenance_quality": (
            "Excellent. Review comments and pushed commits are attributable, "
            "timestamped GitHub objects."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "With Automatic reviews on, a pull request event triggers it and the "
            "output is a GitHub review. Nobody opens a link for the content to exist "
            "somewhere a machine reads. This lane did not exercise it: its boundaries "
            "forbid modifying any pull request, so the row is DOCUMENTED and "
            "deliberately not DIRECTLY_REPRODUCED."
        ),
        "maturity": "General availability. Security Review is research preview.",
        "status": "ESTABLISHED_MECHANISM_NOT_ACTIVATED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "codex-third-party-github",
             "locator": "Codex posts a review on the pull request, just like a teammate would."},
            {"kind": "source", "source": "codex-third-party-github",
             "locator": "Codex will post a review whenever someone opens a new PR for review, without"},
            {"kind": "source", "source": "codex-third-party-github",
             "locator": "Codex starts a cloud chat with the pull request as context and can push a fix"},
            {"kind": "source", "source": "codex-third-party-github",
             "locator": "To configure automatic reviews, you need a connected GitHub repository and"},
        ],
    },
    {
        "route_id": "R16",
        "name": "Codex GitHub Action (openai/codex-action@v1)",
        "endpoint": "GitHub Actions workflow running codex exec",
        "direction": "repository_to_openai_platform_and_back",
        "surface": "This repository's own CI, calling the API Platform",
        "reaches": [
            "The repository contents, once the workflow checks them out.",
            "Model execution through the Responses API proxy the action starts when "
            "given an API key.",
            "The pull request, via a following job that posts the captured output.",
        ],
        "cannot_reach": [
            "The founder's ChatGPT account content. This route authenticates with a "
            "Platform API key, so it never enters the ChatGPT workspace at all.",
        ],
        "credential_required": ["OPENAI_API_KEY, stored as a GitHub secret"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Store the OpenAI key as a repository secret. This is a secrets act and "
            "therefore his, not a lane's.",
        ],
        "provenance_quality": (
            "Very good. A workflow run is logged, attributable and re-runnable, and "
            "its output is a commit or a PR comment."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "CI runs on a repository event and writes back to the repository. Worth "
            "distinguishing carefully from R14 and R15: this one is model capacity "
            "hosted in our CI, not the founder's account reaching outward. It is "
            "excellent for capacity and contributes nothing to recovering his context."
        ),
        "maturity": "Versioned action at v1, with a published source repository.",
        "status": "ESTABLISHED_MECHANISM_NOT_ACTIVATED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "codex-github-action",
             "locator": "The action installs the Codex CLI, starts the Responses API proxy when you provide an API key"},
            {"kind": "source", "source": "codex-github-action",
             "locator": "Store your OpenAI key as a GitHub secret"},
            {"kind": "source", "source": "codex-github-action",
             "locator": "The sample workflow below reviews new pull requests, captures Codex's response, and posts it back on the PR."},
        ],
    },
    {
        "route_id": "R17",
        "name": "Codex access token running non-interactive automation",
        "endpoint": "codex exec / app-server client, authenticated by a Codex access token",
        "direction": "our_automation_as_chatgpt_workspace_identity",
        "surface": "Our own runner, acting as a ChatGPT workspace user",
        "reaches": [
            "Codex CLI and app-server runs without a browser sign-in, tied to the "
            "workspace identity that created the token.",
            "That user's access and workspace-managed entitlements, with runs "
            "appearing in workspace governance data.",
        ],
        "cannot_reach": [
            "Workspace agent trigger calls. The documentation states plainly that "
            "Codex access tokens do not authenticate those.",
            "General OpenAI API calls, which want a Platform API key instead.",
            "Confirmed availability on this account: tokens are supported for "
            "ChatGPT Business and Enterprise workspaces only.",
        ],
        "credential_required": ["A Codex access token — a third credential type, distinct from the other two"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "A workspace admin turns on Allow users to create access tokens, and "
            "Allow members to use Codex Local if a local surface is needed.",
            "Create the token under Admin → Access tokens and place it in a secret manager.",
        ],
        "provenance_quality": (
            "Notably good, and this is its real value: runs are attributable to a "
            "named workspace identity and appear in governance data, so automated "
            "work is auditable as that identity rather than as an anonymous key."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Our runner invokes it and reads the output directly, non-interactively. "
            "The important caveat is scope, not return: it grants the workspace "
            "identity's access to Codex, which is code work, and does not thereby "
            "open his chats and projects."
        ),
        "maturity": "Available on Business and Enterprise. Expiry limits are admin-configurable.",
        "status": "ESTABLISHED_MECHANISM_PLAN_GATED",
        "confidence": "high on the mechanism; plan eligibility for this account is unknown",
        "evidence": [
            {"kind": "source", "source": "chatgpt-access-tokens",
             "locator": "They authenticate trusted non-interactive local workflows, including Codex CLI and app-server-based automation, with a ChatGPT workspace identity."},
            {"kind": "source", "source": "chatgpt-access-tokens",
             "locator": "Codex access tokens are currently supported for ChatGPT Business and"},
            {"kind": "source", "source": "chatgpt-access-tokens",
             "locator": "The token represents the ChatGPT workspace user who created it, so runs can use that user's access and appear in workspace governance data."},
        ],
    },
    {
        "route_id": "R18",
        "name": "ChatGPT service account (non-human workspace identity)",
        "endpoint": "chatgpt.com/admin/service-accounts",
        "direction": "our_automation_as_non_human_identity",
        "surface": "A workspace identity that is not a person",
        "reaches": [
            "Headless Codex workflows at scale, without depending on an employee's account.",
            "Its own plugins and connected apps, configured for the account itself.",
            "Its own access tokens, representing the service account rather than its creator.",
        ],
        "cannot_reach": [
            "The creator's plugins or connected apps. A service account inherits none of them.",
            "Any workspace not on a pay-as-you-go plan: service accounts are "
            "available only on those.",
        ],
        "credential_required": ["A service-account access token"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Only workspace owners and admins can create service accounts. He creates "
            "it, or delegates management explicitly.",
        ],
        "provenance_quality": (
            "The cleanest attribution available: each runner or scheduled job gets "
            "its own identity with the same roles and auditability as a person, which "
            "is what makes independent acceptance meaningful rather than nominal."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "The identity is designed for exactly this: automation that does not "
            "route through a person. It answers the durability objection to R17, "
            "because it does not break when one employee's account changes."
        ),
        "maturity": "Available on pay-as-you-go plans only.",
        "status": "ESTABLISHED_MECHANISM_PLAN_GATED",
        "confidence": "high on the mechanism; plan eligibility unknown",
        "evidence": [
            {"kind": "source", "source": "chatgpt-service-accounts",
             "locator": "Service accounts let you run and scale headless Codex workflows across your organization without relying on an employee's account."},
            {"kind": "source", "source": "chatgpt-service-accounts",
             "locator": "Service accounts are available only on pay-as-you-go plans."},
            {"kind": "source", "source": "chatgpt-service-accounts",
             "locator": "It doesn't inherit the creator's plugins or connected apps."},
        ],
    },
    {
        "route_id": "R19",
        "name": "ChatGPT import from Cursor",
        "endpoint": "ChatGPT desktop app Settings → Import; Codex CLI /import",
        "direction": "cursor_to_chatgpt_account",
        "surface": "The founder's machine, reading local Cursor state into his account",
        "reaches": [
            "Cursor instruction files into AGENTS.md, settings.json into config.toml, "
            "skills, plugins, MCP server configuration, hooks, slash commands and subagents.",
            "Existing project folders, becoming ChatGPT projects over the same folders.",
            "Chats from the last 30 days, becoming ChatGPT chats. Codex CLI imports up to 50.",
            "Continuous synchronisation, when automatic updates are turned on.",
        ],
        "cannot_reach": [
            "Anything not on the founder's local disk. User-level setup comes from "
            "files on his machine and project-level setup from the folders he selects.",
            "A running task, a remote session, or a session connected to a local "
            "app-server daemon — /import is unavailable in all three.",
        ],
        "credential_required": ["The founder's ChatGPT session on his own machine"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Run the import once, and optionally turn on automatic updates.",
        ],
        "provenance_quality": (
            "Good in the direction it runs: the source is files under version control. "
            "The direction is the point, though — this carries Cursor's context into "
            "ChatGPT, and returns nothing."
        ),
        "returns_without_founder_touch": "NOT_APPLICABLE",
        "returns_without_founder_touch_reason": (
            "It carries no result toward Cursor; it is the reverse direction. Recorded "
            "because the brief asked for routes the list omits and because it is "
            "genuinely useful: it is the documented way to give the account the "
            "repository's own instructions, which makes account-side work more likely "
            "to be accepted when it does return by another route."
        ),
        "maturity": "Available in the desktop app and Codex CLI. Cursor is a named supported source.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-import",
             "locator": "The desktop app can import from **Claude Code**, **Claude Cowork**,",
             "window": 2},
            {"kind": "source", "source": "chatgpt-import",
             "locator": "Codex CLI imports up to 50 chats from the last 30 days."},
            {"kind": "source", "source": "chatgpt-import",
             "locator": "User-level setup comes from files on your machine."},
            {"kind": "source", "source": "chatgpt-import",
             "locator": "turn on automatic\nupdates to keep imported work in sync with the original agent"},
        ],
    },
    {
        "route_id": "R20",
        "name": "ChatGPT Chrome extension driving the founder's browser",
        "endpoint": "ChatGPT Chrome extension",
        "direction": "chatgpt_account_to_authenticated_web_sessions",
        "surface": "The founder's own Chrome profile, on his own machine",
        "reaches": [
            "Sites where he is already signed in, read or acted on, using his real "
            "Chrome profile.",
            "Context from his open tabs, when a task needs it.",
        ],
        "cannot_reach": [
            "Anything without his browser running and the extension installed.",
            "This runtime. It is an extension in his Chrome, not a service.",
        ],
        "credential_required": ["Whatever sessions his Chrome profile already holds"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["Install the extension and keep Chrome open for a task to run."],
        "provenance_quality": (
            "Weak for our purposes. Output is chat content, and the acting identity is "
            "the founder's own live sessions, which makes attribution of an action to "
            "an agent rather than to him inherently muddy."
        ),
        "returns_without_founder_touch": "NO",
        "returns_without_founder_touch_reason": (
            "Results land in a chat on his machine. Recorded because it is the one "
            "route that genuinely reaches authenticated sessions nothing else can, "
            "and precisely for that reason it is the most founder-coupled route in "
            "the table."
        ),
        "maturity": "Available.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-chrome-extension",
             "locator": "Use the Chrome extension to let ChatGPT control your Chrome browser. ChatGPT can",
             "window": 3},
            {"kind": "source", "source": "chatgpt-chrome-extension",
             "locator": "ChatGPT can use context from your open tabs when a task needs it."},
        ],
    },
    {
        "route_id": "R21",
        "name": "ChatGPT built-in browser and Computer Use (desktop app)",
        "endpoint": "@Browser in ChatGPT web and desktop; Computer Use plugin",
        "direction": "chatgpt_account_to_web_and_desktop_gui",
        "surface": "OpenAI-side browser, or the founder's macOS/Windows desktop",
        "reaches": [
            "Websites, opened and acted on from inside a chat, in a separate browser profile.",
            "With Computer Use: graphical interfaces on macOS or Windows, seen and operated.",
        ],
        "cannot_reach": [
            "His existing sessions. The built-in browser uses a separate profile and "
            "does not share his tabs or session.",
            "This Linux runtime. Computer Use is documented for macOS and Windows in "
            "the desktop app, and requires Screen Recording and Accessibility grants.",
            "Codex CLI or the IDE extension, where Browser is unavailable.",
        ],
        "credential_required": ["Interactive sign-in inside the built-in browser, where a task needs an account"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Install the Computer Use plugin and grant OS permissions, on a supported OS.",
        ],
        "provenance_quality": "Chat-resident: screenshots and narration. Not a structured record.",
        "returns_without_founder_touch": "NO",
        "returns_without_founder_touch_reason": (
            "Output is chat content, and the desktop variant needs his machine and his "
            "OS grants. Included to close off a tempting misreading: the existence of "
            "ChatGPT-side computer control does not give Cursor a way to reach his account."
        ),
        "maturity": "Available in supported regions, on ChatGPT Work and Codex, macOS and Windows.",
        "status": "ESTABLISHED_AND_PLATFORM_INCOMPATIBLE_WITH_THIS_RUNTIME",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "chatgpt-computer-use",
             "locator": "Computer Use in the ChatGPT desktop app is available on\n  macOS and Windows with ChatGPT Work and Codex"},
            {"kind": "source", "source": "chatgpt-browser",
             "locator": "The built-in browser uses a browser profile that is separate from your regular\nbrowser. It doesn't automatically share your existing tabs or browser session."},
            {"kind": "source", "source": "chatgpt-browser",
             "locator": "Browser isn't available in Codex CLI or the Codex IDE extension."},
        ],
    },
    {
        "route_id": "R22",
        "name": "Cursor-side browser control of chatgpt.com",
        "endpoint": "Cursor agent Browser tool, or the Responses API computer tool with a harness we supply",
        "direction": "cursor_to_chatgpt_ui",
        "surface": "This runtime's own Chrome, driving the ChatGPT web UI",
        "reaches": [
            "Any web UI the browser can reach and is authenticated to.",
            "Full console logs and network traffic, on the Cursor tool.",
            "In principle the ChatGPT UI itself, including projects and chats, which "
            "no API route reaches.",
        ],
        "cannot_reach": [
            "An authenticated ChatGPT session. This runtime holds no ChatGPT "
            "credential of any name, and acquiring one is an owner-identity act this "
            "lane is forbidden to attempt.",
        ],
        "credential_required": [
            "An authenticated chatgpt.com session — the entire blocker",
        ],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "A decision about session delegation, which is an owner-identity act and "
            "carries a real security cost. This lane raises it and does not recommend it.",
        ],
        "provenance_quality": (
            "Mixed and worth being honest about. Screenshots and scraped DOM are "
            "evidence of what a page showed, but the content is unstructured and its "
            "fidelity depends on the scrape holding as the UI changes. Better than no "
            "route; much worse than a documented contract."
        ),
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "Mechanically YES once a session exists: the agent drives the browser and "
            "reads the result with no founder act. The brief's framing is confirmed by "
            "this runtime — rendering is not the constraint. Chrome 148 is installed "
            "and an X server is live on DISPLAY=:1, and the agent-facing browser tool "
            "is documented and needs no external tools. The constraint is the session "
            "alone, and it is an authorization question rather than a technical one."
        ),
        "maturity": (
            "Cursor's tool is generally available and, for enterprise, governed by MCP "
            "allowlist or denylist. Driving another vendor's UI is inherently brittle: "
            "it depends on markup nobody promised to keep."
        ),
        "status": "TECHNICALLY_AVAILABLE_CREDENTIAL_BLOCKED",
        "confidence": "high on capability and on the blocker",
        "evidence": [
            {"kind": "source", "source": "cursor-agent-browser",
             "locator": "Agent can control a web browser to test applications, audit accessibility, convert designs into code"},
            {"kind": "source", "source": "cursor-agent-browser",
             "locator": "You can use Browser without installing or configuring any external tools."},
            {"kind": "source", "source": "cursor-agent-browser",
             "locator": "For enterprise customers, browser controls are governed by MCP allowlist or denylist."},
            {"kind": "source", "source": "api-computer-use",
             "locator": "It can inspect screenshots, return interface actions for your code to execute",
             "note": "The API-side tool returns actions for the caller to execute, so the caller supplies the browser."},
            {"kind": "source", "source": "api-computer-use",
             "locator": "Before you begin, prepare an environment that can capture screenshots and run the returned actions."},
            {"kind": "runtime", "note": "Google Chrome 148.0.7778.96 installed; X.Org 21.1.11 live on DISPLAY=:1; no ChatGPT credential of any name present."},
        ],
    },
    {
        "route_id": "R23",
        "name": "Cursor Cloud Agents API — inbound trigger and content return",
        "endpoint": "POST /v1/agents, GET /v1/agents/{id}, /v1/agents/{id}/runs/{id}/stream",
        "direction": "external_system_to_cursor_and_back",
        "surface": "Cursor's own API",
        "reaches": [
            "Creating a cloud agent and enqueuing its first run, programmatically.",
            "The agent's actual output: the stream emits assistant text deltas, "
            "thinking, tool calls with args and results, and a terminal result event "
            "whose text is the final assistant reply.",
            "Artifacts, listable and downloadable.",
            "Repository work: agents clone, work on a branch, and push for handoff.",
        ],
        "cannot_reach": [
            "Anything in the ChatGPT account. This is the Cursor side of the boundary.",
        ],
        "credential_required": ["CURSOR_API_KEY — a user API key, or a service-account key"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "Generate the key from Cursor Dashboard → API Keys, or issue a service-account key.",
            "Connect source control for the account, which a Cursor account admin must do.",
        ],
        "provenance_quality": (
            "The best on either side of this boundary. Status, reasoning, tool calls "
            "with arguments and results, the final reply text, run duration and git "
            "information all arrive as structured events."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "This is the asymmetry that decides the whole question, so it is worth "
            "stating side by side. Cursor's agent API returns the agent's actual reply "
            "text over a documented stream. OpenAI's Workspace Agents API states that "
            "its agent's response cannot currently be retrieved through the API. Two "
            "agent platforms, the same architectural question, opposite answers — so "
            "any loop between them should be built to end on the Cursor side, where "
            "content is retrievable, rather than on the ChatGPT side, where it is not."
        ),
        "maturity": (
            "Public beta, explicitly may change before general availability. v1 "
            "webhooks are marked coming soon; the legacy v0 API still has them."
        ),
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "cursor-api-endpoints",
             "locator": "The Cloud Agents API lets you programmatically launch and manage cloud agents that work on your repositories."},
            {"kind": "source", "source": "cursor-api-endpoints",
             "locator": "`text` is the final assistant reply"},
            {"kind": "source", "source": "cursor-api-endpoints",
             "locator": "The Cloud Agents API v1 is in public beta. APIs may change before general",
             "window": 2},
            {"kind": "source", "source": "cursor-api-endpoints",
             "locator": "Webhooks are coming soon. The legacy"},
            {"kind": "source", "source": "cursor-cloud-agents",
             "locator": "Cloud agents clone your repo from GitHub, GitLab, Azure DevOps Services, or Bitbucket Cloud and work on a separate branch, then push changes to your repo for handoff."},
            {"kind": "fetch_failure", "sources": ["cursor-api-agents-w6"],
             "note": (
                 "OE-W6 recorded 404 for cursor.com/docs/background-agent/api/overview.md "
                 "and therefore could not establish this route. That path does not "
                 "exist. This lane read the published docs sitemap instead of guessing "
                 "again, which produced cloud-agent/api/endpoints and "
                 "cloud-agent/api/webhooks, both HTTP 200. The route was never absent; "
                 "the guess was wrong. Correcting it is the single largest change this "
                 "lane makes to the inherited picture."
             )},
        ],
    },
    {
        "route_id": "R24",
        "name": "Cursor inbound triggers from GitHub, Slack and Linear",
        "endpoint": "@cursor comment on a GitHub PR or issue; @cursor in Slack or Linear",
        "direction": "third_party_to_cursor",
        "surface": "GitHub, Slack or Linear, starting Cursor work",
        "reaches": [
            "A cloud agent started by commenting @cursor on a GitHub PR or issue, or "
            "on a Bitbucket PR.",
            "The same from Slack and Linear.",
        ],
        "cannot_reach": [
            "Anything before an account admin connects source control.",
        ],
        "credential_required": ["A connected source-control integration; the Slack app, where used"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": [
            "A Cursor account admin connects source control before anyone can start "
            "an agent from a repository.",
        ],
        "provenance_quality": (
            "Good. The trigger is a durable GitHub or Slack object with an author and "
            "a timestamp."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Any system that can post a GitHub comment can start Cursor work without "
            "him. Composed with R15, where Codex posts to pull requests, this is the "
            "shape of a machine-to-machine loop between his account and Cursor. That "
            "composition is HYPOTHESIS, not documentation: nothing this lane read says "
            "Codex would emit the literal @cursor trigger, and this lane may not test "
            "it because its boundaries forbid commenting on any pull request."
        ),
        "maturity": "Generally available across the listed integrations.",
        "status": "ESTABLISHED",
        "confidence": "high for the trigger; the Codex composition is explicitly HYPOTHESIS",
        "evidence": [
            {"kind": "source", "source": "cursor-cloud-agents",
             "locator": "**GitHub or Bitbucket**: Comment `@cursor` on a GitHub PR or issue, or on a Bitbucket PR, to kick off an agent"},
            {"kind": "source", "source": "cursor-cloud-agents",
             "locator": "Before anyone can start a cloud agent from a repository, a Cursor account admin needs to connect source control for the account."},
        ],
    },
    {
        "route_id": "R25",
        "name": "Cursor cloud agent webhooks",
        "endpoint": "statusChange POST to a webhook URL supplied at agent creation",
        "direction": "cursor_to_external_system",
        "surface": "Cursor announcing its own completion",
        "reaches": [
            "ERROR and FINISHED transitions, pushed as signed HTTP POSTs.",
            "A payload carrying status, repository, ref, branch name, PR URL and a summary.",
            "HMAC-SHA256 signature verification via X-Webhook-Signature.",
        ],
        "cannot_reach": [
            "Any state other than ERROR or FINISHED: statusChange is the only event.",
            "A v1 caller today. Webhooks are marked coming soon for v1 and remain on "
            "the legacy v0 API.",
        ],
        "credential_required": ["A webhook signing secret; a reachable HTTPS endpoint"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["None beyond providing an endpoint that outlives an agent run."],
        "provenance_quality": (
            "Strong. Signed, replay-loggable, and carrying the branch and PR that "
            "resulted, which is enough to reconcile without trusting the message."
        ),
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Push notification straight to a machine. Recorded to keep the ledger "
            "symmetric: the Cursor side has both a content-returning API and a push "
            "channel, and the ChatGPT side has neither."
        ),
        "maturity": "Available on v0; coming soon on v1. Only one event type.",
        "status": "ESTABLISHED_ON_LEGACY_API",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "cursor-api-webhooks",
             "locator": "When you create an agent with a webhook URL, Cursor will send HTTP POST requests to notify you about status changes."},
            {"kind": "source", "source": "cursor-api-webhooks",
             "locator": "**`X-Webhook-Signature`** – Contains the HMAC-SHA256 signature"},
            {"kind": "source", "source": "cursor-api-endpoints",
             "locator": "Webhooks are coming soon. The legacy"},
        ],
    },
    {
        "route_id": "R26",
        "name": "OpenAI platform webhooks",
        "endpoint": "Endpoints registered in the OpenAI dashboard, subscribed to response.* and batch.* events",
        "direction": "openai_platform_to_our_endpoint",
        "surface": "The API Platform announcing its own completions",
        "reaches": [
            "response.completed and related events for background responses, batches "
            "and fine-tuning jobs.",
        ],
        "cannot_reach": [
            "Anything about the ChatGPT account. These are platform-object events.",
            "Any endpoint that does not outlive an agent run.",
        ],
        "credential_required": ["OPENAI_WEBHOOK_SECRET, separate from the API key"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["Register the endpoint in the dashboard and subscribe it to events."],
        "provenance_quality": "Good: authenticity is validated before parsing, per the Standard Webhooks specification.",
        "returns_without_founder_touch": "CONDITIONAL",
        "returns_without_founder_touch_reason": (
            "Precondition: a durable HTTPS endpoint, which this runtime does not have. "
            "Until one exists the honest fallback is background execution plus "
            "scheduled polling from a durable runner, carried as a known deficiency "
            "rather than presented as a live push route."
        ),
        "maturity": "Generally available.",
        "status": "ESTABLISHED_MECHANISM_BLOCKED_BY_MISSING_ENDPOINT",
        "confidence": "high",
        "evidence": [
            {"kind": "l5", "claim_id": "C-WH-EVENTS"},
            {"kind": "l5", "claim_id": "C-WH-SECRET-ENV"},
        ],
    },
    {
        "route_id": "R27",
        "name": "Cursor consuming MCP servers",
        "endpoint": "Cursor MCP configuration",
        "direction": "cursor_to_external_tools",
        "surface": "Cursor's own agents, given external tools",
        "reaches": [
            "External tools and data sources: databases, APIs, third-party services.",
        ],
        "cannot_reach": [
            "The ChatGPT account, absent an MCP server that itself holds ChatGPT "
            "access. No such server is evidenced here, and building one returns to "
            "the credential problem in R22.",
        ],
        "credential_required": ["Whatever each MCP server requires"],
        "credential_present_in_this_runtime": False,
        "founder_action_required": ["None inherently; per-server authorization where a server needs it."],
        "provenance_quality": "As good as the server's own outputs, and the server can be ours and therefore auditable.",
        "returns_without_founder_touch": "YES",
        "returns_without_founder_touch_reason": (
            "Cursor calls the tool and reads the result. Listed to complete the "
            "symmetry with R05: both platforms consume MCP, which makes MCP the one "
            "vocabulary both sides already speak, and therefore the natural place to "
            "put a bridge."
        ),
        "maturity": "Generally available on both sides.",
        "status": "ESTABLISHED",
        "confidence": "high",
        "evidence": [
            {"kind": "source", "source": "cursor-cloud-agents",
             "locator": "Cloud agents support [MCP servers](https://cursor.com/docs/mcp.md), giving them access to external tools and data sources like databases, APIs, and third-party services."},
        ],
    },
]


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LocatorMiss(Exception):
    pass


def cut(body_text: str, locator: str, window: int) -> tuple[int, str]:
    """Find a literal locator and return its line number and an excerpt."""
    idx = body_text.find(locator)
    if idx < 0:
        raise LocatorMiss(locator)
    line_no = body_text.count("\n", 0, idx) + 1
    lines = body_text.splitlines()
    start = line_no - 1
    end = min(len(lines), start + max(1, window))
    return line_no, "\n".join(lines[start:end]).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", required=True)
    ap.add_argument("--gap-log", required=True)
    ap.add_argument("--w6-log", required=True)
    ap.add_argument("--l5-evidence", required=True)
    ap.add_argument("--runtime-facts", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bodies = pathlib.Path(args.bodies)
    gap = json.loads(pathlib.Path(args.gap_log).read_text())
    w6 = json.loads(pathlib.Path(args.w6_log).read_text())
    l5 = json.loads(pathlib.Path(args.l5_evidence).read_text())
    l5_claims = {c["claim_id"]: c for c in l5["claims"]}

    cited: dict[str, dict] = {}
    misses: list[str] = []
    reused_l5 = 0
    cut_here = 0
    scans = 0

    def note_source(sid: str) -> dict:
        rec = gap["sources"].get(sid)
        if rec is None:
            raise LocatorMiss(f"source not fetched: {sid}")
        cited.setdefault(sid, {
            "source_id": sid,
            "url": rec.get("url_effective") or rec["url_requested"],
            "http_status": rec.get("http_status"),
            "sha256": rec.get("sha256"),
            "bytes": rec.get("bytes"),
            "fetched_at_utc": rec.get("fetched_at_utc"),
            "byte_identical_to_w6_harvest": rec.get("harvest_sha256_match"),
            "w6_source_id": rec.get("w6_source_id"),
            "why_fetched": rec.get("why_fetched"),
        })
        return cited[sid]

    for route in ROUTES:
        resolved = []
        for ev in route["evidence"]:
            kind = ev["kind"]
            if kind == "source":
                sid = ev["source"]
                meta = note_source(sid)
                text = (bodies / f"{sid}.body").read_text(errors="replace")
                try:
                    line_no, excerpt = cut(text, ev["locator"], ev.get("window", 1))
                except LocatorMiss:
                    misses.append(f"{route['route_id']} {sid}: {ev['locator'][:70]}")
                    continue
                cut_here += 1
                item = {
                    "evidence_label": "DOCUMENTED",
                    "source_id": sid,
                    "source_url": meta["url"],
                    "source_sha256": meta["sha256"],
                    "fetched_at_utc": meta["fetched_at_utc"],
                    "byte_identical_to_w6_harvest": meta["byte_identical_to_w6_harvest"],
                    "matched_at_line": line_no,
                    "verbatim_excerpt": excerpt,
                }
                if ev.get("note"):
                    item["note"] = ev["note"]
                resolved.append(item)
            elif kind == "l5":
                cid = ev["claim_id"]
                c = l5_claims.get(cid)
                if c is None:
                    misses.append(f"{route['route_id']} missing L5 claim {cid}")
                    continue
                reused_l5 += 1
                resolved.append({
                    "evidence_label": c["evidence_label"],
                    "reused_from_lane": "OE-L5-CHATGPT-SCALE",
                    "reused_claim_id": cid,
                    "claim": c["claim"],
                    "source_url": c["source_url"],
                    "source_sha256": c["source_sha256"],
                    "fetched_at_utc": c["fetched_at_utc"],
                    "matched_at_line": c["matched_at_line"],
                    "verbatim_excerpt": c["verbatim_excerpt"],
                })
            elif kind == "scan":
                sid = ev["source"]
                meta = note_source(sid)
                text = (bodies / f"{sid}.body").read_text(errors="replace")
                hits = re.findall(ev["pattern"] + r".{0,44}", text, flags=re.S)
                norm = sorted({re.sub(r"\s+", " ", h).strip() for h in hits})
                scans += 1
                resolved.append({
                    "evidence_label": "DOCUMENTED",
                    "evidence_kind": "counted_scan_for_absence",
                    "source_id": sid,
                    "source_url": meta["url"],
                    "source_sha256": meta["sha256"],
                    "fetched_at_utc": meta["fetched_at_utc"],
                    "pattern": ev["pattern"],
                    "total_occurrences": len(hits),
                    "distinct_contexts": norm[:40],
                    "distinct_context_count": len(norm),
                    "interpretation": ev["interpretation"],
                })
            elif kind == "index_absence":
                sid = ev["source"]
                meta = note_source(sid)
                text = (bodies / f"{sid}.body").read_text(errors="replace")
                lines = [ln.strip() for ln in text.splitlines() if re.search(ev["pattern"], ln)]
                scans += 1
                resolved.append({
                    "evidence_label": "DOCUMENTED",
                    "evidence_kind": "searched_published_index_and_found_no_entry",
                    "source_id": sid,
                    "source_url": meta["url"],
                    "source_sha256": meta["sha256"],
                    "fetched_at_utc": meta["fetched_at_utc"],
                    "pattern": ev["pattern"],
                    "matching_index_entries": [ln[:190] for ln in lines],
                    "interpretation": ev["interpretation"],
                })
            elif kind == "fetch_failure":
                items = []
                for sid in ev["sources"]:
                    rec = gap["sources"].get(sid)
                    if rec is None:
                        w6rec = w6["sources"].get(sid.replace("-w6", ""))
                        items.append({
                            "source_id": sid,
                            "only_in_w6_harvest": True,
                            "url": (w6rec or {}).get("url_requested"),
                            "http_status": (w6rec or {}).get("http_status"),
                            "w6_fetched_at_utc": (w6rec or {}).get("fetched_at_utc"),
                        })
                        continue
                    note_source(sid)
                    items.append({
                        "source_id": sid,
                        "url": rec["url_requested"],
                        "http_status_this_lane": rec.get("http_status"),
                        "http_status_w6": rec.get("w6_http_status"),
                        "user_agent_used": rec.get("user_agent"),
                        "fetched_at_utc": rec.get("fetched_at_utc"),
                        "sha256": rec.get("sha256"),
                    })
                resolved.append({
                    "evidence_label": "DIRECTLY_REPRODUCED",
                    "evidence_kind": "fetch_failure_reproduced",
                    "attempts": items,
                    "note": ev["note"],
                })
            elif kind == "runtime":
                resolved.append({
                    "evidence_label": "DIRECTLY_REPRODUCED",
                    "evidence_kind": "runtime_observation",
                    "receipt": "receipts/so02/2026-08-22/oe-w7-route-evidence/raw/runtime-facts.txt",
                    "observation": ev["note"],
                })
            else:
                raise SystemExit(f"unknown evidence kind {kind}")
        route["evidence"] = resolved

    if misses:
        print("REFUSED: locator(s) no longer match their source:", file=sys.stderr)
        for m in misses:
            print("  " + m, file=sys.stderr)
        return 3

    decisive: dict[str, list[str]] = {}
    for r in ROUTES:
        decisive.setdefault(r["returns_without_founder_touch"], []).append(r["route_id"])

    out = {
        "artifact_id": "OE-W7-ROUTE-EVIDENCE-TABLE-20260822-v001",
        "lane": "OE-W7-CHATGPT-ROUTE-EVIDENCE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "built_at_utc": utcnow(),
        "terminal_state": "READY_TO_COMMIT",
        "scope": (
            "Every route by which anything can travel between Ahmed Sadek's "
            "authorised ChatGPT account and Cursor. One deliverable. This lane "
            "evidences routes; it does not open them, and it authenticated to nothing."
        ),
        "founder_authority_basis": (
            "The founder's standing instruction that the entire authorised ChatGPT "
            "account, not only active threads, may be used to recover context, "
            "initiate follow-ups and message its models, preserving provenance. "
            "Recorded verbatim at workstreams/so02/control-plane/operating-environment/"
            "FOUNDER-STANDING-INSTRUCTION-20260822.md."
        ),
        "evidence_label_meaning": LABEL_MEANING,
        "decisive_column": DECISIVE_COLUMN,
        "how_to_reproduce": [
            "python3 tools/fetch_route_gaps.py --harvest W6LOG --out BODIES --log GAPLOG",
            "bash    tools/capture_runtime_facts.sh",
            "python3 tools/build_route_table.py --bodies BODIES --gap-log GAPLOG "
            "--w6-log W6LOG --l5-evidence L5JSON --runtime-facts FACTS --out TABLE.json",
        ],
        "evidence_reuse": {
            "position": (
                "The predecessor lane's harvest is treated as evidence to carry "
                "forward, not as work to redo. Re-fetching everything is what "
                "exhausted it."
            ),
            "w6_harvest": {
                "commit": "2d2b346cd90e4059e26f2d3238f702a582943c32",
                "branch": "cursor/oe-w6-chatgpt-connection-696d",
                "source_count": w6.get("source_count"),
                "http_200_count": w6.get("http_200_count"),
                "built_at_utc": w6.get("built_at_utc"),
                "authenticated_requests": w6.get("authenticated_requests"),
                "what_it_lacked": (
                    "It committed the log but not the bodies, so the text behind each "
                    "recorded hash was unavailable. That is the gap this lane filled, "
                    "and the only reason any fetching was necessary."
                ),
            },
            "l5_prior_work": {
                "artifact": l5.get("artifact_id"),
                "claim_count": l5.get("claim_count"),
                "built_at_utc": l5.get("built_at_utc"),
                "claims_reused_here": reused_l5,
            },
            "this_lane_fetch": {
                "source_count": gap.get("source_count"),
                "http_200_count": gap.get("http_200_count"),
                "byte_identical_to_w6": gap.get("verified_identical_to_w6_count"),
                "changed_since_w6": gap.get("changed_since_w6"),
                "non_200": gap.get("non_200"),
                "authenticated_requests": gap.get("authenticated_requests"),
                "credential_used": gap.get("credential_used"),
                "sources_cited_by_a_claim": len(cited),
                "fetched_but_not_cited": sorted(set(gap["sources"]) - set(cited)),
                "note_on_the_404": (
                    "developers.openai.com/api/docs/guides/tools-remote-mcp.md returns "
                    "404: the .md convention that resolves elsewhere on that host does "
                    "not resolve for this path. No claim in this table cites it. The "
                    "claims it was meant to support were established from "
                    "api-secure-mcp-tunnels and chatgpt-extend-mcp instead, both 200."
                ),
            },
            "cross_harvest_corroboration": (
                "Twenty-six URLs were fetched independently by OE-L5 at 20:36Z and "
                "OE-W6 at 00:03Z, and every sha256 agrees. The documentation was "
                "stable across that window, so L5's excerpts remain valid against W6's "
                "hashes and this lane reuses them rather than re-cutting them."
            ),
        },
        "excerpt_discipline": (
            f"{cut_here} excerpts cut out of bodies fetched by this lane using literal "
            f"locators; {reused_l5} claims reused from OE-L5 with their own hashes; "
            f"{scans} counted scans used for absence claims. A locator that stops "
            "matching fails the build rather than emitting a stale quotation."
        ),
        "route_count": len(ROUTES),
        "decisive_column_rollup": {
            k: {"count": len(v), "route_ids": v} for k, v in sorted(decisive.items())
        },
        "unestablished": [
            {
                "route_id": r["route_id"],
                "name": r["name"],
                "why": r["cannot_reach"][0] if r["cannot_reach"] else "",
            }
            for r in ROUTES if r["status"] == "UNESTABLISHED"
        ],
        "routes": ROUTES,
        "sources_cited": dict(sorted(cited.items())),
        "what_this_lane_did_not_do": [
            "Did not authenticate to ChatGPT, acquire any credential, or sign up for anything.",
            "Did not print or store any credential value. Presence was reported by name only.",
            "Did not open, comment on, merge or modify any pull request.",
            "Did not message or configure SW, and did not touch PO-01, PO-03 or MANUS.",
            "Did not attempt to defeat the bot challenge on the three 403 sources.",
            "Did not write outside its own two namespaces on its own branch.",
        ],
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"routes: {len(ROUTES)}  excerpts cut: {cut_here}  L5 reused: {reused_l5}  scans: {scans}")
    for k, v in sorted(decisive.items()):
        print(f"  {k:<16} {len(v):>2}  {' '.join(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
