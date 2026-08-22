#!/bin/sh
# PO-03 offline suite runner (unit a3-u06).
#
# Runs the PO-03 test suite with outbound network removed, and refuses to call
# the result a pass unless it has observed that the network was reachable before
# the sandbox was entered and unreachable inside it.  An offline transcript from
# a host that never had a route is indistinguishable from one that proves
# something, so the two preconditions are checked and reported separately.
#
# Dependency-free: POSIX shell, git, python3 and unshare only.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)

POLICY="$SCRIPT_DIR/offline-policy.json"
SUITE_DIR="workstreams/po03/tests"
SUITE_PATTERN="test_*.py"
SANDBOX=""
OUT=""
REMOTE=""
PROBE_ONLY=0

usage() {
	cat <<'EOF'
usage: offline_check.sh [options]

  --policy FILE      offline policy document (default: runtime/offline-policy.json)
  --suite-dir DIR    unittest discovery start directory, repo-relative
  --suite-pattern P  unittest discovery pattern (default: test_*.py)
  --sandbox CMD      override the sandbox command; used by the tests to plant a
                     no-op sandbox and prove the enforcement probe fires
  --remote URL       remote to probe (default: origin of this checkout)
  --out FILE         write the JSON transcript here
  --probe-only       run the probes and skip the suite
  -h, --help         show this message
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--policy) POLICY="$2"; shift 2 ;;
	--suite-dir) SUITE_DIR="$2"; shift 2 ;;
	--suite-pattern) SUITE_PATTERN="$2"; shift 2 ;;
	--sandbox) SANDBOX="$2"; shift 2 ;;
	--remote) REMOTE="$2"; shift 2 ;;
	--out) OUT="$2"; shift 2 ;;
	--probe-only) PROBE_ONLY=1; shift ;;
	-h | --help) usage; exit 0 ;;
	*) echo "offline_check.sh: unknown argument: $1" >&2; usage >&2; exit 64 ;;
	esac
done

if [ ! -f "$POLICY" ]; then
	echo "offline_check.sh: policy not found: $POLICY" >&2
	exit 66
fi

POLICY_SCHEMA=$(python3 -I -c '
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("schema", ""))
' "$POLICY")
if [ "$POLICY_SCHEMA" != "po03-offline-policy-v1" ]; then
	echo "offline_check.sh: unexpected policy schema: $POLICY_SCHEMA" >&2
	exit 66
fi

if [ -z "$SANDBOX" ]; then
	SANDBOX=$(python3 -I -c '
import json, shlex, sys
policy = json.load(open(sys.argv[1], encoding="utf-8"))
print(shlex.join(policy["sandbox"]["command"]))
' "$POLICY")
fi

if [ -z "$REMOTE" ]; then
	REMOTE=$(git -C "$REPO_ROOT" remote get-url origin)
fi

redact() { sed -e 's#://[^/@ ]*@#://***@#g'; }
redact_value() { printf '%s' "$1" | redact; }
json_escape() { python3 -I -c 'import json, sys; sys.stdout.write(json.dumps(sys.stdin.read()))'; }
now_ms() { python3 -I -c 'import time; print(int(time.time() * 1000))'; }

REMOTE_HOST=$(python3 -I -c '
import sys, urllib.parse
raw = sys.argv[1]
if "://" in raw:
    print(urllib.parse.urlsplit(raw).hostname or "")
elif "@" in raw and ":" in raw:
    print(raw.split("@", 1)[1].split(":", 1)[0])
else:
    print("")
' "$REMOTE")

if [ -z "$REMOTE_HOST" ]; then
	echo "offline_check.sh: cannot derive a probe host from the remote" >&2
	exit 66
fi

SCRATCH=$(mktemp -d)
case "$SCRATCH/" in
"$REPO_ROOT"/*)
	rm -rf "$SCRATCH"
	echo "offline_check.sh: refusing scratch inside the repository: $SCRATCH" >&2
	exit 65
	;;
esac
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT INT TERM
mkdir -p "$SCRATCH/logs" "$SCRATCH/home" "$SCRATCH/tmp"

PROBES="$SCRATCH/probes.jsonl"
: >"$PROBES"

# PATH is rebuilt rather than inherited, matching the clean-clone runner: an
# offline pass that depended on an inherited PATH entry would be a different
# kind of hidden dependency.
CLEAN_PATH=""
for candidate in "$(dirname -- "$(command -v python3)")" "$(dirname -- "$(command -v git)")" "$(dirname -- "$(command -v sh)")" /usr/bin /bin; do
	case ":$CLEAN_PATH:" in
	*":$candidate:"*) ;;
	*) if [ -z "$CLEAN_PATH" ]; then CLEAN_PATH="$candidate"; else CLEAN_PATH="$CLEAN_PATH:$candidate"; fi ;;
	esac
done

clean_run() {
	env -i \
		PATH="$CLEAN_PATH" \
		HOME="$SCRATCH/home" \
		TMPDIR="$SCRATCH/tmp" \
		LC_ALL=C.UTF-8 \
		sh -c "cd '$REPO_ROOT' && $1"
}

# The probe commands come from the policy so that adding a probe is a data
# change.  {host} and {remote} are the only substitutions.
probe_command() {
	python3 -I -c '
import json, shlex, sys
policy = json.load(open(sys.argv[1], encoding="utf-8"))
host, remote, wanted = sys.argv[2], sys.argv[3], sys.argv[4]
for probe in policy["probes"]:
    if probe["id"] != wanted:
        continue
    argv = [part.replace("{host}", host).replace("{remote}", remote) for part in probe["command"]]
    print(shlex.join(argv))
    break
else:
    raise SystemExit(f"no probe {wanted!r}")
' "$POLICY" "$REMOTE_HOST" "$REMOTE" "$1"
}

PROBE_IDS=$(python3 -I -c '
import json, sys
policy = json.load(open(sys.argv[1], encoding="utf-8"))
print(" ".join(probe["id"] for probe in policy["probes"]))
' "$POLICY")

record_probe() {
	probe_id=$1
	phase=$2
	rc=$3
	log=$4
	sha=$(python3 -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$log")
	printf '{"probe_id":"%s","phase":"%s","exit_code":%d,"log_sha256":"%s"}\n' \
		"$probe_id" "$phase" "$rc" "$sha" >>"$PROBES"
}

run_probe() {
	probe_id=$1
	phase=$2
	prefix=$3
	cmd=$(probe_command "$probe_id")
	log="$SCRATCH/logs/$phase-$probe_id.log"
	set +e
	if [ -z "$prefix" ]; then
		clean_run "$cmd" >"$log" 2>&1
	else
		clean_run "$prefix $cmd" >"$log" 2>&1
	fi
	rc=$?
	set -e
	redact <"$log" >"$log.redacted"
	mv "$log.redacted" "$log"
	record_probe "$probe_id" "$phase" "$rc" "$log"
	echo "$rc"
}

RUN_START=$(now_ms)

# Pinning the commit lets a reader tell which tree the transcript describes,
# rather than having to trust that it is current.
REPOSITORY_COMMIT=$(git -C "$REPO_ROOT" rev-parse HEAD)

# Precondition one: the sandbox command must exist and run something.
SANDBOX_LOG="$SCRATCH/logs/sandbox-available.log"
set +e
clean_run "$SANDBOX true" >"$SANDBOX_LOG" 2>&1
SANDBOX_RC=$?
set -e
if [ "$SANDBOX_RC" -ne 0 ]; then
	SANDBOX_AVAILABLE=false
else
	SANDBOX_AVAILABLE=true
fi

# Precondition two: the remote is reachable outside the sandbox.  Without this
# the inside-the-sandbox failures are not attributable to the sandbox.
BASELINE_FAILURES=0
for probe_id in $PROBE_IDS; do
	rc=$(run_probe "$probe_id" baseline "")
	if [ "$rc" -ne 0 ]; then
		BASELINE_FAILURES=$((BASELINE_FAILURES + 1))
	fi
done

# Precondition three: every probe fails inside the sandbox.
SANDBOX_UNEXPECTED_SUCCESSES=0
if [ "$SANDBOX_AVAILABLE" = true ]; then
	for probe_id in $PROBE_IDS; do
		rc=$(run_probe "$probe_id" sandboxed "$SANDBOX")
		if [ "$rc" -eq 0 ]; then
			SANDBOX_UNEXPECTED_SUCCESSES=$((SANDBOX_UNEXPECTED_SUCCESSES + 1))
		fi
	done
fi

# Marked modules are recomputed from the tree, not read from the policy, so a
# module that marks itself is separated whether or not anyone updated the list.
MARKED=$(python3 -I -c '
import json, pathlib, sys
policy = json.load(open(sys.argv[1], encoding="utf-8"))
constant = policy["marker"]["constant"]
start = pathlib.Path(sys.argv[2])
found = []
if start.is_dir():
    for path in sorted(start.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(constant) and stripped.endswith("True"):
                found.append(path.name)
                break
print(" ".join(found))
' "$POLICY" "$REPO_ROOT/$SUITE_DIR")

MARKED_COUNT=0
for _ in $MARKED; do MARKED_COUNT=$((MARKED_COUNT + 1)); done

SUITE_RC=0
TESTS_RUN=0
TESTS_SKIPPED=0
SUITE_LOG="$SCRATCH/logs/suite.log"
: >"$SUITE_LOG"

if [ "$PROBE_ONLY" -eq 0 ] && [ "$SANDBOX_AVAILABLE" = true ]; then
	set +e
	clean_run "$SANDBOX python3 -I -B -m unittest discover -s '$SUITE_DIR' -p '$SUITE_PATTERN' -v" \
		>"$SUITE_LOG" 2>&1
	SUITE_RC=$?
	set -e
	TESTS_RUN=$(sed -n 's/^Ran \([0-9][0-9]*\) test.*/\1/p' "$SUITE_LOG" | tail -1)
	[ -n "$TESTS_RUN" ] || TESTS_RUN=0
	TESTS_SKIPPED=$(grep -c ' \.\.\. skipped ' "$SUITE_LOG" || true)
fi

RUN_END=$(now_ms)

# Status is decided by which precondition failed, so a reader can tell a proved
# offline pass from an unproved one without reading the probe log.
if [ "$SANDBOX_AVAILABLE" != true ]; then
	STATUS=NOT_SUPPORTED
	DETAIL="sandbox command failed: $(redact_value "$SANDBOX")"
elif [ "$SANDBOX_UNEXPECTED_SUCCESSES" -gt 0 ]; then
	STATUS=OFFLINE_NOT_ENFORCED
	DETAIL="$SANDBOX_UNEXPECTED_SUCCESSES probe(s) reached the network inside the sandbox"
elif [ "$BASELINE_FAILURES" -gt 0 ]; then
	STATUS=INCONCLUSIVE_NO_BASELINE
	DETAIL="$BASELINE_FAILURES baseline probe(s) failed outside the sandbox"
elif [ "$PROBE_ONLY" -eq 1 ]; then
	STATUS=PROBES_ONLY
	DETAIL="suite not run"
elif [ "$SUITE_RC" -ne 0 ]; then
	STATUS=FAIL
	DETAIL="suite exited $SUITE_RC with outbound network disabled"
else
	STATUS=PASS
	DETAIL="suite exited 0 with outbound network disabled"
fi

PROBES_JSON=$(python3 -I -c '
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
sys.stdout.write(json.dumps(rows, indent=2, sort_keys=True))
' "$PROBES")

MARKED_JSON=$(python3 -I -c '
import json, sys
sys.stdout.write(json.dumps(sys.argv[1].split(), indent=2))
' "$MARKED")

SUITE_TAIL=$(tail -12 "$SUITE_LOG" | redact | json_escape)
DETAIL_JSON=$(redact_value "$DETAIL" | json_escape)
SANDBOX_JSON=$(redact_value "$SANDBOX" | json_escape)

TRANSCRIPT=$(
	cat <<EOF
{
  "schema": "po03-offline-transcript-v1",
  "unit_id": "a3-u06",
  "status": "$STATUS",
  "detail": $DETAIL_JSON,
  "remote_host": "$REMOTE_HOST",
  "repository_commit": "$REPOSITORY_COMMIT",
  "sandbox": $SANDBOX_JSON,
  "sandbox_available": $SANDBOX_AVAILABLE,
  "baseline_probe_failures": $BASELINE_FAILURES,
  "sandboxed_probe_successes": $SANDBOX_UNEXPECTED_SUCCESSES,
  "suite": {
    "start_directory": "$SUITE_DIR",
    "pattern": "$SUITE_PATTERN",
    "exit_code": $SUITE_RC,
    "tests_run": $TESTS_RUN,
    "tests_skipped": $TESTS_SKIPPED,
    "tail": $SUITE_TAIL
  },
  "separated_modules": $MARKED_JSON,
  "separated_module_count": $MARKED_COUNT,
  "environment": {
    "mode": "env -i",
    "path": "$CLEAN_PATH",
    "home": "scratch/home",
    "tmpdir": "scratch/tmp",
    "inherited_variables": 0
  },
  "wall_ms": $((RUN_END - RUN_START)),
  "probes": $PROBES_JSON
}
EOF
)

if [ -n "$OUT" ]; then
	mkdir -p "$(dirname -- "$OUT")"
	printf '%s\n' "$TRANSCRIPT" >"$OUT"
	echo "offline_check.sh: transcript written to $OUT"
fi

printf '%s\n' "$TRANSCRIPT"

case "$STATUS" in
PASS | PROBES_ONLY) exit 0 ;;
NOT_SUPPORTED) exit 3 ;;
INCONCLUSIVE_NO_BASELINE) exit 4 ;;
OFFLINE_NOT_ENFORCED) exit 5 ;;
*) exit 1 ;;
esac
