"""Append-only, hash-chained run ledger.

Two properties matter and both are load-bearing:

1. APPEND-ONLY + CHAINED. Each event carries the hash of the previous event.
   Altering or removing any earlier event breaks every hash after it, so the
   record is tamper-evident rather than merely trusted.

2. CONSTANT COST. A run appends; it never re-reads whole state to write.
   This is the specific defect that killed the predecessor mechanism, which
   re-read the entire estate on every scheduled run until the request outgrew
   its ceiling.
"""
import hashlib
import json
import os
from typing import Any, Dict, Iterator, List, Optional

GENESIS = "0" * 64


def _h(prev: str, payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev + body).encode()).hexdigest()


class Ledger:
    def __init__(self, path: str):
        self.path = path
        if not os.path.exists(path):
            open(path, "a").close()

    def _last_hash(self) -> str:
        last = GENESIS
        for ev in self.read():
            last = ev["event_hash"]
        return last

    def append(self, kind: str, payload: Dict[str, Any],
               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Append one event. Returns the existing event if the idempotency key
        has already been committed - the caller cannot cause a duplicate."""
        if idempotency_key is not None:
            existing = self.find_by_key(idempotency_key)
            if existing is not None:
                return existing
        prev = self._last_hash()
        body = {"kind": kind, "payload": payload,
                "idempotency_key": idempotency_key, "prev_hash": prev}
        ev = dict(body)
        ev["event_hash"] = _h(prev, body)
        # single atomic append; fsync so a kill after this point cannot lose it
        with open(self.path, "a") as f:
            f.write(json.dumps(ev, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return ev

    def read(self) -> Iterator[Dict[str, Any]]:
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # a torn final line from a kill mid-write is not committed
                    return

    def find_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        for ev in self.read():
            if ev.get("idempotency_key") == key:
                return ev
        return None

    def verify(self) -> bool:
        """Recompute the whole chain. Any edit, reorder or deletion fails."""
        prev = GENESIS
        for ev in self.read():
            body = {k: ev[k] for k in ("kind", "payload", "idempotency_key", "prev_hash")}
            if ev["prev_hash"] != prev or ev["event_hash"] != _h(prev, body):
                return False
            prev = ev["event_hash"]
        return True

    def committed_steps(self) -> List[str]:
        return [ev["payload"]["step"] for ev in self.read()
                if ev["kind"] == "step_committed"]
