#!/usr/bin/env python3
"""Recompile WA-011 from all frozen and exhaustive traversal orders."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any


UNIT_RELATIVE = Path("workstreams/po03/wave-a/units/wa-011")


def _load_generator(unit_root: Path) -> Any:
    module_path = unit_root / "manifest_generator.py"
    specification = importlib.util.spec_from_file_location(
        "wa011_recurrence_generator", module_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load generator from {module_path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def verify(repo_root: Path) -> dict[str, Any]:
    unit_root = repo_root.resolve(strict=True) / UNIT_RELATIVE
    generator = _load_generator(unit_root)
    source_root = unit_root / "fixtures" / "source"
    order_fixture = json.loads(
        (unit_root / "fixtures" / "shuffled-orders.json").read_text(encoding="utf-8")
    )
    expected = (unit_root / "reproduction" / "expected-manifest.json").read_bytes()

    orders = order_fixture["orders"]
    ascending = orders["ascending"]
    exhaustive = [list(order) for order in itertools.permutations(ascending)]
    named_outputs = {
        name: generator.compile_manifest_bytes(source_root, order)
        for name, order in orders.items()
    }
    exhaustive_outputs = [
        generator.compile_manifest_bytes(source_root, order) for order in exhaustive
    ]
    repeated_outputs = [
        generator.compile_manifest_bytes(source_root, orders["seed-1102"])
        for _ in range(8)
    ]
    discovered = generator.compile_manifest_bytes(source_root)
    outputs = [
        *named_outputs.values(),
        *exhaustive_outputs,
        *repeated_outputs,
        discovered,
    ]
    if any(output != expected for output in outputs):
        raise RuntimeError("at least one compilation differed from the frozen bytes")

    manifest = json.loads(expected)
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        raise RuntimeError("expected manifest artifact count is inconsistent")
    if manifest["total_bytes"] != sum(item["bytes"] for item in manifest["artifacts"]):
        raise RuntimeError("expected manifest byte count is inconsistent")
    for artifact in manifest["artifacts"]:
        content = (source_root / artifact["path"]).read_bytes()
        if len(content) != artifact["bytes"]:
            raise RuntimeError(f"byte mismatch: {artifact['path']}")
        if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            raise RuntimeError(f"hash mismatch: {artifact['path']}")

    return {
        "artifact_count": manifest["artifact_count"],
        "exhaustive_permutations": len(exhaustive),
        "frozen_named_orders": sorted(named_outputs),
        "manifest_bytes": len(expected),
        "manifest_sha256": hashlib.sha256(expected).hexdigest(),
        "protocol_version": "OBZIO-MANIFEST-RECURRENCE-v1",
        "repeat_compilations": len(repeated_outputs),
        "status": "PASS",
        "task_id": "PO03-WA-011",
        "total_compilations": len(outputs),
        "total_source_bytes": manifest["total_bytes"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        result = verify(args.repo_root)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "FAIL", "task_id": "PO03-WA-011"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
