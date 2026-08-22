"""Make the unit root importable regardless of how the tests are discovered."""

from __future__ import annotations

import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))
