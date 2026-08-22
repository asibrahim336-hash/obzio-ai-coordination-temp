#!/usr/bin/env python3
"""Require exactly one unambiguous portable execution route."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import PurePosixPath, Path
from typing import Any


SHELL_META = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "&"}


def _normalize_route(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        try:
            argv = shlex.split(value, posix=True)
        except ValueError:
            return None
    elif isinstance(value, dict) and isinstance(value.get("argv"), list):
        argv = value["argv"]
    elif isinstance(value, list):
        argv = value
    else:
        return None
    if not argv or not all(isinstance(item, str) and item for item in argv):
        return None
    if any(item in SHELL_META or "`" in item or "$(" in item or "\n" in item for item in argv):
        return None
    if argv[0] not in {"python", "python3"} or len(argv) < 2 or argv[1].startswith("-"):
        return None
    script = PurePosixPath(argv[1])
    if script.is_absolute() or ".." in script.parts or script.name != "successor_reproducer.py":
        return None
    return tuple(argv)


def qualify_routes(manifest: dict[str, Any]) -> dict[str, Any]:
    declarations: list[dict[str, Any]] = []
    if "reproduction_command" in manifest:
        declarations.append(
            {"field": "reproduction_command", "value": manifest["reproduction_command"]}
        )
    if "portable_routes" in manifest:
        routes = manifest["portable_routes"]
        if isinstance(routes, list):
            declarations.extend(
                {"field": f"portable_routes[{index}]", "value": route}
                for index, route in enumerate(routes)
            )
        else:
            declarations.append({"field": "portable_routes", "value": routes})

    valid = []
    invalid = []
    for declaration in declarations:
        normalized = _normalize_route(declaration["value"])
        if normalized is None:
            invalid.append(declaration["field"])
        else:
            valid.append({"field": declaration["field"], "argv": list(normalized)})

    defects: list[dict[str, Any]] = []
    if invalid:
        defects.append({"code": "AMBIGUOUS_OR_UNSUPPORTED_ROUTE", "fields": invalid})
    if len(declarations) != 1:
        defects.append(
            {
                "code": "PORTABLE_ROUTE_CARDINALITY",
                "expected": 1,
                "observed": len(declarations),
            }
        )
    if len(valid) != 1:
        defects.append(
            {
                "code": "VALID_PORTABLE_ROUTE_CARDINALITY",
                "expected": 1,
                "observed": len(valid),
            }
        )
    return {
        "declarations": len(declarations),
        "valid_routes": valid,
        "defects": defects,
        "disposition": "PASS" if not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    report = qualify_routes(json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
