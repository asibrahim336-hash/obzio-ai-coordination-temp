#!/usr/bin/env python3
"""Build the interface evidence register from a live documentation fetch ledger.

Every interface and UI claim in AGENTIC-OFFICE-LAUNCH-GUIDE.md must be traceable
to a page that was fetched during this lane, with its URL, HTTP status, byte
length, sha256 and fetch timestamp. Cursor's interface changes; a claim recalled
from memory is not admissible here and this register is what makes that
checkable rather than asserted.

Input is a TSV with header: url, http, bytes, sha256, fetched_at, local.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

# Which guide section each fetched page supports. A page with no mapping is
# still recorded — provenance is kept even when the page did not end up cited.
SUPPORTS = {
    "cursor.com/docs/cloud-agent.md": ["S1", "S2", "S3", "S7"],
    "cursor.com/docs/cloud-agent/setup.md": ["S2", "S6", "S8"],
    "cursor.com/docs/cloud-agent/settings.md": ["S2", "S4", "S6"],
    "cursor.com/docs/cloud-agent/capabilities.md": ["S2", "S3", "S5"],
    "cursor.com/docs/cloud-agent/best-practices.md": ["S3"],
    "cursor.com/docs/cloud-agent/automations.md": ["S1", "S3", "S6", "S7"],
    "cursor.com/docs/cloud-agent/builds.md": ["S6", "S8"],
    "cursor.com/docs/cloud-agent/identity.md": ["S8"],
    "cursor.com/docs/cloud-agent/metadata.md": ["S2"],
    "cursor.com/docs/cloud-agent/mobile.md": ["S2"],
    "cursor.com/docs/cloud-agent/security.md": ["S4"],
    "cursor.com/docs/cloud-agent/security-network.md": ["S2", "S8"],
    "cursor.com/docs/cloud-agent/self-hosted.md": ["S7"],
    "cursor.com/docs/cloud-agent/api/endpoints.md": ["S3", "S6", "S8"],
    "cursor.com/docs/cloud-agent/api/webhooks.md": ["S5"],
    "cursor.com/docs/agent/overview.md": ["S2", "S5"],
    "cursor.com/docs/agent/agents-window.md": ["S1", "S2", "S3"],
    "cursor.com/docs/agent/plan-mode.md": ["S2"],
    "cursor.com/docs/agent/prompting.md": ["S6"],
    "cursor.com/docs/agent/agent-review.md": ["S5"],
    "cursor.com/docs/agent/security.md": ["S4"],
    "cursor.com/docs/agent/security/run-modes.md": ["S4"],
    "cursor.com/docs/agent/tools/browser.md": ["S8"],
    "cursor.com/docs/agent/tools/terminal.md": ["S2"],
    "cursor.com/docs/configuration/worktrees.md": ["S3"],
    "cursor.com/docs/subagents.md": ["S1", "S3", "S7"],
    "cursor.com/docs/skills.md": ["S6"],
    "cursor.com/docs/rules.md": ["S1", "S4"],
    "cursor.com/docs/hooks.md": ["S4", "S5"],
    "cursor.com/docs/mcp.md": ["S2", "S8"],
    "cursor.com/docs/mcp/install-links.md": ["S8"],
    "cursor.com/docs/models-and-pricing.md": ["S2", "S7"],
    "cursor.com/docs/cli/overview.md": ["S3"],
    "cursor.com/docs/cli/headless.md": ["S3"],
    "cursor.com/docs/cli/github-actions.md": ["S5"],
    "cursor.com/docs/integrations/github.md": ["S5"],
    "cursor.com/docs/integrations/slack.md": ["S5", "S8"],
    "cursor.com/docs/integrations/linear.md": ["S5", "S8"],
    "cursor.com/docs/account/teams/dashboard.md": ["S2", "S4"],
    "cursor.com/docs/account/teams/members.md": ["S4"],
    "cursor.com/docs/account/teams/pricing.md": ["S7"],
    "cursor.com/docs/account/pricing/request-based-legacy.md": ["S7"],
    "cursor.com/docs/enterprise/model-and-integration-management.md": ["S8"],
    "cursor.com/help/ai-features/multi-agent": ["S1", "S3"],
    "cursor.com/help/ai-features/cloud-agents": ["S2"],
    "cursor.com/help/ai-features/agent": ["S2"],
    "cursor.com/help/ai-features/agentic-coding": ["S1"],
    "cursor.com/help/models-and-usage/usage-limits": ["S7"],
    "cursor.com/help/models-and-usage/available-models": ["S7"],
    "cursor.com/help/models-and-usage/api-keys": ["S8"],
    "cursor.com/help/models-and-usage/token-rate": ["S7"],
    "cursor.com/help/account-and-billing/pricing": ["S7"],
    "cursor.com/help/account-and-billing/spend-limits": ["S7"],
    "cursor.com/help/account-and-billing/overages": ["S7"],
    "cursor.com/help/account-and-billing/spend-alerts": ["S7"],
    "cursor.com/help/troubleshooting/agent-issues": ["S6"],
    "cursor.com/help/customization/mcp": ["S8"],
    "cursor.com/help/integrations/github-gitlab": ["S5"],
    "cursor.com/pricing": ["S7"],
    "cursor.com/docs-static/cloud-agents-openapi.yaml": ["S3", "S8"],
    "cursor.com/schemas/environment.schema.json": ["S6", "S8"],
}

SECTIONS = {
    "S1": "What the office is",
    "S2": "The current Cursor interface",
    "S3": "Launching at scale",
    "S4": "Roles in the office",
    "S5": "The results contract",
    "S6": "The launch sequence",
    "S7": "Scale and cost reality",
    "S8": "What is not ready yet",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = list(csv.DictReader(pathlib.Path(a.ledger).read_text().splitlines(), delimiter="\t"))
    pages = []
    failures = []
    for r in rows:
        key = r["url"].replace("https://", "")
        entry = {
            "url": r["url"],
            "http_status": int(r["http"]),
            "bytes": int(r["bytes"]),
            "sha256": r["sha256"],
            "fetched_at_utc": r["fetched_at"],
            "supports_sections": SUPPORTS.get(key, []),
        }
        pages.append(entry)
        if entry["http_status"] != 200 or entry["bytes"] == 0:
            failures.append(entry)

    unmapped = [p["url"] for p in pages if not p["supports_sections"]]
    coverage = {s: sorted(p["url"] for p in pages if s in p["supports_sections"]) for s in SECTIONS}

    doc = {
        "record_id": "OE-W5-INTERFACE-EVIDENCE-20260822-v001",
        "lane": "OE-W5-AGENTIC-OFFICE-GUIDE",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "evidence_label": "DOCUMENTED",
        "rule": (
            "Every interface, UI, pricing and platform-behaviour claim in the launch guide is "
            "sourced from one of these pages, fetched live during this lane. No such claim is "
            "recalled from model memory, because Cursor's interface changes and a recalled UI is "
            "an unfalsifiable claim."
        ),
        "fetch_method": "curl -sS -L --max-time 40 --retry 2, one request per URL, body written to disk and hashed",
        "reproduce": "bash workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/refetch_docs.sh",
        "totals": {
            "pages_fetched": len(pages),
            "http_200": sum(1 for p in pages if p["http_status"] == 200),
            "non_200_or_empty": len(failures),
            "pages_not_cited_but_recorded": len(unmapped),
        },
        "guide_sections": SECTIONS,
        "section_coverage": coverage,
        "pages": sorted(pages, key=lambda p: p["url"]),
        "failures": failures,
        "honest_limits": [
            "A documentation page states intended behaviour. It is not a measurement of this account's behaviour. Where the two can diverge, the guide labels the account-specific claim DIRECTLY_REPRODUCED and cites a command instead.",
            "Screens the founder sees are rendered from an authenticated session that no cloud agent holds. Every screen described here is described from its own documentation page, and any step that could not be checked that way is marked in the guide rather than smoothed over.",
        ],
    }
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes), {len(pages)} pages, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
