#!/usr/bin/env python3
"""Resolve durable configuration with explicit, lossless precedence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


UNKNOWN_MARKERS = {"UNKNOWN", "UNAVAILABLE", "NOT_SUPPORTED", "NOT_YET"}


def _availability(value: Any) -> str:
    if value is None:
        return "UNAVAILABLE"
    if isinstance(value, dict) and value.get("state") in UNKNOWN_MARKERS:
        return str(value["state"])
    if isinstance(value, str) and value.strip().upper() in UNKNOWN_MARKERS:
        return value.strip().upper()
    return "AVAILABLE"


def resolve_config(
    keys: Iterable[str],
    declared: Mapping[str, Any],
    environment: Mapping[str, str],
    defaults: Mapping[str, Any],
    *,
    env_prefix: str = "PO03_",
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key in keys:
        env_key = f"{env_prefix}{key.upper()}"
        if key in declared:
            source = "declared"
            value = declared[key]
        elif env_key in environment:
            source = "environment"
            value = environment[env_key]
        elif key in defaults:
            source = "defaults"
            value = defaults[key]
        else:
            source = "unavailable"
            value = {"state": "UNAVAILABLE"}
        resolved[key] = {
            "source": source,
            "availability": _availability(value),
            "value": value,
        }
    return {
        "precedence": ["declared", "environment", "defaults"],
        "values": resolved,
        "unknown_values_preserved": True,
        "disposition": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    declared = json.loads(args.manifest.read_text(encoding="utf-8"))
    keys = (
        "generation_id",
        "source_commit",
        "reproduction_command",
        "execution_timeout",
    )
    report = resolve_config(
        keys,
        declared,
        os.environ,
        {"execution_timeout": "NOT_SUPPORTED"},
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
