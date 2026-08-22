#!/usr/bin/env python3
"""Allocate fence tokens from a separate process.

Used to observe whether the live allocator stays unique when several real
workers race for the counter.  Prints one JSON line so the parent can collect
every token that was actually handed out.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("po03_c6_045_child_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--allocations", type=int, default=5)
    parser.add_argument("--allocator", choices=("LIVE", "REPAIR_CANDIDATE"), default="LIVE")
    arguments = parser.parse_args(argv)

    module = kit.bind_sandbox(kit.load_factory("045_child"), Path(arguments.sandbox).resolve())
    if arguments.allocator == "LIVE":
        allocate = module.allocate_fence
    else:
        spec = importlib.util.spec_from_file_location(
            "po03_c6_045_child_repair", HERE / "repair_candidate_fencing.py"
        )
        assert spec is not None and spec.loader is not None
        repair = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(repair)

        def allocate():
            return repair.allocate_fence_exclusive(module)

    tokens = [allocate() for _ in range(arguments.allocations)]
    json.dump({"tokens": tokens}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
