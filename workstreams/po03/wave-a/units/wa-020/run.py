#!/usr/bin/env python3
"""Entry point for the WA-020 blind review harness.

Isolated mode (``-I``) deliberately keeps the working directory and the script
directory off ``sys.path``, which is the right default and means the harness
package has to be located explicitly. Doing it here rather than in every module
keeps the harness importable from a clean clone with no environment variables
set:

    python3 -I -B run.py
    python3 -I -B run.py --offline
"""

from __future__ import annotations

import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

from harness.run_harness import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
