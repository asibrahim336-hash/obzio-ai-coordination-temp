#!/usr/bin/env python3
"""Compare qualification in producer memory with a fresh interpreter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_fixture(path: Path) -> Any:
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("synthetic_qualifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixture {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare(path: Path) -> dict[str, Any]:
    fixture = load_fixture(path)
    fixture.prime_producer_memory()
    in_process = fixture.qualify()
    proc = subprocess.run(
        (sys.executable, "-I", str(path)),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess_result = json.loads(proc.stdout)
    divergence = in_process["qualified"] != subprocess_result["qualified"]
    return {
        "fixture": str(path.name),
        "fixture_label": in_process["fixture_label"],
        "in_process": in_process,
        "subprocess": subprocess_result,
        "subprocess_returncode": proc.returncode,
        "divergence_detected": divergence,
        "verdict": "FAIL_PROCESS_BOUNDARY" if divergence else "PASS_STABLE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qualifier", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.qualifier.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
