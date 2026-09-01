#!/usr/bin/env bash
# Capture the runtime facts the browser-control and credential rows depend on.
#
# Credential presence is reported as PRESENT/ABSENT by name. No value is read,
# printed or stored. The point of this file is to establish what this runtime
# can and cannot do on its own, so that a route is not credited to Cursor when
# it actually needs a credential this pod does not hold.
set -u

say() { printf '%s\n' "$*"; }

say "OE-W7-CHATGPT-ROUTE-EVIDENCE — runtime facts, DIRECTLY_REPRODUCED"
say "Lane: OE-W7-CHATGPT-ROUTE-EVIDENCE · Commission: COM-CUR-ENV-01-20260822-v001"
say "Captured: $(date -u +%Y-%m-%dT%H:%M:%SZ) inside the Cursor cloud-agent runtime for this lane."
say ""
say "No credential value is printed anywhere below. Presence is reported as a"
say "yes/no by name only."
say ""
say "--- credential presence (names only, never values) ---"
for v in OPENAI_API_KEY OPENAI_WEBHOOK_SECRET OPENAI_ADMIN_KEY \
         CHATGPT_ACCESS_TOKEN CHATGPT_API_KEY CURSOR_API_KEY \
         OPENAI_TUNNEL_ID GITHUB_TOKEN; do
  if [ -n "${!v:-}" ]; then say "\$$v PRESENT"; else say "\$$v ABSENT"; fi
done
say ""
say "--- every secret configured for this scope (names only) ---"
say "\$CLOUD_AGENT_ALL_SECRET_NAMES      = ${CLOUD_AGENT_ALL_SECRET_NAMES:-<unset>}"
say "\$CLOUD_AGENT_INJECTED_SECRET_NAMES = ${CLOUD_AGENT_INJECTED_SECRET_NAMES:-<unset>}"
say ""
say "--- browser and display: is rendering the constraint? ---"
say "\$ google-chrome --version"
google-chrome --version 2>&1 | head -1
say "\$ echo \"DISPLAY=\$DISPLAY\""
say "DISPLAY=${DISPLAY:-<unset>}"
say "\$ xdpyinfo -display \${DISPLAY} | head -5"
xdpyinfo -display "${DISPLAY:-:1}" 2>&1 | head -5
say ""
say "--- can this runtime reach the two API hosts unauthenticated? ---"
for u in https://api.openai.com/v1/models https://api.chatgpt.com/v1/workspace_agents/x/runs/y; do
  say "\$ curl -s -o /dev/null -w '%{http_code}' $u"
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$u" 2>&1)
  say "$code   (401 = the route exists and is gated; 000 = egress broken; 404 = wrong path)"
done
say ""
say "--- tooling ---"
say "\$ curl --version | head -1"
curl --version 2>&1 | head -1
say "\$ python3 --version"
python3 --version 2>&1
say "\$ git --version"
git --version 2>&1
