#!/usr/bin/env python3
"""Seal the evaluator-held case files by digest.

The seal is what makes the holdout auditable: a later generation run records the
seal it measured against, so a case that was edited, added or removed after the
current generation was measured is detectable by digest comparison alone.

The seal is a chronology and integrity control, not secrecy: the files are
committed to Git so that they are durable, and the seal proves they did not
change afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SEAL_VERSION = "PO03-HOLDOUT-SEAL-v1"
SEALED_FILES = ("hidden/hidden_result_cases.py", "hidden/holdout_custody_cases.py")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def build_seal(unit_root: Path) -> dict:
    entries = []
    for relative in SEALED_FILES:
        payload = (unit_root / relative).read_bytes()
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    combined = b"".join(
        (unit_root / relative).read_bytes() for relative in SEALED_FILES
    )
    return {
        "seal_version": SEAL_VERSION,
        "sealed_at": utc_now(),
        "files": entries,
        "combined_sha256": hashlib.sha256(combined).hexdigest(),
        "visibility": "evaluator-held: excluded from the producer-visible suite in workstreams/po03/tests",
        "integrity_rule": (
            "A generation run must record this combined_sha256. A run whose recorded seal differs "
            "from another run's seal is not comparable with it."
        ),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    seal = build_seal(Path(args.unit_root).resolve())
    Path(args.out).write_bytes(canonical(seal))
    print(json.dumps(seal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
