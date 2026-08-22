#!/usr/bin/env python3
"""Register one a5 unit's hypothesis before any reproduction is executed.

This is the preregistration step in the mandatory conversion chain:

    source claim -> frozen hypothesis -> Obzio reproduction -> result -> ...

Running this script appends exactly one row to
``workstreams/po03/research/hypotheses.jsonl`` and nothing else. The row
keeps the four custody states distinct:

* ``source``            -- external claims and citations gathered for this
                            unit (never asserted as tested).
* ``frozen_hypothesis``  -- the exact hypothesis and acceptance wording taken
                            verbatim from the immutable dispatch record.
* ``registration``       -- this worker's own falsifiable prediction and the
                             comparison it commits to running, written before
                             the reproduction below is executed.

Nothing about the ``reproduction``, ``mechanism_change`` or ``proposal``
states is written here; those only ever appear in
``reproduction-ledger.jsonl``, produced strictly after this file is
committed, so git history itself proves preregistration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.ledger_io import append_jsonl  # noqa: E402

RESEARCH_ROOT = Path(__file__).resolve().parent
PO03_ROOT = RESEARCH_ROOT.parent
DISPATCH_DIR = PO03_ROOT / "control" / "dispatch"
HYPOTHESES_PATH = RESEARCH_ROOT / "hypotheses.jsonl"
SOURCES_PATH = RESEARCH_ROOT / "sources.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def already_registered(unit_id: str) -> bool:
    if not HYPOTHESES_PATH.exists():
        return False
    for line in HYPOTHESES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if json.loads(line).get("unit_id") == unit_id:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit_id")
    parser.add_argument("--force", action="store_true", help="allow re-registration (still appended, never rewritten)")
    args = parser.parse_args()

    if already_registered(args.unit_id) and not args.force:
        print(f"ALREADY_REGISTERED {args.unit_id} (pass --force to append a superseding row)")
        return 0

    dispatch = json.loads((DISPATCH_DIR / f"{args.unit_id}.json").read_text(encoding="utf-8"))
    sources_doc = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    unit_sources = sources_doc["units"][args.unit_id]

    row = {
        "row_kind": "hypothesis_registration",
        "unit_id": args.unit_id,
        "cohort_id": dispatch["cohort_id"],
        "commission_id": dispatch["commission_id"],
        "registered_at": utc_now(),
        "registered_before_reproduction": True,
        "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
        "source": {
            "state": "source",
            "claims": unit_sources.get("sources", []),
            "scope_limitation": unit_sources.get("scope_limitation"),
        },
        "frozen_hypothesis": {
            "state": "frozen_hypothesis",
            "hypothesis_text": dispatch["hypothesis"],
            "acceptance_assertion": dispatch["acceptance"]["assertion"],
            "acceptance_artifact": dispatch["acceptance"]["artifact"],
            "falsified_if": dispatch["acceptance"]["falsified_if"],
        },
        "registration": {
            "state": "registration",
            "prediction": unit_sources["prediction"],
        },
    }
    row_sha256 = append_jsonl(HYPOTHESES_PATH, row)
    print(json.dumps({"unit_id": args.unit_id, "row_sha256": row_sha256, "path": str(HYPOTHESES_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
