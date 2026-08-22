#!/usr/bin/env python3
"""Execute the event-sourced coordination candidate."""

from __future__ import annotations

import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(UNIT_ROOT))

from benchmark.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--topology", "event-sourced", *sys.argv[1:]]))
