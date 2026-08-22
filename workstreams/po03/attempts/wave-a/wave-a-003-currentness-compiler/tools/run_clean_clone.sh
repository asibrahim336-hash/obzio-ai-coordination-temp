#!/usr/bin/env bash
# Reproduce wave-a-003 from a fresh clone at one immutable commit.
#
# Usage: run_clean_clone.sh <clone-url-or-path> <commit> <destination>
#
# The suite runs with an emptied environment, an isolated interpreter and no
# reuse of the caller's checkout, so a pass cannot depend on provider memory,
# a warm worktree, uncommitted files or a populated HOME.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <clone-url-or-path> <commit> <destination>" >&2
  exit 2
fi

SOURCE="$1"
COMMIT="$2"
DESTINATION="$3"
UNIT="workstreams/po03/attempts/wave-a/wave-a-003-currentness-compiler"

rm -rf "$DESTINATION"
git clone -q "$SOURCE" "$DESTINATION"
git -C "$DESTINATION" checkout -q "$COMMIT"

echo "clean_clone_commit=$(git -C "$DESTINATION" rev-parse HEAD)"
echo "clean_clone_dirty_files=$(git -C "$DESTINATION" status --porcelain | wc -l)"

cd "$DESTINATION"
env -i HOME=/nonexistent PATH=/usr/bin:/bin LANG=C.UTF-8 \
  python3 -I -m unittest discover -s "$UNIT/tests" -p 'test_*.py' -v
env -i HOME=/nonexistent PATH=/usr/bin:/bin LANG=C.UTF-8 \
  python3 -I "$UNIT/tools/currentness_compiler.py" --commit "$COMMIT" --quiet
env -i HOME=/nonexistent PATH=/usr/bin:/bin LANG=C.UTF-8 \
  python3 -I "$UNIT/tools/run_cases.py"
