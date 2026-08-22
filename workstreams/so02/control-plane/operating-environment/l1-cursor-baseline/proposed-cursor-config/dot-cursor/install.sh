#!/usr/bin/env bash
# Runs during an environment Build, after the repository source is available.
# Must be idempotent: it can run repeatedly and on top of previously prepared disk state.
# Must not start any process — Builds preserve disk state only.
set -euo pipefail

echo ">>> obzio install: begin"

python3 --version
git --version

# Repository tooling. The control plane is stdlib-only by design; these are the
# validation dependencies used by the checks, not by the runtime state itself.
python3 -m pip install --quiet --user --disable-pip-version-check \
  jsonschema==4.26.0

# Fail the Build rather than an agent turn if the repository's own currentness
# contract is already broken at the recorded commit.
python3 scripts/check_operator_taxonomy.py

echo ">>> obzio install: complete"
