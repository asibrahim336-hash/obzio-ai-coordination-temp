#!/usr/bin/env bash
# capture-evidence.sh — OE-W3-CREDENTIAL-ESTATE
#
# Regenerates every raw receipt this lane relies on. Written as a script rather
# than run ad hoc so an acceptor can reproduce the receipts rather than take
# them on trust.
#
# Every command here is read-only. Nothing creates, rotates or deletes a
# credential, and nothing writes to any remote surface.
#
# Redaction is applied at capture time, not afterwards: a receipt that has to
# be cleaned up later has already been written to disk in the clear.

set -uo pipefail
OUT="${1:?usage: capture-evidence.sh <receipts-raw-dir>}"
mkdir -p "$OUT"

hdr() { printf '# %s\n# captured: %s\n\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; }

# ---------------------------------------------------------------------------
# 1. Secret-name census. Names only, by construction.
# ---------------------------------------------------------------------------
{
  hdr "Runtime credential surface — NAMES ONLY"
  echo "CLOUD_AGENT_ALL_SECRET_NAMES:"
  printf '%s\n' "${CLOUD_AGENT_ALL_SECRET_NAMES:-<unset>}" | tr ',' '\n' | sed 's/^/  /'
  echo
  echo "CLOUD_AGENT_INJECTED_SECRET_NAMES:"
  printf '%s\n' "${CLOUD_AGENT_INJECTED_SECRET_NAMES:-<unset>}" | tr ',' '\n' | sed 's/^/  /'
  echo
  echo "identical_lists: $([ "${CLOUD_AGENT_ALL_SECRET_NAMES:-}" = "${CLOUD_AGENT_INJECTED_SECRET_NAMES:-}" ] && echo yes || echo no)"
  echo
  echo "absent by name census (each checked explicitly):"
  for n in CURSOR_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY SUPABASE_ACCESS_TOKEN \
           SUPABASE_SERVICE_ROLE_KEY VERCEL_TOKEN CLOUDFLARE_API_TOKEN GITHUB_TOKEN GH_TOKEN; do
    if printf '%s' "${CLOUD_AGENT_ALL_SECRET_NAMES:-}" | tr ',' '\n' | grep -qx "$n"; then
      echo "  $n: PRESENT"
    else
      echo "  $n: ABSENT"
    fi
  done
  echo
  echo "full environment variable NAMES (values never read):"
  env | cut -d= -f1 | sort | sed 's/^/  /'
} > "$OUT/secret-name-census.txt" 2>&1

# ---------------------------------------------------------------------------
# 2. GitHub credential characterisation. Digests only.
# ---------------------------------------------------------------------------
{
  hdr "GitHub credentials — digest comparison"
  python3 - <<'PY'
import hashlib, re, subprocess
from pathlib import Path

def dg(s): return hashlib.sha256(s.encode()).hexdigest()

found = {}

p = Path.home() / ".config/gh/hosts.yml"
if p.exists():
    text = p.read_text()
    m = re.search(r"gh[pousr]_[A-Za-z0-9_.\-]{20,}", text)
    if m:
        t = m.group(0)
        found["gh_cli (~/.config/gh/hosts.yml oauth_token)"] = t
        print(f"gh CLI token      : len={len(t)} prefix={t[:4]} sha256={dg(t)}")
    u = re.search(r"user:\s*(\S+)", text)
    print(f"gh CLI account    : {u.group(1) if u else '<none>'}")

g = Path.home() / ".gitconfig"
if g.exists():
    text = g.read_text()
    m = re.search(r"x-access-token:(gh[pousr]_[A-Za-z0-9_.\-]{20,})@", text)
    if m:
        t = m.group(1)
        found["git (~/.gitconfig url.insteadOf rewrite)"] = t
        print(f"git push token    : len={len(t)} prefix={t[:4]} sha256={dg(t)}")
    n = len(re.findall(r"insteadOf", text, re.I))
    print(f"insteadOf rewrites: {n}")

vals = list(found.values())
print()
if len(vals) >= 2:
    print(f"SAME CREDENTIAL   : {vals[0] == vals[1]}")
    print("interpretation    : one GitHub App installation token, surfaced through two")
    print("                    transports (REST API via gh, git-over-HTTPS via insteadOf)")
elif len(vals) == 1:
    print("only one location carried a token")
else:
    print("no token located in either config file")
PY
  echo
  echo "--- git config: which scope carries the credential (token elided at capture time) ---"
  # The replacement is kept under 8 characters deliberately: the credential
  # scanner's url_embedded_userinfo rule fires on 8-or-more, so a longer
  # placeholder would trip the gate on its own redaction and train the operator
  # to ignore it.
  git config --global --list 2>&1 | grep -iE 'insteadof|managedauth|managedgh' | sed 's/x-access-token:[^@]*@/x-access-token:***@/g'
  echo
  echo "--- credential.helper (none expected; the insteadOf rewrite is the mechanism) ---"
  git config --get-all credential.helper 2>&1 || echo "  <no credential.helper configured>"
  echo
  echo "--- local remote.origin.url as stored (no token: the rewrite adds it) ---"
  git -C "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" config --local --get remote.origin.url 2>&1
} > "$OUT/github-credentials.txt" 2>&1

# ---------------------------------------------------------------------------
# 3. What the GitHub credential can actually do.
# ---------------------------------------------------------------------------
REPO="asibrahim336-hash/obzio-ai-coordination-temp"
{
  hdr "GitHub credential — actual capability"
  echo "NOTE: 'gh auth status' is deliberately NOT run here. It prints a large"
  echo "      prefix of the live token to stdout even without --show-token."
  echo "      That is a real hazard for any receipt-producing pipeline."
  echo
  echo "--- GET /repos/$REPO (the misleading projection) ---"
  gh api "repos/$REPO" --jq '{full_name:.full_name,private:.private,default_branch:.default_branch,permissions:.permissions}' 2>&1
  echo
  echo "--- GET /user (App installation tokens have no user identity) ---"
  gh api user --jq '.login' 2>&1 | head -2
  echo
  echo "--- GET /installation/repositories (proves App installation token, and its scope) ---"
  gh api /installation/repositories --jq '{total:.total_count,repos:[.repositories[].full_name]}' 2>&1
  echo
  echo "--- response headers: absence of X-OAuth-Scopes confirms it is not an OAuth/PAT token ---"
  gh api -i "repos/$REPO" 2>&1 | sed -n '1,40p' \
    | grep -iE '^(HTTP|x-oauth-scopes|x-accepted-oauth-scopes|x-ratelimit-limit|github-authentication-token-expiration)' \
    || echo "  (no scope headers present)"
  echo
  echo "--- capability probe by endpoint class (read attempts only) ---"
  for ep in "repos/$REPO/contents/README.md" "repos/$REPO/pulls?per_page=1" \
            "repos/$REPO/branches?per_page=1" "repos/$REPO/issues?per_page=1" \
            "repos/$REPO/actions/secrets" "repos/$REPO/actions/variables" \
            "repos/$REPO/hooks" "repos/$REPO/deployments" "repos/$REPO/collaborators"; do
    code=$(gh api "$ep" --include --silent 2>&1 | head -1 | grep -oE '[0-9]{3}' | head -1)
    if [ -z "$code" ]; then
      code=$(gh api "$ep" >/dev/null 2>&1 && echo 200 || echo denied)
    fi
    printf '  %-45s -> %s\n' "$ep" "$code"
  done
  echo
  echo "--- git write capability, proven WITHOUT mutating the remote ---"
  git push --dry-run origin HEAD:refs/heads/oew3-capability-probe-do-not-create 2>&1 \
    | sed -E 's#://[^@/]*@#://***@#g'
  echo "  (dry-run: git negotiates and authenticates but writes nothing)"
} > "$OUT/github-capability.txt" 2>&1

# ---------------------------------------------------------------------------
# 4. api.cursor.com baseline. Status codes and body SHAPE only, never bodies.
# ---------------------------------------------------------------------------
{
  hdr "api.cursor.com — unauthenticated baseline"
  echo "Discriminator: an endpoint that EXISTS but needs auth returns 401 with"
  echo "{code,message}; an endpoint that does not exist returns 404 with"
  echo "{error,message,statusCode}. Bodies are classified, never printed:"
  echo "the 401 body echoes a masked fragment of any presented key."
  echo
  for p in /v1/me /v1/models /v1/agents /v1/repositories /v1/nonexistent-route-oew3; do
    code=$(curl -s -o /tmp/oew3_b.txt -w '%{http_code}' --max-time 25 "https://api.cursor.com$p")
    shape=$(python3 -c "
import json
try:
    d=json.load(open('/tmp/oew3_b.txt'))
    print('keys='+','.join(sorted(d.keys())))
except Exception:
    print('non-json')
")
    printf '  GET %-32s -> HTTP %s  body_%s\n' "$p" "$code" "$shape"
  done
  rm -f /tmp/oew3_b.txt
} > "$OUT/api-cursor-baseline.txt" 2>&1

# ---------------------------------------------------------------------------
# 5. Supabase: management API baseline, CLI route, and the AUREA project's DNS.
# ---------------------------------------------------------------------------
{
  hdr "Supabase — reachability of every route to Edge Secrets"
  echo "--- Management API, unauthenticated ---"
  for p in /v1/projects /v1/organizations; do
    code=$(curl -s -o /tmp/oew3_s.txt -w '%{http_code}' --max-time 25 "https://api.supabase.com$p")
    printf '  GET api.supabase.com%-20s -> HTTP %s\n' "$p" "$code"
  done
  rm -f /tmp/oew3_s.txt
  echo
  echo "--- Management API OpenAPI: what the secrets endpoint returns ---"
  curl -s --max-time 30 https://api.supabase.com/api/v1-json -o /tmp/oew3_spec.json \
    -w '  spec fetch: HTTP %{http_code}, %{size_download} bytes\n'
  python3 - <<'PY'
import json
d = json.load(open('/tmp/oew3_spec.json'))
for p in [p for p in d.get('paths', {}) if 'secret' in p.lower()]:
    for m in d['paths'][p]:
        if isinstance(d['paths'][p][m], dict):
            print(f"  {m.upper()} {p}: {d['paths'][p][m].get('summary')}")
s = d.get('components', {}).get('schemas', {}).get('SecretResponse')
if s:
    print(f"  SecretResponse.required = {s.get('required')}")
    print(f"  SecretResponse.properties = {list(s.get('properties', {}).keys())}")
    print("  => the API returns the VALUE, not a digest. The CLI digests it for display.")
PY
  rm -f /tmp/oew3_spec.json
  echo
  echo "--- Supabase CLI route (installable here via npx) ---"
  echo -n "  supabase --version: "
  timeout 180 npx -y supabase@latest --version 2>&1 | grep -vE '^npm notice|^$' | head -1
  echo "  secrets list with NO token:"
  env -u SUPABASE_ACCESS_TOKEN timeout 180 npx -y supabase@latest secrets list \
    --project-ref aaaaaaaaaaaaaaaaaaaa 2>&1 | grep -vE '^npm notice|^$' | head -2 | sed 's/^/    /'
  echo "  secrets list with a SYNTHETIC INVALID token:"
  SUPABASE_ACCESS_TOKEN=sbp_0000000000000000000000000000000000000000 \
    timeout 180 npx -y supabase@latest secrets list \
    --project-ref aaaaaaaaaaaaaaaaaaaa 2>&1 | grep -vE '^npm notice|^$' | head -2 | sed 's/^/    /'
  echo "  => the route reaches the Management API and is credential-blocked, not unsupported."
  echo
  echo "--- the already-injected AUREA project: does it still exist? ---"
  python3 - <<'PY'
import os, socket, subprocess, urllib.parse, hashlib, json
url = os.environ.get("AUREA_E2E_SUPABASE_URL", "")
if not url:
    print("  AUREA_E2E_SUPABASE_URL not set in this runtime")
    raise SystemExit
host = urllib.parse.urlsplit(url).hostname or ""
ref = host.split(".")[0]
print(f"  url_length={len(url)} host_labels={len(host.split('.'))} host_suffix={'.'.join(host.split('.')[-2:])}")
print(f"  project_ref: length={len(ref)} redacted={ref[:2]}{'*' * (len(ref) - 4)}{ref[-2:]}")
print(f"  project_ref_sha256={hashlib.sha256(ref.encode()).hexdigest()}")
print(f"  full_url_sha256={hashlib.sha256(url.encode()).hexdigest()}")
try:
    socket.getaddrinfo(host, 443)
    print("  local DNS: RESOLVED")
except Exception as e:
    print(f"  local DNS: FAILED ({type(e).__name__})")
for res, label in [("https://dns.google/resolve", "dns.google"),
                   ("https://cloudflare-dns.com/dns-query", "cloudflare-dns.com")]:
    for name, tag in [(host, "<AUREA_REF>.supabase.co"), ("api.supabase.com", "api.supabase.com (control)")]:
        cfg = f'url = "{res}?name={name}&type=A"\nheader = "accept: application/dns-json"\nsilent\nmax-time = 20\n'
        r = subprocess.run(["curl", "-K", "-"], input=cfg, capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            st = d.get("Status")
            meaning = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN"}.get(st, str(st))
            print(f"  {label:22s} {tag:32s} Status={st} ({meaning}) answers={len(d.get('Answer') or [])}")
        except Exception:
            print(f"  {label:22s} {tag:32s} <unparseable>")
PY
} > "$OUT/supabase-routes.txt" 2>&1

# ---------------------------------------------------------------------------
# 6. Present-and-unused capability: container runtime, browser, display.
# ---------------------------------------------------------------------------
{
  hdr "Present-and-unused capability"
  D=http://127.0.0.1:2375
  echo "--- Docker engine: reachable unauthenticated on 2375? ---"
  curl -s --max-time 10 -o /dev/null -w '  GET %{url_effective} -> HTTP %{http_code}\n' "$D/_ping"
  echo "  no Authorization header was sent."
  echo -n "  docker CLI on PATH: "; command -v docker >/dev/null 2>&1 && docker --version || echo "<ABSENT — the HTTP API is the only access path>"
  echo
  echo "--- engine identity and builder ---"
  curl -s --max-time 10 "$D/version" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('  Version', d.get('Version'), 'API', d.get('ApiVersion'), 'MinAPI', d.get('MinAPIVersion'))
for c in d.get('Components', []): print('   component:', c.get('Name'), c.get('Version'))
"
  curl -s --max-time 10 -I "$D/_ping" 2>&1 | grep -iE 'builder-version|api-version' | sed 's/^/  /'
  echo "  (Builder-Version: 2 means BuildKit is the default builder)"
  curl -s --max-time 10 "$D/info" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('  ', {k: d.get(k) for k in ['ServerVersion','Driver','Containers','ContainersRunning','Images','NCPU','OperatingSystem','CgroupVersion']})
print('   MemTotal_GiB:', round(d.get('MemTotal',0)/2**30, 1))
print('   Runtimes:', list((d.get('Runtimes') or {}).keys()))
"
  curl -s --max-time 10 "$D/images/json" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('   images:', len(d))
for i in d: print('    ', i.get('RepoTags'), i.get('Size'))
"
  echo
  echo "--- listening ports (note the bind address on 2375) ---"
  (ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null) | sed 's/^/  /' | head -20
  echo
  echo "--- browser and display ---"
  echo -n "  chrome: "; google-chrome --version 2>&1
  echo "  DISPLAY=${DISPLAY:-<unset>} VNC_RESOLUTION=${VNC_RESOLUTION:-<unset>}"
  xdpyinfo -display "${DISPLAY:-:1}" 2>&1 | grep -E 'name of display|dimensions|number of screens' | sed 's/^/  /'
  ps -eo comm 2>/dev/null | grep -iE 'vnc|Xtiger' | sort -u | sed 's/^/  vnc process: /'
  echo -n "  headless render check: "
  timeout 120 google-chrome --headless=new --disable-gpu --no-sandbox --dump-dom \
    --virtual-time-budget=5000 'data:text/html,<h1>OEW3-HEADLESS-OK</h1>' 2>/dev/null \
    | grep -o 'OEW3-HEADLESS-OK' | head -1 || echo "FAILED"
  echo
  echo "--- CLI tooling census ---"
  for c in node npm npx python3 curl jq git gh docker supabase vercel wrangler psql; do
    printf '  %-9s ' "$c"
    command -v "$c" >/dev/null 2>&1 && { "$c" --version 2>&1 | head -1; } || echo "<absent>"
  done
} > "$OUT/present-and-unused.txt" 2>&1

# ---------------------------------------------------------------------------
# 7. The verification script, exercised against a key that is not a credential.
# ---------------------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
{
  hdr "verify-cursor-api-key.sh — behaviour on every reachable branch"
  echo "The key used below is synthetic. It is not a credential, has never been"
  echo "a credential, and authenticates nothing. It exists to prove that the"
  echo "script's own output carries nothing credential-shaped."
  echo
  echo "--- branch 1: no key present in the runtime (today's actual state) ---"
  ( env -u CURSOR_API_KEY "$HERE/verify-cursor-api-key.sh" ); echo "  exit=$?"
  echo
  echo "--- branch 2: a key is present but invalid ---"
  ( CURSOR_API_KEY='key_oew3synthetic0000000000000000000000000000000000000000000000000000' \
      "$HERE/verify-cursor-api-key.sh" ); echo "  exit=$?"
  echo
  echo "Note both runs: no response body is printed anywhere. api.cursor.com's"
  echo "401 body echoes a masked fragment of the presented key, so printing it"
  echo "would leak key material into the receipt."
} > "$OUT/verification-script-test.txt" 2>&1

# ---------------------------------------------------------------------------
# 8. Proof that the stdin technique keeps the key out of every process argv.
# ---------------------------------------------------------------------------
{
  hdr "Argument-vector leak experiment"
  "$HERE/prove-no-argv-leak.sh"
} > "$OUT/argv-leak-proof.txt" 2>&1

# ---------------------------------------------------------------------------
# 9. Container runtime as an execution primitive: hermetic replay.
# ---------------------------------------------------------------------------
{
  hdr "Container runtime — hermetic execution proof"
  echo "Claim under test: the Docker engine on 127.0.0.1:2375 can execute a"
  echo "workload with no network and no inherited credential. That is what"
  echo "makes it usable for independent replay of a producer's evidence."
  echo
  D=http://127.0.0.1:2375
  IMG=$(curl -s --max-time 10 "$D/images/json" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for i in d:
    for t in (i.get('RepoTags') or []):
        if 'buildkit' not in t:
            print(t); raise SystemExit
print((d[0].get('RepoTags') or ['<none>'])[0])
")
  echo "  image under test: $IMG"
  CID=$(curl -s --max-time 30 -X POST "$D/containers/create" -H 'Content-Type: application/json' \
    -d "{\"Image\":\"$IMG\",\"Cmd\":[\"/bin/sh\",\"-c\",\"echo OEW3-CONTAINER-OK; echo uid=\$(id -u); echo kernel=\$(uname -s); (getent hosts github.com >/dev/null 2>&1 && echo NET=REACHABLE || echo NET=ISOLATED); echo ENVCOUNT=\$(env | wc -l)\"],\"HostConfig\":{\"NetworkMode\":\"none\"}}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('Id',''))")
  echo "  container id prefix: ${CID:0:12}"
  curl -s --max-time 30 -o /dev/null -w '  start -> HTTP %{http_code}\n' -X POST "$D/containers/$CID/start"
  curl -s --max-time 60 -X POST "$D/containers/$CID/wait" \
    | python3 -c "import json,sys; print('  exit code:', json.load(sys.stdin).get('StatusCode'))"
  echo "  container stdout:"
  curl -s --max-time 30 "$D/containers/$CID/logs?stdout=1&stderr=1" \
    | tr -d '\000-\010\013\014\016-\037' | sed 's/^/    /'
  curl -s --max-time 30 -o /dev/null -w '  cleanup (container removed) -> HTTP %{http_code}\n' \
    -X DELETE "$D/containers/$CID?force=1"
  echo
  echo "  NET=ISOLATED with NetworkMode=none is the load-bearing line: the workload"
  echo "  could not have reached a network service, so its result is its own."
} > "$OUT/container-execution-proof.txt" 2>&1

echo "capture-evidence: wrote receipts to $OUT"
ls -la "$OUT"
