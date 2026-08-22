"""Helpers for appending rows to ``reproduction-ledger.jsonl``.

A row always carries a ``reproduction`` sub-object (state: "reproduction")
describing what was actually executed and measured. It may additionally
carry a ``mechanism_change`` sub-object (state: "mechanism_change") when the
result changes a live mechanism this worker owns, or a ``proposal``
sub-object (state: "proposal") when the change would need the coordinator to
apply it to a coordinator-owned file such as
``workstreams/po03/tools/control_plane.py``. These sub-objects are always
optional and always separate keys -- a reproduction row is never allowed to
assert a mechanism change through its measurement fields alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger_io import append_jsonl

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
REPRODUCTION_LEDGER_PATH = RESEARCH_ROOT / "reproduction-ledger.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_reproduction(
    *,
    unit_id: str,
    reproduction_id: str,
    command: str,
    arms: list[str],
    measurement: dict[str, Any],
    outcome: str,
    outcome_rationale: str,
    evidence_artifacts: list[str],
    mechanism_change: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
) -> str:
    """Append one reproduction row. Returns the row's own sha256."""
    if outcome not in {"SUPPORTED", "REJECTED", "PARTIALLY_SUPPORTED", "NOT_YET"}:
        raise ValueError(f"invalid outcome: {outcome}")
    row: dict[str, Any] = {
        "row_kind": "reproduction_record",
        "unit_id": unit_id,
        "executed_at": utc_now(),
        "reproduction": {
            "state": "reproduction",
            "reproduction_id": reproduction_id,
            "command": command,
            "arms_executed": arms,
            "both_arms_executed": len(arms) >= 2,
            "measurement": measurement,
            "outcome": outcome,
            "outcome_rationale": outcome_rationale,
            "evidence_artifacts": evidence_artifacts,
        },
        "limitations": limitations or [],
    }
    if mechanism_change is not None:
        row["mechanism_change"] = {"state": "mechanism_change", **mechanism_change}
    if proposal is not None:
        row["proposal"] = {"state": "proposal", **proposal}
    return append_jsonl(REPRODUCTION_LEDGER_PATH, row)
