#!/usr/bin/env python3
"""Report unreachable state/instruction files from explicit current pointers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

REFERENCE = re.compile(r"(?<![\w./-])(?:state|instructions)/[\w./-]+")
SCOPE = ("state", "instructions")


def _repo_path(repo: Path, value: str) -> Path:
    return (repo / value).resolve()


def _references(body: str) -> list[str]:
    return sorted({match.rstrip(".,;:)\\]}") for match in REFERENCE.findall(body)})


def _readable(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def detect(repo: str | Path, pointer_paths: Iterable[str]) -> dict[str, object]:
    """Traverse references and identify in-scope files never reached."""

    root = Path(repo).resolve()
    roots = [str(path) for path in pointer_paths]
    reachable: set[str] = set()
    missing_roots: list[str] = []
    missing_references: list[dict[str, str]] = []
    queue = list(roots)
    queued = set(queue)
    while queue:
        relative = queue.pop(0)
        path = _repo_path(root, relative)
        if not path.is_file():
            (missing_roots if relative in roots else missing_references).append(
                {"path": relative} if relative not in roots else relative
            )
            continue
        if relative.startswith(SCOPE):
            reachable.add(relative)
        for reference in _references(_readable(path)):
            reference_path = _repo_path(root, reference)
            if not reference_path.is_file():
                missing_references.append({"from": relative, "path": reference})
            elif reference not in queued:
                queued.add(reference)
                queue.append(reference)

    candidates = sorted(
        path.relative_to(root).as_posix()
        for scope in SCOPE
        for path in (root / scope).rglob("*")
        if path.is_file()
    )
    orphans = [path for path in candidates if path not in reachable]
    return {
        "pointer_paths": roots,
        "reachable": sorted(reachable),
        "orphans": orphans,
        "missing_roots": missing_roots,
        "missing_references": sorted(
            missing_references, key=lambda item: (item.get("from", ""), item["path"])
        ),
        "scanned_count": len(candidates),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("pointer", nargs="+")
    args = parser.parse_args()
    print(json.dumps(detect(args.repo, args.pointer), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
