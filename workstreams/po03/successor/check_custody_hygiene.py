#!/usr/bin/env python3
"""Refuse derived bytecode as committed evidence under this cohort's paths.

    python3 -I workstreams/po03/successor/check_custody_hygiene.py

Why this exists as a mechanism rather than a habit
-------------------------------------------------
Cohort a6 found tracked ``__pycache__`` bytecode in the shared tree while
reviewing another cohort, and then corrected its own attribution: the escape
originated in coordinator commits that staged with a broad ``git add -A``, and
the reviewed cohort had inherited it.  Both halves of that finding matter here.

The first half is that a custody engine which verifies artifacts *by hash*
cannot tell evidence from residue.  Bytecode has a stable digest and a real byte
count, so it satisfies every integrity check G1 and G2 apply while being
regenerated on the next import - which is exactly the property a result must not
have.  Nothing a result depends on may be a build product.

The second half is that the escape came from *how work was staged*, not from the
engine.  So the mechanism belongs at the boundary where files are admitted to
the repository, and it is enforced by a test rather than by remembering to stage
narrowly.

Scope, stated honestly: this checks the paths this cohort owns.  a6 attributed
the origin to coordinator-owned paths, which this cohort must not modify, so
those are reported separately as an observation rather than a failure.  That is
why the lesson's disposition is RETEST and not RETAIN.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Paths this cohort owns and is therefore accountable for.
OWNED = (
    "workstreams/po03/successor/",
    "workstreams/po03/control/units/a8/",
    "receipts/po03/",
)

# Everything else in the wave-one allowlist, reported but not failed on.
OBSERVED = ("workstreams/po03/",)

DERIVED_SUFFIXES = (".pyc", ".pyo")
DERIVED_DIRECTORIES = ("__pycache__",)


def tracked_files(prefix: str) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", prefix],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def is_derived(path: str) -> bool:
    if path.endswith(DERIVED_SUFFIXES):
        return True
    return any(part in DERIVED_DIRECTORIES for part in path.split("/"))


def derived_under(prefixes: tuple[str, ...]) -> list[str]:
    found: set[str] = set()
    for prefix in prefixes:
        found.update(path for path in tracked_files(prefix) if is_derived(path))
    return sorted(found)


def main() -> int:
    owned = derived_under(OWNED)
    elsewhere = [path for path in derived_under(OBSERVED) if path not in owned]

    for path in elsewhere:
        print(f"OBSERVED (not owned by this cohort, reported not failed): {path}")
    if owned:
        for path in owned:
            print(f"REFUSED derived file tracked under an owned path: {path}")
        return 1
    print(f"CLEAN: no derived bytecode tracked under {len(OWNED)} owned prefixes")
    if elsewhere:
        print(f"BOUNDARY: {len(elsewhere)} derived file(s) remain tracked outside this cohort's ownership")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
