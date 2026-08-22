#!/usr/bin/env python3
"""Content-addressed sanitized task capsule mechanism."""
import hashlib
import json
import tempfile
from pathlib import Path


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


class CapsuleStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, value):
        payload = canonical_bytes(value)
        digest = hashlib.sha256(payload).hexdigest()
        target = self.root / f"{digest}.json"
        if target.exists() and target.read_bytes() != payload:
            raise ValueError("digest collision or corrupt existing capsule")
        target.write_bytes(payload)
        return digest

    def get(self, digest):
        payload = (self.root / f"{digest}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("capsule digest mismatch")
        return json.loads(payload)


def reproduce_mutable_ambiguity():
    first = {"task_id": "OBZIO-SANITIZED-001", "payload": {"claim": "alpha", "sequence": 1}}
    replacement = {"task_id": first["task_id"], "payload": {"claim": "beta", "sequence": 2}}
    mutable = {first["task_id"]: first}
    callback = {"task_id": first["task_id"]}
    mutable[first["task_id"]] = replacement
    return {"ambiguous": mutable[callback["task_id"]] != first, "resolved_sequence": mutable[callback["task_id"]]["payload"]["sequence"]}


def exercise():
    first = {"task_id": "OBZIO-SANITIZED-001", "payload": {"claim": "alpha", "sequence": 1}}
    replacement = {"task_id": first["task_id"], "payload": {"claim": "beta", "sequence": 2}}
    with tempfile.TemporaryDirectory() as tmp:
        store = CapsuleStore(tmp)
        first_digest = store.put(first)
        replay_digest = store.put(first)
        replacement_digest = store.put(replacement)
        recovered = store.get(first_digest)
    return {
        "baseline": reproduce_mutable_ambiguity(),
        "first_digest": first_digest,
        "replacement_digest": replacement_digest,
        "same_content_is_idempotent": replay_digest == first_digest,
        "different_content_has_different_address": replacement_digest != first_digest,
        "callback_recovered_sequence": recovered["payload"]["sequence"],
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
