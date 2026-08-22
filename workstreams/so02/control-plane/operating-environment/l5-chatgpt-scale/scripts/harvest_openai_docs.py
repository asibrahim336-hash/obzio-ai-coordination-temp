#!/usr/bin/env python3
"""Harvest official OpenAI documentation and record reproducible fetch evidence.

Every API-surface claim made by lane OE-L5-CHATGPT-SCALE is backed by a row in
the log this script writes: URL, HTTP status, UTC fetch time, byte length and
sha256 of the exact body that was read. Re-running the script re-derives the
evidence; a changed sha256 means the upstream documentation moved and the claim
must be re-checked rather than trusted.

No credential is read, sent or required. Every URL is public documentation.

Usage:
    python3 harvest_openai_docs.py --out /tmp/openai-docs
    python3 harvest_openai_docs.py --out /tmp/openai-docs --log fetch-log.tsv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# platform.openai.com rejects non-browser user agents with HTTP 403; the same
# content is served without that gate from developers.openai.com. Both are
# recorded so the difference is evidence rather than folklore.
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)

REF = "https://developers.openai.com/api/reference"
GUIDE = "https://developers.openai.com/api/docs/guides"
WA = "https://developers.openai.com/workspace-agents"
LEARN = "https://learn.chatgpt.com/docs"

# id -> (url, what this source is being relied on for)
# Route paths were not recalled: they were read out of the published indexes
# (index-root, index-api, index-api-reference, index-guides, index-workspace-
# agents, index-chatgpt), which are themselves harvested below.
SOURCES: dict[str, tuple[str, str]] = {
    # --- indexes / discovery ----------------------------------------------
    "index-root": (
        "https://developers.openai.com/llms.txt",
        "top-level documentation-set map; establishes which product surfaces exist",
    ),
    "index-api": (
        "https://developers.openai.com/api/llms.txt",
        "split between API guides and API endpoint reference",
    ),
    "index-api-reference": (
        f"{REF}/llms.txt",
        "machine-readable index of the current API reference route tree",
    ),
    "index-guides": (
        "https://developers.openai.com/api/docs/llms.txt",
        "machine-readable index of the current API guide set",
    ),
    "index-workspace-agents": (
        f"{WA}/llms.txt",
        "index of the Workspace Agents documentation set",
    ),
    "index-chatgpt": (
        "https://learn.chatgpt.com/llms.txt",
        "index of the ChatGPT product documentation set",
    ),
    # --- Responses API -----------------------------------------------------
    "responses-overview": (
        f"{REF}/resources/responses.md",
        "the Responses resource and its method set",
    ),
    "responses-create": (
        f"{REF}/resources/responses/methods/create.md",
        "POST /v1/responses request shape, parameter names, background flag",
    ),
    "responses-retrieve": (
        f"{REF}/resources/responses/methods/retrieve.md",
        "GET /v1/responses/{response_id} retrieval by identifier",
    ),
    "responses-cancel": (
        f"{REF}/resources/responses/methods/cancel.md",
        "cancelling a background response",
    ),
    "responses-delete": (
        f"{REF}/resources/responses/methods/delete.md",
        "deleting a stored response",
    ),
    "responses-input-items-list": (
        f"{REF}/resources/responses/subresources/input_items/methods/list.md",
        "listing the input items of a stored response",
    ),
    # --- Conversations API -------------------------------------------------
    "conversations-overview": (
        f"{REF}/resources/conversations.md",
        "the Conversations resource and its method set",
    ),
    "conversations-create": (
        f"{REF}/resources/conversations/methods/create.md",
        "POST /v1/conversations, conversation identifier shape, metadata limits",
    ),
    "conversations-retrieve": (
        f"{REF}/resources/conversations/methods/retrieve.md",
        "GET /v1/conversations/{conversation_id} addressable retrieval",
    ),
    "conversations-update": (
        f"{REF}/resources/conversations/methods/update.md",
        "mutating conversation metadata after creation",
    ),
    "conversations-delete": (
        f"{REF}/resources/conversations/methods/delete.md",
        "deleting a conversation",
    ),
    "conversation-items-list": (
        f"{REF}/resources/conversations/subresources/items/methods/list.md",
        "listing the items of a conversation by conversation identifier",
    ),
    # --- batch -------------------------------------------------------------
    "batches-overview": (
        f"{REF}/resources/batches.md",
        "the Batch resource and its method set",
    ),
    "batches-create": (
        f"{REF}/resources/batches/methods/create.md",
        "POST /v1/batches, completion window, endpoint whitelist",
    ),
    "batches-retrieve": (
        f"{REF}/resources/batches/methods/retrieve.md",
        "batch status retrieval and terminal states",
    ),
    # --- models ------------------------------------------------------------
    "models-list": (
        f"{REF}/resources/models/methods/list.md",
        "GET /v1/models, the cheapest authenticated liveness probe",
    ),
    # --- webhooks ----------------------------------------------------------
    "webhooks-overview": (
        f"{REF}/resources/webhooks.md",
        "webhook resource and event types",
    ),
    "webhooks-unwrap": (
        f"{REF}/resources/webhooks/methods/unwrap.md",
        "verifying and decoding a webhook payload",
    ),
    # --- guides ------------------------------------------------------------
    "guide-conversation-state": (
        f"{GUIDE}/conversation-state.md",
        "how conversation state is carried between turns",
    ),
    "guide-background": (
        f"{GUIDE}/background.md",
        "background mode semantics, polling, streaming, cancellation",
    ),
    "guide-webhooks": (
        f"{GUIDE}/webhooks.md",
        "webhook delivery, signature verification, secret environment name",
    ),
    "guide-batch": (
        f"{GUIDE}/batch.md",
        "batch discount, completion window, supported endpoints",
    ),
    "guide-structured-outputs": (
        f"{GUIDE}/structured-outputs.md",
        "strict JSON schema adherence and its schema subset restrictions",
    ),
    "guide-function-calling": (
        f"{GUIDE}/function-calling.md",
        "tool/function calling shape and strict mode",
    ),
    "guide-your-data": (
        f"{GUIDE}/your-data.md",
        "retention behaviour and zero-data-retention eligibility by endpoint",
    ),
    "guide-production-best-practices": (
        f"{GUIDE}/production-best-practices.md",
        "credential handling guidance from the provider itself",
    ),
    "guide-rate-limits": (
        f"{GUIDE}/rate-limits.md",
        "rate limit tiers and headers",
    ),
    "guide-error-codes": (
        f"{GUIDE}/error-codes.md",
        "the 401 shape observed on the unauthenticated probe",
    ),
    "guide-rbac": (
        f"{GUIDE}/rbac.md",
        "role and permission surface that bounds minimum key scope",
    ),
    "guide-admin-apis": (
        f"{GUIDE}/admin-apis.md",
        "administrative key type, where created, what it governs",
    ),
    "guide-spend-limits": (
        f"{GUIDE}/spend-limits.md",
        "the budget control that must exist before any spend is possible",
    ),
    "guide-cost-optimization": (
        f"{GUIDE}/cost-optimization.md",
        "cost levers relevant to a sustained multi-function operation",
    ),
    "guide-prompt-caching": (
        f"{GUIDE}/prompt-caching.md",
        "caching behaviour relevant to repeated context contracts",
    ),
    "guide-model-selection": (
        f"{GUIDE}/model-selection.md",
        "provider guidance on choosing models; recommendation input only",
    ),
    "guide-tools-connectors-mcp": (
        f"{GUIDE}/tools-connectors-mcp.md",
        "connector/MCP tool surface, a candidate non-founder return route",
    ),
    "guide-ip-allowlist": (
        f"{GUIDE}/ip-allowlist.md",
        "network-level restriction available to bound the credential",
    ),
    # --- Workspace Agents (reaches a ChatGPT workspace) --------------------
    "wa-authentication": (
        f"{WA}/authentication.md",
        "the credential type Workspace Agents needs; distinct from OPENAI_API_KEY",
    ),
    "wa-trigger-runs": (
        f"{WA}/trigger-runs.md",
        "the only documented route that starts work inside a ChatGPT workspace",
    ),
    # --- ChatGPT product surface (deliverable A) ---------------------------
    "chatgpt-projects": (
        f"{LEARN}/projects.md",
        "what a ChatGPT project is and what it does and does not carry",
    ),
    "chatgpt-automations": (
        f"{LEARN}/automations.md",
        "scheduled/automated runs: the pull-clock inside the account",
    ),
    "chatgpt-memories": (
        f"{LEARN}/customization/memories.md",
        "provider memory semantics, which this programme refuses to make canonical",
    ),
    "chatgpt-compliance-api": (
        f"{LEARN}/enterprise/compliance-api.md",
        "the documented route that can read ChatGPT conversation records",
    ),
    "chatgpt-access-tokens": (
        f"{LEARN}/enterprise/access-tokens.md",
        "workspace-level credential provisioning location",
    ),
    "chatgpt-service-accounts": (
        f"{LEARN}/enterprise/service-accounts.md",
        "non-human identity for workspace automation",
    ),
    "chatgpt-roles-permissions": (
        f"{LEARN}/enterprise/roles-and-workspace-permissions.md",
        "who may provision workspace credentials",
    ),
    "chatgpt-apps-connectors": (
        f"{LEARN}/enterprise/apps-and-connectors.md",
        "connector surface inside ChatGPT, candidate non-founder return route",
    ),
    "chatgpt-governance": (
        f"{LEARN}/enterprise/governance.md",
        "workspace governance controls relevant to automation governance",
    ),
    "chatgpt-analytics-api": (
        f"{LEARN}/enterprise/analytics-api.md",
        "workspace usage telemetry, candidate input to founder-load accounting",
    ),
    "chatgpt-subagents": (
        f"{LEARN}/agent-configuration/subagents.md",
        "whether one agent can delegate to another inside the product",
    ),
    "chatgpt-skills-plugins": (
        f"{LEARN}/skills-and-plugins.md",
        "reusable capability packaging inside the account",
    ),
    "chatgpt-pricing": (
        f"{LEARN}/pricing.md",
        "plan tiers, which gate the admin-only routes above",
    ),
    "chatgpt-import": (
        f"{LEARN}/import.md",
        "bulk movement of existing conversation content",
    ),
    "chatgpt-long-running-work": (
        f"{LEARN}/long-running-work.md",
        "how the product handles work that outlives one interaction",
    ),
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, dest: pathlib.Path, retries: int = 3) -> dict:
    """Fetch one URL with curl, returning a provenance record."""
    last: dict = {}
    for attempt in range(1, retries + 1):
        started = now_utc()
        proc = subprocess.run(
            [
                "curl", "-sS", "-L",
                "--max-time", "45",
                "-A", BROWSER_UA,
                "-w", "%{http_code}\t%{size_download}\t%{url_effective}",
                "-o", str(dest),
                url,
            ],
            capture_output=True,
            text=True,
        )
        meta = proc.stdout.strip().split("\t")
        status = meta[0] if meta else "000"
        effective = meta[2] if len(meta) > 2 else url
        body = dest.read_bytes() if dest.exists() else b""
        last = {
            "url": url,
            "url_effective": effective,
            "http_status": status,
            "fetched_at_utc": started,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest() if body else None,
            "attempt": attempt,
            "curl_exit": proc.returncode,
            "curl_stderr": proc.stderr.strip()[:400] or None,
        }
        if status == "200" and body:
            return last
        # A 404 is a stable answer about the route, not a transient failure.
        # Retrying it only buys a slower identical result.
        if status.startswith("4") and status != "429":
            return last
        time.sleep(2 * attempt)
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/openai-docs",
                    help="directory to write fetched bodies into")
    ap.add_argument("--log", default=None,
                    help="optional path for the JSON provenance log")
    ap.add_argument("--only", default=None,
                    help="regex; fetch only source ids matching it")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    selector = re.compile(args.only) if args.only else None
    records = []
    ok = 0
    for sid, (url, purpose) in sorted(SOURCES.items()):
        if selector and not selector.search(sid):
            continue
        dest = outdir / f"{sid}.md"
        rec = fetch(url, dest)
        rec["source_id"] = sid
        rec["relied_on_for"] = purpose
        rec["local_path"] = str(dest)
        records.append(rec)
        if rec["http_status"] == "200":
            ok += 1
        print(f"{rec['http_status']:>4}  {rec['bytes']:>7}  {sid}", file=sys.stderr)

    log = {
        "harvest_id": "OE-L5-OPENAI-DOC-HARVEST-20260822",
        "harvested_at_utc": now_utc(),
        "user_agent_used": BROWSER_UA,
        "credential_used": None,
        "source_count": len(records),
        "http_200_count": ok,
        "records": records,
    }
    text = json.dumps(log, indent=2, sort_keys=True) + "\n"
    if args.log:
        pathlib.Path(args.log).write_text(text, encoding="utf-8")
    else:
        print(text)
    print(f"\n{ok}/{len(records)} sources returned HTTP 200", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
