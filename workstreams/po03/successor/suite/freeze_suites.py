#!/usr/bin/env python3
"""Freeze the scoring suites by file digest.

The scorer refuses to run if a suite's bytes no longer match this manifest.
That is the enforcement behind "frozen public suite": freezing is not a promise
in a document, it is a precondition of producing a score at all.

    python3 -I workstreams/po03/successor/suite/freeze_suites.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
MANIFEST = HERE / "suite-manifest.json"

SUITES = [
    {
        "key": "public",
        "role": "public",
        "path": "workstreams/po03/successor/suite/public/cases.json",
        "authored_by": "po03-worker-a8",
        "generator": "workstreams/po03/successor/suite/build_public_suite.py",
        "note": "authored by the same owner as the generations, so it measures capability against the commission's custody requirements but cannot by itself rule out suite overfitting",
    },
    {
        "key": "holdout",
        "role": "holdout",
        "path": "workstreams/po03/successor/suite/holdout/cases.json",
        "authored_by": "po03-worker-a6",
        "generator": "workstreams/po03/successor/suite/build_holdout_suite.py",
        "note": "case selection, attacks and expected outcomes authored by cohort a6 before any producer branch was published; the executable binding is authored by po03-worker-a8 and that boundary is recorded in holdout/provenance.json",
    },
]


def digest(relative: str) -> tuple[str, int]:
    data = (REPO_ROOT / relative).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def build() -> dict:
    entries = []
    for suite in SUITES:
        sha256, size = digest(suite["path"])
        cases = json.loads((REPO_ROOT / suite["path"]).read_text(encoding="utf-8"))["cases"]
        entries.append({**suite, "sha256": sha256, "bytes": size, "case_count": len(cases)})
    return {
        "manifest_id": "po03-a8-suite-freeze-v001",
        "owner": "po03-worker-a8",
        "rule": "The scorer refuses to run when any declared suite digest does not match. Adding, editing or removing a case after a generation has been scored requires a new case_set_id and a new preregistration.",
        "suites": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text = json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != text:
            print(f"DRIFTED {MANIFEST}: a declared suite changed after freezing")
            return 1
        print(f"FROZEN {MANIFEST}")
        return 0
    MANIFEST.write_text(text, encoding="utf-8")
    print(f"WROTE {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
