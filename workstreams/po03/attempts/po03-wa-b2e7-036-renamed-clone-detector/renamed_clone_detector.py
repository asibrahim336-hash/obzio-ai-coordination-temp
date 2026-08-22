#!/usr/bin/env python3
"""Find exact and near-duplicate committed artifacts by content."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

_WHITESPACE = re.compile(r"\s+")


def _files(paths: Iterable[str | Path]) -> list[Path]:
    found: set[Path] = set()
    for value in paths:
        path = Path(value)
        if path.is_file():
            found.add(path)
        elif path.is_dir():
            found.update(item for item in path.rglob("*") if item.is_file())
    return sorted(found, key=lambda item: item.as_posix())


def _similarity(left: bytes, right: bytes) -> float:
    try:
        left_text = _WHITESPACE.sub(" ", left.decode("utf-8")).strip()
        right_text = _WHITESPACE.sub(" ", right.decode("utf-8")).strip()
    except UnicodeDecodeError:
        return 1.0 if left == right else 0.0
    return SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()


def detect(paths: Iterable[str | Path], threshold: float = 0.90) -> list[dict[str, object]]:
    """Return duplicate pairs, including hashes and measured similarity."""

    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    entries = []
    for path in _files(paths):
        body = path.read_bytes()
        entries.append((path, body, hashlib.sha256(body).hexdigest()))
    pairs: list[dict[str, object]] = []
    for index, (left_path, left_body, left_hash) in enumerate(entries):
        for right_path, right_body, right_hash in entries[index + 1 :]:
            similarity = _similarity(left_body, right_body)
            if similarity >= threshold:
                pairs.append(
                    {
                        "left": left_path.as_posix(),
                        "right": right_path.as_posix(),
                        "left_sha256": left_hash,
                        "right_sha256": right_hash,
                        "similarity": round(similarity, 6),
                        "kind": "renamed-clone" if left_hash == right_hash else "near-duplicate",
                    }
                )
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", type=Path)
    parser.add_argument("--threshold", type=float, default=0.90)
    args = parser.parse_args()
    print(json.dumps(detect(args.path, args.threshold), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
