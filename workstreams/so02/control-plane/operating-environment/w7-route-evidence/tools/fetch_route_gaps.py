#!/usr/bin/env python3
"""Fetch only the documentation bodies the OE-W6 harvest did not preserve.

The W6 harvest (commit 2d2b346cd90e4059e26f2d3238f702a582943c32) recorded, for
79 sources, the final URL, HTTP status, byte count and sha256 -- but committed
only that log. The bodies it wrote to disk were not committed, so the text
behind each hash is unavailable to this lane. Re-fetching every source is what
exhausted the predecessor's budget, so this fetches a named subset chosen
because a route conclusion depends on its wording.

Every fetched body is checked against the sha256 the W6 harvest recorded for the
same URL. A match means this lane is reading the exact bytes the predecessor
hashed, so W6's provenance carries forward instead of being restated. A mismatch
is recorded, not silently accepted: it means the page moved between the two
fetches and any claim cut from it is this lane's own, dated now.

Non-200 responses are recorded. Three sources answered 403 for W6 behind a bot
challenge; this re-requests them once with curl's default user agent to
establish whether the block is agent-string-dependent or unconditional. No
attempt is made to defeat the challenge.

No credential is read, sent or stored. Every request is unauthenticated.

    python3 fetch_route_gaps.py --harvest W6LOG --out BODYDIR --log LOGFILE
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys

# (id, url, why). `why` records the route conclusion that depends on this body,
# so a later reader can tell whether the fetch was necessary or padding.
GAPS: list[tuple[str, str, str]] = [
    # --- connectors inside ChatGPT: reach, and whether one can hold repo write
    ("chatgpt-extend-mcp", "https://learn.chatgpt.com/docs/extend/mcp.md",
     "whether a ChatGPT-side MCP connector can carry write actions"),
    ("chatgpt-apps-connectors", "https://learn.chatgpt.com/docs/enterprise/apps-and-connectors.md",
     "what connectors reach and who admits them"),
    ("chatgpt-plugins", "https://learn.chatgpt.com/docs/plugins.md",
     "the plugin/connector surface available to the account"),
    ("chatgpt-build-skills", "https://learn.chatgpt.com/docs/build-skills.md",
     "whether an account-side skill can act on an external system"),
    ("plugins-auth", "https://developers.openai.com/plugins/build/auth.md",
     "the credential a connector holds, and whose identity it acts as"),
    ("api-tools-connectors-mcp", "https://developers.openai.com/api/docs/guides/tools-connectors-mcp.md",
     "connectors reachable from the API side rather than the UI"),

    # --- Codex: the account-resident surface that already reaches repositories
    ("codex-third-party-github", "https://learn.chatgpt.com/docs/third-party/github.md",
     "whether an account-side GitHub integration reaches this repository"),
    ("codex-cloud", "https://learn.chatgpt.com/docs/cloud.md",
     "the account-resident agent that runs against a repository"),
    ("codex-github-action", "https://learn.chatgpt.com/docs/github-action.md",
     "whether a repository-side trigger can invoke the account"),
    ("codex-code-review", "https://learn.chatgpt.com/docs/code-review.md",
     "whether account-side output lands in the repository without a person"),
    ("codex-remote-connections", "https://learn.chatgpt.com/docs/remote-connections.md",
     "how an account-side agent is reached from outside"),

    # --- scheduled work inside the account
    ("chatgpt-automations", "https://learn.chatgpt.com/docs/automations.md",
     "whether ChatGPT Tasks/automations can emit a result outside the UI"),
    ("chatgpt-notifications", "https://learn.chatgpt.com/docs/notifications.md",
     "whether completion can be signalled anywhere a machine reads"),

    # --- browser and computer control
    ("chatgpt-browser", "https://learn.chatgpt.com/docs/browser.md",
     "the ChatGPT-side browsing surface and its direction of travel"),
    ("chatgpt-computer-use", "https://learn.chatgpt.com/docs/computer-use.md",
     "account-side computer control and what it is allowed to drive"),
    ("chatgpt-chrome-extension", "https://learn.chatgpt.com/docs/chrome-extension.md",
     "whether a browser extension bridges an authenticated session"),
    ("api-computer-use", "https://developers.openai.com/api/docs/guides/tools-computer-use.md",
     "the API-side computer-use tool: who supplies the browser"),

    # --- what the account itself holds
    ("chatgpt-projects", "https://learn.chatgpt.com/docs/projects.md",
     "what a project is, since projects are the content to be reached"),
    ("chatgpt-import", "https://learn.chatgpt.com/docs/import.md",
     "the reverse direction: repository content into the account"),

    # --- admin read routes and the credentials they need
    ("chatgpt-access-tokens", "https://learn.chatgpt.com/docs/enterprise/access-tokens.md",
     "which tokens the account can mint and what each scope reaches"),
    ("chatgpt-service-accounts", "https://learn.chatgpt.com/docs/enterprise/service-accounts.md",
     "whether a non-human identity can hold account access"),
    ("chatgpt-analytics-api", "https://learn.chatgpt.com/docs/enterprise/analytics-api.md",
     "whether analytics is a content read route or a metrics route"),
    ("chatgpt-work-admin-faq", "https://learn.chatgpt.com/docs/enterprise/work-admin-faq.md",
     "the admin surface, and any export statement on a non-403 host"),

    # --- the index, read to find an export page on a host that answers
    ("index-chatgpt", "https://learn.chatgpt.com/llms.txt",
     "published path list, to locate export docs outside the 403 hosts"),

    # --- the Cursor side of any return route
    ("cursor-mcp", "https://cursor.com/docs/mcp.md",
     "what Cursor can be handed as a tool surface"),
    ("cursor-cloud-agents", "https://cursor.com/docs/cloud-agent.md",
     "what reaches a Cursor cloud agent, and what it can be triggered by"),

    # --- the Cursor inbound API. W6 recorded 404 for
    # cursor.com/docs/background-agent/api/overview.md, which is a guessed path
    # that does not exist. The real paths were read out of the published docs
    # sitemap rather than guessed again, which is why they answer.
    ("cursor-docs-sitemap", "https://cursor.com/docs/sitemap.xml",
     "the published path index that located the API docs W6 recorded as 404"),
    ("cursor-api-endpoints", "https://cursor.com/docs/cloud-agent/api/endpoints.md",
     "whether an external system can start Cursor work without a person"),
    ("cursor-api-webhooks", "https://cursor.com/docs/cloud-agent/api/webhooks.md",
     "whether Cursor completion can announce itself to a machine"),
    ("cursor-agent-browser", "https://cursor.com/docs/agent/tools/browser.md",
     "the agent-facing browser tool: the real constraint, not rendering"),

    # --- Secure MCP Tunnel. Not harvested by W6 at all; found by following a
    # link out of the connectors guide. It bears directly on the return-route
    # question, because the prior lane's blocker was the absence of a durable
    # public HTTPS endpoint in this runtime.
    ("api-secure-mcp-tunnels", "https://developers.openai.com/api/docs/guides/secure-mcp-tunnels.md",
     "whether a private MCP server can be reached without a public endpoint"),
    ("api-tools-remote-mcp", "https://developers.openai.com/api/docs/guides/tools-remote-mcp.md",
     "which OpenAI products a remote MCP server and its connectors reach"),

    # --- the platform/UI boundary, checked for any mention of ChatGPT content
    ("api-conversations-overview", "https://developers.openai.com/api/reference/resources/conversations.md",
     "whether the Conversations API references ChatGPT UI content at all"),
    ("api-responses-create", "https://developers.openai.com/api/reference/resources/responses/methods/create.md",
     "whether the Responses API references ChatGPT UI content at all"),

    # --- data export: W6 got 403 on all three. Re-established, not assumed.
    ("openai-export-data", "https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data",
     "the owner's own export: viability could not be documented for W6"),
    ("openai-data-controls-faq", "https://help.openai.com/en/articles/7730893-data-controls-faq",
     "data controls: 403 for W6"),
    ("openai-privacy-portal", "https://privacy.openai.com/policies",
     "privacy portal: 403 for W6"),
]

# W6 sent a lane-identifying agent string. Sources that answered 403 for W6 are
# re-requested with curl's default agent to separate "this page blocks
# non-browser agents" from "this page blocks this agent string".
RETRY_DEFAULT_UA = {"openai-export-data", "openai-data-controls-faq", "openai-privacy-portal"}

UA = "obzio-oe-w7-route-evidence/1.0 (+documentation review; unauthenticated)"

CREDENTIAL_VARS = (
    "OPENAI_API_KEY", "OPENAI_WEBHOOK_SECRET", "CHATGPT_ACCESS_TOKEN",
    "CHATGPT_API_KEY", "CURSOR_API_KEY", "OPENAI_ADMIN_KEY",
)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url: str, dest: pathlib.Path, default_ua: bool) -> dict:
    started = utcnow()
    fmt = "%{http_code}\\n%{url_effective}\\n%{content_type}\\n%{size_download}\\n%{num_redirects}"
    cmd = ["curl", "-sS", "-L", "--max-time", "45", "--retry", "1", "--retry-delay", "2"]
    if not default_ua:
        cmd += ["-A", UA]
    cmd += ["-o", str(dest), "-w", fmt, url]
    rec: dict = {
        "url_requested": url,
        "fetched_at_utc": started,
        "credential_sent": False,
        "user_agent": "curl-default" if default_ua else UA,
    }
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        rec.update({"http_status": None, "error": "timeout", "ok": False})
        return rec
    if p.returncode != 0:
        rec.update({"http_status": None, "curl_exit": p.returncode,
                    "error": (p.stderr or "").strip()[:400], "ok": False})
        return rec
    parts = (p.stdout or "").strip().split("\n")
    while len(parts) < 5:
        parts.append("")
    body = dest.read_bytes() if dest.exists() else b""
    rec.update({
        "curl_exit": 0,
        "http_status": int(parts[0]) if parts[0].isdigit() else None,
        "url_effective": parts[1],
        "content_type": parts[2],
        "bytes": len(body),
        "num_redirects": int(parts[4]) if parts[4].isdigit() else None,
        "sha256": hashlib.sha256(body).hexdigest(),
        "ok": parts[0] == "200",
    })
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", required=True, help="the W6 doc-fetch-log.json")
    ap.add_argument("--out", required=True, help="directory for fetched bodies")
    ap.add_argument("--log", required=True, help="path for this lane's fetch log")
    args = ap.parse_args()

    present = [v for v in CREDENTIAL_VARS if os.environ.get(v)]
    if present:
        print(f"REFUSED: {','.join(present)} present; this lane fetches unauthenticated only",
              file=sys.stderr)
        return 2

    w6 = json.loads(pathlib.Path(args.harvest).read_text())
    w6_by_url: dict[str, dict] = {}
    for sid, rec in w6["sources"].items():
        for key in ("url_effective", "url_requested"):
            u = rec.get(key)
            if u:
                w6_by_url.setdefault(u, {"w6_source_id": sid, **rec})

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    ids = [g[0] for g in GAPS]
    if len(set(ids)) != len(ids):
        print("REFUSED: duplicate source id", file=sys.stderr)
        return 2

    entries: dict[str, dict] = {}
    for sid, url, why in GAPS:
        rec = fetch(url, outdir / f"{sid}.body", sid in RETRY_DEFAULT_UA)
        rec["why_fetched"] = why
        prior = w6_by_url.get(rec.get("url_effective") or url) or w6_by_url.get(url)
        if prior:
            rec["w6_source_id"] = prior["w6_source_id"]
            rec["w6_sha256"] = prior.get("sha256")
            rec["w6_http_status"] = prior.get("http_status")
            rec["w6_fetched_at_utc"] = prior.get("fetched_at_utc")
            rec["harvest_sha256_match"] = (rec.get("sha256") == prior.get("sha256"))
        else:
            rec["w6_source_id"] = None
            rec["harvest_sha256_match"] = None
        entries[sid] = rec
        flag = {True: "SAME-AS-W6", False: "CHANGED", None: "NEW"}[rec["harvest_sha256_match"]]
        print(f"{rec.get('http_status') or 'ERR':>4}  {sid:<28} {rec.get('bytes', 0):>8}B  {flag}")

    ok = sum(1 for r in entries.values() if r.get("ok"))
    matched = sum(1 for r in entries.values() if r.get("harvest_sha256_match") is True)
    changed = sorted(k for k, r in entries.items() if r.get("harvest_sha256_match") is False)
    log = {
        "artifact_id": "OE-W7-ROUTE-GAP-FETCH-LOG",
        "lane": "OE-W7-CHATGPT-ROUTE-EVIDENCE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "built_at_utc": utcnow(),
        "purpose": (
            "Fetch only the bodies the W6 harvest recorded a hash for but did not "
            "commit. Each body is verified against the W6 sha256 so W6 provenance "
            "carries forward rather than being restated."
        ),
        "reused_harvest": {
            "commit": "2d2b346cd90e4059e26f2d3238f702a582943c32",
            "branch": "cursor/oe-w6-chatgpt-connection-696d",
            "path": "receipts/so02/2026-08-22/oe-w6-chatgpt-connection/raw/doc-fetch-log.json",
            "source_count": w6.get("source_count"),
            "http_200_count": w6.get("http_200_count"),
            "built_at_utc": w6.get("built_at_utc"),
        },
        "credential_used": None,
        "authenticated_requests": 0,
        "source_count": len(entries),
        "http_200_count": ok,
        "verified_identical_to_w6_count": matched,
        "changed_since_w6": changed,
        "non_200": {k: v.get("http_status") for k, v in entries.items() if not v.get("ok")},
        "sources": entries,
    }
    pathlib.Path(args.log).write_text(json.dumps(log, indent=2, sort_keys=True) + "\n")
    print(f"\n{ok}/{len(entries)} at HTTP 200; {matched} byte-identical to the W6 harvest.")
    if changed:
        print(f"CHANGED since W6: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
