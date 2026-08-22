"""Staged atomic result outbox with mandatory hash read-back."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_result(directory: Path, record: Mapping[str, object]) -> dict[str, object]:
    task_id = record.get("task_id")
    if not isinstance(task_id, str) or not task_id or "/" in task_id or ".." in task_id:
        raise ValueError("safe task_id is required")
    directory.mkdir(parents=True, exist_ok=True)
    body = canonical(dict(record))
    digest = hashlib.sha256(body).hexdigest()
    final = directory / f"{task_id}.json"
    temporary = directory / f".{task_id}.tmp"
    if final.exists():
        existing = final.read_bytes()
        if hashlib.sha256(existing).hexdigest() != digest:
            raise ValueError("conflicting committed outbox record")
    else:
        with temporary.open("wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, final)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    locator = {"path": str(final), "sha256": digest, "bytes": len(body)}
    read_result(locator)
    return locator


def read_result(locator: Mapping[str, object]) -> dict[str, object]:
    path = Path(str(locator["path"]))
    body = path.read_bytes()
    if len(body) != locator["bytes"]:
        raise ValueError("outbox byte-count mismatch")
    actual = hashlib.sha256(body).hexdigest()
    if actual != locator["sha256"]:
        raise ValueError("outbox hash mismatch")
    return json.loads(body)
