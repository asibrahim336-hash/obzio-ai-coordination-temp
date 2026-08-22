#!/usr/bin/env python3
"""Run every PO-03 test in the tree, including work-unit subtrees.

Wave A producers commit their tests inside their own owned subtree, so a gate
that only discovers `workstreams/po03/tests` would report green while most of
the suite never ran.  This runner loads every `test_*.py` under the PO-03
namespace by file path, which also works for directories that are deliberately
not Python packages.

Dependency-free and importable from a clean clone with no warm state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import unittest
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRECTORIES = {"__pycache__", ".git"}


def discover(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("test_*.py")
        if not any(part in SKIP_DIRECTORIES for part in path.parts)
    )


def load(path: Path, root: Path) -> tuple[unittest.TestSuite | None, str | None]:
    """Load one test file by path under a unique module name."""
    relative = path.relative_to(root).with_suffix("")
    module_name = "po03_suite_" + "_".join(relative.parts).replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None, f"{path}: unloadable"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # a producer's broken test file must fail the gate, not hide
        return None, f"{path}: import failed: {exc!r}"
    finally:
        sys.dont_write_bytecode = previous
    return unittest.defaultTestLoader.loadTestsFromModule(module), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--verbosity", type=int, default=1)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    files = discover(root)
    suite = unittest.TestSuite()
    load_errors: list[str] = []
    for path in files:
        loaded, error = load(path, root)
        if error:
            load_errors.append(error)
            continue
        if loaded is not None:
            suite.addTest(loaded)

    runner = unittest.TextTestRunner(verbosity=args.verbosity, stream=sys.stderr)
    result = runner.run(suite)

    summary = {
        "suite_version": "PO03-AGGREGATE-SUITE-v1",
        "root": root.name,
        "test_files_discovered": len(files),
        "test_files_loaded": len(files) - len(load_errors),
        "load_errors": load_errors,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "verdict": "PASS" if result.wasSuccessful() and not load_errors else "FAIL",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
