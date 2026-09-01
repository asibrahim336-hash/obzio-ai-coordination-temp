#!/usr/bin/env bash
# Harvest live Cursor documentation for lane OE-W5. Records URL, HTTP status,
# byte size, sha256 and fetch timestamp so every UI/interface claim in the guide
# is DOCUMENTED from a live fetch rather than recalled.
set -u
OUT=/tmp/w5fetch/pages
mkdir -p "$OUT"
LEDGER=/tmp/w5fetch/fetch-ledger.tsv
: > "$LEDGER"
printf 'url\thttp\tbytes\tsha256\tfetched_at\tlocal\n' >> "$LEDGER"

urls=(
  "https://cursor.com/docs/cloud-agent.md"
  "https://cursor.com/docs/cloud-agent/setup.md"
  "https://cursor.com/docs/cloud-agent/capabilities.md"
  "https://cursor.com/docs/cloud-agent/settings.md"
  "https://cursor.com/docs/cloud-agent/best-practices.md"
  "https://cursor.com/docs/cloud-agent/automations.md"
  "https://cursor.com/docs/cloud-agent/builds.md"
  "https://cursor.com/docs/cloud-agent/identity.md"
  "https://cursor.com/docs/cloud-agent/metadata.md"
  "https://cursor.com/docs/cloud-agent/mobile.md"
  "https://cursor.com/docs/cloud-agent/security.md"
  "https://cursor.com/docs/cloud-agent/security-network.md"
  "https://cursor.com/docs/cloud-agent/self-hosted.md"
  "https://cursor.com/docs/cloud-agent/api/endpoints.md"
  "https://cursor.com/docs/cloud-agent/api/webhooks.md"
  "https://cursor.com/docs/agent/overview.md"
  "https://cursor.com/docs/agent/agents-window.md"
  "https://cursor.com/docs/agent/plan-mode.md"
  "https://cursor.com/docs/agent/prompting.md"
  "https://cursor.com/docs/agent/agent-review.md"
  "https://cursor.com/docs/agent/security.md"
  "https://cursor.com/docs/agent/security/run-modes.md"
  "https://cursor.com/docs/agent/tools/browser.md"
  "https://cursor.com/docs/agent/tools/terminal.md"
  "https://cursor.com/docs/configuration/worktrees.md"
  "https://cursor.com/docs/subagents.md"
  "https://cursor.com/docs/skills.md"
  "https://cursor.com/docs/rules.md"
  "https://cursor.com/docs/hooks.md"
  "https://cursor.com/docs/mcp.md"
  "https://cursor.com/docs/mcp/install-links.md"
  "https://cursor.com/docs/models-and-pricing.md"
  "https://cursor.com/docs/cli/overview.md"
  "https://cursor.com/docs/cli/headless.md"
  "https://cursor.com/docs/cli/github-actions.md"
  "https://cursor.com/docs/integrations/github.md"
  "https://cursor.com/docs/integrations/slack.md"
  "https://cursor.com/docs/integrations/linear.md"
  "https://cursor.com/docs/account/teams/dashboard.md"
  "https://cursor.com/docs/account/teams/members.md"
  "https://cursor.com/docs/account/teams/pricing.md"
  "https://cursor.com/docs/account/pricing/request-based-legacy.md"
  "https://cursor.com/docs/enterprise/model-and-integration-management.md"
  "https://cursor.com/help/ai-features/multi-agent"
  "https://cursor.com/help/ai-features/cloud-agents"
  "https://cursor.com/help/ai-features/agent"
  "https://cursor.com/help/ai-features/agentic-coding"
  "https://cursor.com/help/models-and-usage/usage-limits"
  "https://cursor.com/help/models-and-usage/available-models"
  "https://cursor.com/help/models-and-usage/api-keys"
  "https://cursor.com/help/models-and-usage/token-rate"
  "https://cursor.com/help/account-and-billing/pricing"
  "https://cursor.com/help/account-and-billing/spend-limits"
  "https://cursor.com/help/account-and-billing/overages"
  "https://cursor.com/help/account-and-billing/spend-alerts"
  "https://cursor.com/help/troubleshooting/agent-issues"
  "https://cursor.com/help/customization/mcp"
  "https://cursor.com/help/integrations/github-gitlab"
  "https://cursor.com/pricing"
  "https://cursor.com/docs-static/cloud-agents-openapi.yaml"
  "https://cursor.com/schemas/environment.schema.json"
)

for u in "${urls[@]}"; do
  slug=$(printf '%s' "$u" | sed -E 's#^https://##; s#[/?=&]#_#g')
  f="$OUT/$slug"
  code=$(curl -sS -L --max-time 40 --retry 2 --retry-delay 2 -o "$f" -w '%{http_code}' "$u" 2>/dev/null)
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [ -f "$f" ]; then
    b=$(stat -c%s "$f"); h=$(sha256sum "$f" | cut -d' ' -f1)
  else
    b=0; h=NONE
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$u" "$code" "$b" "$h" "$ts" "$slug" >> "$LEDGER"
  printf '%-70s %s %8s\n' "$u" "$code" "$b"
done
echo "HARVEST_COMPLETE $(wc -l < "$LEDGER") ledger rows"
