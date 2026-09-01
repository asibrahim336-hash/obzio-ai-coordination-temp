#!/usr/bin/env bash
# Re-run every DIRECTLY_REPRODUCED probe this lane relies on, into receipts/raw.
# No secret value is ever printed: secrets appear by name and set/unset only.
# Usage: bash tools/capture_run_evidence.sh <repo-root>
set -u
ROOT="${1:-$(git rev-parse --show-toplevel)}"
RAW="$ROOT/receipts/so02/2026-08-22/oe-w5-agentic-office/raw"
mkdir -p "$RAW"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

{
  echo "# OE-W5 run evidence — captured $(ts)"
  echo "# Every line below is command output produced in this runtime."
  echo
  echo "## P1  Cursor Agent API surface: 401 means gated, 404 means absent"
  for p in /v1/me /v1/agents /v1/models /v1/repositories /v1/nonexistent-route-oew5; do
    printf '%-34s ' "GET https://api.cursor.com$p"
    curl -sS --max-time 20 -o /tmp/.oew5resp -w '%{http_code} ' "https://api.cursor.com$p" 2>&1
    head -c 160 /tmp/.oew5resp; echo
  done
  rm -f /tmp/.oew5resp
  echo
  echo "## P2  Secret-name census (names only, never values)"
  echo "CLOUD_AGENT_ALL_SECRET_NAMES ->"
  echo "${CLOUD_AGENT_ALL_SECRET_NAMES:-<unset>}" | tr ',' '\n' | sed '/^$/d' | sort | sed 's/^/    /'
  echo "CURSOR_API_KEY present? ->"
  if echo "${CLOUD_AGENT_ALL_SECRET_NAMES:-}" | tr ',' '\n' | grep -qx CURSOR_API_KEY; then
    echo "    PRESENT"
  else
    echo "    ABSENT"
  fi
  echo
  echo "## P3  Store scope: does a subagent get its own store, or its parent's?"
  ls -la /cursor/stores/ 2>&1 | sed 's/^/    /'
  echo "    self resolves to: $(readlink -f /cursor/stores/self 2>&1)"
  echo
  echo "## P4  VM sharing: sibling lane worktrees visible from this lane"
  echo "    hostname: $(hostname)"
  echo "    uptime:   $(uptime)"
  ls -d /tmp/oe-* 2>/dev/null | sed 's/^/    /'
  echo
  echo "## P5  Shared-checkout hazard: HEAD state of the shared /workspace checkout"
  echo "    /workspace HEAD  -> $(git -C /workspace rev-parse --abbrev-ref HEAD 2>&1)"
  echo "    this worktree    -> $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>&1)"
  echo
  echo "## P6  Agent metadata socket"
  echo "    socket: $(ls -la /run/cursor/api.sock 2>&1)"
  echo "    GET /v1/meta-data/ ->"
  curl -sS --max-time 10 --unix-socket /run/cursor/api.sock http://localhost/v1/meta-data/ 2>&1 | sed 's/^/        /'
  echo
  echo "## P7  Role-partition constitution still holds"
  ( cd "$ROOT/workstreams/so02/control-plane/operating-environment/w4-platform-roles" \
    && python3 tools/rolectl.py check 2>&1 | sed 's/^/    /' \
    && python3 tools/negative_tests.py 2>&1 | tail -2 | sed 's/^/    /' )
  echo
  echo "# end $(ts)"
} > "$RAW/run-evidence.txt" 2>&1

echo "wrote $RAW/run-evidence.txt ($(wc -c < "$RAW/run-evidence.txt") bytes)"
