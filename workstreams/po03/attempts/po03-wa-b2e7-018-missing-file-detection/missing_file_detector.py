#!/usr/bin/env python3
"""Detect declarations whose files are absent; never trust manifest status."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable


def declared_paths(manifest_path: str, manifest: dict[str, Any]) -> list[str]:
    parent = PurePosixPath(manifest_path).parent
    files = manifest.get("files", {})
    if isinstance(files, dict):
        return [str(parent / name) for name in files]
    return [
        item["path"] if "/" in item["path"] else str(parent / item["path"])
        for item in files
    ]


def detect(manifest_path: str, manifest: dict[str, Any], exists: Callable[[str], bool]) -> dict[str, Any]:
    declared = declared_paths(manifest_path, manifest)
    missing = sorted(path for path in declared if not exists(path))
    return {
        "declared_count": len(declared),
        "missing_count": len(missing),
        "missing": missing,
        "verdict": "FAIL" if missing else "PASS",
    }


def detect_git(repo: str, commit: str, manifest_path: str) -> dict[str, Any]:
    raw = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{manifest_path}"),
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    manifest = json.loads(raw)

    def exists(path: str) -> bool:
        return subprocess.run(
            ("git", "cat-file", "-e", f"{commit}:{path}"),
            cwd=repo,
            check=False,
            capture_output=True,
        ).returncode == 0

    result = detect(manifest_path, manifest, exists)
    result.update({"source": "git", "commit": commit, "manifest_path": manifest_path})
    return result


def detect_directory(pack_dir: Path, manifest_name: str = "manifest.json") -> dict[str, Any]:
    manifest = json.loads((pack_dir / manifest_name).read_text(encoding="utf-8"))
    result = detect(
        manifest_name,
        manifest,
        lambda path: (pack_dir / PurePosixPath(path).name).is_file(),
    )
    result.update(
        {
            "source": "synthetic_directory",
            "fixture_label": manifest.get("fixture_label"),
            "manifest_path": manifest_name,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo")
    source.add_argument("--pack-dir", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--manifest", default="manifest.json")
    args = parser.parse_args()
    if args.repo:
        if not args.commit:
            parser.error("--commit is required with --repo")
        result = detect_git(args.repo, args.commit, args.manifest)
    else:
        result = detect_directory(args.pack_dir, args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
