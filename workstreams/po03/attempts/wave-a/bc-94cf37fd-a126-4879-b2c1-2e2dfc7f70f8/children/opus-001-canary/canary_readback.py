#!/usr/bin/env python3
"""Read one PO-03 child-canary artifact back from disk and report its digest.

This runs as its own OS process so the recorded SHA-256 and byte count come
from a fresh read of the bytes on disk rather than from the writer's memory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RECEIPT_VERSION = "PO03-CHILD-CANARY-READBACK-v1"


def repo_root(script: Path) -> Path:
    root = script.resolve().parents[7]
    if not (root / "AGENTS.md").is_file():
        raise ValueError(f"repository root not resolved from {script}")
    return root


def readback(subject: Path, root: Path) -> dict:
    data = subject.read_bytes()
    return {
        "receipt_version": RECEIPT_VERSION,
        "subject_path": subject.resolve().relative_to(root).as_posix(),
        "observed_sha256": hashlib.sha256(data).hexdigest(),
        "observed_bytes": len(data),
        "readback_process": "independent python3 process, separate from the writer process",
        "reader_pid": os.getpid(),
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True)
    parser.add_argument("--out")
    parser.add_argument("--expect-sha256")
    args = parser.parse_args(argv)

    try:
        root = repo_root(Path(__file__))
        receipt = readback(Path(args.subject), root)
    except (OSError, ValueError) as exc:
        print(f"PO03_CANARY_READBACK_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.expect_sha256 and args.expect_sha256 != receipt["observed_sha256"]:
        print(
            "PO03_CANARY_READBACK_MISMATCH: "
            f"expected={args.expect_sha256} observed={receipt['observed_sha256']}",
            file=sys.stderr,
        )
        return 1

    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
