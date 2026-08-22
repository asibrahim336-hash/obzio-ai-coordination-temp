"""Make the harness package importable under an isolated interpreter.

``unittest discover`` inserts its top-level directory into ``sys.path``, so
running from the unit root already works. This module makes the import explicit
so a single test file can also be run directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent.parent
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))
