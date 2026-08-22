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

Removal is not prevention
-------------------------
Deleting the files closes the instance and leaves the escape one broad
``git add -A`` away.  So this check has two halves.  The first refuses derived
files that are tracked now.  The second asks git whether a derived path under an
owned prefix *would* be ignored if it appeared, which is the property that keeps
the first half true without anyone having to remember anything.  The question is
put to ``git check-ignore`` rather than to a named ``.gitignore``, so the check
is about the rule being in force and not about which file supplies it.

Scope, stated honestly: this checks the paths this cohort owns.  a6 attributed
the origin to coordinator-owned paths, which this cohort must not modify, so
those are reported separately as an observation rather than a failure.  Missing
prevention is likewise reported rather than failed where this cohort cannot
supply it: its grant under ``receipts/po03/`` is a single file, so it cannot add
an ignore rule there and says so instead of claiming coverage it does not have.
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

# Representative derived paths, one per owned prefix, used to ask git whether the
# prevention rule is in force.  These paths are never created; only classified.
IGNORE_PROBES = tuple(f"{prefix}__pycache__/probe.cpython-312.pyc" for prefix in OWNED) + tuple(
    f"{prefix}probe.pyc" for prefix in OWNED
)


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


def is_ignored(path: str) -> bool:
    """Ask git whether ``path`` would be ignored, without creating it."""
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def unprevented() -> list[str]:
    """Owned prefixes where a derived file would not be ignored if it appeared."""
    return sorted({probe for probe in IGNORE_PROBES if not is_ignored(probe)})


def main() -> int:
    owned = derived_under(OWNED)
    elsewhere = [path for path in derived_under(OBSERVED) if path not in owned]
    unignored = unprevented()

    for path in elsewhere:
        print(f"OBSERVED (not owned by this cohort, reported not failed): {path}")
    if owned:
        for path in owned:
            print(f"REFUSED derived file tracked under an owned path: {path}")
        return 1
    print(f"CLEAN: no derived bytecode tracked under {len(OWNED)} owned prefixes")
    for path in unignored:
        print(f"UNPREVENTED (would not be ignored if it appeared): {path}")
    if unignored:
        print(
            f"BOUNDARY: {len(unignored)} owned probe path(s) lack an ignore rule; "
            "this cohort's grant there is a single file, so it cannot add one"
        )
    else:
        print(f"PREVENTED: an ignore rule is in force for all {len(IGNORE_PROBES)} owned probe paths")
    if elsewhere:
        print(f"BOUNDARY: {len(elsewhere)} derived file(s) remain tracked outside this cohort's ownership")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
