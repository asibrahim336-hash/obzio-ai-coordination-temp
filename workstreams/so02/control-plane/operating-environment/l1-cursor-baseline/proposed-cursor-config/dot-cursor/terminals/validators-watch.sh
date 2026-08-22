#!/usr/bin/env bash
# Runs as a named tmux-backed terminal for the lifetime of the agent run.
# Purpose: make a currentness break visible while the agent is working, rather
# than after a commit already exists and CI reports it.
#
# Deliberately a poll, not a filesystem watcher: no watcher is installed in the
# base image, and a 30-second poll over a small tracked tree costs nothing.
set -uo pipefail

INTERVAL="${OBZIO_WATCH_INTERVAL:-30}"
LAST_FINGERPRINT=""

fingerprint() {
  git ls-files -s state operations instructions workstreams 2>/dev/null | sha256sum | cut -d' ' -f1
}

echo "validators-watch: polling every ${INTERVAL}s; Ctrl-C is safe, the agent run is unaffected"

while true; do
  fp="$(fingerprint)"
  if [ "$fp" != "$LAST_FINGERPRINT" ]; then
    LAST_FINGERPRINT="$fp"
    echo "----- $(date -u +%Y-%m-%dT%H:%M:%SZ) tracked state changed -----"

    if python3 scripts/check_operator_taxonomy.py; then
      echo "  currentness: PASS"
    else
      echo "  currentness: FAIL — repair before commit; the write-scope guard will refuse the commit" >&2
    fi

    for v in workstreams/so02/control-plane/tools/scctl.py workstreams/so02/control-plane/tools/orchqual.py; do
      if [ -f "$v" ]; then
        if python3 -I "$v" validate >/dev/null 2>&1 || python3 -I "$v" verify >/dev/null 2>&1; then
          echo "  $(basename "$v"): PASS"
        else
          echo "  $(basename "$v"): FAIL" >&2
        fi
      fi
    done
  fi
  sleep "$INTERVAL"
done
