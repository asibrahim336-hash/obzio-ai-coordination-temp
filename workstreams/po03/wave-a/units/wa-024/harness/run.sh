#!/usr/bin/env bash
# Clean-environment reproduction for PO03-WA-024.
#
# The script takes a repository (a local path or a clone URL) and an immutable
# commit, materialises a fresh clone of committed content only, and runs this
# unit's tests, its static control and its differential harness from inside that
# fresh clone.  Nothing outside the output directory and a private temporary
# directory is written, and the caller's checkout is never modified.
#
# Requirements: bash, git and python3.  No third-party package is used.
#
#   ./run.sh                                   # reproduce against this checkout's HEAD
#   ./run.sh --commit <sha> --out /path/report  # reproduce a specific commit
#   ./run.sh --repo https://github.com/owner/name --commit <sha>

set -euo pipefail

UNIT_REL="workstreams/po03/wave-a/units/wa-024"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

REPO=""
COMMIT=""
OUT=""
KEEP_CLONE="no"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --keep-clone) KEEP_CLONE="yes"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$REPO" ]; then
  REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
fi
if [ -z "$COMMIT" ] && [ -d "$REPO/.git" ]; then
  COMMIT="$(git -C "$REPO" rev-parse HEAD)"
fi
if [ -z "$COMMIT" ]; then
  echo "a --commit is required when --repo is a URL" >&2
  exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/wa024-reproduction-XXXXXX")"
CLONE="$WORK/clone"
if [ -z "$OUT" ]; then
  OUT="$WORK/report"
fi
mkdir -p "$OUT"
# Every stage below runs with the clean clone as its working directory, so a
# relative output path would resolve inside the clone: the reports would be
# discarded with it, and the writes would dirty the very tree the probes measure.
OUT="$(cd -- "$OUT" && pwd)"

cleanup() {
  if [ "$KEEP_CLONE" = "no" ]; then
    rm -rf "$WORK"
  else
    echo "clean clone retained at $CLONE" >&2
  fi
}
trap cleanup EXIT

case "$REPO" in
  http://*|https://*|git@*|ssh://*|file://*) SOURCE="$REPO" ;;
  *) SOURCE="file://$(cd -- "$REPO" && pwd)" ;;
esac

echo "== PO03-WA-024 clean-environment reproduction"
echo "   source:      $SOURCE"
echo "   commit:      $COMMIT"
echo "   clean clone: $CLONE"
echo "   output:      $OUT"
echo "   git:         $(git --version)"
echo "   python3:     $(python3 --version 2>&1)"

git init --quiet "$CLONE"
git -C "$CLONE" remote add origin "$SOURCE"
if ! git -C "$CLONE" fetch --quiet origin "$COMMIT" 2>/dev/null; then
  echo "   note: fetching an explicit commit was refused; fetching all refs instead" >&2
  git -C "$CLONE" fetch --quiet origin
fi
git -C "$CLONE" checkout --quiet --detach "$COMMIT"

ACTUAL="$(git -C "$CLONE" rev-parse HEAD)"
if [ "$ACTUAL" != "$COMMIT" ]; then
  echo "clean clone HEAD $ACTUAL does not match requested $COMMIT" >&2
  exit 1
fi

RESIDUE="$(git -C "$CLONE" status --porcelain --untracked-files=all)"
if [ -n "$RESIDUE" ]; then
  echo "fresh clone is unexpectedly dirty:" >&2
  echo "$RESIDUE" >&2
  exit 1
fi

# A scrubbed environment: no inherited PYTHON* settings, a private HOME and a
# private TMPDIR, so nothing the caller's session accumulated can leak in.
export HOME="$WORK/home"
export TMPDIR="$WORK/tmp"
mkdir -p "$HOME" "$TMPDIR"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONDONTWRITEBYTECODE VIRTUAL_ENV || true

STATUS=0

echo
echo "== 1/4 focused tests"
if ( cd "$CLONE" && python3 -B -I -m unittest discover -s "$UNIT_REL/tests" -p 'test_*.py' -v ) \
    >"$OUT/tests-output.txt" 2>&1; then
  echo "   tests: PASS"
else
  echo "   tests: FAIL (see $OUT/tests-output.txt)"
  STATUS=1
fi
tail -n 5 "$OUT/tests-output.txt"

echo
echo "== 2/4 static local-state control"
LINT_STATUS=0
( cd "$CLONE" && python3 -B "$UNIT_REL/harness/local_state_lint.py" \
    --repo . --commit "$COMMIT" --json "$OUT/lint-report.json" \
    --allow-external-object-ids "$UNIT_REL/harness/external-object-ids.json" ) \
  >"$OUT/lint-output.txt" 2>&1 || LINT_STATUS=$?
echo "   lint exit status: $LINT_STATUS (1 means findings at or above the error threshold)"
tail -n 3 "$OUT/lint-output.txt"

echo
echo "== 3/4 clean-runner differential harness"
PROBE_STATUS=0
( cd "$CLONE" && python3 -B "$UNIT_REL/harness/clean_runner_probe.py" \
    --repo . --commit "$COMMIT" --probes "$UNIT_REL/harness/probes.json" \
    --json "$OUT/probe-report.json" --require-expectations ) \
  >"$OUT/probe-output.txt" 2>&1 || PROBE_STATUS=$?
echo "   probe exit status: $PROBE_STATUS (non-zero means a binding expectation was not met)"
tail -n 12 "$OUT/probe-output.txt"
if [ "$PROBE_STATUS" -ne 0 ]; then
  STATUS=1
fi

echo
echo "== 4/4 mechanism-change verification"
MECHANISM_STATUS=0
( cd "$CLONE" && python3 -B "$UNIT_REL/proposals/verify_mechanism_changes.py" \
    --repo . --commit "$COMMIT" --json "$OUT/mechanism-verification.json" ) \
  >"$OUT/mechanism-output.txt" 2>&1 || MECHANISM_STATUS=$?
echo "   mechanism exit status: $MECHANISM_STATUS (non-zero means a proposed change did not verify)"
tail -n 3 "$OUT/mechanism-output.txt"
if [ "$MECHANISM_STATUS" -ne 0 ]; then
  STATUS=1
fi

FINAL_RESIDUE="$(git -C "$CLONE" status --porcelain --untracked-files=all)"
echo
if [ -n "$FINAL_RESIDUE" ]; then
  echo "== residue left in the clean clone after the reproduction:"
  echo "$FINAL_RESIDUE"
else
  echo "== clean clone is unchanged after the reproduction"
fi

echo
echo "== reproduction complete, exit status $STATUS"
echo "   reports: $OUT"
exit "$STATUS"
