"""
Pack 09 - commit-first acceptance.

"Did the operation land exactly once?" is arithmetic, and the acceptor can do
the arithmetic itself. It reads the `events` table - the immutable input - and
the declared ops from the objective, computes what every balance MUST be if
each effect landed exactly once, reads the actual balances, and commits its own
verdict. Only then does it open `consolidation_report.json`.

What the acceptor reads to derive: `events`, `cursors`, `balances` - shared
world state. What it does NOT read: `consolidation_report.json`, `op_log.jsonl`,
`db_state.json` - the producer's account of itself.

derive_expectation() takes the objective only.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import _spine
from _spine import BASIS_INDEPENDENT_SOURCE, Objective, read_json

OBJECTIVE_KIND = "idempotent-infrastructure-operation"


def objective_for(db_path, cursor_name, ops) -> Objective:
    return Objective(
        objective_id=f"infra:{Path(db_path).name}:{cursor_name}",
        kind=OBJECTIVE_KIND,
        declared={
            "db": str(db_path),
            "cursor": cursor_name,
            "ops": [{"op_id": o.op_id, "op_type": o.op_type,
                     "target": o.target, "cents": int(o.payload["cents"])}
                    for o in ops],
        },
        derivable=True,
        independence_basis=BASIS_INDEPENDENT_SOURCE,
        note="the acceptor recomputes expected balances from the events table "
             "and the declared ops; the producer's report is not an input",
    )


def derive_expectation(objective: Objective) -> Dict[str, Any]:
    """Compute what exactly-once REQUIRES, then look at what is actually there."""
    db = objective.declared["db"]
    cursor_name = objective.declared["cursor"]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        expected: Dict[str, int] = {}
        for r in conn.execute("SELECT account, SUM(delta_cents) AS d "
                              "FROM events GROUP BY account"):
            expected[r["account"]] = int(r["d"])
        for op in objective.declared["ops"]:
            delta = op["cents"] if op["op_type"] == "credit" else -op["cents"]
            expected[op["target"]] = expected.get(op["target"], 0) + delta

        actual = {r["account"]: int(r["cents"])
                  for r in conn.execute("SELECT account, cents FROM balances")}
        max_event = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM events").fetchone()["m"]
        row = conn.execute("SELECT position FROM cursors WHERE name = ?",
                           (cursor_name,)).fetchone()
        position = int(row["position"]) if row else 0
        keys = conn.execute(
            "SELECT COUNT(*) AS n FROM applied_ops").fetchone()["n"]
    finally:
        conn.close()

    expected = {k: v for k, v in expected.items() if v != 0 or k in actual}
    return {
        "expected_balances": dict(sorted(expected.items())),
        "actual_balances": dict(sorted(actual.items())),
        "max_event_id": int(max_event),
        "cursor_position": position,
        "distinct_idempotency_keys": int(keys),
        "verdict": bool(expected == actual and position == int(max_event)),
    }


def compare_to_expectation(expected: Dict[str, Any], workdir: Path) -> bool:
    """One bit."""
    if not expected["verdict"]:
        return False
    try:
        c = read_json(Path(workdir) / "consolidation_report.json")
    except Exception:  # noqa: BLE001
        return False
    if c.get("end_position") != expected["cursor_position"]:
        return False
    if c.get("end_position") != expected["max_event_id"]:
        return False
    start = c.get("start_position")
    if not isinstance(start, int):
        return False
    counted = sum(b.get("rows", 0) for b in c.get("batches", [])
                  if not b.get("replayed"))
    if c.get("rows_consolidated") != counted:
        return False
    # rows drained must reconcile with the distance the watermark travelled
    replayed = sum(b.get("rows", 0) for b in c.get("batches", [])
                   if b.get("replayed"))
    return c.get("rows_consolidated") + replayed == c["end_position"] - start
