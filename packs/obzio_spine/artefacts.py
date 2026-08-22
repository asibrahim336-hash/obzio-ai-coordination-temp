"""Durable artefact I/O. Every write is flushed and read back before it is
reported as written -- a write that was not re-read is not evidence."""

import hashlib
import json
import os


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj) -> bytes:
    """Byte-stable JSON. Sorted keys, no incidental whitespace, UTF-8.
    Two runs producing equal data MUST produce identical bytes -- the
    continuity pack's determinism check depends on this."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def write_json(path: str, obj) -> str:
    """Write, fsync, re-read, verify. Returns the sha256 of what is ON DISK,
    not of what we intended to write."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = canonical(obj)
    with open(path, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    with open(path, "rb") as f:
        ondisk = f.read()
    if ondisk != payload:
        raise IOError(f"read-back mismatch for {path}")
    return sha256_bytes(ondisk)


def read_json(path: str):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def run_digest(paths) -> str:
    """Digest over the ordered (relpath, content-hash) pairs of the artefact
    set. This is what an acceptance token is bound to. Changing ANY artefact
    after acceptance invalidates the token."""
    h = hashlib.sha256()
    h.update(b"obzio.rundigest.v1")
    for p in sorted(paths):
        h.update(os.path.basename(p).encode("utf-8"))
        h.update(b"\x00")
        h.update(sha256_file(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
