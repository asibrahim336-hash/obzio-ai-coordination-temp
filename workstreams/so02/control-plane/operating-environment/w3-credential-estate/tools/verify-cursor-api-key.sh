#!/usr/bin/env bash
# verify-cursor-api-key.sh — OE-W3-CREDENTIAL-ESTATE
#
# Confirms that a Cursor API key present in the runtime environment actually
# authenticates against api.cursor.com, without ever exposing the key.
#
# Safety properties, each enforced by construction rather than by convention:
#
#   1. The key is read from an environment variable by NAME. It is never
#      accepted as a command-line argument, so it cannot appear in shell
#      history, in `ps` output, or in /proc/<pid>/cmdline.
#   2. The Authorization header is handed to curl on STDIN (`-H @-`), so the
#      key never enters curl's argument vector either. The header is produced
#      by the bash builtin `printf`, which forks no process, so there is no
#      intermediate argv to inspect.
#   3. No response body is ever printed. Bodies are written to /dev/null.
#      api.cursor.com's 401 body echoes a masked fragment of the presented
#      key, so printing bodies would defeat the whole exercise.
#   4. Output is restricted to HTTP status codes, a fixed verdict vocabulary,
#      and a SHA-256 digest of the key. A digest identifies a key across
#      stores without disclosing it.
#
# Usage:
#   ./verify-cursor-api-key.sh                 # reads $CURSOR_API_KEY
#   CURSOR_KEY_VAR=OTHER_NAME ./verify-...     # reads $OTHER_NAME
#
# Exit codes: 0 verified, 1 present but rejected, 2 absent, 3 transport failure.

set -uo pipefail

KEY_VAR="${CURSOR_KEY_VAR:-CURSOR_API_KEY}"
ENDPOINT="https://api.cursor.com/v1/me"
MAX_TIME="${MAX_TIME:-25}"

emit() { printf '%s\n' "$*"; }

emit "verify-cursor-api-key: begin"
emit "  endpoint            : ${ENDPOINT}"
emit "  key_variable_name   : ${KEY_VAR}"

# --- Step 0: presence by name only -------------------------------------------
# `grep -x` against the platform's own name census. This proves the secret is
# configured for this scope without reading it.
if [ -n "${CLOUD_AGENT_ALL_SECRET_NAMES:-}" ]; then
  if printf '%s' "${CLOUD_AGENT_ALL_SECRET_NAMES}" | tr ',' '\n' | grep -qx "${KEY_VAR}"; then
    emit "  name_census         : PRESENT"
  else
    emit "  name_census         : ABSENT"
  fi
else
  emit "  name_census         : UNAVAILABLE (CLOUD_AGENT_ALL_SECRET_NAMES unset)"
fi

# --- Step 1: unauthenticated baseline ----------------------------------------
# Establishes that a rejection is distinguishable from a success on this
# endpoint right now. Without this, a 401 later is uninterpretable.
BASELINE=$(curl -s -o /dev/null -w '%{http_code}' --max-time "${MAX_TIME}" "${ENDPOINT}")
emit "  baseline_no_header  : HTTP ${BASELINE}"
if [ "${BASELINE}" != "401" ]; then
  emit "  baseline_warning    : expected 401, got ${BASELINE} — interpret the result below with care"
fi

# --- Step 2: is the key even present in this runtime? ------------------------
KEY_VALUE="${!KEY_VAR:-}"
if [ -z "${KEY_VALUE}" ]; then
  emit "  key_in_environment  : ABSENT"
  emit "  verdict             : NOT_PRESENT"
  emit "  note                : Secrets are injected at pod start. A secret added"
  emit "                        after this run began is not visible to this run."
  emit "                        Re-run in a NEW cloud agent run."
  emit "verify-cursor-api-key: end"
  exit 2
fi

emit "  key_in_environment  : PRESENT"
emit "  key_length          : ${#KEY_VALUE}"
# A digest lets a later operator confirm "this is the same key as the one in
# Supabase Edge Secrets" by comparison, with no disclosure in either direction.
KEY_DIGEST=$(printf '%s' "${KEY_VALUE}" | sha256sum | cut -d' ' -f1)
emit "  key_sha256          : ${KEY_DIGEST}"

# --- Step 3: authenticated request, header on stdin --------------------------
# `printf` is a bash builtin: no fork, no execve, no argv containing the key.
# `-H @-` instructs curl to read the header line from standard input.
STATUS=$(printf 'Authorization: Bearer %s' "${KEY_VALUE}" \
  | curl -s -o /dev/null -w '%{http_code}' --max-time "${MAX_TIME}" -H @- "${ENDPOINT}")
CURL_RC=$?

emit "  authenticated_call  : HTTP ${STATUS} (curl rc=${CURL_RC})"

# --- Step 4: verdict from the status code alone ------------------------------
case "${STATUS}" in
  200)
    emit "  verdict             : VERIFIED"
    emit "  meaning             : the key authenticates; baseline was ${BASELINE}"
    emit "verify-cursor-api-key: end"
    exit 0
    ;;
  401)
    emit "  verdict             : REJECTED_INVALID_KEY"
    emit "  meaning             : key present but not accepted (expired, revoked, or wrong value)"
    emit "verify-cursor-api-key: end"
    exit 1
    ;;
  403)
    emit "  verdict             : REJECTED_FORBIDDEN"
    emit "  meaning             : key authenticated but lacks authority for this endpoint"
    emit "verify-cursor-api-key: end"
    exit 1
    ;;
  429)
    emit "  verdict             : RATE_LIMITED"
    emit "  meaning             : inconclusive; retry after the documented window"
    emit "verify-cursor-api-key: end"
    exit 1
    ;;
  000)
    emit "  verdict             : TRANSPORT_FAILURE"
    emit "  meaning             : no HTTP response (DNS, TLS, egress policy or timeout)"
    emit "verify-cursor-api-key: end"
    exit 3
    ;;
  *)
    emit "  verdict             : UNEXPECTED_STATUS"
    emit "  meaning             : unclassified HTTP ${STATUS}"
    emit "verify-cursor-api-key: end"
    exit 1
    ;;
esac
