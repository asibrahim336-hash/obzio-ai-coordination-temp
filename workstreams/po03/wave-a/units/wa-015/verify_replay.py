#!/usr/bin/env python3
"""Recurrence check for the PO-03 transactional outbox replay report.

Recompiles the replay report from the committed fixtures several times and
requires every compilation to be byte-identical to itself and to the committed
oracle.  A clean clone with no warm store, no provider memory and no ``/tmp``
carry-over must reproduce the oracle exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

_UNIT_ROOT = Path(__file__).resolve().parent
if str(_UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(_UNIT_ROOT))

import replay_harness  # noqa: E402
from outbox_processor import canonical_bytes  # noqa: E402


ORACLE = _UNIT_ROOT / "reproduction" / "expected-report.json"


def compile_bytes() -> bytes:
    return canonical_bytes(replay_harness.compile_report()) + b"\n"


def verify(repeats: int = 5, oracle: Path = ORACLE) -> dict[str, Any]:
    if repeats < 2:
        raise ValueError("recurrence requires at least two compilations")
    compilations = [compile_bytes() for _ in range(repeats)]
    digests = sorted({hashlib.sha256(data).hexdigest() for data in compilations})
    expected = oracle.read_bytes() if oracle.exists() else None
    report = {
        "compilations": repeats,
        "distinct_digests": len(digests),
        "report_sha256": digests[0] if len(digests) == 1 else None,
        "report_bytes": len(compilations[0]) if len(digests) == 1 else None,
        "oracle_present": expected is not None,
        "oracle_sha256": None if expected is None else hashlib.sha256(expected).hexdigest(),
        "self_consistent": len(digests) == 1,
        "matches_oracle": expected is not None and expected == compilations[0],
    }
    report["outcome"] = (
        "PASS" if report["self_consistent"] and report["matches_oracle"] else "FAIL"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--oracle", type=Path, default=ORACLE)
    parser.add_argument(
        "--write-oracle",
        action="store_true",
        help="Freeze the current compilation as the committed oracle.",
    )
    args = parser.parse_args(argv)
    if args.write_oracle:
        args.oracle.parent.mkdir(parents=True, exist_ok=True)
        args.oracle.write_bytes(compile_bytes())
    report = verify(args.repeats, args.oracle)
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
