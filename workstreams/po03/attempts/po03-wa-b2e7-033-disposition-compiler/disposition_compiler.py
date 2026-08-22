#!/usr/bin/env python3
"""Compile route dispositions without orphaning predecessor records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

DECISIONS = frozenset({"RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT"})


class DispositionError(ValueError):
    """Raised when a route disposition cannot be safely compiled."""


def compile_dispositions(routes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and return deterministic route dispositions.

    A SUPERSEDE record must name an existing predecessor.  Any supplied
    predecessor reference is checked for every decision, so a typo cannot
    silently orphan lineage.
    """

    records = [dict(route) for route in routes]
    identifiers: dict[str, dict[str, Any]] = {}
    for record in records:
        route_id = record.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            raise DispositionError("each route requires a non-empty route_id")
        if route_id in identifiers:
            raise DispositionError(f"duplicate route_id: {route_id}")
        decision = record.get("decision")
        if decision not in DECISIONS:
            raise DispositionError(
                f"{route_id}: decision must be one of {sorted(DECISIONS)}"
            )
        identifiers[route_id] = record

    for record in records:
        route_id = record["route_id"]
        predecessor = record.get("predecessor_route_id")
        if record["decision"] == "SUPERSEDE" and not predecessor:
            raise DispositionError(f"{route_id}: SUPERSEDE requires predecessor_route_id")
        if predecessor is not None:
            if not isinstance(predecessor, str) or predecessor not in identifiers:
                raise DispositionError(
                    f"{route_id}: predecessor_route_id does not resolve: {predecessor!r}"
                )
            if predecessor == route_id:
                raise DispositionError(f"{route_id}: route cannot precede itself")

    return sorted(records, key=lambda item: item["route_id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON array of route records")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    routes = json.loads(args.input.read_text(encoding="utf-8"))
    compiled = compile_dispositions(routes)
    encoded = json.dumps(compiled, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
