#!/usr/bin/env python3
"""Load a Python source file directly without importing its package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any


class SourceLoadError(RuntimeError):
    pass


def load_source(repo: Path, relative_path: str) -> dict[str, Any]:
    root = repo.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SourceLoadError("SOURCE_PATH_ESCAPES_REPOSITORY") from error
    if not candidate.is_file():
        raise SourceLoadError("SOURCE_FILE_UNAVAILABLE")
    source = candidate.read_bytes()
    before_modules = frozenset(sys.modules)
    namespace: dict[str, Any] = {
        "__name__": "_po03_direct_source_",
        "__file__": str(candidate),
        "__package__": None,
        "__cached__": None,
    }
    try:
        code = compile(source, str(candidate), "exec", dont_inherit=True)
        exec(code, namespace, namespace)
    except (ImportError, SyntaxError) as error:
        raise SourceLoadError(f"SOURCE_NOT_PORTABLY_LOADABLE:{type(error).__name__}") from error
    imported_modules = sorted(frozenset(sys.modules) - before_modules)
    return {
        "namespace": MappingProxyType(namespace),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "source_bytes": len(source),
        "package_imported": False,
        "new_stdlib_modules": imported_modules,
    }


def qualify(repo: Path, relative_path: str, required_symbol: str) -> dict[str, Any]:
    try:
        loaded = load_source(repo, relative_path)
    except SourceLoadError as error:
        return {"disposition": "FAIL", "defects": [str(error)]}
    symbol = loaded["namespace"].get(required_symbol)
    defects = [] if callable(symbol) else [f"REQUIRED_CALLABLE_MISSING:{required_symbol}"]
    return {
        "path": relative_path,
        "required_symbol": required_symbol,
        "source_sha256": loaded["source_sha256"],
        "source_bytes": loaded["source_bytes"],
        "package_imported": loaded["package_imported"],
        "stdlib_modules_loaded": loaded["new_stdlib_modules"],
        "defects": defects,
        "disposition": "PASS" if not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    report = qualify(args.repo, args.path, args.symbol)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
