"""Planted defect fixture: an entry point that only works in-process.

Reads a variable at module scope. Imported into a parent that has the variable
set, it succeeds; run as a command with a constructed environment, the variable
is absent and it fails before main() is reached.

This is the shape of every "works on my machine" portability bug, and it is what
proves the harness distinguishes in-process success from subprocess success
rather than reporting whichever it happened to run.
"""

import os

TOKEN = os.environ["PO03_BOUNDARY_TOKEN"]


def main(argv=None) -> int:
    print(f"token resolved: {TOKEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
