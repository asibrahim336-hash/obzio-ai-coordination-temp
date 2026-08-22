"""Append-only JSONL writers for the a5 research ledgers.

Both ``hypotheses.jsonl`` and ``reproduction-ledger.jsonl`` are append-only:
existing lines are never rewritten. Each row is canonicalised (sorted keys,
compact separators) before hashing so a row's own ``row_sha256`` is a stable
function of its content, independent of dict insertion order.

The four custody states named in the commission -- ``source``,
``frozen_hypothesis``, ``reproduction``, ``mechanism_change`` and
``proposal`` -- are always carried in a dedicated ``state`` field (or, where a
single row legitimately spans two states, in clearly separated sub-objects)
so they can never be silently conflated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_jsonl(path: Path, row: dict[str, Any]) -> str:
    """Append one canonicalised row and return its row_sha256.

    The hash is computed over the row *before* the row_sha256 field is added,
    matching the pattern used by the coordinator's ledger so provenance can be
    checked the same way in both places.
    """
    body = dict(row)
    body.pop("row_sha256", None)
    row_sha256 = sha256_text(canonical(body))
    body["row_sha256"] = row_sha256
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical(body) + "\n")
        handle.flush()
    return row_sha256


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)
