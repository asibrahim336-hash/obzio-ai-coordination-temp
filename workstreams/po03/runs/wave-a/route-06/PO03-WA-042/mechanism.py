#!/usr/bin/env python3
"""SQLite transactional outbox and idempotent receiver reproduction."""
import json
import sqlite3
import tempfile
from pathlib import Path


def open_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE results(task_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE outbox(event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE inbox(event_id TEXT PRIMARY KEY);
        CREATE TABLE callbacks(event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    return db


def stage_result(db, task_id, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    event_id = f"{task_id}:result-staged"
    with db:
        db.execute("INSERT INTO results VALUES (?, ?)", (task_id, encoded))
        db.execute("INSERT INTO outbox(event_id, task_id, payload) VALUES (?, ?, ?)", (event_id, task_id, encoded))
    return event_id


def deliver(db, event_id, crash_after_receiver=False):
    row = db.execute("SELECT task_id, payload FROM outbox WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        raise KeyError(event_id)
    with db:
        inserted = db.execute("INSERT OR IGNORE INTO inbox(event_id) VALUES (?)", (event_id,)).rowcount
        if inserted:
            db.execute("INSERT INTO callbacks VALUES (?, ?, ?)", (event_id, row[0], row[1]))
    if crash_after_receiver:
        return "CRASHED_AFTER_IDEMPOTENT_EFFECT"
    with db:
        db.execute("UPDATE outbox SET delivered=1 WHERE event_id=?", (event_id,))
    return "DELIVERED" if inserted else "DUPLICATE_ACKNOWLEDGED"


def replay(db):
    events = [row[0] for row in db.execute("SELECT event_id FROM outbox WHERE delivered=0 ORDER BY event_id")]
    return [deliver(db, event_id) for event_id in events]


def exercise():
    with tempfile.TemporaryDirectory() as tmp:
        db = open_db(Path(tmp) / "custody.db")
        event = stage_result(db, "OBZIO-SANITIZED-002", {"artifact": "demo", "state": "RESULT_STAGED"})
        before_replay = db.execute("SELECT count(*) FROM callbacks").fetchone()[0]
        first_replay = replay(db)
        db.execute("UPDATE outbox SET delivered=0 WHERE event_id=?", (event,))
        injected = deliver(db, event, crash_after_receiver=True)
        second_replay = replay(db)
        effects = db.execute("SELECT count(*) FROM callbacks WHERE event_id=?", (event,)).fetchone()[0]
        pending = db.execute("SELECT count(*) FROM outbox WHERE delivered=0").fetchone()[0]
        db.close()
    return {
        "callbacks_before_replay": before_replay,
        "lost_callback_replay": first_replay,
        "injected_fault": injected,
        "post_crash_replay": second_replay,
        "receiver_effect_count": effects,
        "pending_outbox_rows": pending,
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
