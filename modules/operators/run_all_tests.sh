#!/usr/bin/env bash
# Runs every pack's test suite. Exit non-zero if any pack fails.
set -u
PACKS="strategic-orchestration founder-intent-processing repository-engineering independent-acceptance continuity-recovery"
rc=0
for p in $PACKS; do
  ( cd "/tmp/packs/$p" && python3 test_pack.py ) || rc=1
  echo
done
if [ $rc -eq 0 ]; then echo "ALL PACKS PASSED"; else echo "AT LEAST ONE PACK FAILED"; fi
exit $rc
