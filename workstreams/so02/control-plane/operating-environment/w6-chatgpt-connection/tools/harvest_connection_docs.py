#!/usr/bin/env python3
"""Fetch the official documentation this lane's route claims rest on.

Records, per source: final URL after redirects, HTTP status, byte count,
sha256 of the exact body, content type and UTC fetch time. Bodies are written
to disk so a later build step can cut excerpts out of them rather than
paraphrasing from memory.

A non-200 is recorded, not hidden. "This path 404s" is evidence about the
surface and several route conclusions in this lane depend on it.

No credential is read, sent or stored. Every request is unauthenticated.

    python3 harvest_connection_docs.py --out DOCDIR --log LOGFILE
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

# (id, url). Ids are stable handles used by build_route_evidence.py, so
# renaming one breaks the excerpt build loudly rather than silently.
SOURCES: list[tuple[str, str]] = [
    # --- published indexes: the paths below were read out of these, not guessed
    ("index-root", "https://developers.openai.com/llms.txt"),
    ("index-chatgpt", "https://learn.chatgpt.com/llms.txt"),
    ("index-plugins", "https://developers.openai.com/plugins/llms.txt"),
    ("index-workspace-agents", "https://developers.openai.com/workspace-agents/llms.txt"),
    ("index-api", "https://developers.openai.com/api/llms.txt"),

    # --- the ChatGPT surface the founder's account actually is
    ("chatgpt-projects", "https://learn.chatgpt.com/docs/projects.md"),
    ("chatgpt-memories", "https://learn.chatgpt.com/docs/customization/memories.md"),
    ("chatgpt-personalize", "https://learn.chatgpt.com/docs/personalize.md"),
    ("chatgpt-voice", "https://learn.chatgpt.com/docs/features/voice.md"),
    ("chatgpt-automations", "https://learn.chatgpt.com/docs/automations.md"),
    ("chatgpt-notifications", "https://learn.chatgpt.com/docs/notifications.md"),
    ("chatgpt-web", "https://learn.chatgpt.com/docs/web.md"),
    ("chatgpt-app", "https://learn.chatgpt.com/docs/app.md"),
    ("chatgpt-import", "https://learn.chatgpt.com/docs/import.md"),
    ("chatgpt-auth", "https://learn.chatgpt.com/docs/auth.md"),
    ("chatgpt-pricing", "https://learn.chatgpt.com/docs/pricing.md"),
    ("chatgpt-artifacts-viewer", "https://learn.chatgpt.com/docs/artifacts-viewer.md"),

    # --- connectors / plugins: can one reach the repository, and hold write?
    ("chatgpt-plugins", "https://learn.chatgpt.com/docs/plugins.md"),
    ("chatgpt-build-plugins", "https://learn.chatgpt.com/docs/build-plugins.md"),
    ("chatgpt-skills-plugins", "https://learn.chatgpt.com/docs/skills-and-plugins.md"),
    ("chatgpt-build-skills", "https://learn.chatgpt.com/docs/build-skills.md"),
    ("chatgpt-apps-connectors", "https://learn.chatgpt.com/docs/enterprise/apps-and-connectors.md"),
    ("chatgpt-extend-mcp", "https://learn.chatgpt.com/docs/extend/mcp.md"),
    ("plugins-auth", "https://developers.openai.com/plugins/build/auth.md"),
    ("plugins-quickstart", "https://developers.openai.com/plugins/build/app-quickstart.md"),
    ("plugins-submission", "https://developers.openai.com/plugins/deploy/submission.md"),
    ("api-tools-connectors-mcp", "https://developers.openai.com/api/docs/guides/tools-connectors-mcp.md"),

    # --- Codex: the account-resident surface that already reaches repositories
    ("codex-cloud", "https://learn.chatgpt.com/docs/cloud.md"),
    ("codex-cloud-internet", "https://learn.chatgpt.com/docs/cloud/internet-access.md"),
    ("codex-environments-modes", "https://learn.chatgpt.com/docs/environments/modes.md"),
    ("codex-cloud-environment", "https://learn.chatgpt.com/docs/environments/cloud-environment.md"),
    ("codex-github-action", "https://learn.chatgpt.com/docs/github-action.md"),
    ("codex-third-party-github", "https://learn.chatgpt.com/docs/third-party/github.md"),
    ("codex-code-review", "https://learn.chatgpt.com/docs/code-review.md"),
    ("codex-cli", "https://learn.chatgpt.com/docs/codex/cli.md"),
    ("codex-non-interactive", "https://learn.chatgpt.com/docs/non-interactive-mode.md"),
    ("codex-sdk", "https://learn.chatgpt.com/docs/codex-sdk.md"),
    ("codex-mcp-server", "https://learn.chatgpt.com/docs/mcp-server.md"),
    ("codex-agents-md", "https://learn.chatgpt.com/docs/agent-configuration/agents-md.md"),
    ("codex-subagents", "https://learn.chatgpt.com/docs/agent-configuration/subagents.md"),
    ("codex-third-party-slack", "https://learn.chatgpt.com/docs/third-party/slack.md"),
    ("codex-remote", "https://learn.chatgpt.com/docs/remote.md"),
    ("codex-remote-connections", "https://learn.chatgpt.com/docs/remote-connections.md"),
    ("codex-approvals-security", "https://learn.chatgpt.com/docs/agent-approvals-security.md"),
    ("codex-sandboxing", "https://learn.chatgpt.com/docs/sandboxing.md"),
    ("codex-env-vars", "https://learn.chatgpt.com/docs/config-file/environment-variables.md"),
    ("codex-long-running-work", "https://learn.chatgpt.com/docs/long-running-work.md"),
    ("codex-get-started-work", "https://learn.chatgpt.com/docs/get-started-with-work.md"),

    # --- browser and computer control on the ChatGPT side
    ("chatgpt-browser", "https://learn.chatgpt.com/docs/browser.md"),
    ("chatgpt-computer-use", "https://learn.chatgpt.com/docs/computer-use.md"),
    ("chatgpt-chrome-extension", "https://learn.chatgpt.com/docs/chrome-extension.md"),
    ("chatgpt-permission-modes", "https://learn.chatgpt.com/docs/permission-modes.md"),
    ("chatgpt-record-replay", "https://learn.chatgpt.com/docs/extend/record-and-replay.md"),

    # --- admin / read routes over account content
    ("chatgpt-compliance-api", "https://learn.chatgpt.com/docs/enterprise/compliance-api.md"),
    ("chatgpt-analytics-api", "https://learn.chatgpt.com/docs/enterprise/analytics-api.md"),
    ("chatgpt-governance", "https://learn.chatgpt.com/docs/enterprise/governance.md"),
    ("chatgpt-workspace-analytics", "https://learn.chatgpt.com/docs/enterprise/workspace-analytics.md"),
    ("chatgpt-access-tokens", "https://learn.chatgpt.com/docs/enterprise/access-tokens.md"),
    ("chatgpt-service-accounts", "https://learn.chatgpt.com/docs/enterprise/service-accounts.md"),
    ("chatgpt-roles-permissions", "https://learn.chatgpt.com/docs/enterprise/roles-and-workspace-permissions.md"),
    ("chatgpt-administration", "https://learn.chatgpt.com/docs/administration.md"),
    ("chatgpt-security-admin", "https://learn.chatgpt.com/docs/security-administration.md"),
    ("chatgpt-work-overview", "https://learn.chatgpt.com/docs/enterprise/chatgpt-work-overview.md"),
    ("chatgpt-work-admin-faq", "https://learn.chatgpt.com/docs/enterprise/work-admin-faq.md"),
    ("chatgpt-gpts-sharing", "https://learn.chatgpt.com/docs/enterprise/gpts-and-sharing.md"),

    # --- workspace agents: the dispatch route, re-verified live
    ("wa-trigger-runs", "https://developers.openai.com/workspace-agents/trigger-runs.md"),
    ("wa-authentication", "https://developers.openai.com/workspace-agents/authentication.md"),

    # --- the platform API boundary claim, re-verified live
    ("api-conversations-overview", "https://developers.openai.com/api/reference/resources/conversations.md"),
    ("api-conversation-state", "https://developers.openai.com/api/docs/guides/conversation-state.md"),
    ("api-responses-create", "https://developers.openai.com/api/reference/resources/responses/methods/create.md"),
    ("api-your-data", "https://developers.openai.com/api/docs/guides/your-data.md"),
    ("api-webhooks", "https://developers.openai.com/api/docs/guides/webhooks.md"),
    ("api-computer-use", "https://developers.openai.com/api/docs/guides/tools-computer-use.md"),

    # --- data export: the owner's own complete read
    ("openai-export-data", "https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data"),
    ("openai-privacy-portal", "https://privacy.openai.com/policies"),
    ("openai-data-controls-faq", "https://help.openai.com/en/articles/7730893-data-controls-faq"),

    # --- the Cursor side of any return route
    ("cursor-mcp", "https://cursor.com/docs/mcp.md"),
    ("cursor-cloud-agents", "https://cursor.com/docs/cloud-agent.md"),
    ("cursor-api-agents", "https://cursor.com/docs/background-agent/api/overview.md"),
]


def sh(cmd: list[str], timeout: int = 90) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def fetch(url: str, dest: pathlib.Path) -> dict:
    """One unauthenticated GET. Returns provenance, never raises on HTTP error."""
    started = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # -w writes the metadata we need to a separate stream so it cannot
    # contaminate the body whose sha256 we are about to record.
    fmt = "%{http_code}\\n%{url_effective}\\n%{content_type}\\n%{size_download}\\n%{num_redirects}"
    rc, out, err = sh([
        "curl", "-sS", "-L", "--max-time", "60",
        "--retry", "2", "--retry-delay", "2",
        "-A", "obzio-oe-w6-doc-harvest/1.0 (+documentation review; unauthenticated)",
        "-o", str(dest), "-w", fmt, url,
    ])
    rec: dict = {
        "url_requested": url,
        "fetched_at_utc": started,
        "curl_exit": rc,
        "credential_sent": False,
    }
    if rc != 0:
        rec.update({"http_status": None, "error": (err or "").strip()[:400], "ok": False})
        return rec
    parts = (out or "").strip().split("\n")
    while len(parts) < 5:
        parts.append("")
    body = dest.read_bytes() if dest.exists() else b""
    rec.update({
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
    ap.add_argument("--out", required=True, help="directory for fetched bodies")
    ap.add_argument("--log", required=True, help="path for the provenance log")
    args = ap.parse_args()

    # A harvest that quietly used a key would produce evidence this lane is not
    # allowed to produce, so refuse rather than trust the curl invocation.
    for var in ("OPENAI_API_KEY", "CHATGPT_ACCESS_TOKEN", "CURSOR_API_KEY"):
        if os.environ.get(var):
            print(f"REFUSED: {var} is present; this harvest must be unauthenticated", file=sys.stderr)
            return 2

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    ids = [s[0] for s in SOURCES]
    if len(set(ids)) != len(ids):
        print("REFUSED: duplicate source id", file=sys.stderr)
        return 2

    entries: dict[str, dict] = {}
    for sid, url in SOURCES:
        dest = outdir / f"{sid}.body"
        rec = fetch(url, dest)
        entries[sid] = rec
        status = rec.get("http_status")
        print(f"{status if status is not None else 'ERR':>4}  {sid:<32} {rec.get('bytes', 0):>8}B  {url}")

    ok = sum(1 for r in entries.values() if r.get("ok"))
    log = {
        "artifact_id": "OE-W6-CONNECTION-DOC-FETCH-LOG",
        "lane": "OE-W6-CHATGPT-CONNECTION",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "built_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "credential_used": None,
        "authenticated_requests": 0,
        "source_count": len(entries),
        "http_200_count": ok,
        "non_200": {k: v.get("http_status") for k, v in entries.items() if not v.get("ok")},
        "sources": entries,
    }
    pathlib.Path(args.log).write_text(json.dumps(log, indent=2, sort_keys=True) + "\n")
    print(f"\n{ok}/{len(entries)} sources returned HTTP 200. Log: {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
