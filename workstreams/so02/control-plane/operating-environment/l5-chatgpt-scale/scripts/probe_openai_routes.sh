#!/usr/bin/env bash
# Probe the OpenAI and ChatGPT API routes WITHOUT any credential.
#
# Purpose: distinguish "route does not exist" from "route exists and is
# credential-blocked". A 401 proves reachability and gating; a 404 or a DNS
# failure would prove something else entirely. This lane's claim that the
# OpenAI route is credential-blocked rather than unsupported rests on the
# output of this script.
#
# This script deliberately sends NO Authorization header. It reads no secret,
# writes no secret, and cannot leak one. Run it before activation to establish
# the baseline, and after revocation to prove the credential is really gone.
#
# Usage:
#   bash probe_openai_routes.sh                 # human-readable to stdout
#   bash probe_openai_routes.sh > receipt.txt   # capture as evidence

set -u

ROUTES=(
  "GET  https://api.openai.com/v1/models"
  "GET  https://api.openai.com/v1/conversations/conv_probe_nonexistent"
  "GET  https://api.openai.com/v1/responses/resp_probe_nonexistent"
  "GET  https://api.openai.com/v1/batches"
  "GET  https://api.chatgpt.com/v1/workspace_agents/agtch_probe/runs/apirun_probe"
)

echo "=== UNAUTHENTICATED OPENAI ROUTE PROBE ==="
echo "-- run at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "-- credential sent: NONE (no Authorization header is set by this script)"
echo "-- OPENAI_API_KEY present in this environment: $([ -n "${OPENAI_API_KEY:-}" ] && echo yes || echo no)"
echo

body="$(mktemp)"
trap 'rm -f "$body"' EXIT

for entry in "${ROUTES[@]}"; do
  method="${entry%% *}"
  url="${entry##* }"
  echo "--- ${method} ${url}"
  code="$(curl -sS -X "${method}" -o "${body}" \
            -w '%{http_code}' --max-time 20 "${url}" 2>/dev/null)"
  echo "    http_status: ${code}"
  # Truncated so an unexpectedly large body cannot flood the receipt.
  echo "    body: $(head -c 400 "${body}" | tr -d '\n')"
  echo
done

echo "=== INTERPRETATION ==="
echo "401  -> route exists, is reachable, and is gated on a credential."
echo "404  -> route does not exist at that path; the path claim is wrong."
echo "000  -> network or DNS failure; egress is the problem, not the credential."
