#!/usr/bin/env python3
"""G1's own entry point.

Nothing here reads ``workstreams/po03/control/``: G1 builds its dispatch
records, ledger, result slots and locator store under a directory it is handed,
which is what makes it runnable from a clean clone and independent of the live
control directory.

    python3 -I workstreams/po03/successor/g1/run.py
    python3 -I workstreams/po03/successor/g1/run.py --suite holdout --verbose
"""

from __future__ import annotations

import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[2]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g1.factory import PROVENANCE, G1Controller, build  # noqa: E402
from successor.harness.cli import run_generation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(
        run_generation(po03=PO03, controller_cls=G1Controller, build=build, provenance=PROVENANCE)
    )
