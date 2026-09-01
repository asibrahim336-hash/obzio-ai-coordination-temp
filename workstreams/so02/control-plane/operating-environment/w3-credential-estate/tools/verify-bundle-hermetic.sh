#!/usr/bin/env bash
# verify-bundle-hermetic.sh — OE-W3-CREDENTIAL-ESTATE
#
# Verifies this lane's delivery bundle inside a container with no network and
# no inherited credential, using the Docker engine on 127.0.0.1:2375.
#
# Why bother. Recomputing digests on the host proves the bytes are consistent
# with each other. It does not prove the checker did not reach the producer,
# reuse the producer's authentication, or consult something outside the
# supplied inputs. Running the same recomputation under HostConfig.NetworkMode
# = none removes all three possibilities at once. That is the difference
# between "the producer says it verifies" and "it verifies here, hermetically",
# and it is the concrete first use of the container primitive recorded as
# IA-01 in FOUNDER-ALIGNMENT-PLAN.json.
#
# The in-container checker is POSIX shell plus awk and sha256sum, because the
# available image has no python3 and no jq, and there is no network to fetch
# them. It reconstructs the canonical entries string that defines
# bundle_sha256 — json.dumps(entries, sort_keys=True, separators=(",",":")) —
# which for this entry shape means keys in alphabetical order (path, sha256,
# size_bytes) with no whitespace, in the list order the manifest already uses.
# Every path in this bundle is plain ASCII with no JSON-escapable character,
# so reconstruction is exact rather than approximate.
#
# A trap worth knowing about. The Docker daemon on 2375 runs in a DIFFERENT
# mount namespace from the agent VM: its /tmp contains none of the agent's
# files. A bind mount of an agent path therefore does not fail — Docker
# creates the missing source directory on the daemon host and mounts it
# EMPTY, so the container starts happily and sees nothing. The bundle is
# instead uploaded with PUT /containers/{id}/archive, which is explicit about
# which bytes cross the boundary and works regardless of filesystem sharing.
#
# Usage: ./verify-bundle-hermetic.sh [repo-root]

set -uo pipefail
REPO="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../../.." && pwd)}"
D=http://127.0.0.1:2375
MANIFEST_REL="receipts/so02/2026-08-22/oe-w3-credential-estate/MANIFEST.json"

[ -f "$REPO/$MANIFEST_REL" ] || { echo "no manifest at $REPO/$MANIFEST_REL"; exit 2; }
echo "repo root : $REPO"
echo "manifest  : $MANIFEST_REL"

IMG=$(curl -s --max-time 15 "$D/images/json" | python3 -c "
import json,sys
for i in json.load(sys.stdin):
    for t in (i.get('RepoTags') or []):
        if 'buildkit' not in t:
            print(t); raise SystemExit
")
[ -n "$IMG" ] || { echo "no usable local image"; exit 2; }
echo "image     : $IMG"
echo "network   : none (HostConfig.NetworkMode=none)"

read -r -d '' SCRIPT <<'INNER'
set -u
cd / || exit 2
M=receipts/so02/2026-08-22/oe-w3-credential-estate/MANIFEST.json
echo "hermetic verification starting"
echo "  network check: $(getent hosts github.com >/dev/null 2>&1 && echo REACHABLE || echo ISOLATED)"
echo "  inherited env vars: $(env | wc -l)"

# Declared values, read straight out of the manifest.
DECL_BUNDLE=$(tr ',' '\n' < "$M" | grep '"bundle_sha256"' | head -1 | sed 's/.*"bundle_sha256"[[:space:]]*:[[:space:]]*"\([0-9a-f]*\)".*/\1/')
DECL_COUNT=$(tr ',' '\n' < "$M" | grep '"entry_count"' | head -1 | sed 's/[^0-9]*\([0-9]*\).*/\1/')
echo "  declared entry_count  : $DECL_COUNT"
echo "  declared bundle_sha256: $DECL_BUNDLE"

# Pull (path, sha256, size_bytes) triples out of the entries array, in order.
awk '
  /"entries"[[:space:]]*:/ { inentries=1 }
  inentries && /"path"[[:space:]]*:/      { p=$0; sub(/.*"path"[[:space:]]*:[[:space:]]*"/,"",p); sub(/".*/,"",p) }
  inentries && /"size_bytes"[[:space:]]*:/{ z=$0; gsub(/[^0-9]/,"",z) }
  inentries && /"sha256"[[:space:]]*:/    { s=$0; sub(/.*"sha256"[[:space:]]*:[[:space:]]*"/,"",s); sub(/".*/,"",s);
                                            if (p != "") { print p "\t" s "\t" z; p=""; s=""; z="" } }
' "$M" > /tmp/triples.tsv

N=$(wc -l < /tmp/triples.tsv)
echo "  entries parsed        : $N"

# 1. Every listed file must exist and hash to its listed digest.
FAIL=0
while IFS="$(printf '\t')" read -r path want size; do
  [ -n "$path" ] || continue
  if [ ! -f "$path" ]; then echo "  MISSING: $path"; FAIL=$((FAIL+1)); continue; fi
  got=$(sha256sum "$path" | cut -d' ' -f1)
  [ "$got" = "$want" ] || { echo "  DIGEST MISMATCH: $path"; FAIL=$((FAIL+1)); }
  gotsize=$(wc -c < "$path" | tr -d ' ')
  [ "$gotsize" = "$size" ] || { echo "  SIZE MISMATCH: $path ($gotsize vs $size)"; FAIL=$((FAIL+1)); }
done < /tmp/triples.tsv
echo "  per-file digest+size failures: $FAIL"

# 2. Rebuild the canonical entries string and re-derive bundle_sha256.
awk -F'\t' '
  BEGIN { printf "[" }
  { if (NR>1) printf ",";
    printf "{\"path\":\"%s\",\"sha256\":\"%s\",\"size_bytes\":%s}", $1, $2, $3 }
  END { printf "]" }
' /tmp/triples.tsv > /tmp/canonical.json
GOT_BUNDLE=$(sha256sum /tmp/canonical.json | cut -d' ' -f1)
echo "  recomputed bundle_sha256: $GOT_BUNDLE"

# 3. Nothing in the bundle may be absent from the manifest, except the
#    manifest itself, whose self-exclusion the manifest declares.
ONDISK=$(find workstreams/so02/control-plane/operating-environment/w3-credential-estate \
              receipts/so02/2026-08-22/oe-w3-credential-estate -type f | grep -v "$M" | wc -l)
echo "  files on disk (excluding the manifest): $ONDISK"

RC=0
[ "$FAIL" -eq 0 ]                || RC=1
[ "$GOT_BUNDLE" = "$DECL_BUNDLE" ] || { echo "  BUNDLE DIGEST MISMATCH"; RC=1; }
[ "$N" = "$DECL_COUNT" ]         || { echo "  ENTRY COUNT MISMATCH"; RC=1; }
[ "$ONDISK" = "$N" ]             || { echo "  CLOSURE FAILURE: on-disk file count does not equal entry count"; RC=1; }
grep -q '"REMOTE-READBACK.json"' "$M" || grep -q 'REMOTE-READBACK.json' "$M" \
  || { echo "  CLOSURE FAILURE: read-back record absent from the manifest"; RC=1; }

[ "$RC" -eq 0 ] && echo "HERMETIC VERIFY: PASS" || echo "HERMETIC VERIFY: FAIL"
exit $RC
INNER

export IMG SCRIPT
CID=$(curl -s --max-time 30 -X POST "$D/containers/create" -H 'Content-Type: application/json' \
  -d "$(python3 -c "
import json, os
print(json.dumps({
  'Image': os.environ['IMG'],
  'Cmd': ['/bin/sh', '-c', os.environ['SCRIPT']],
  'HostConfig': {'NetworkMode': 'none', 'AutoRemove': False},
  'Env': [],
}))
")" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('Id') or d.get('message',''))")

case "$CID" in
  *[!0-9a-f]*|"") echo "container create failed: $CID"; exit 2 ;;
esac
echo "container : ${CID:0:12}"

# Ship exactly the two lane namespaces in, and nothing else. The tar is built
# on this side, so what the container verifies is precisely what was sent.
echo -n "upload    : "
tar -C "$REPO" -cf - \
    workstreams/so02/control-plane/operating-environment/w3-credential-estate \
    receipts/so02/2026-08-22/oe-w3-credential-estate \
  | curl -s --max-time 120 -o /dev/null -w 'HTTP %{http_code}\n' \
      -X PUT "$D/containers/$CID/archive?path=%2F" \
      -H 'Content-Type: application/x-tar' --data-binary @-

curl -s --max-time 30 -o /dev/null -X POST "$D/containers/$CID/start"
RC=$(curl -s --max-time 120 -X POST "$D/containers/$CID/wait" \
     | python3 -c "import json,sys; print(json.load(sys.stdin).get('StatusCode'))")
echo "--- container output ---"
# Docker multiplexes container logs into 8-byte-framed chunks. Stripping
# control characters is not enough: the frame's length bytes can themselves be
# printable ASCII and appear as stray characters mid-line. Demultiplex properly.
curl -s --max-time 30 "$D/containers/$CID/logs?stdout=1&stderr=1" --output - \
  | python3 -c "
import sys
buf = sys.stdin.buffer.read()
out, i = [], 0
while i + 8 <= len(buf):
    n = int.from_bytes(buf[i+4:i+8], 'big')
    out.append(buf[i+8:i+8+n]); i += 8 + n
sys.stdout.write(b''.join(out).decode('utf-8', 'replace'))
"
echo "--- exit code: $RC ---"
curl -s --max-time 30 -o /dev/null -X DELETE "$D/containers/$CID?force=1"
exit "${RC:-1}"
