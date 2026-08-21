"""
Pack 09 - infrastructure-operation
Execute against a real database with exactly-once effects and bounded requests.

TWO DEFECTS THIS PACK IS BUILT AGAINST
--------------------------------------
1. DOUBLE EFFECT ON RETRY. A process killed between doing the thing and
   recording that it did the thing. The retry does it again.

   Answer: the record and the effect are the SAME TRANSACTION. The
   idempotency key is INSERTed first, the effect follows, one COMMIT covers
   both. There is no instant at which one exists without the other. A kill
   before COMMIT rolls back everything; a kill after COMMIT leaves a key that
   turns the retry into a no-op returning the stored result.

2. THE CONSOLIDATION JOB THAT RE-READ WHOLE STATE EVERY RUN until its request
   outgrew a per-request ceiling (observed in this operation).

   Answer, in three parts:
     * there IS no whole-state read - `read_all()` raises by construction
     * every read is bounded twice, by row count AND by serialized bytes
     * the batch effect and the WATERMARK ADVANCE are one transaction, so
       each run reads only what arrived since the last run. Request size
       tracks new work, not accumulated history, and stops growing.

CLI (used by the crash tests, and usable operationally):
    python3 state_machine.py apply       --db D --op-id ID --account A --cents N
    python3 state_machine.py consolidate --db D [--cursor main]
    python3 state_machine.py seed        --db D --count N [--note-size B]
    python3 state_machine.py dump        --db D
  env OBZIO_CRASH_AT=<point> hard-kills the process at that point.
"""
from __future__ import annotations

import argparse
import enum
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _spine
from _spine import (
    AcceptanceGate, AcceptanceOutcome, CheckReport, CommitFirstAcceptor,
    Objective, Phase, Run, canon, sha256_bytes, sha256_obj, write_json,
)

PACK = "09-infrastructure-operation"

# Per-request ceilings. The observed incident was a request that grew past a
# platform limit; these are OUR limits, set below any platform's, so we fail
# with a diagnostic instead of being failed by someone else's error page.
MAX_ROWS_PER_REQUEST = 500
MAX_REQUEST_BYTES = 65_536
GROWTH_ALARM_FRACTION = 0.8       # warn before the ceiling, not at it

CRASH_POINTS = (
    "before_begin",
    "after_insert_before_effect",
    "after_effect_before_commit",
    "after_commit_before_return",
    "consolidate_before_commit",
    "consolidate_after_commit",
)


class InfraError(Exception):
    pass


class UnboundedReadRefused(InfraError):
    """The defect path. Not implemented on purpose."""


class IdempotencyKeyConflict(InfraError):
    pass


class RowTooLarge(InfraError):
    pass


class RequestCeilingApproach(InfraError):
    pass


def _crash(point: str) -> None:
    """Hard kill with no unwinding, no atexit, no flush - as close to a
    machine losing power as a test can get."""
    if os.environ.get("OBZIO_CRASH_AT") == point:
        sys.stderr.write(f"[injected-crash] {point}\n")
        sys.stderr.flush()
        os._exit(9)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS applied_ops (
    idem_key       TEXT PRIMARY KEY,
    op_type        TEXT NOT NULL,
    target         TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    result_json    TEXT NOT NULL,
    applied_at     REAL NOT NULL,
    run_id         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS balances (
    account TEXT PRIMARY KEY,
    cents   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account     TEXT NOT NULL,
    delta_cents INTEGER NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cursors (
    name     TEXT PRIMARY KEY,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_stats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    cursor_name   TEXT NOT NULL,
    batch_no      INTEGER NOT NULL,
    rows          INTEGER NOT NULL,
    request_bytes INTEGER NOT NULL,
    at            REAL NOT NULL
);
"""


def connect(db_path: os.PathLike | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Op:
    op_id: str                  # caller-supplied; retries MUST reuse it
    op_type: str                # credit | debit
    target: str                 # account
    payload: Dict[str, Any]

    @property
    def payload_digest(self) -> str:
        return sha256_obj(self.payload)

    @property
    def idem_key(self) -> str:
        return self.op_id

    def to_dict(self):
        return {**asdict(self), "payload_digest": self.payload_digest}


@dataclass
class ApplyResult:
    idem_key: str
    applied: bool          # True = the effect happened in THIS call
    replayed: bool         # True = key already present, effect not repeated
    result: Dict[str, Any]

    def to_dict(self):
        return asdict(self)


class IdempotentExecutor:
    def __init__(self, conn: sqlite3.Connection, run_id: str,
                 op_log: Optional[os.PathLike | str] = None):
        self.conn = conn
        self.run_id = run_id
        self.op_log = Path(op_log) if op_log else None

    def _log(self, row: Dict[str, Any]) -> None:
        if self.op_log is None:
            return
        self.op_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.op_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), **row},
                                sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _existing(self, idem_key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM applied_ops WHERE idem_key = ?", (idem_key,)).fetchone()

    def apply(self, op: Op) -> ApplyResult:
        """Exactly-once. The idempotency record and the effect commit together
        or not at all."""
        _crash("before_begin")

        prior = self._existing(op.idem_key)
        if prior is not None:
            if prior["payload_digest"] != op.payload_digest:
                raise IdempotencyKeyConflict(
                    f"op_id {op.op_id!r} was already applied with a different "
                    f"payload ({prior['payload_digest'][:12]} vs "
                    f"{op.payload_digest[:12]}); refusing to reinterpret it")
            res = ApplyResult(op.idem_key, applied=False, replayed=True,
                              result=json.loads(prior["result_json"]))
            self._log({"kind": "REPLAY", "op_id": op.op_id,
                       "idem_key": op.idem_key, "applied": False})
            return res

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # 1. claim the key FIRST, inside the transaction
            self.conn.execute(
                "INSERT INTO applied_ops"
                " (idem_key, op_type, target, payload_digest, result_json,"
                "  applied_at, run_id) VALUES (?,?,?,?,?,?,?)",
                (op.idem_key, op.op_type, op.target, op.payload_digest,
                 "{}", time.time(), self.run_id))
            _crash("after_insert_before_effect")

            # 2. the effect
            delta = int(op.payload["cents"])
            if op.op_type == "debit":
                delta = -delta
            elif op.op_type != "credit":
                raise InfraError(f"unknown op_type {op.op_type!r}")
            self.conn.execute(
                "INSERT INTO balances (account, cents) VALUES (?, ?) "
                "ON CONFLICT(account) DO UPDATE SET cents = cents + excluded.cents",
                (op.target, delta))
            row = self.conn.execute(
                "SELECT cents FROM balances WHERE account = ?",
                (op.target,)).fetchone()
            result = {"account": op.target, "delta": delta,
                      "balance_after": row["cents"]}

            # 3. store the result under the same key, same transaction
            self.conn.execute(
                "UPDATE applied_ops SET result_json = ? WHERE idem_key = ?",
                (json.dumps(result, sort_keys=True), op.idem_key))

            _crash("after_effect_before_commit")
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

        _crash("after_commit_before_return")
        self._log({"kind": "APPLY", "op_id": op.op_id, "idem_key": op.idem_key,
                   "op_type": op.op_type, "target": op.target,
                   "applied": True, "result": result})
        return ApplyResult(op.idem_key, applied=True, replayed=False, result=result)


# --------------------------------------------------------------------------
# Bounded reads
# --------------------------------------------------------------------------
@dataclass
class Window:
    rows: List[Dict[str, Any]]
    request_bytes: int
    from_position: int
    to_position: int
    truncated_by: Optional[str]   # "rows" | "bytes" | None

    def to_dict(self):
        return {**asdict(self), "rows": len(self.rows)}


class BoundedStateReader:
    def __init__(self, conn: sqlite3.Connection,
                 max_rows: int = MAX_ROWS_PER_REQUEST,
                 max_bytes: int = MAX_REQUEST_BYTES):
        self.conn = conn
        self.max_rows = int(max_rows)
        self.max_bytes = int(max_bytes)

    # The defect path, kept present and named so nobody re-invents it.
    def read_all(self) -> None:
        raise UnboundedReadRefused(
            "whole-state reads are not available in this pack. Every read is "
            "bounded by row count and serialized bytes, and every consumer "
            "advances a durable watermark. This is the control that prevents "
            "the request from growing until it exceeds a per-request ceiling."
        )

    def measure_full_state_bytes(self) -> int:
        """Size the whole table WITHOUT materialising it - SQL does the
        arithmetic. Used for the growth pre-mortem, never to fetch."""
        r = self.conn.execute(
            "SELECT COUNT(*) AS n, "
            "  COALESCE(SUM(LENGTH(account) + LENGTH(note) + 48), 0) AS b "
            "FROM events").fetchone()
        return int(r["b"])

    @staticmethod
    def _row_bytes(d: Dict[str, Any]) -> int:
        return len(canon(d))

    def read_window(self, after_id: int) -> Window:
        cur = self.conn.execute(
            "SELECT id, account, delta_cents, note, created_at FROM events "
            "WHERE id > ? ORDER BY id LIMIT ?", (after_id, self.max_rows))
        fetched = [dict(r) for r in cur.fetchall()]

        rows: List[Dict[str, Any]] = []
        total = 0
        truncated = None
        for d in fetched:
            b = self._row_bytes(d)
            if b > self.max_bytes:
                raise RowTooLarge(
                    f"event {d['id']} serialises to {b} bytes, above the "
                    f"{self.max_bytes}-byte request ceiling; it can never be "
                    "batched and would stall the cursor forever")
            if total + b > self.max_bytes:
                truncated = "bytes"
                break
            rows.append(d)
            total += b
        if truncated is None and len(fetched) == self.max_rows:
            truncated = "rows"

        return Window(rows=rows, request_bytes=total, from_position=after_id,
                      to_position=rows[-1]["id"] if rows else after_id,
                      truncated_by=truncated)


# --------------------------------------------------------------------------
# Consolidation
# --------------------------------------------------------------------------
@dataclass
class ConsolidationReport:
    cursor_name: str
    run_id: str
    batches: List[Dict[str, Any]] = field(default_factory=list)
    rows_consolidated: int = 0
    accounts_touched: List[str] = field(default_factory=list)
    start_position: int = 0
    end_position: int = 0
    max_request_bytes_seen: int = 0
    ceiling_bytes: int = MAX_REQUEST_BYTES
    ceiling_rows: int = MAX_ROWS_PER_REQUEST
    full_state_bytes_at_start: int = 0
    replayed_batches: int = 0

    def to_dict(self):
        return asdict(self)


class ConsolidationPlanner:
    def __init__(self, conn: sqlite3.Connection, run_id: str,
                 reader: BoundedStateReader,
                 executor: IdempotentExecutor, cursor_name: str = "main"):
        self.conn = conn
        self.run_id = run_id
        self.reader = reader
        self.executor = executor
        self.cursor_name = cursor_name

    def position(self) -> int:
        r = self.conn.execute("SELECT position FROM cursors WHERE name = ?",
                              (self.cursor_name,)).fetchone()
        return int(r["position"]) if r else 0

    def guard_request_growth(self) -> Dict[str, Any]:
        """Pre-mortem for the observed incident. Compares what a whole-state
        read WOULD cost against the ceiling, and confirms the bounded path is
        the one in use."""
        full = self.reader.measure_full_state_bytes()
        pos = self.position()
        pending = self.conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE id > ?", (pos,)).fetchone()["n"]
        would_exceed = full > self.reader.max_bytes
        return {
            "full_state_bytes": full,
            "ceiling_bytes": self.reader.max_bytes,
            "whole_state_read_would_exceed_ceiling": bool(would_exceed),
            "pending_rows": int(pending),
            "cursor_position": pos,
            "bounded_path_in_use": True,
        }

    def consolidate(self) -> ConsolidationReport:
        rep = ConsolidationReport(cursor_name=self.cursor_name, run_id=self.run_id)
        rep.full_state_bytes_at_start = self.reader.measure_full_state_bytes()
        rep.start_position = self.position()
        touched: set = set()
        batch_no = 0

        while True:
            pos = self.position()
            win = self.reader.read_window(pos)
            if not win.rows:
                break
            batch_no += 1

            if win.request_bytes > self.reader.max_bytes * GROWTH_ALARM_FRACTION:
                self.conn.execute(
                    "INSERT INTO run_stats (run_id, cursor_name, batch_no, rows,"
                    " request_bytes, at) VALUES (?,?,?,?,?,?)",
                    (self.run_id, self.cursor_name, batch_no, len(win.rows),
                     win.request_bytes, time.time()))

            agg: Dict[str, int] = {}
            for r in win.rows:
                agg[r["account"]] = agg.get(r["account"], 0) + int(r["delta_cents"])
            touched.update(agg)

            # one key per (cursor, from, to) - a retry of the same batch is a
            # no-op even if the process died between effect and acknowledgement
            idem_key = "consolidate:" + sha256_obj(
                [self.cursor_name, win.from_position, win.to_position])
            prior = self.conn.execute(
                "SELECT * FROM applied_ops WHERE idem_key = ?", (idem_key,)).fetchone()
            if prior is not None:
                rep.replayed_batches += 1
                self.executor._log({
                    "kind": "REPLAY", "op_id": idem_key, "idem_key": idem_key,
                    "op_type": "consolidate", "target": self.cursor_name,
                    "applied": False, "rows": len(win.rows),
                    "request_bytes": win.request_bytes})
                self.conn.execute(
                    "UPDATE cursors SET position = ? WHERE name = ?",
                    (win.to_position, self.cursor_name))
                rep.batches.append({"batch_no": batch_no, "rows": len(win.rows),
                                    "request_bytes": win.request_bytes,
                                    "from": win.from_position,
                                    "to": win.to_position, "replayed": True,
                                    "truncated_by": win.truncated_by})
                continue

            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    "INSERT INTO applied_ops (idem_key, op_type, target,"
                    " payload_digest, result_json, applied_at, run_id)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (idem_key, "consolidate", self.cursor_name,
                     sha256_obj(agg), json.dumps({"rows": len(win.rows)}),
                     time.time(), self.run_id))
                for acct, delta in sorted(agg.items()):
                    self.conn.execute(
                        "INSERT INTO balances (account, cents) VALUES (?, ?) "
                        "ON CONFLICT(account) DO UPDATE SET "
                        "cents = cents + excluded.cents", (acct, delta))
                # THE WATERMARK MOVES IN THE SAME TRANSACTION AS THE EFFECT
                self.conn.execute(
                    "INSERT INTO cursors (name, position) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET position = excluded.position",
                    (self.cursor_name, win.to_position))
                _crash("consolidate_before_commit")
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            _crash("consolidate_after_commit")

            self.executor._log({
                "kind": "APPLY", "op_id": idem_key, "idem_key": idem_key,
                "op_type": "consolidate", "target": self.cursor_name,
                "applied": True, "rows": len(win.rows),
                "request_bytes": win.request_bytes,
                "from": win.from_position, "to": win.to_position})
            rep.rows_consolidated += len(win.rows)
            rep.max_request_bytes_seen = max(rep.max_request_bytes_seen,
                                             win.request_bytes)
            rep.batches.append({"batch_no": batch_no, "rows": len(win.rows),
                                "request_bytes": win.request_bytes,
                                "from": win.from_position, "to": win.to_position,
                                "replayed": False,
                                "truncated_by": win.truncated_by})

        rep.end_position = self.position()
        rep.accounts_touched = sorted(touched)
        return rep


# --------------------------------------------------------------------------
# Pack run
# --------------------------------------------------------------------------
class InfrastructureOperationRun(Run):
    def __init__(self, workdir, producer_id, gate, db_path,
                 cursor_name="main", **kw):
        super().__init__(PACK, workdir, producer_id, gate,
                         mandate={"db": str(db_path), "cursor": cursor_name,
                                  "max_rows": MAX_ROWS_PER_REQUEST,
                                  "max_bytes": MAX_REQUEST_BYTES}, **kw)
        self.db_path = Path(db_path)
        self.cursor_name = cursor_name
        self.conn = connect(db_path)
        ensure_schema(self.conn)
        self.executor = IdempotentExecutor(self.conn, self.run_id,
                                           self.workdir / "op_log.jsonl")
        self.reader = BoundedStateReader(self.conn)
        self.planner = ConsolidationPlanner(self.conn, self.run_id, self.reader,
                                            self.executor, cursor_name)
        self.consolidation: Optional[ConsolidationReport] = None
        self.applied: List[ApplyResult] = []

    def preflight(self):
        self.advance(Phase.PREFLIGHT, {"db": str(self.db_path),
                                       "ceilings": {"rows": MAX_ROWS_PER_REQUEST,
                                                    "bytes": MAX_REQUEST_BYTES}})

    def recover_state(self) -> Dict[str, Any]:
        """After a kill this is what tells us where we actually are: the
        watermark and the set of keys already applied. Both are in the DB, both
        were committed atomically with their effects."""
        pos = self.planner.position()
        n = self.conn.execute("SELECT COUNT(*) AS n FROM applied_ops").fetchone()["n"]
        guard = self.planner.guard_request_growth()
        self.advance(Phase.CURRENT_STATE_RECOVERED,
                     {"cursor_position": pos, "applied_ops": int(n),
                      "growth_guard": guard})
        return {"cursor_position": pos, "applied_ops": int(n), "growth_guard": guard}

    def admit_ops(self, ops: List[Op]) -> None:
        dupes = [o.op_id for o in ops if [x.op_id for x in ops].count(o.op_id) > 1]
        if dupes:
            raise InfraError(f"duplicate op_ids in one batch: {sorted(set(dupes))}")
        self._ops = ops
        self.advance(Phase.INPUT_ADMITTED,
                     {"n_ops": len(ops), "op_ids": [o.op_id for o in ops]})

    def execute(self, consolidate: bool = True):
        self.executor._log({"kind": "EXECUTE_BEGIN", "run_id": self.run_id,
                            "n_ops": len(getattr(self, "_ops", [])),
                            "consolidate": consolidate,
                            "cursor_position": self.planner.position()})
        for op in getattr(self, "_ops", []):
            self.applied.append(self.executor.apply(op))
        if consolidate:
            self.consolidation = self.planner.consolidate()
            write_json(self.workdir / "consolidation_report.json",
                       self.consolidation.to_dict())
        self.advance(Phase.ACTION_EXECUTED, {
            "ops_applied": sum(1 for r in self.applied if r.applied),
            "ops_replayed": sum(1 for r in self.applied if r.replayed),
            "batches": len(self.consolidation.batches) if self.consolidation else 0,
        })

    def artefacts_present(self):
        import checks
        write_json(self.workdir / "db_state.json", snapshot(self.conn))
        missing = checks.missing_artefacts(self.workdir)
        if missing:
            raise FileNotFoundError(f"missing artefacts: {missing}")
        self.advance(Phase.REQUIRED_ARTEFACTS_PRESENT,
                     {"artefacts": checks.REQUIRED_ARTEFACTS})

    def machine_checks(self) -> CheckReport:
        import checks
        rep = checks.run_checks(self.workdir)
        write_json(self.workdir / "checks_report.json", rep.to_dict())
        if not rep.ok:
            raise RuntimeError(f"machine checks failed: {rep.failed}")
        self.advance(Phase.MACHINE_CHECKS_PASSED, {"check_digest": rep.digest()})
        return rep

    def finish(self, acceptor: CommitFirstAcceptor,
               objective: Objective) -> Path:
        """Commit-first acceptance. The acceptor recomputes the exactly-once
        balances from the event log and commits its own verdict before opening
        the consolidation report."""
        acceptor.precommit(self, objective)
        outcome = acceptor.decide(self)
        self.accept_with(outcome)
        p = self.write_return_state({
            "cursor_position": self.planner.position(),
            "consolidation": "consolidation_report.json"})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": p.name})
        self.advance(Phase.COMPLETE, {})
        return p


def snapshot(conn: sqlite3.Connection) -> Dict[str, Any]:
    return {
        "balances": {r["account"]: r["cents"] for r in
                     conn.execute("SELECT * FROM balances ORDER BY account")},
        "applied_ops": int(conn.execute(
            "SELECT COUNT(*) AS n FROM applied_ops").fetchone()["n"]),
        "cursors": {r["name"]: r["position"] for r in
                    conn.execute("SELECT * FROM cursors")},
        "events": int(conn.execute(
            "SELECT COUNT(*) AS n FROM events").fetchone()["n"]),
    }


# --------------------------------------------------------------------------
# CLI - the crash-test subject
# --------------------------------------------------------------------------
def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="state_machine.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply")
    a.add_argument("--db", required=True)
    a.add_argument("--op-id", required=True)
    a.add_argument("--account", required=True)
    a.add_argument("--cents", type=int, required=True)
    a.add_argument("--op-type", default="credit")

    c = sub.add_parser("consolidate")
    c.add_argument("--db", required=True)
    c.add_argument("--cursor", default="main")

    s = sub.add_parser("seed")
    s.add_argument("--db", required=True)
    s.add_argument("--count", type=int, required=True)
    s.add_argument("--note-size", type=int, default=40)
    s.add_argument("--account", default="acct-1")
    s.add_argument("--delta", type=int, default=1)

    d = sub.add_parser("dump")
    d.add_argument("--db", required=True)

    ns = ap.parse_args(argv[1:])
    conn = connect(ns.db)
    ensure_schema(conn)
    run_id = os.environ.get("OBZIO_RUN_ID", "cli")

    if ns.cmd == "apply":
        ex = IdempotentExecutor(conn, run_id)
        res = ex.apply(Op(ns.op_id, ns.op_type, ns.account, {"cents": ns.cents}))
        print(json.dumps(res.to_dict(), sort_keys=True))
        return 0

    if ns.cmd == "consolidate":
        reader = BoundedStateReader(conn)
        ex = IdempotentExecutor(conn, run_id)
        rep = ConsolidationPlanner(conn, run_id, reader, ex, ns.cursor).consolidate()
        print(json.dumps(rep.to_dict(), sort_keys=True))
        return 0

    if ns.cmd == "seed":
        note = "x" * ns.note_size
        conn.execute("BEGIN IMMEDIATE")
        for _ in range(ns.count):
            conn.execute(
                "INSERT INTO events (account, delta_cents, note, created_at)"
                " VALUES (?,?,?,?)", (ns.account, ns.delta, note, time.time()))
        conn.execute("COMMIT")
        print(json.dumps({"seeded": ns.count}))
        return 0

    if ns.cmd == "dump":
        print(json.dumps(snapshot(conn), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
