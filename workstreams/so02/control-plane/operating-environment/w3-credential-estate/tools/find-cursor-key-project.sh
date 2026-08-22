#!/usr/bin/env bash
# find-cursor-key-project.sh — OE-W3-CREDENTIAL-ESTATE
#
# Answers one question: WHICH Supabase project holds the existing Cursor API
# key in its Edge Function secrets?
#
# This is a locator, not a retriever. It prints secret NAMES and a digest of
# each value. It never prints a secret value, and it is written so that it
# cannot: values are hashed the moment they are parsed and the parsed
# structure is discarded.
#
# Requires a Supabase personal access token in SUPABASE_ACCESS_TOKEN. If the
# founder prefers not to mint one, this script is unnecessary — he can read the
# project name directly from the Supabase dashboard, which is the recommended
# route (see CURSOR-API-KEY-RECOVERY-ROUTES.json, route R4). This script exists
# for the case where the key's location is genuinely unknown and enumeration
# across many projects is faster than clicking through them.
#
# Usage:
#   SUPABASE_ACCESS_TOKEN=... ./find-cursor-key-project.sh
#   SUPABASE_ACCESS_TOKEN=... ./find-cursor-key-project.sh 'cursor|anthropic'

set -uo pipefail

PATTERN="${1:-cursor}"
API="https://api.supabase.com"

if [ -z "${SUPABASE_ACCESS_TOKEN:-}" ]; then
  echo "SUPABASE_ACCESS_TOKEN is not set."
  echo "Baseline for comparison: an unauthenticated GET ${API}/v1/projects returns HTTP 401."
  exit 2
fi

# Header on stdin, exactly as in verify-cursor-api-key.sh: the token never
# enters an argument vector.
sb_get() {
  printf 'Authorization: Bearer %s' "${SUPABASE_ACCESS_TOKEN}" \
    | curl -s --max-time 30 -H @- "${API}$1"
}

echo "find-cursor-key-project: matching secret names against /${PATTERN}/i"

PROJECTS_JSON=$(sb_get /v1/projects)
export PROJECTS_JSON PATTERN

python3 - <<'PY'
import json, os, subprocess, hashlib, sys

pattern = os.environ["PATTERN"].lower()
try:
    projects = json.loads(os.environ["PROJECTS_JSON"])
except Exception:
    print("  could not parse /v1/projects — check the token and retry")
    sys.exit(1)
if isinstance(projects, dict):
    print(f"  /v1/projects returned an error object: {projects.get('message', 'unknown')}")
    sys.exit(1)

print(f"  projects visible to this token: {len(projects)}")
token = os.environ["SUPABASE_ACCESS_TOKEN"]
import re
found_any = False

for p in projects:
    ref, name = p.get("id"), p.get("name")
    status = p.get("status")
    # Redact the ref the same way the register does: it identifies a project,
    # and there is no reason to widen its exposure in a shared receipt.
    ref_r = (ref[:2] + "*" * max(0, len(ref) - 4) + ref[-2:]) if ref and len(ref) > 4 else "<short>"
    r = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-H", "@-",
         f"https://api.supabase.com/v1/projects/{ref}/secrets"],
        input=f"Authorization: Bearer {token}", capture_output=True, text=True,
    )
    try:
        secrets = json.loads(r.stdout)
    except Exception:
        print(f"  project {ref_r} ({name}, {status}): secrets unreadable")
        continue
    if isinstance(secrets, dict):
        print(f"  project {ref_r} ({name}, {status}): {secrets.get('message', 'error')}")
        continue

    names = [s.get("name", "") for s in secrets]
    matches = [n for n in names if re.search(pattern, n, re.I)]
    print(f"  project {ref_r} ({name}, {status}): {len(names)} secret(s); "
          f"{len(matches)} matching /{pattern}/i")
    for s in secrets:
        n = s.get("name", "")
        if not re.search(pattern, n, re.I):
            continue
        found_any = True
        v = s.get("value") or ""
        # Hash immediately. The value is never printed and never stored.
        dg = hashlib.sha256(v.encode()).hexdigest()
        print(f"      MATCH name={n} value_len={len(v)} value_sha256={dg} "
              f"updated_at={s.get('updated_at')}")

if not found_any:
    print(f"  no secret name matched /{pattern}/i in any visible project")
else:
    print("  Compare value_sha256 above with key_sha256 from verify-cursor-api-key.sh")
    print("  to confirm the key mirrored into Cursor is the same key, with no disclosure.")
PY
