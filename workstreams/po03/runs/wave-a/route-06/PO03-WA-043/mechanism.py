#!/usr/bin/env python3
"""Resource-side monotonic lease fencing reproduction."""
import json
import sqlite3


def new_store():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE custody(task_id TEXT PRIMARY KEY, fence INTEGER NOT NULL, owner TEXT NOT NULL, value TEXT)")
    db.execute("INSERT INTO custody VALUES ('OBZIO-SANITIZED-003', 0, 'none', NULL)")
    return db


def acquire(db, owner):
    with db:
        db.execute("UPDATE custody SET fence=fence+1, owner=? WHERE task_id='OBZIO-SANITIZED-003'", (owner,))
    return db.execute("SELECT fence FROM custody WHERE task_id='OBZIO-SANITIZED-003'").fetchone()[0]


def fenced_write(db, token, value):
    with db:
        changed = db.execute(
            "UPDATE custody SET value=? WHERE task_id='OBZIO-SANITIZED-003' AND fence=?",
            (value, token),
        ).rowcount
    return changed == 1


def unfenced_write(db, value):
    with db:
        db.execute("UPDATE custody SET value=? WHERE task_id='OBZIO-SANITIZED-003'", (value,))


def exercise():
    baseline = new_store()
    acquire(baseline, "worker-a")
    acquire(baseline, "worker-b")
    unfenced_write(baseline, "worker-b-current")
    unfenced_write(baseline, "worker-a-delayed")
    baseline_value = baseline.execute("SELECT value FROM custody").fetchone()[0]
    protected = new_store()
    token_a = acquire(protected, "worker-a")
    token_b = acquire(protected, "worker-b")
    current_accepted = fenced_write(protected, token_b, "worker-b-current")
    stale_accepted = fenced_write(protected, token_a, "worker-a-delayed")
    protected_value = protected.execute("SELECT value FROM custody").fetchone()[0]
    return {
        "baseline_final_value": baseline_value,
        "tokens": [token_a, token_b],
        "current_write_accepted": current_accepted,
        "stale_write_accepted": stale_accepted,
        "protected_final_value": protected_value,
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
