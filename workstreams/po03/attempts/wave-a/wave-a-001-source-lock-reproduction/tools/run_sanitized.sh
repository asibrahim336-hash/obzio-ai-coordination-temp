#!/bin/sh
# Run the unit's tests and reproduction in a sanitized environment.
#
# `env -i` clears every inherited variable, so no provider token, agent identity,
# proxy setting or warm Git configuration can influence the result. Only PATH,
# HOME, locale, timezone and deterministic Python switches are reintroduced.
set -eu

UNIT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPO_ROOT=${1:-$(CDPATH= cd -- "$UNIT_DIR/../../../../.." && pwd)}
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

RECEIPT_COMMIT=${RECEIPT_COMMIT:-f5b758f373e8d0cb14660c167f4b0b3673251862}
DRIFT_COMMIT=${DRIFT_COMMIT:-f5b758f373e8d0cb14660c167f4b0b3673251862}

exec env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME="$SCRATCH" \
  TMPDIR="$SCRATCH" \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  TZ=UTC \
  PYTHONHASHSEED=0 \
  PYTHONDONTWRITEBYTECODE=1 \
  UNIT_DIR="$UNIT_DIR" \
  REPO_ROOT="$REPO_ROOT" \
  RECEIPT_COMMIT="$RECEIPT_COMMIT" \
  DRIFT_COMMIT="$DRIFT_COMMIT" \
  /bin/sh -eu -c '
    echo "=== sanitized environment ==="
    env | sort
    echo "=== toolchain ==="
    python3 -VV
    git --version
    echo "=== unit tests (stdlib unittest, no network, no third-party packages) ==="
    cd "$UNIT_DIR"
    python3 -m unittest discover -s tests -p "test_*.py" -v
    echo "=== reproduction against immutable commits ==="
    python3 tools/reproduce.py \
      --repo "$REPO_ROOT" \
      --spec fixtures/spec/source-lock.spec.json \
      --receipt-commit "$RECEIPT_COMMIT" \
      --drift-commit "$DRIFT_COMMIT" \
      --out evidence/reproduction.json
    echo "=== done ==="
  '
