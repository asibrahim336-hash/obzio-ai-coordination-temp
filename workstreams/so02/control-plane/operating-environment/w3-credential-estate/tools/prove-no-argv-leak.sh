#!/usr/bin/env bash
# prove-no-argv-leak.sh — OE-W3-CREDENTIAL-ESTATE
#
# Demonstrates, rather than asserts, that the technique used by
# verify-cursor-api-key.sh keeps a credential out of every process argument
# vector on the machine.
#
# Method. A canary string stands in for a credential. It is defined inside this
# file, so it never appears in the command line that launched the script — an
# earlier attempt at this experiment self-contaminated exactly that way and
# reported false positives on its own harness. A local HTTP server holds each
# request open long enough to inspect /proc while the request is in flight.
#
#   SAFE   arm: printf | curl -H @-      (header arrives on stdin)
#   UNSAFE arm: curl -H "Authorization: Bearer $CANARY"
#
# Every /proc/<pid>/cmdline on the machine is then searched for the canary. The
# scanner receives the canary through a file, so the scanner's own argv is
# clean too. Expected result: SAFE 0, UNSAFE 1.

set -uo pipefail
CANARY='key_oew3argvcanary9999999999999999999999999999'
PAT=/tmp/oew3-argv-canary.pat
SRV_PY=/tmp/oew3-argv-server.py
PORT=8791

printf '%s' "$CANARY" > "$PAT"
cat > "$SRV_PY" <<'PY'
import http.server, time
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(6)
        self.send_response(401); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', 8791), H).serve_forever()
PY

python3 "$SRV_PY" & SRV=$!
sleep 1

scan() {
  python3 - "$1" <<'PY'
import glob, os, sys
label = sys.argv[1]
pat = open('/tmp/oew3-argv-canary.pat', 'rb').read()
mine = {str(os.getpid()), str(os.getppid())}
hits = []
for path in glob.glob('/proc/[0-9]*/cmdline'):
    pid = path.split('/')[2]
    try:
        data = open(path, 'rb').read()
    except OSError:
        continue
    if pat in data:
        argv = data.replace(b'\x00', b' ').decode('utf-8', 'replace').strip()
        argv = argv.replace(pat.decode(), '<CANARY>')   # keep the receipt clean
        hits.append((pid, argv[:120], pid in mine))
print(f"  [{label}] processes with the canary in cmdline: {len(hits)}")
for pid, argv, is_self in hits:
    print(f"      pid={pid} is_scanner_or_parent={is_self} argv={argv}")
PY
}

echo "--- SAFE arm: header delivered to curl on stdin (-H @-) ---"
( printf 'Authorization: Bearer %s' "$CANARY" \
    | curl -s -o /dev/null --max-time 12 -H @- "http://127.0.0.1:${PORT}/" ) &
CPID=$!
sleep 2
scan SAFE
CURLPID=$(pgrep -f "curl -s -o /dev/null --max-time 12 -H @-" | head -1)
[ -n "${CURLPID:-}" ] && echo "      curl argv as the process list sees it: $(tr '\0' ' ' < "/proc/$CURLPID/cmdline")"
wait $CPID 2>/dev/null

echo
echo "--- UNSAFE control: header passed as a command-line argument ---"
( curl -s -o /dev/null --max-time 12 -H "Authorization: Bearer $CANARY" "http://127.0.0.1:${PORT}/" ) &
CPID2=$!
sleep 2
scan UNSAFE
wait $CPID2 2>/dev/null

kill $SRV 2>/dev/null
rm -f "$PAT" "$SRV_PY"

echo
echo "--- why the SAFE arm forks nothing that could carry the value ---"
echo "  'type -t printf' => $(type -t printf)"
echo "  a bash builtin performs no execve, so no argv containing the key ever exists."
