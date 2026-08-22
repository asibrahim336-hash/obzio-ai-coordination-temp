#!/usr/bin/env python3
"""Rebuild and verify the WA-009 capsule from any clean repository clone."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


UNIT_RELATIVE = Path("workstreams/po03/wave-a/units/wa-009")


def _load_builder(unit_root: Path) -> Any:
    path = unit_root / "capsule_builder.py"
    specification = importlib.util.spec_from_file_location(
        "wa009_recurrence_builder", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load builder from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def verify(repo_root: Path) -> dict[str, Any]:
    unit_root = repo_root.resolve(strict=True) / UNIT_RELATIVE
    builder = _load_builder(unit_root)
    source_root = unit_root / "fixtures" / "source"
    request_root = unit_root / "fixtures" / "requests"
    committed = unit_root / "reproduction" / "capsule"

    with tempfile.TemporaryDirectory(prefix="po03-wa-009-recurrence-") as temporary:
        temporary_root = Path(temporary)
        first = temporary_root / "first"
        second = temporary_root / "second"
        first_manifest = builder.build_capsule(
            source_root, request_root / "valid.json", first
        )
        second_manifest = builder.build_capsule(
            source_root, request_root / "valid.json", second
        )
        first_files = _file_map(first)
        second_files = _file_map(second)
        committed_files = _file_map(committed)
        if first_files != second_files:
            raise RuntimeError("two fresh capsule builds were not byte-identical")
        if first_files != committed_files:
            raise RuntimeError(
                "fresh capsule did not match the committed recurrence fixture"
            )

        rejected: list[dict[str, str]] = []
        for request_name, expected_code in (
            ("over-byte-budget.json", "BYTE_BUDGET_EXCEEDED"),
            ("omitted-critical-source.json", "MISSING_CRITICAL_SOURCE"),
        ):
            try:
                builder.build_capsule(
                    source_root,
                    request_root / request_name,
                    temporary_root / request_name.removesuffix(".json"),
                )
            except builder.CapsuleError as exc:
                if exc.code != expected_code:
                    raise RuntimeError(
                        f"{request_name} returned {exc.code}, expected {expected_code}"
                    ) from exc
                rejected.append({"fixture": request_name, "error_code": exc.code})
            else:
                raise RuntimeError(f"{request_name} was unexpectedly admitted")

    manifest_bytes = committed_files["capsule-manifest.json"]
    return {
        "deterministic_rebuilds": 2,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "negative_fixtures": rejected,
        "protocol_version": "OBZIO-SOURCE-CAPSULE-RECURRENCE-v1",
        "source_bytes": first_manifest["source_bytes"],
        "source_count": first_manifest["source_count"],
        "status": "PASS",
        "task_id": "PO03-WA-009",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        result = verify(args.repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "FAIL", "task_id": "PO03-WA-009"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
