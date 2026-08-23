#!/usr/bin/env bash
# Read every lane file back from the remote and recompute its sha256.
#
# The control this implements is remote read-back by recomputation rather than
# trusting a claim. `git push` reporting success is a claim. So is `git status`
# reporting a clean tree. This fetches the branch from origin, streams each blob
# out of the fetched object store with `git cat-file`, and hashes the bytes that
# actually arrived. A local file that was never pushed, or pushed with different
# content, fails here instead of passing silently.
#
# One file is necessarily absent from the remote: this run's own output, which
# does not exist until the run finishes and cannot be pushed until it does. That
# single exception is declared by path in SELF_OUTPUT rather than left to make the
# verdict look worse than it is. Anything else missing is a real failure.
#
#   SELF_OUTPUT=<path> bash remote_read_back.sh <branch> <path-prefix>...
set -uo pipefail

BRANCH="${1:?usage: remote_read_back.sh <branch> <prefix>...}"
shift
PREFIXES=("$@")
SELF_OUTPUT="${SELF_OUTPUT:-}"

printf 'OE-W7-CHATGPT-ROUTE-EVIDENCE — remote read-back by recomputation\n'
printf 'Lane: OE-W7-CHATGPT-ROUTE-EVIDENCE · Commission: COM-CUR-ENV-01-20260822-v001\n'
printf 'Verified at: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Branch: %s\n\n' "$BRANCH"

printf '$ git fetch origin %s\n' "$BRANCH"
git fetch --quiet origin "$BRANCH" || { printf 'FETCH FAILED\n'; exit 2; }
REMOTE_SHA="$(git rev-parse FETCH_HEAD)"
printf 'FETCH_HEAD = %s\n' "$REMOTE_SHA"
printf '$ git ls-remote origin refs/heads/%s\n' "$BRANCH"
git ls-remote origin "refs/heads/$BRANCH"
printf '\n'

printf 'Each row recomputes sha256 over the bytes read back out of the fetched\n'
printf 'remote object store, and compares it with the local working file.\n\n'
printf '%-8s %-64s %s\n' 'RESULT' 'SHA256 (recomputed from remote)' 'PATH'

ok=0; bad=0; missing=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  if ! remote_hash="$(git cat-file blob "$REMOTE_SHA:$path" 2>/dev/null | sha256sum | cut -d' ' -f1)"; then
    printf '%-8s %-64s %s\n' 'ABSENT' '-' "$path"; missing=$((missing+1)); continue
  fi
  if [ -z "$remote_hash" ]; then
    printf '%-8s %-64s %s\n' 'ABSENT' '-' "$path"; missing=$((missing+1)); continue
  fi
  local_hash="$(sha256sum "$path" | cut -d' ' -f1)"
  if [ "$remote_hash" = "$local_hash" ]; then
    printf '%-8s %-64s %s\n' 'MATCH' "$remote_hash" "$path"; ok=$((ok+1))
  else
    printf '%-8s %-64s %s\n' 'DIFFER' "$remote_hash" "$path"
    printf '%-8s %-64s %s\n' '  local' "$local_hash" "$path"
    bad=$((bad+1))
  fi
done < <(git ls-tree -r --name-only "$REMOTE_SHA" -- "${PREFIXES[@]}")

printf '\nmatched=%d differed=%d absent_from_remote=%d\n' "$ok" "$bad" "$missing"

# Files present locally under the lane prefixes but absent from the remote tree
# are the failure this control exists to catch: a push that silently no-ops.
printf '\nlocal files under the lane prefixes that the remote does not have:\n'
untracked=0
while IFS= read -r path; do
  git cat-file -e "$REMOTE_SHA:$path" 2>/dev/null && continue
  if [ -n "$SELF_OUTPUT" ] && [ "$path" = "$SELF_OUTPUT" ]; then
    printf '  DECLARED EXCEPTION (this run own output, cannot pre-exist): %s\n' "$path"
    continue
  fi
  printf '  NOT ON REMOTE: %s\n' "$path"; untracked=$((untracked+1))
done < <(git ls-files -- "${PREFIXES[@]}"; git ls-files --others --exclude-standard -- "${PREFIXES[@]}" | sort -u)
[ "$untracked" -eq 0 ] && printf '  none beyond the declared exception\n'

if [ "$bad" -eq 0 ] && [ "$missing" -eq 0 ] && [ "$untracked" -eq 0 ]; then
  printf '\nVERDICT: READ_BACK_VERIFIED — every lane file on the remote recomputes to\n'
  printf 'the local hash, and no local lane file is missing from the remote apart\n'
  printf 'from this run own output, declared above.\n'
  exit 0
fi
printf '\nVERDICT: READ_BACK_FAILED\n'
exit 1
