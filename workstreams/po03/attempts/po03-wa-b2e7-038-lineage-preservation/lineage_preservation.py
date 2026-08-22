#!/usr/bin/env python3
"""Validate decision lineage, especially SUPERSEDE predecessor links."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

DECISIONS = frozenset({"RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT"})


def validate_lineage(records: Iterable[dict[str, Any]]) -> list[str]:
    """Return deterministic defects; an empty list proves valid input."""

    items = [dict(record) for record in records]
    by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for record in items:
        route_id = record.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            errors.append("record has no non-empty route_id")
            continue
        if route_id in by_id:
            errors.append(f"{route_id}: duplicate route_id")
        by_id[route_id] = record
        if record.get("decision") not in DECISIONS:
            errors.append(f"{route_id}: unknown decision")

    for record in items:
        route_id = record.get("route_id")
        if not isinstance(route_id, str):
            continue
        predecessor = record.get("predecessor_route_id")
        if record.get("decision") == "SUPERSEDE":
            if not predecessor:
                errors.append(f"{route_id}: SUPERSEDE has no predecessor_route_id")
            elif predecessor not in by_id:
                errors.append(f"{route_id}: unresolved predecessor {predecessor}")
        elif predecessor is not None and predecessor not in by_id:
            errors.append(f"{route_id}: unresolved predecessor {predecessor}")

    for route_id, record in by_id.items():
        if record.get("decision") != "SUPERSEDE":
            continue
        seen: set[str] = set()
        current = route_id
        while current in by_id and by_id[current].get("decision") == "SUPERSEDE":
            if current in seen:
                errors.append(f"{route_id}: predecessor cycle detected")
                break
            seen.add(current)
            predecessor = by_id[current].get("predecessor_route_id")
            if predecessor not in by_id:
                break
            current = predecessor
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    errors = validate_lineage(json.loads(args.input.read_text(encoding="utf-8")))
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
