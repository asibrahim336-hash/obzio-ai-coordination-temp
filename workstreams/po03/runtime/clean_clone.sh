#!/bin/sh
# PO-03 clean-clone runner (unit a3-u01).
#
# Clones the repository from a real remote into a scratch directory that lives
# outside the working repository, then executes the complete PO-03 test suite
# inside that clone with a stripped environment.  Nothing in the working
# checkout can influence the run: the environment is rebuilt with `env -i`,
# HOME and TMPDIR are redirected into the scratch tree, and the clone is
# asserted to be free of uncommitted files before the suite starts.
#
# The scratch tree is deleted on exit unless --keep is given, so no committed
# result can ever depend on it.
#
# Dependency-free: POSIX shell, git and python3 only.

set -eu

REMOTE=""
REF=""
SCRATCH=""
OUT=""
EXPECT_COMMIT=""
KEEP=0

usage() {
	cat <<'EOF'
usage: clean_clone.sh [options]

  --remote URL      remote to clone from (default: origin of this checkout)
  --ref REF         branch or tag to clone (default: current branch)
  --expect-commit S require the cloned HEAD to equal this commit sha
  --scratch DIR     scratch parent directory (default: mktemp -d)
  --out FILE        write the JSON transcript here (default: stdout only)
  --keep            do not delete the scratch tree on exit
  -h, --help        show this message
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--remote) REMOTE="$2"; shift 2 ;;
	--ref) REF="$2"; shift 2 ;;
	--expect-commit) EXPECT_COMMIT="$2"; shift 2 ;;
	--scratch) SCRATCH="$2"; shift 2 ;;
	--out) OUT="$2"; shift 2 ;;
	--keep) KEEP=1; shift ;;
	-h | --help) usage; exit 0 ;;
	*) echo "clean_clone.sh: unknown argument: $1" >&2; usage >&2; exit 64 ;;
	esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)

now_ms() { python3 -I -c 'import time; print(int(time.time() * 1000))'; }

# Credentials are commonly embedded in the push URL as userinfo.  Every value
# that reaches the transcript, the log or the terminal passes through here.
redact() { sed -e 's#://[^/@ ]*@#://***@#g'; }

redact_value() { printf '%s' "$1" | redact; }

json_escape() {
	python3 -I -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

if [ -z "$REMOTE" ]; then
	REMOTE=$(git -C "$REPO_ROOT" remote get-url origin)
fi
if [ -z "$REF" ]; then
	REF=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
fi

# A scratch tree inside the repository would reintroduce exactly the warm-state
# coupling this runner exists to disprove.  The requested parent is rejected
# before any directory is created, so a refused run leaves nothing behind.
if [ -n "$SCRATCH" ]; then
	# realpath resolves without creating, so a rejected path is never made.
	SCRATCH_PARENT=$(python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$SCRATCH")
	case "$SCRATCH_PARENT/" in
	"$REPO_ROOT"/*)
		echo "clean_clone.sh: refusing scratch directory inside the repository: $SCRATCH_PARENT" >&2
		exit 65
		;;
	esac
	mkdir -p "$SCRATCH_PARENT"
	SCRATCH=$(mktemp -d "$SCRATCH_PARENT/po03-clean-clone.XXXXXX")
else
	SCRATCH=$(mktemp -d)
fi

case "$SCRATCH/" in
"$REPO_ROOT"/*)
	rm -rf "$SCRATCH"
	echo "clean_clone.sh: refusing scratch directory inside the repository: $SCRATCH" >&2
	exit 65
	;;
esac

cleanup() {
	if [ "$KEEP" -eq 0 ]; then
		rm -rf "$SCRATCH"
	else
		echo "clean_clone.sh: scratch retained at $SCRATCH" >&2
	fi
}
trap cleanup EXIT INT TERM

CLONE="$SCRATCH/clone"
mkdir -p "$SCRATCH/logs" "$SCRATCH/home" "$SCRATCH/tmp"
STEPS="$SCRATCH/steps.jsonl"
: >"$STEPS"

STEP_FAILURES=0

run_step() {
	name=$1
	shift
	log="$SCRATCH/logs/$name.log"
	start=$(now_ms)
	set +e
	"$@" >"$log" 2>&1
	rc=$?
	set -e
	end=$(now_ms)
	# Redact in place before anything reads the log back.
	redact <"$log" >"$log.redacted"
	mv "$log.redacted" "$log"
	sha=$(python3 -I -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$log")
	lines=$(wc -l <"$log" | tr -d ' ')
	argv=$(printf '%s ' "$@" | redact | sed -e 's/ $//' | json_escape)
	printf '{"name":"%s","argv":%s,"exit_code":%d,"duration_ms":%d,"log_sha256":"%s","log_lines":%s}\n' \
		"$name" "$argv" "$rc" "$((end - start))" "$sha" "$lines" >>"$STEPS"
	echo "--- step $name (exit $rc) ---"
	cat "$log"
	if [ "$rc" -ne 0 ]; then
		STEP_FAILURES=$((STEP_FAILURES + 1))
	fi
	return 0
}

RUN_START=$(now_ms)

run_step clone git clone --depth 1 --single-branch --branch "$REF" "$REMOTE" "$CLONE"
if [ ! -d "$CLONE/.git" ]; then
	echo "clean_clone.sh: clone failed; no repository at $CLONE" >&2
	exit 70
fi

CLONED_COMMIT=$(git -C "$CLONE" rev-parse HEAD)
if [ -n "$EXPECT_COMMIT" ] && [ "$CLONED_COMMIT" != "$EXPECT_COMMIT" ]; then
	echo "clean_clone.sh: cloned HEAD $CLONED_COMMIT != expected $EXPECT_COMMIT" >&2
	exit 71
fi

# A fresh clone must have no uncommitted files.  If this ever fails, the suite
# under test is writing into its own source tree.
run_step tree_clean_before git -C "$CLONE" status --porcelain
if [ -s "$SCRATCH/logs/tree_clean_before.log" ]; then
	echo "clean_clone.sh: fresh clone is not clean" >&2
	STEP_FAILURES=$((STEP_FAILURES + 1))
fi

TRACKED_FILES=$(git -C "$CLONE" ls-files | wc -l | tr -d ' ')

# env -i removes every inherited variable: no provider memory, no PYTHONPATH,
# no warm cache, no shared TMPDIR.  PATH is reconstructed from a fixed minimal
# value plus the interpreter and git directories so both remain reachable.
CLEAN_PATH=""
for candidate in "$(dirname -- "$(command -v python3)")" "$(dirname -- "$(command -v git)")" /usr/bin /bin; do
	case ":$CLEAN_PATH:" in
	*":$candidate:"*) ;;
	*) if [ -z "$CLEAN_PATH" ]; then CLEAN_PATH="$candidate"; else CLEAN_PATH="$CLEAN_PATH:$candidate"; fi ;;
	esac
done

clean_env() {
	env -i \
		PATH="$CLEAN_PATH" \
		HOME="$SCRATCH/home" \
		TMPDIR="$SCRATCH/tmp" \
		LC_ALL=C.UTF-8 \
		sh -c "cd '$CLONE' && $1"
}

# Pass one runs the suite with bytecode writing disabled.  `python3 -I` implies
# `-E`, so PYTHONDONTWRITEBYTECODE is ignored and only the `-B` flag suppresses
# __pycache__; with it the clone must be byte-for-byte untouched.
run_step suite_no_bytecode clean_env "python3 -I -B -m unittest discover -s workstreams/po03/tests -p 'test_*.py' -v"
run_step tree_after_no_bytecode git -C "$CLONE" status --porcelain
LEFTOVER_NO_BYTECODE=$(wc -l <"$SCRATCH/logs/tree_after_no_bytecode.log" | tr -d ' ')
if [ "$LEFTOVER_NO_BYTECODE" -ne 0 ]; then
	echo "clean_clone.sh: -B suite run left files in the clone" >&2
	STEP_FAILURES=$((STEP_FAILURES + 1))
fi

# Pass two runs the exact canonical gate command with no extra flags, so the
# transcript proves the command the commission requires, not a variant of it.
run_step suite clean_env "python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py' -v"

SUITE_LOG="$SCRATCH/logs/suite.log"
TESTS_RUN=$(sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' "$SUITE_LOG" | tail -1)
[ -n "$TESTS_RUN" ] || TESTS_RUN=0

# After the canonical run only interpreter bytecode caches are tolerated, and
# they are counted rather than ignored.  Anything else is a real leftover.
run_step tree_clean_after git -C "$CLONE" status --porcelain
LEFTOVER_BYTECODE=$(grep -c '__pycache__\|\.pyc' "$SCRATCH/logs/tree_clean_after.log" || true)
LEFTOVER_UNEXPECTED=$(grep -v '__pycache__\|\.pyc' "$SCRATCH/logs/tree_clean_after.log" | grep -c . || true)
if [ "$LEFTOVER_UNEXPECTED" -ne 0 ]; then
	echo "clean_clone.sh: suite left $LEFTOVER_UNEXPECTED unexpected uncommitted path(s) in the clone" >&2
	STEP_FAILURES=$((STEP_FAILURES + 1))
fi

RUN_END=$(now_ms)

if [ "$STEP_FAILURES" -eq 0 ]; then
	STATUS=PASS
else
	STATUS=FAIL
fi

STEPS_JSON=$(python3 -I -c '
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
sys.stdout.write(json.dumps(rows, indent=2, sort_keys=True))
' "$STEPS")

REMOTE_REDACTED=$(redact_value "$REMOTE")

TRANSCRIPT=$(
	cat <<EOF
{
  "schema": "po03-clean-clone-transcript-v1",
  "unit_id": "a3-u01",
  "status": "$STATUS",
  "remote": "$REMOTE_REDACTED",
  "ref": "$REF",
  "cloned_commit": "$CLONED_COMMIT",
  "tracked_files": $TRACKED_FILES,
  "tests_run": $TESTS_RUN,
  "wall_ms": $((RUN_END - RUN_START)),
  "scratch_inside_repository": false,
  "leftovers": {
    "after_no_bytecode_run": $LEFTOVER_NO_BYTECODE,
    "bytecode_caches_after_canonical_run": $LEFTOVER_BYTECODE,
    "unexpected_after_canonical_run": $LEFTOVER_UNEXPECTED
  },
  "environment": {
    "mode": "env -i",
    "path": "$CLEAN_PATH",
    "home": "scratch/home",
    "tmpdir": "scratch/tmp",
    "inherited_variables": 0
  },
  "steps": $STEPS_JSON
}
EOF
)

if [ -n "$OUT" ]; then
	mkdir -p "$(dirname -- "$OUT")"
	printf '%s\n' "$TRANSCRIPT" >"$OUT"
	echo "clean_clone.sh: transcript written to $OUT"
fi

printf '%s\n' "$TRANSCRIPT"

if [ "$STATUS" = "PASS" ]; then
	exit 0
fi
exit 1
