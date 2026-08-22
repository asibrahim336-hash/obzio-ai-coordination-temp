#!/usr/bin/env bash
# Runs at the start of every agent run, including runs that boot from a stale
# Build where the install phase is skipped. Everything an agent needs on every
# boot belongs here, not in install.
#
# Must be idempotent, must tolerate restarts, must not hang, and must reach a
# clear success or failure. A non-zero exit prevents a successful start.
set -euo pipefail

echo ">>> obzio start: begin"

RUN_DIR=".cursor/.run"
mkdir -p "$RUN_DIR"

# 1. Record the runtime binding for this boot from the local metadata service.
#    This requires no credential and no MCP call, so it is available to every
#    later step and to the hooks. Failure here must not prevent the start.
SOCK="${CURSOR_AGENT_SOCKET:-/run/cursor/api.sock}"
meta() {
  curl -s --max-time 5 --unix-socket "$SOCK" "http://localhost/v1/meta-data/$1" 2>/dev/null || true
}
if [ -S "$SOCK" ]; then
  cat > "$RUN_DIR/runtime-binding.json" <<EOF
{
  "recorded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "agent_id": "$(meta agent/id)",
  "agent_runtime": "$(meta agent/runtime)",
  "agent_source": "$(meta agent/source)",
  "turn_id": "$(meta turn/id)",
  "turn_model": "$(meta turn/model)",
  "owner_team_id": "$(meta owner/team-id)",
  "run_branch_name": "$(meta workspace/branch-name)",
  "checked_out_branch": "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)",
  "checked_out_sha": "$(git rev-parse HEAD 2>/dev/null || echo unknown)",
  "environment_id": "$(meta workspace/environment-id)"
}
EOF
  echo "start: recorded runtime binding for turn $(meta turn/id)"
else
  echo "start: agent metadata socket absent; runtime binding not recorded" >&2
fi

# 2. Record which named secrets are present, by NAME only. This is the
#    non-disclosing instrument that lets an agent verify an activation without
#    ever reading a value.
cat > "$RUN_DIR/secret-names.json" <<EOF
{
  "recorded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "all_secret_names": "${CLOUD_AGENT_ALL_SECRET_NAMES:-}",
  "injected_secret_names": "${CLOUD_AGENT_INJECTED_SECRET_NAMES:-}"
}
EOF

# 3. Ensure the validation dependency exists even when install was skipped
#    because the pod booted from a stale Build.
python3 -c "import jsonschema" 2>/dev/null || \
  python3 -m pip install --quiet --user --disable-pip-version-check jsonschema==4.26.0 || \
  echo "start: jsonschema unavailable; schema validation will be skipped" >&2

# 4. Report currentness once, loudly, at boot. Do not fail the start on it:
#    a currentness break must block promotion, not the running programme.
if python3 scripts/check_operator_taxonomy.py; then
  echo "start: operator taxonomy currentness PASS"
else
  echo "start: WARNING operator taxonomy currentness FAILED at boot" >&2
fi

echo ">>> obzio start: complete"
