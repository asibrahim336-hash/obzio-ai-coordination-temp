#!/usr/bin/env python3
"""Report present-but-undeclared and declared-but-unhashed gaps separately."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def declaration_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files", {})
    if isinstance(files, dict):
        return {name: value if isinstance(value, dict) else {} for name, value in files.items()}
    return {
        item["path"]: {key: value for key, value in item.items() if key != "path"}
        for item in files
    }


def detect(pack_dir: Path, manifest_name: str = "fixture_manifest.json") -> dict[str, Any]:
    manifest = json.loads((pack_dir / manifest_name).read_text(encoding="utf-8"))
    declarations = declaration_map(manifest)
    present = sorted(
        path.relative_to(pack_dir).as_posix()
        for path in pack_dir.rglob("*")
        if path.is_file() and path.name != manifest_name
    )
    undeclared_present = sorted(set(present) - set(declarations))
    declared_unhashed = sorted(
        path for path, metadata in declarations.items() if not metadata.get("sha256")
    )
    return {
        "fixture_label": manifest.get("fixture_label"),
        "declared_count": len(declarations),
        "present_count": len(present),
        "undeclared_present": undeclared_present,
        "declared_unhashed": declared_unhashed,
        "verdict": "FAIL" if undeclared_present or declared_unhashed else "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-dir", required=True, type=Path)
    parser.add_argument("--manifest", default="fixture_manifest.json")
    args = parser.parse_args()
    print(json.dumps(detect(args.pack_dir, args.manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
