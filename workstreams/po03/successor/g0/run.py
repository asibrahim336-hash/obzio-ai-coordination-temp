#!/usr/bin/env python3
"""G0's own entry point.

    python3 -I workstreams/po03/successor/g0/run.py
    python3 -I workstreams/po03/successor/g0/run.py --suite holdout --verbose
"""

from __future__ import annotations

import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[2]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g0.controller import PROVENANCE, G0Controller, build  # noqa: E402
from successor.harness.cli import run_generation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(
        run_generation(po03=PO03, controller_cls=G0Controller, build=build, provenance=PROVENANCE)
    )
